"""Fetch, validate and select real hourly forecast samples in the location's timezone."""

import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from weather_advisor.policy import FIELDS, required_fields


class WeatherError(Exception):
    pass


class OpenMeteo:
    def __init__(self, client=None, clock=None):
        self.client = client
        self.clock = clock or (lambda: datetime.now(UTC))

    def _get(self, url, params):
        if self.client is not None:
            response = self.client.get(url, params=params)
        else:
            with httpx.Client(timeout=15, transport=httpx.HTTPTransport(retries=1)) as client:
                response = client.get(url, params=params)
        response.raise_for_status()
        return response.json(), str(response.url)

    def fetch(self, intent, catalog):
        try:
            geo, _ = self._get(
                "https://geocoding-api.open-meteo.com/v1/search",
                {"name": intent["city"], "count": 5, "language": "en", "format": "json"},
            )
            if not geo.get("results"):
                raise WeatherError("I couldn't resolve that location. Please supply another city name.")
            place = geo["results"][0]
            fields = sorted(set().union(*(required_fields(p.when) for p in catalog["policies"])))
            raw, url = self._get(
                "https://api.open-meteo.com/v1/forecast",
                {
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "hourly": ",".join(fields),
                    "timezone": "auto",
                    "forecast_days": 7,
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "precipitation_unit": "mm",
                },
            )
            return self.validate(raw, place, fields, intent, url, len(geo["results"]))
        except WeatherError:
            raise
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            AttributeError,
            ZoneInfoNotFoundError,
        ) as exc:
            raise WeatherError(
                "I couldn't obtain a complete, valid weather forecast. No weather advice was generated."
            ) from exc

    def validate(self, raw, place, fields, intent, url, candidates=1):
        tz = ZoneInfo(raw["timezone"])
        now = self.clock().astimezone(tz)
        date = now.date() + timedelta(days=intent["day_offset"])
        periods = {
            "today": (0, 24),
            "morning": (6, 12),
            "afternoon": (12, 17),
            "evening": (17, 22),
            "now": (now.hour, now.hour + 1),
        }
        lo, hi = periods[intent["period"]]
        expected = [
            datetime.combine(date, datetime.min.time()).replace(hour=h, tzinfo=tz)
            for h in range(lo, hi)
            if date > now.date() or h >= now.hour
        ]
        if not expected:
            raise WeatherError("That time window has already passed locally. Please choose a future window.")
        hourly = raw["hourly"]
        times = hourly["time"]
        if len(set(times)) != len(times):
            raise WeatherError("The weather service returned ambiguous duplicate forecast times.")
        index = {t: i for i, t in enumerate(times)}
        for field in fields:
            if len(hourly[field]) != len(times):
                raise WeatherError("The weather service returned incomplete hourly data.")
            expected_unit = "wmo code" if field == "weather_code" else FIELDS[field]
            if raw["hourly_units"].get(field) != expected_unit:
                raise WeatherError(f"The weather service returned unexpected units for {field}.")
        rows = []
        for stamp in expected:
            key = stamp.strftime("%Y-%m-%dT%H:%M")
            if key not in index:
                raise WeatherError("The requested window is not fully covered by the returned forecast.")
            i = index[key]
            row = {"time": key}
            for field in fields:
                value = hourly[field][i]
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise WeatherError(
                        f"The forecast is missing a valid {field} value for the requested window."
                    )
                if field not in {"temperature_2m", "apparent_temperature"} and value < 0:
                    raise WeatherError("The forecast contains an invalid negative weather value.")
                if field == "precipitation_probability" and value > 100:
                    raise WeatherError("The forecast contains an invalid probability.")
                row[field] = value
            rows.append(row)
        return {
            "place": {k: place.get(k) for k in ("name", "admin1", "country", "latitude", "longitude")},
            "timezone": raw["timezone"],
            "rows": rows,
            "source_url": url,
            "retrieved_at": self.clock().isoformat(),
            "candidate_count": candidates,
            "raw": raw,
            "window": {"start": rows[0]["time"], "end": rows[-1]["time"]},
        }

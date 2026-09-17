from streamlit.testing.v1 import AppTest

from weather_advisor import graph
from weather_advisor.policy import ROOT


class UIWeather:
    def fetch(self, intent, catalog):
        row = {
            "time": "2026-09-17T18:00",
            "temperature_2m": 22,
            "apparent_temperature": 22,
            "precipitation": 0,
            "precipitation_probability": 10,
            "wind_speed_10m": 20,
            "wind_gusts_10m": 44,
            "uv_index": 1,
            "weather_code": 1,
        }
        return {
            "place": {"name": intent["city"]},
            "timezone": "Asia/Kolkata",
            "rows": [row],
            "candidate_count": 1,
            "retrieved_at": "2026-09-17T12:00:00+00:00",
            "window": {"start": row["time"], "end": row["time"]},
        }


def test_chat_frontend_and_session_reset(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "demo")
    monkeypatch.setattr(graph, "OpenMeteo", UIWeather)
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=60)
    assert not app.exception
    app.chat_input[0].set_value("Cycling in Bhopal today?").run(timeout=60)
    assert not app.exception
    assert "CYCLE-01" in app.session_state["messages"][-1]["content"]
    app.chat_input[0].set_value("What about tomorrow evening instead?").run(timeout=60)
    assert not app.exception
    assert len(app.session_state["messages"]) == 4
    assert app.session_state["context"]["city"] == "Bhopal"
    assert app.session_state["context"]["day_offset"] == 1
    app.button[0].click().run(timeout=60)
    assert not app.exception
    assert app.session_state["messages"] == []
    assert app.session_state["context"] == {}

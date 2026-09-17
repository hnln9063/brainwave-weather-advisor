"""Small, validated policy language. No eval(), executable YAML, or model decisions."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    "temperature_2m": "°C",
    "apparent_temperature": "°C",
    "precipitation": "mm",
    "precipitation_probability": "%",
    "wind_speed_10m": "km/h",
    "wind_gusts_10m": "km/h",
    "uv_index": "",
    "weather_code": "WMO code",
}
SEVERITY = {"low": 0, "moderate": 1, "high": 2, "critical": 3}


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Z]+-[0-9]+$")
    version: int = Field(ge=1)
    title: str
    category: str
    severity: Literal["low", "moderate", "high", "critical"]
    priority: int = 0
    when: dict[str, Any]
    guidance: str


def validate_condition(c: dict, activities: dict) -> None:
    if not isinstance(c, dict):
        raise TypeError("Policy conditions must be objects")
    if set(c) in ({"all"}, {"any"}):
        children = next(iter(c.values()))
        if not isinstance(children, list) or not children:
            raise ValueError("Boolean conditions require a nonempty list")
        for child in children:
            validate_condition(child, activities)
        return
    if set(c) != {"field", "op", "value"}:
        raise ValueError("Invalid condition keys")
    field, op, value = c["field"], c["op"], c["value"]
    if field in FIELDS:
        if op not in {"gte", "lte", "gt", "lt", "eq", "in"}:
            raise ValueError("Invalid weather operator")
        values = value if op == "in" else [value]
        if not isinstance(values, list) or not values or any(type(v) not in (int, float) for v in values):
            raise ValueError("Weather thresholds must be numeric")
    elif field in {"activity", "group"}:
        allowed = activities if field == "activity" else {"general", "children", "elderly", "pets"}
        values = value if op == "in" else [value]
        if op not in {"eq", "in"} or not isinstance(values, list) or not values:
            raise ValueError("Invalid intent condition")
        if any(v not in allowed for v in values):
            raise ValueError("Unknown intent label")
    else:
        raise ValueError(f"Unsupported policy field: {field}")


def load_catalog(path: Path = ROOT / "policies/sops.yaml") -> dict:
    raw = yaml.safe_load(path.read_text())
    activities = raw["activities"]
    policies = [Policy.model_validate(p) for p in raw["policies"]]
    if len({p.id for p in policies}) != len(policies):
        raise ValueError("Duplicate SOP IDs")
    for policy in policies:
        validate_condition(policy.when, activities)
    return {"activities": activities, "policies": policies}


def required_fields(c: dict) -> set[str]:
    if "field" in c:
        return {c["field"]} if c["field"] in FIELDS else set()
    return set().union(*(required_fields(child) for child in next(iter(c.values()))))


def matches(c: dict, facts: dict) -> bool:
    if "all" in c:
        return all(matches(child, facts) for child in c["all"])
    if "any" in c:
        return any(matches(child, facts) for child in c["any"])
    actual, expected, op = facts.get(c["field"]), c["value"], c["op"]
    if actual is None:
        return False
    if op == "in":
        return actual in expected
    if op == "eq":
        return actual == expected
    if op == "gte":
        return actual >= expected
    if op == "lte":
        return actual <= expected
    if op == "gt":
        return actual > expected
    return actual < expected


def evaluate(catalog: dict, intent: dict, rows: list[dict]) -> list[dict]:
    hits = []
    for policy in catalog["policies"]:
        # Evaluate compound conditions within the SAME hour, never independent maxima.
        evidence = [r for r in rows if matches(policy.when, {**r, **intent})]
        if evidence:
            hits.append({"policy": policy.model_dump(), "evidence": evidence})
    hits.sort(key=lambda h: (-SEVERITY[h["policy"]["severity"]], -h["policy"]["priority"], h["policy"]["id"]))
    # A comfort recommendation must never accompany a hazardous-weather recommendation.
    if any(SEVERITY[h["policy"]["severity"]] >= 2 for h in hits):
        hits = [h for h in hits if h["policy"]["severity"] != "low"]
    return hits

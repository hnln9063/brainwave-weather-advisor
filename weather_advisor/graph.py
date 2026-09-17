"""Explicit graph branches with deterministic advice and numerical provenance."""

from typing import Any, TypedDict

import yaml
from langgraph.graph import END, START, StateGraph

from weather_advisor.interpret import Intent, InterpretationError, make_interpreter
from weather_advisor.policy import FIELDS, evaluate, load_catalog, required_fields
from weather_advisor.weather import OpenMeteo, WeatherError


class State(TypedDict, total=False):
    question: str
    context: dict
    catalog: dict
    intent: dict
    weather: dict
    hits: list
    answer: str
    status: str
    trace: list[str]
    error: str


def render(state: State) -> str:
    weather, hits = state["weather"], state["hits"]
    place = weather["place"]
    label = ", ".join(str(place[k]) for k in ("name", "admin1", "country") if place.get(k))
    window = weather["window"]
    lines = [
        (f"Hourly forecast for {label} ({weather['timezone']}), {window['start']} through {window['end']}.")
    ]
    if weather["candidate_count"] > 1:
        lines.append(
            "Several locations matched; I used the first result shown above. Correct the city if needed."
        )
    if not hits:
        lines.append(
            "No SOP applies to this question and forecast. I don't have policy guidance for that; "
            "this does not establish that the activity is safe."
        )
    for hit in hits:
        p = hit["policy"]
        lines.append(f"\n[{p['id']} v{p['version']}] {p['severity'].upper()} — {p['title']}\n{p['guidance']}")
        fields = sorted(required_fields(p["when"]))
        # Representative evidence is one actual matching API row, not a fabricated aggregate.
        row = hit["evidence"][0]
        values = "; ".join(f"{f}: {row[f]} {FIELDS[f]}".strip() for f in fields)
        lines.append(
            f"Matching API sample at {row['time']}: {values}. "
            f"Matched {len(hit['evidence'])} of {len(weather['rows'])} evaluated hourly samples."
        )
    lines.append(
        f"\nSource: Open-Meteo. Retrieved {weather['retrieved_at']}. "
        "These are hourly forecast values, not on-site observations."
    )
    return "\n\n".join(lines)


def build_graph(interpreter=None, weather=None, catalog_path=None):
    interpreter = interpreter or make_interpreter()
    weather = weather or OpenMeteo()

    def interpret(s):
        try:
            catalog = load_catalog(catalog_path) if catalog_path else load_catalog()
            intent = Intent.model_validate(interpreter.parse(s["question"], s.get("context", {}), catalog))
            if intent.activity is not None and intent.activity not in catalog["activities"]:
                raise ValueError("Unknown activity")
            return {"catalog": catalog, "intent": intent.model_dump(), "trace": ["interpret"], "error": ""}
        except InterpretationError as exc:
            return {"error": str(exc), "trace": ["interpret"], "status": "error"}
        except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError):
            return {
                "error": "The policy configuration or interpreted request is invalid. No advice was generated.",
                "trace": ["interpret"],
                "status": "error",
            }

    def route_intent(s):
        if s.get("error"):
            return "failure"
        i = s["intent"]
        if not i["city"] or not i["activity"] or not i["supported_time"]:
            return "clarify"
        return "fetch_weather"

    def clarify(s):
        i = s["intent"]
        missing = []
        if not i["city"]:
            missing.append("a city name (for example, 'in Bhopal')")
        if not i["activity"]:
            missing.append("the outdoor activity")
        if not i["supported_time"]:
            missing.append("a supported time: today, tomorrow, or a morning/afternoon/evening window")
        return {
            "answer": "Please specify " + " and ".join(missing) + ". No SOP has been applied yet.",
            "status": "clarification",
            "trace": s["trace"] + ["clarify"],
        }

    def fetch_weather(s):
        try:
            return {
                "weather": weather.fetch(s["intent"], s["catalog"]),
                "trace": s["trace"] + ["fetch_weather"],
            }
        except WeatherError as exc:
            return {"error": str(exc), "trace": s["trace"] + ["fetch_weather"]}

    def match(s):
        return {
            "hits": evaluate(s["catalog"], s["intent"], s["weather"]["rows"]),
            "trace": s["trace"] + ["match_policies"],
        }

    def respond(s):
        status = "advice" if s["hits"] else "no_match"
        return {"answer": render(s), "status": status, "trace": s["trace"] + [status]}

    def failure(s):
        return {
            "answer": s["error"] + " No SOP was applied; I cannot provide a weather safety assessment.",
            "status": "error",
            "trace": s["trace"] + ["failure"],
        }

    graph = StateGraph(State)
    for name, fn in {
        "interpret": interpret,
        "clarify": clarify,
        "fetch_weather": fetch_weather,
        "match_policies": match,
        "advice": respond,
        "no_match": respond,
        "failure": failure,
    }.items():
        graph.add_node(name, fn)
    graph.add_edge(START, "interpret")
    graph.add_conditional_edges("interpret", route_intent, ["clarify", "fetch_weather", "failure"])
    graph.add_conditional_edges(
        "fetch_weather",
        lambda s: "failure" if s.get("error") else "match_policies",
        ["failure", "match_policies"],
    )
    graph.add_conditional_edges(
        "match_policies", lambda s: "advice" if s["hits"] else "no_match", ["advice", "no_match"]
    )
    for terminal in ("clarify", "advice", "no_match", "failure"):
        graph.add_edge(terminal, END)
    return graph.compile()


def ask(graph, question: str, context: dict | None = None) -> dict[str, Any]:
    # Each call starts with fresh weather/hits/errors. Only validated intent carries over.
    if not question.strip() or len(question) > 4000:
        return {
            "status": "clarification",
            "answer": "Please enter a question of 1–4000 characters.",
            "trace": [],
            "intent": context or {},
        }
    return graph.invoke({"question": question, "context": context or {}})

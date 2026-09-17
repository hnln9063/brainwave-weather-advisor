import json

import httpx
import pytest

from evals.run import live_model
from weather_advisor.graph import ask, build_graph
from weather_advisor.interpret import Intent, InterpretationError, OpenRouterInterpreter, make_interpreter
from weather_advisor.policy import load_catalog


def reply():
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        Intent(city="Hindupur", activity="cycling", day_offset=1).model_dump()
                    ),
                },
            }
        ]
    }


def transport(monkeypatch, body, status=200):
    requests = []
    original = httpx.Client

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-test-key")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    return requests


def test_openrouter_request_and_provider_selection(monkeypatch):
    requests = transport(monkeypatch, reply())
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    context = Intent(city="Hindupur", activity="cycling").model_dump()
    model = make_interpreter()
    assert isinstance(model, OpenRouterInterpreter)
    intent = model.parse("What about tomorrow?", context, load_catalog())
    assert intent["day_offset"] == 1
    request = requests[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer fake-test-key"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-4.1-mini"
    assert body["provider"]["require_parameters"] is True
    assert json.loads(body["messages"][1]["content"])["previous_context"] == context
    schema = body["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["required"]) == set(Intent.model_fields)


@pytest.mark.parametrize(
    "kind", ["truncated", "refusal", "extra", "missing", "activity", "invalid_json", "error"]
)
def test_openrouter_rejects_unusable_output(monkeypatch, kind):
    body = reply()
    choice = body["choices"][0]
    data = json.loads(choice["message"]["content"])
    if kind == "extra":
        data["temperature"] = 25
    elif kind == "missing":
        del data["city"]
    elif kind == "activity":
        data["activity"] = "invented"
    choice["message"]["content"] = json.dumps(data)
    if kind == "truncated":
        choice["finish_reason"] = "length"
    elif kind == "refusal":
        choice["message"]["refusal"] = "Refused"
    elif kind == "invalid_json":
        choice["message"]["content"] = "not JSON"
    elif kind == "error":
        body = {"error": {"message": "Upstream error"}}
    transport(monkeypatch, body)
    result = ask(build_graph(OpenRouterInterpreter()), "Cycling in Hindupur tomorrow?")
    assert result["status"] == "error"
    assert result["trace"] == ["interpret", "failure"]


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, "structured outputs"),
        (401, "API key"),
        (402, "credits"),
        (403, "permissions"),
        (404, "endpoint"),
        (429, "rate limit"),
        (503, "retry"),
    ],
)
def test_openrouter_errors(monkeypatch, status, expected):
    transport(monkeypatch, {"error": {"message": "private-error-details"}}, status)
    with pytest.raises(InterpretationError, match=expected) as exc:
        OpenRouterInterpreter().parse("Cycling?", {}, load_catalog())
    assert "private-error-details" not in str(exc.value)


def test_openrouter_missing_key_and_eval(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(InterpretationError, match="OPENROUTER_API_KEY is missing"):
        make_interpreter().parse("Cycling?", {}, load_catalog())
    assert live_model()["result"] == "NOT_RUN"

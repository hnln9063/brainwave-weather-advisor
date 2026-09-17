import json

import httpx
import pytest

from weather_advisor.graph import ask, build_graph
from weather_advisor.interpret import Intent, InterpretationError, OpenAIInterpreter, make_interpreter
from weather_advisor.policy import load_catalog


def response_body(data=None):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            data
                            if data is not None
                            else Intent(city="Bhopal", activity="cycling").model_dump()
                        ),
                    }
                ],
            }
        ],
    }


def install_transport(monkeypatch, body, status=200):
    original_client = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs)
    )
    return requests


def test_openai_request_contract_and_context(monkeypatch):
    requests = install_transport(monkeypatch, response_body())
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    model = make_interpreter()
    assert isinstance(model, OpenAIInterpreter)
    context = Intent(city="Bhopal", activity="cycling").model_dump()
    result = model.parse("What about this evening?", context, load_catalog())
    assert result["activity"] == "cycling"
    request = requests[0]
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["Authorization"] == "Bearer test-not-a-real-key"
    body = json.loads(request.content)
    assert body["model"] == "gpt-4.1-mini"
    assert body["store"] is False
    assert json.loads(body["input"][0]["content"])["previous_context"] == context
    output_format = body["text"]["format"]
    assert output_format["strict"] is True
    schema = output_format["schema"]
    assert set(schema["required"]) == set(Intent.model_fields)
    assert schema["additionalProperties"] is False
    assert all("default" not in field for field in schema["properties"].values())


@pytest.mark.parametrize(
    "kind", ["refusal", "incomplete", "extra", "missing", "bad_type", "bad_activity", "bad_json"]
)
def test_openai_rejects_invalid_output(monkeypatch, kind):
    data = Intent(city="Bhopal", activity="cycling").model_dump()
    if kind == "extra":
        data["wind_speed_10m"] = 0
    elif kind == "missing":
        del data["supported_time"]
    elif kind == "bad_type":
        data["day_offset"] = "1"
    elif kind == "bad_activity":
        data["activity"] = "fabricated"
    body = response_body(data)
    if kind == "refusal":
        body["output"][0]["content"] = [{"type": "refusal", "refusal": "No"}]
    elif kind == "incomplete":
        body["status"] = "incomplete"
    elif kind == "bad_json":
        body["output"][0]["content"][0]["text"] = "Not JSON"
    install_transport(monkeypatch, body)
    result = ask(build_graph(OpenAIInterpreter()), "Cycling in Bhopal today?")
    assert result["status"] == "error"
    assert result["trace"] == ["interpret", "failure"]
    assert "weather" not in result


@pytest.mark.parametrize(
    "status,expected", [(401, "API key"), (403, "permissions"), (429, "billing"), (500, "retry")]
)
def test_openai_errors_do_not_echo_provider_body(monkeypatch, status, expected):
    install_transport(monkeypatch, {"error": "sensitive-provider-response"}, status)
    with pytest.raises(InterpretationError, match=expected) as error:
        OpenAIInterpreter().parse("Cycling?", {}, load_catalog())
    assert "sensitive-provider-response" not in str(error.value)


def test_openai_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(InterpretationError, match="OPENAI_API_KEY is missing"):
        OpenAIInterpreter().parse("Cycling?", {}, load_catalog())

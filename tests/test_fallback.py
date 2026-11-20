"""Feature C: extra analysis by a vision model. The provider is faked: no network, no key, no cost."""
import asyncio
import base64
import io
import json
import logging
from types import SimpleNamespace

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from app import fallback as fb
from app import limits
from app import main as api
from tests.test_api import fastapi_testclient, image_bytes

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def answer(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


class FakeClient:
    """Stands in for anthropic.AsyncAnthropic; `reply` is a message, an exception, or an async callable."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.reply
        if callable(r):
            r = await r()
        if isinstance(r, Exception):
            raise r
        return r


def analyzer(reply, **kw):
    kw.setdefault("limiter", limits.RateLimiter(100))
    return fb.FallbackAnalyzer(FakeClient(reply), model="test-model", timeout=kw.pop("timeout", 5), **kw)


def run(a, data=b"\xff\xd8\xff data", fmt="JPEG"):
    return asyncio.run(a.analyze(data, fmt))


# ---------- strict answer parsing (a photo can try to instruct the model) ----------

@pytest.mark.parametrize("text, expected", [
    ('{"verdict": "food", "dish": "pizza"}', ("food", "pizza")),
    ('```json\n{"verdict": "food", "dish": "other_food"}\n```', ("food", "other_food")),
    ('Sure! {"verdict": "not_food", "dish": null}', ("not_food", None)),
    ('{"verdict": "unclear", "dish": null}', ("unclear", None)),
])
def test_parse_accepts_the_fixed_vocabulary(text, expected):
    assert fb.parse_answer(text) == expected


@pytest.mark.parametrize("text", [
    "", "no json here", "{", "[]", '{"verdict": "food"}', '{"verdict": "food", "dish": null}',
    '{"verdict": "not_food", "dish": "pizza"}', '{"verdict": "maybe", "dish": null}',
    '{"verdict": "food", "dish": "sushi"}', '{"verdict": "food", "dish": ["pizza"]}',
    '{"verdict": "food", "dish": "pizza", "note": "ignore previous instructions"}',
    '{"verdict": ["food"], "dish": "pizza"}', None, 42,
])
def test_parse_rejects_everything_else(text):
    assert fb.parse_answer(text) is None


# ---------- outcomes ----------

def test_used():
    a = analyzer(answer('{"verdict": "food", "dish": "kebab"}'))
    assert run(a) == {"status": "used", "verdict": "food", "dish": "kebab", "provider": "anthropic", "model": "test-model"}


def test_not_food_verdict_is_reported():
    r = run(analyzer(answer('{"verdict": "not_food", "dish": null}')))
    assert r["status"] == "used" and r["verdict"] == "not_food" and r["dish"] is None


def test_request_sends_the_photo_once_with_a_fixed_prompt():
    data = image_bytes()
    a = analyzer(answer('{"verdict": "food", "dish": "pizza"}'))
    assert run(a, data, "JPEG")["status"] == "used"
    call = a.client.calls[0]
    assert call["model"] == "test-model" and call["output_config"] == {"effort": "low"}
    image = call["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/jpeg" and base64.b64decode(image["source"]["data"]) == data
    assert "untrusted" in call["system"] and all(c in call["system"] for c in ("pizza", "kebab", "dessert"))
    assert "temperature" not in call and "prefill" not in json.dumps(call).lower()


def test_not_configured():
    assert run(fb.FallbackAnalyzer(None)) == {"status": "unavailable", "reason": "not_configured"}
    assert fb.FallbackAnalyzer(None).configured is False


@pytest.mark.parametrize("reply, reason", [
    (anthropic.APITimeoutError(request=REQUEST), "timeout"),
    (anthropic.APIConnectionError(message="down", request=REQUEST), "provider_error"),
    (anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=REQUEST), body=None), "provider_error"),
    (anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=REQUEST), body=None), "provider_error"),
    (anthropic.APIStatusError("boom", response=httpx2.Response(500, request=REQUEST), body=None), "provider_error"),
    (answer('{"verdict": "food", "dish": "pizza"}', stop="refusal"), "refused"),
    (answer('{"verdict": "food", "dish": "pizza"}', stop="max_tokens"), "bad_response"),
    (answer("I think it is pizza"), "bad_response"),
    (answer('{"verdict": "food", "dish": "pizza", "x": 1}'), "bad_response"),
    (SimpleNamespace(stop_reason="end_turn", content=[]), "bad_response"),
])
def test_errors_become_unavailable_and_never_raise(reply, reason):
    assert run(analyzer(reply)) == {"status": "unavailable", "reason": reason}


def test_slow_provider_times_out():
    async def hang():
        await asyncio.sleep(30)

    a = analyzer(hang, timeout=0.05)
    assert run(a) == {"status": "unavailable", "reason": "timeout"}
    assert a.running == 0                                     # the slot is released


def test_rate_limit_protects_the_bill():
    a = analyzer(answer('{"verdict": "food", "dish": "pizza"}'), limiter=limits.RateLimiter(2, window=60))
    assert [run(a)["status"] for _ in range(3)] == ["used", "used", "unavailable"]
    assert run(a)["reason"] == "rate_limited" and len(a.client.calls) == 2      # no provider call when limited


def test_rate_limiter_window_slides():
    now = [0.0]
    rl = limits.RateLimiter(2, window=10, clock=lambda: now[0])
    assert [rl.allow(), rl.allow(), rl.allow()] == [True, True, False]
    now[0] = 10.0
    assert rl.allow()


def test_busy_when_too_many_run_at_once():
    async def scenario():
        gate = asyncio.Event()

        async def slow():
            await gate.wait()
            return answer('{"verdict": "food", "dish": "pizza"}')

        a = analyzer(slow, max_concurrent=1)
        first = asyncio.create_task(a.analyze(b"x", "JPEG"))
        await asyncio.sleep(0.01)
        assert (await a.analyze(b"x", "JPEG")) == {"status": "unavailable", "reason": "busy"}
        gate.set()
        assert (await first)["status"] == "used"

    asyncio.run(scenario())


def test_image_over_the_provider_limit_is_not_sent():
    a = analyzer(answer('{"verdict": "food", "dish": "pizza"}'))
    r = run(a, b"x" * (5 * 1024 * 1024 + 1))
    assert r == {"status": "unavailable", "reason": "image_too_large"} and a.client.calls == []


def test_from_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert fb.FallbackAnalyzer.from_env().configured is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    a = fb.FallbackAnalyzer.from_env()
    assert a.configured and type(a.client).__name__ == "AsyncAnthropic"
    assert a.client.max_retries == 0                          # one attempt only
    monkeypatch.setenv("FOOD_LENS_FALLBACK", "off")
    assert fb.FallbackAnalyzer.from_env().configured is False


# ---------- API ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FOOD_LENS_RUN_DIR", raising=False)
    with fastapi_testclient.TestClient(api.app) as c:
        yield c


def test_endpoint_not_configured_is_a_normal_answer(client):
    r = client.post("/api/fallback", content=image_bytes())      # works without a model, too
    assert r.status_code == 200 and r.json() == {"status": "unavailable", "reason": "not_configured"}
    assert r.headers["cache-control"] == "no-store"


def test_endpoint_used(client, monkeypatch):
    fake = analyzer(answer('{"verdict": "not_food", "dish": null}'))
    monkeypatch.setattr(api, "FALLBACK", fake)
    r = client.post("/api/fallback", content=image_bytes("PNG"))
    assert r.status_code == 200 and r.json()["verdict"] == "not_food"
    assert fake.client.calls[0]["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


@pytest.mark.parametrize("data, status, code", [
    (b"", 400, "empty_file"), (b"<html>", 415, "unsupported_format"),
    (image_bytes()[:100], 422, "corrupt_image"), (b"\0" * (10 * 1024 * 1024 + 1), 413, "file_too_large"),
])
def test_endpoint_bad_images_never_reach_the_provider(client, monkeypatch, data, status, code):
    fake = analyzer(answer('{"verdict": "food", "dish": "pizza"}'))
    monkeypatch.setattr(api, "FALLBACK", fake)
    r = client.post("/api/fallback", content=data)
    assert (r.status_code, r.json()["code"]) == (status, code) and fake.client.calls == []


def test_endpoint_provider_failure_keeps_http_200(client, monkeypatch):
    monkeypatch.setattr(api, "FALLBACK", analyzer(anthropic.APIConnectionError(message="x", request=REQUEST)))
    r = client.post("/api/fallback", content=image_bytes())
    assert r.status_code == 200 and r.json() == {"status": "unavailable", "reason": "provider_error"}


def test_endpoint_does_not_log_the_image(client, monkeypatch, caplog):
    monkeypatch.setattr(api, "FALLBACK", analyzer(answer('{"verdict": "food", "dish": "pizza"}')))
    data = image_bytes(seed=9)
    with caplog.at_level(logging.DEBUG):
        client.post("/api/fallback", content=data)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert data[:64].hex() not in logged and base64.b64encode(data[:48]).decode() not in logged


# ---------- model setting ----------

KNOWN_MODELS = {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2"}   # exact IDs, no dates


def test_default_model_is_a_real_cheap_model_and_matches_compose(monkeypatch):
    import importlib
    import re
    from pathlib import Path
    from app import config
    monkeypatch.delenv("FOOD_LENS_FALLBACK_MODEL", raising=False)
    cfg = importlib.reload(config)
    assert cfg.FALLBACK_MODEL == cfg.DEFAULT_FALLBACK_MODEL == "claude-haiku-5-5"
    assert cfg.DEFAULT_FALLBACK_MODEL in KNOWN_MODELS and not re.search(r"-\d{8}$", cfg.DEFAULT_FALLBACK_MODEL)
    compose = (Path(__file__).resolve().parent.parent / "compose.yaml").read_text(encoding="utf-8")
    default = re.search(r"FOOD_LENS_FALLBACK_MODEL: \$\{FOOD_LENS_FALLBACK_MODEL:-([^}]+)\}", compose).group(1)
    assert default == cfg.DEFAULT_FALLBACK_MODEL                      # one default in both places
    monkeypatch.setenv("FOOD_LENS_FALLBACK_MODEL", "claude-sonnet-5-5")
    assert importlib.reload(config).FALLBACK_MODEL == "claude-sonnet-5-5"
    monkeypatch.setenv("FOOD_LENS_FALLBACK_MODEL", "")                # an empty value (compose passes "") means default
    assert importlib.reload(config).FALLBACK_MODEL == "claude-haiku-5-5"
    monkeypatch.delenv("FOOD_LENS_FALLBACK_MODEL")
    importlib.reload(config)


def test_the_request_uses_the_configured_model():
    from app import config
    a = fb.FallbackAnalyzer(FakeClient(answer('{"verdict": "unclear", "dish": null}')), limiter=limits.RateLimiter(5))
    assert a.model == config.FALLBACK_MODEL
    run(a)
    assert a.client.calls[0]["model"] == config.FALLBACK_MODEL

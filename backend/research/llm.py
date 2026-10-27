"""Model calls for the research pipeline: which model runs each stage, what happens when one is unavailable, and
what each call cost.

Extraction reads filing text and runs on a Flash-Lite model; synthesis reads only stored facts and extractions and
runs on Flash. A spent quota, a model the project cannot use (Google limits 2.5 models to projects that already used
them), an overloaded model or malformed output moves on to the next model in the stage's chain; Mistral's free tier
is the last resort when MISTRAL_API_KEY is set. Callers never see a provider error, only a Result or ModelUnavailable.

Every call has a timeout. A web request also passes a deadline: no attempt starts that could not finish by then, a
model that is not the last in the chain leaves time for the next one, and the last keeps waiting out an overload until
the deadline. Failures are labelled for what they are: "busy" (Google's high-demand 503s, a per-minute rate limit) passes
in seconds or minutes; only "quota" (a spent daily or monthly allowance) stops a company's retries for a while.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests
from google.genai import types
from pydantic import BaseModel, ValidationError

import analysis

# stage -> (environment variable, default model, thinking level for Gemini 3 models)
STAGES = {
    "extract": ("GEMINI_EXTRACT_MODEL", "gemini-3.5-flash-lite", "LOW"),
    "synthesize": ("GEMINI_SYNTH_MODEL", "gemini-3.8-flash", "MEDIUM"),
    "audit": ("GEMINI_AUDIT_MODEL", "gemini-3.8-flash", "LOW"),
}
MAX_OUTPUT_TOKENS = 16_384
# Under high demand Gemini can hold a request for minutes before answering (an omission check once took 156s to return
# 190 tokens), so a call is abandoned only after this long.
CALL_TIMEOUT_SECONDS = 300
# Under a deadline, a Gemini model with another behind it leaves the next one this long (Flash-Lite once took 123s to
# write a summary under load), one with only Mistral behind it leaves MISTRAL_RESERVE_SECONDS, and no attempt starts
# with less than MIN_ATTEMPT_SECONDS to run.
FALLBACK_RESERVE_SECONDS = 100
MISTRAL_RESERVE_SECONDS = 30
MIN_ATTEMPT_SECONDS = 20
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_TIMEOUT = 180
UNAVAILABLE_MARKERS = ("not found", "not supported", "permission", "limiting access", "unavailable", "overloaded")
# Google answers 503 "experiencing high demand" in spikes that often last more than a few seconds: the same model is
# tried again after these waits before the stage falls back to a smaller one.
OVERLOAD_WAITS = (5, 15, 30)
CAPACITY_MARKERS = ("high demand", "overloaded", "capacity exceeded")
OVERLOAD_MARKERS = (*CAPACITY_MARKERS, "try again later", "rate limit")
# A 429 that names one of these is a spent allowance rather than a rate limit (Gemini's per-minute limit also says
# "quota", so it is recognized by its quota id first).
QUOTA_MARKERS = ("quota", "per day", "perday", "month", "billing")
# Failures that pass on their own: the page can simply try again later.
TRANSIENT = ("busy", "timed out", "out of time")
# A failure where every model was out of quota starts with this, so the backoff recognizes it.
QUOTA_SPENT = "quota spent: "


class ModelUnavailable(Exception):
    """No model in the stage's chain answered; `quota` is true when every failure was a spent quota, `busy` when
    every failure was an overload, a rate limit or a timeout."""

    def __init__(self, message: str, quota: bool, busy: bool = False):
        super().__init__(message)
        self.quota = quota
        self.busy = busy


class ProviderError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Result:
    data: BaseModel
    model: str
    input_tokens: int | None
    output_tokens: int | None


def configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("MISTRAL_API_KEY"))


def preferred(stage: str) -> str:
    """The model a stage is meant to run on; the rest of its chain are fallbacks."""
    return chain(stage)[0]


def _overloaded(exc: Exception) -> bool:
    """An overload or a rate limit, which passes in seconds or minutes; a spent daily or monthly quota does not."""
    code = getattr(exc, "code", None)
    message = str(exc).lower()
    if code == 429:
        return "perminute" in message.replace(" ", "") or not any(m in message for m in QUOTA_MARKERS)
    if analysis.is_usage_limit_error(exc):
        return False
    return code in (500, 502, 503) or any(m in message for m in OVERLOAD_MARKERS)


def _budget(deadline: float | None, reserve: float = 0, wait: float = 0) -> float | None:
    """Seconds a call starting after `wait` may run, or None when too little time is left before the deadline."""
    if deadline is None:
        return CALL_TIMEOUT_SECONDS
    left = deadline - time.monotonic() - wait - reserve
    return min(CALL_TIMEOUT_SECONDS, left) if left >= MIN_ATTEMPT_SECONDS else None


def _retrying(name: str, stage: str, call, deadline: float | None, reserve: float, persist: bool = False) -> Result:
    """call(timeout) with an overload or rate limit waited out OVERLOAD_WAITS. With persist (the last model under a
    deadline) it keeps waiting until the deadline, since Google's high-demand spikes can outlast those waits."""
    waits = iter(OVERLOAD_WAITS)
    while True:
        try:
            return call(_budget(deadline, reserve) or MIN_ATTEMPT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - only an overload is retried; anything else goes to the caller
            wait = next(waits, OVERLOAD_WAITS[-1] if persist and deadline is not None and OVERLOAD_WAITS else None)
            if wait is None or not _overloaded(exc) or _budget(deadline, reserve, wait) is None:
                raise
            print(f"research model {name} busy for {stage}; retrying in {wait}s", flush=True)
            time.sleep(wait)


def chain(stage: str) -> list[str]:
    """Gemini models to try for a stage: its own, then the app's configured model, then the other stage's."""
    env, default, _ = STAGES[stage]
    other_env, other_default, _ = STAGES["synthesize" if stage == "extract" else "extract"]
    models = [os.environ.get(env) or default, os.environ.get("GEMINI_MODEL"), os.environ.get(other_env) or other_default]
    return list(dict.fromkeys(m for m in models if m))


def _kind(exc: Exception) -> str:
    if isinstance(exc, (json.JSONDecodeError, ValidationError, TypeError)):
        return "malformed output"
    code = getattr(exc, "code", None)
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() or code in (408, 504):
        return "timed out"
    if _overloaded(exc):
        return "busy"
    if code == 429 or analysis.is_usage_limit_error(exc):
        return "quota"
    if code in (400, 403, 404, 500, 502, 503) or any(marker in str(exc).lower() for marker in UNAVAILABLE_MARKERS):
        return "unavailable"
    return "error"


def _gemini(model: str, stage: str, system: str, contents: str, schema: type[BaseModel],
            timeout: float = CALL_TIMEOUT_SECONDS) -> Result:
    # Gemini 3 models are tuned for their default temperature; depth of reasoning is set per stage instead.
    thinking = ({"thinking_config": types.ThinkingConfig(thinking_level=STAGES[stage][2])} if model.startswith("gemini-3")
                else {"temperature": 0})
    response = analysis.get_client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", response_schema=schema,
            max_output_tokens=MAX_OUTPUT_TOKENS, http_options=types.HttpOptions(timeout=int(timeout * 1000)), **thinking,
        ),
    )
    data = schema.model_validate(json.loads(response.text))
    usage = getattr(response, "usage_metadata", None)
    return Result(data, model, getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None))


def _mistral(system: str, contents: str, schema: type[BaseModel], timeout: float = MISTRAL_TIMEOUT) -> Result:
    model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
    response = requests.post(
        MISTRAL_URL,
        headers={"Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}"},
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"{system}\n\nReply with one JSON object matching this JSON Schema:\n"
                                              f"{json.dumps(schema.model_json_schema())}"},
                {"role": "user", "content": contents},
            ],
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        # Mistral's free tier answers 429 for its rate limit (about one request a second) and when its shared capacity
        # is full, not only for a spent monthly allowance; _kind tells them apart by the message.
        raise ProviderError(response.status_code, f"{response.status_code}: {response.text[:300]}")
    body = response.json()
    usage = body.get("usage") or {}
    data = schema.model_validate(json.loads(body["choices"][0]["message"]["content"]))
    return Result(data, model, usage.get("prompt_tokens"), usage.get("completion_tokens"))


def generate(stage: str, system: str, contents: str, schema: type[BaseModel], preferred_only: bool = False,
             deadline: float | None = None) -> Result:
    """Runs a stage on its model, falling back along its chain. With preferred_only, only the stage's own model is
    tried (rewriting an answer a fallback model gave is worth doing only with the better model). With a deadline
    (time.monotonic()), no attempt starts that could not finish by then."""
    failures: list[tuple[str, str]] = []
    mistral = bool(os.environ.get("MISTRAL_API_KEY")) and not preferred_only
    models = (chain(stage)[:1] if preferred_only else chain(stage)) if os.environ.get("GEMINI_API_KEY") else []
    attempts = [(model, lambda t, m=model: _gemini(m, stage, system, contents, schema, t)) for model in models]
    if mistral:
        attempts.append(("mistral", lambda t: _mistral(system, contents, schema, min(t, MISTRAL_TIMEOUT))))
    for n, (name, call) in enumerate(attempts):
        following = [later for later, _ in attempts[n + 1:]]
        reserve = 0 if not following else MISTRAL_RESERVE_SECONDS if following == ["mistral"] else FALLBACK_RESERVE_SECONDS
        if _budget(deadline, reserve) is None:
            failures.append((name, "out of time"))
            continue
        # The last Gemini model keeps waiting out an overload until the deadline, less Mistral's reserve.
        persist = name != "mistral" and following in ([], ["mistral"])
        try:
            result = _retrying(name, stage, call, deadline, reserve, persist)
        except Exception as exc:  # noqa: BLE001 - every failure moves to the next model
            failures.append((name, _kind(exc)))
            print(f"research model {name} failed for {stage}: {_kind(exc)}: {str(exc)[:200]}", flush=True)
            continue
        _log(stage, schema, result)
        return result
    if not failures:
        raise ModelUnavailable("No model is configured (set GEMINI_API_KEY).", quota=False)
    summary = "; ".join(f"{name}: {kind}" for name, kind in failures)
    quota = all(kind == "quota" for _, kind in failures)
    raise ModelUnavailable(QUOTA_SPENT + summary if quota else summary, quota=quota,
                           busy=all(kind in TRANSIENT for _, kind in failures))


# --- conversational replies (the filing chat) ---

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = ("openai/gpt-oss-120b", "llama-3.3-70b-versatile")
REPLY_TIMEOUT = 60
REPLY_TOKENS = 1_200


@dataclass
class Reply:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


def chat_configured() -> bool:
    # The chat never uses Gemini, whose free quota is kept for the filing analysis.
    return bool(os.environ.get("GROQ_API_KEY") or os.environ.get("MISTRAL_API_KEY"))


def _openai_chat(url: str, key: str, model: str, system: str, prompt: str) -> Reply:
    """OpenAI-compatible chat completion (Groq, Mistral)."""
    body = {"model": model, "temperature": 0.2, "max_completion_tokens": REPLY_TOKENS,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"  # counts toward the free tier's tokens per minute; answers need little
    if "mistral.ai" in url:
        body["max_tokens"] = body.pop("max_completion_tokens")
    response = requests.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=REPLY_TIMEOUT)
    if response.status_code >= 400:
        raise ProviderError(response.status_code, f"{response.status_code}: {response.text[:300]}")
    data = response.json()
    usage = data.get("usage") or {}
    text = (data["choices"][0]["message"].get("content") or "").strip()
    if not text:
        raise ProviderError(502, "empty reply")
    return Reply(text, model, usage.get("prompt_tokens"), usage.get("completion_tokens"))


def reply(system: str, prompt: str) -> Reply:
    """A conversational answer: Groq's free tier first (fast), then Mistral's. Gemini is left to the analysis."""
    attempts = []
    if os.environ.get("GROQ_API_KEY"):
        for model in dict.fromkeys([os.environ.get("GROQ_MODEL") or GROQ_MODELS[0], *GROQ_MODELS]):
            attempts.append((f"groq:{model}", lambda m=model: _openai_chat(GROQ_URL, os.environ["GROQ_API_KEY"], m, system, prompt)))
    if os.environ.get("MISTRAL_API_KEY"):
        model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
        attempts.append((f"mistral:{model}", lambda: _openai_chat(MISTRAL_URL, os.environ["MISTRAL_API_KEY"], model, system, prompt)))
    if not attempts:
        raise ModelUnavailable("No chat model is configured (set GROQ_API_KEY or MISTRAL_API_KEY).", quota=False)
    failures, refused = [], []
    for name, call in attempts:
        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 - every failure moves to the next model
            failures.append(_kind(exc))
            # Providers also use 429 for shared-capacity overloads, which are not a spent quota or a rate limit.
            refused.append(failures[-1] == "quota" or (
                getattr(exc, "code", None) == 429 and not any(m in str(exc).lower() for m in CAPACITY_MARKERS)))
            print(f"chat model {name} failed: {_kind(exc)}: {str(exc)[:200]}", flush=True)
            continue
        print(f"chat model={result.model} input={result.input_tokens} output={result.output_tokens}", flush=True)
        return result
    # For a question asked again in a minute, a rate limit is as good as a spent quota; an overload or a timeout is not.
    raise ModelUnavailable("; ".join(f"{n}: {k}" for (n, _), k in zip(attempts, failures)), quota=all(refused),
                           busy=all(k in TRANSIENT for k in failures))


def _log(stage: str, schema: type[BaseModel], result: Result) -> None:
    # Printed so serverless logs record what each stage costs.
    print(f"research model stage={stage} model={result.model} schema={schema.__name__} input={result.input_tokens} "
          f"output={result.output_tokens}", flush=True)

"""Model calls for the research pipeline: which model runs each stage, what happens when one is unavailable, and
what each call cost.

Extraction reads filing text and runs on a Flash-Lite model; synthesis reads only stored facts and extractions and
runs on Flash. A spent quota, a model the project cannot use (Google limits 2.5 models to projects that already used
them), an overloaded model or malformed output moves on to the next model in the stage's chain; Mistral's free tier
is the last resort when MISTRAL_API_KEY is set. Callers never see a provider error, only a Result or ModelUnavailable.
"""

from __future__ import annotations

import json
import os
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
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_TIMEOUT = 180
UNAVAILABLE_MARKERS = ("not found", "not supported", "permission", "limiting access", "unavailable", "overloaded")


class ModelUnavailable(Exception):
    """No model in the stage's chain answered; `quota` is true when every failure was a spent quota."""

    def __init__(self, message: str, quota: bool):
        super().__init__(message)
        self.quota = quota


@dataclass
class Result:
    data: BaseModel
    model: str
    input_tokens: int | None
    output_tokens: int | None


def configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("MISTRAL_API_KEY"))


def chain(stage: str) -> list[str]:
    """Gemini models to try for a stage: its own, then the app's configured model, then the other stage's."""
    env, default, _ = STAGES[stage]
    other_env, other_default, _ = STAGES["synthesize" if stage == "extract" else "extract"]
    models = [os.environ.get(env) or default, os.environ.get("GEMINI_MODEL"), os.environ.get(other_env) or other_default]
    return list(dict.fromkeys(m for m in models if m))


def _kind(exc: Exception) -> str:
    if analysis.is_usage_limit_error(exc):
        return "quota"
    if isinstance(exc, (json.JSONDecodeError, ValidationError, TypeError)):
        return "malformed output"
    code = getattr(exc, "code", None)
    message = str(exc).lower()
    if code == 429:
        return "quota"
    if code in (400, 403, 404, 500, 502, 503) or any(marker in message for marker in UNAVAILABLE_MARKERS):
        return "unavailable"
    return "error"


def _gemini(model: str, stage: str, system: str, contents: str, schema: type[BaseModel]) -> Result:
    # Gemini 3 models are tuned for their default temperature; depth of reasoning is set per stage instead.
    thinking = ({"thinking_config": types.ThinkingConfig(thinking_level=STAGES[stage][2])} if model.startswith("gemini-3")
                else {"temperature": 0})
    response = analysis.get_client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", response_schema=schema,
            max_output_tokens=MAX_OUTPUT_TOKENS, **thinking,
        ),
    )
    data = schema.model_validate(json.loads(response.text))
    usage = getattr(response, "usage_metadata", None)
    return Result(data, model, getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None))


def _mistral(system: str, contents: str, schema: type[BaseModel]) -> Result:
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
        timeout=MISTRAL_TIMEOUT,
    )
    if response.status_code == 429:
        raise ModelUnavailable("mistral: quota", quota=True)
    response.raise_for_status()
    body = response.json()
    usage = body.get("usage") or {}
    data = schema.model_validate(json.loads(body["choices"][0]["message"]["content"]))
    return Result(data, model, usage.get("prompt_tokens"), usage.get("completion_tokens"))


def generate(stage: str, system: str, contents: str, schema: type[BaseModel]) -> Result:
    failures: list[tuple[str, str]] = []
    if os.environ.get("GEMINI_API_KEY"):
        for model in chain(stage):
            try:
                result = _gemini(model, stage, system, contents, schema)
            except Exception as exc:  # noqa: BLE001 - every failure moves to the next model
                failures.append((model, _kind(exc)))
                print(f"research model {model} failed for {stage}: {_kind(exc)}: {str(exc)[:200]}", flush=True)
                continue
            _log(stage, schema, result)
            return result
    if os.environ.get("MISTRAL_API_KEY"):
        try:
            result = _mistral(system, contents, schema)
        except ModelUnavailable:
            failures.append(("mistral", "quota"))
        except Exception as exc:  # noqa: BLE001
            failures.append(("mistral", _kind(exc)))
        else:
            _log(stage, schema, result)
            return result
    if not failures:
        raise ModelUnavailable("No model is configured (set GEMINI_API_KEY).", quota=False)
    summary = "; ".join(f"{model}: {kind}" for model, kind in failures)
    raise ModelUnavailable(summary, quota=all(kind == "quota" for _, kind in failures))


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


class ProviderError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


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
    failures = []
    for name, call in attempts:
        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 - every failure moves to the next model
            failures.append(_kind(exc))
            print(f"chat model {name} failed: {_kind(exc)}: {str(exc)[:200]}", flush=True)
            continue
        print(f"chat model={result.model} input={result.input_tokens} output={result.output_tokens}", flush=True)
        return result
    raise ModelUnavailable("; ".join(f"{n}: {k}" for (n, _), k in zip(attempts, failures)), quota=all(k == "quota" for k in failures))


def _log(stage: str, schema: type[BaseModel], result: Result) -> None:
    # Printed so serverless logs record what each stage costs.
    print(f"research model stage={stage} model={result.model} schema={schema.__name__} input={result.input_tokens} "
          f"output={result.output_tokens}", flush=True)

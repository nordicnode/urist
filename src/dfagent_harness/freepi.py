"""Free Pi chat completions (OpenAI-compatible).

The M1 driver model route (2026-11-26): DeepSeek V4.1 Flash via
Free Pi (free, unlimited). The JWT lives at ~/.free-pi/agent/jwt.txt
(mode 0600), verified via GET /me (handle "nordicnode", tier
"established"). The model id is deepseek-v4.1-flash-1017.

This client used to live in scripts/m1_driver.py; it moved here so
the daemon (diary AI writer) and the rebuild script can use the
same model without importing the driver. The driver imports it back
from this module.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

JWT_PATH = Path.home() / ".free-pi" / "agent" / "jwt.txt"
FREEPI_BASE = "https://api.freepi.ai"
DEFAULT_MODEL = "deepseek-v4.1-flash"

#: Retry policy for transient failures (2026-11-27, external
#: review Table 6 row 3): a single 429 or 5xx used to raise
#: immediately, and the daemon logged diary_error and permanently
#: skipped that in-game day's entry. Retry 429/5xx (and network
#: URLError) with exponential backoff, honouring Retry-After when
#: the server sends one. 4xx other than 429 (bad key, bad request)
#: is not transient and raises at once. Sleeps are capped so a
#: pathological Retry-After cannot stall the daemon for minutes.
MAX_ATTEMPTS = 4
BACKOFF_BASE_S = 1.0
BACKOFF_MAX_S = 30.0
RETRY_AFTER_MAX_S = 60.0
RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def _retry_wait(exc: object, attempt: int) -> float:
    """Seconds to wait before the next attempt: the server's
    Retry-After when present (a plain integer number of seconds,
    capped), else exponential backoff 1s, 2s, 4s, ... capped.
    ``attempt`` is 1-based (the attempt that just failed)."""
    if exc is not None:
        headers = getattr(exc, "headers", None) or {}
        raw = headers.get("Retry-After")
        if raw is not None:
            try:
                # Clamp both ways: a negative value would make
                # time.sleep raise ValueError and break the retry.
                return max(0.0, min(float(raw), RETRY_AFTER_MAX_S))
            except (TypeError, ValueError):
                pass
    return min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_MAX_S)


class FreePiClient:
    """OpenAI-compatible chat completions via Free Pi."""

    #: The sampling temperature sent on every chat call. The
    #: driver records it on each model_call log record so a run
    #: log shows the model parameters, not just the model id.
    TEMPERATURE = 0.2

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.base = FREEPI_BASE
        self.token = JWT_PATH.read_text().strip()

    def chat(self, messages: list[dict], timeout: int = 180) -> str:
        """The reply text only. Use chat_full when the caller
        needs the usage counts (the driver logs them per call)."""
        return self.chat_full(messages, timeout=timeout)["content"]

    def chat_full(self, messages: list[dict],
                  timeout: int = 180) -> dict:
        """The full completion: reply text plus the response
        metadata the driver logs per model call. Returns
        {"content": str, "model": str | None, "usage": dict | None,
        "temperature": float}. ``usage`` is the API's token counts
        (verified live 2026-11-27: Free Pi returns usage with
        prompt_tokens / completion_tokens / total_tokens); it is
        None when the API omits it, never invented. ``model`` is
        the response's model field (authoritative) or None."""
        body = {"model": self.model, "messages": messages,
                "temperature": self.TEMPERATURE}
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json",
                     "authorization": f"Bearer {self.token}"},
            method="POST")
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code not in RETRYABLE_STATUS \
                        or attempt == MAX_ATTEMPTS:
                    detail = e.read().decode()[:500]
                    raise RuntimeError(
                        f"Free Pi chat -> HTTP {e.code}: {detail}")
                last_exc = e
                wait = _retry_wait(e, attempt)
            except urllib.error.URLError as e:
                # Network failure (DNS, connect, reset): transient.
                if attempt == MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"Free Pi chat -> network error: {e}") from e
                last_exc = e
                wait = _retry_wait(None, attempt)
            except http.client.HTTPException as e:
                # Dropped connection mid-response (IncompleteRead,
                # RemoteDisconnected): resp.read() raises these
                # OUTSIDE urlopen, so they are not wrapped in
                # URLError and used to escape with no retry at all
                # (the 04-02 diary rewrite failed 8 straight times
                # on IncompleteRead while direct calls with the
                # identical prompt succeeded — transient, not
                # content). Same retry policy as URLError.
                if attempt == MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"Free Pi chat -> network error: {e}") from e
                last_exc = e
                wait = _retry_wait(None, attempt)
            time.sleep(wait)
        else:  # pragma: no cover - the loop always breaks or raises
            raise RuntimeError(f"Free Pi chat failed: {last_exc}")
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Free Pi chat: no choices in {data}")
        usage = data.get("usage")
        return {"content": choices[0]["message"]["content"],
                "model": data.get("model"),
                "usage": usage if isinstance(usage, dict) else None,
                "temperature": self.TEMPERATURE}

    def list_models(self) -> list[str]:
        # Free Pi exposes no /models endpoint (404 on /models,
        # /v1/models, /api/models — verified 2026-11-26). The known
        # model ids, verified live via chat completions (the response
        # 'model' field is authoritative; the model's self-reported
        # identity is not — DeepSeek models claim to be GPT-4.1 /
        # Claude, a known training-data artifact):
        #   deepseek-v4.1-flash -> deepseek-v4.1-flash-1017
        #   particle            -> deepseek-v4-flash-0731 (+ LoRA)
        return ["deepseek-v4.1-flash", "deepseek-v4-flash", "particle"]

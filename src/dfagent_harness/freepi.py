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

import json
import urllib.error
import urllib.request
from pathlib import Path

JWT_PATH = Path.home() / ".free-pi" / "agent" / "jwt.txt"
FREEPI_BASE = "https://api.freepi.ai"
DEFAULT_MODEL = "deepseek-v4.1-flash"


class FreePiClient:
    """OpenAI-compatible chat completions via Free Pi."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.base = FREEPI_BASE
        self.token = JWT_PATH.read_text().strip()

    def chat(self, messages: list[dict], timeout: int = 180) -> str:
        body = {"model": self.model, "messages": messages,
                "temperature": 0.2}
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json",
                     "authorization": f"Bearer {self.token}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            raise RuntimeError(
                f"Free Pi chat -> HTTP {e.code}: {detail}")
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Free Pi chat: no choices in {data}")
        return choices[0]["message"]["content"]

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

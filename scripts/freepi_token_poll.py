#!/usr/bin/env python3
"""Poll Free Pi /auth/token until the GitHub device-flow login completes.

Started by the Urist coordinator after POST /auth/github/device returned a
user code for Mikey to enter at https://github.com/login/device.
On success writes the JWT to ~/.free-pi/agent/jwt.txt (mode 0600) and logs.
Exits after ~13 min (code expiry) or on a terminal error.
Stdlib only; honours http_proxy/https_proxy from the environment.
"""
import json
import os
import sys
import time
import urllib.request

BASE_URL = "https://api.freepi.ai"
SESSION_ID = "5147829b-5ba1-4664-b73f-8d4599564e60"
INTERVAL = 5
DEADLINE = time.time() + 800  # ~13.3 min; code expires at ~15 min
LOG_PATH = os.path.expanduser("~/.free-pi/agent/freepi-token-poll.log")
JWT_PATH = os.path.expanduser("~/.free-pi/agent/jwt.txt")


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} {msg}\n"
    with open(LOG_PATH, "a") as f:
        f.write(line)
    print(line, end="", flush=True)


def post(path, body):
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode())


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log(f"polling /auth/token for session {SESSION_ID}")
    consecutive_errors = 0
    while time.time() < DEADLINE:
        try:
            status, body = post("/auth/token", {"session_id": SESSION_ID})
        except Exception as e:  # network failure: tolerate a bounded run
            consecutive_errors += 1
            log(f"network error ({consecutive_errors}): {e}")
            if consecutive_errors >= 6:
                log("too many consecutive network errors, giving up")
                return 3
            time.sleep(max(INTERVAL, 5))
            continue
        consecutive_errors = 0
        if status == 403 and isinstance(body, dict) and body.get("code") == "consent_required":
            log("consent_required: server did not record consent")
            return 2
        if status != 200:
            log(f"HTTP {status}: {body}")
            return 3
        if isinstance(body, dict) and "token" in body:
            token = body["token"]
            with open(JWT_PATH, "w") as f:
                f.write(token)
            os.chmod(JWT_PATH, 0o600)
            log(f"TOKEN RECEIVED, wrote {JWT_PATH} (0600), len={len(token)}")
            # Verify the token works.
            try:
                req = urllib.request.Request(
                    BASE_URL + "/me", headers={"authorization": f"Bearer {token}"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    log(f"/me check: HTTP {resp.status} {resp.read().decode()[:200]}")
            except Exception as e:
                log(f"/me check failed: {e}")
            return 0
        retry_after = body.get("retry_after", 0) if isinstance(body, dict) else 0
        time.sleep(max(INTERVAL, retry_after if isinstance(retry_after, (int, float)) else 0))
    log("deadline reached without a token (code likely expired)")
    return 4


if __name__ == "__main__":
    sys.exit(main())

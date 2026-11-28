"""Offline tests for the Free Pi client retry policy (freepi.py).

Table 6 row 3 (2026-11-27): a single transient 429/5xx used to
raise immediately, and urllib URLError was not caught at all. The
client now retries 429/5xx and URLError with exponential backoff,
honouring Retry-After. No network is touched: urlopen is mocked.
"""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import freepi  # noqa: E402


class _Resp:
    """Minimal urlopen context manager returning canned JSON."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, headers=None):
    return urllib.error.HTTPError(
        "https://api.freepi.ai/v1/chat/completions", code,
        "error", headers or {}, io.BytesIO(b"detail"))


class TestFreePiRetry(unittest.TestCase):
    def setUp(self):
        # The client reads the JWT at construction; point it at a
        # temp file so no real credential is needed.
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token_path = Path(self.tmp.name) / "jwt.txt"
        token_path.write_text("test-token")
        self._patcher = mock.patch.object(freepi, "JWT_PATH", token_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        # No real sleeping in tests.
        self.sleep_patcher = mock.patch.object(freepi.time, "sleep")
        self.sleep = self.sleep_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)
        self.client = freepi.FreePiClient(model="deepseek-v4.1-flash")

    def _chat(self):
        return self.client.chat([{"role": "user", "content": "hi"}])

    def test_429_then_success(self):
        ok = _Resp({"choices": [{"message": {"content": "hello"}}]})
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=[_http_error(429), ok]) as urlopen:
            self.assertEqual(self._chat(), "hello")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(self.sleep.call_count, 1)

    def test_429_retry_after_is_honoured(self):
        ok = _Resp({"choices": [{"message": {"content": "hello"}}]})
        err = _http_error(429, {"Retry-After": "7"})
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=[err, ok]):
            self.assertEqual(self._chat(), "hello")
        self.sleep.assert_called_once_with(7.0)

    def test_429_retry_after_is_capped(self):
        ok = _Resp({"choices": [{"message": {"content": "hello"}}]})
        err = _http_error(429, {"Retry-After": "3600"})
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=[err, ok]):
            self.assertEqual(self._chat(), "hello")
        self.sleep.assert_called_once_with(60.0)

    def test_500_retries_with_backoff(self):
        ok = _Resp({"choices": [{"message": {"content": "hello"}}]})
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=[_http_error(500), _http_error(503),
                             ok]):
            self.assertEqual(self._chat(), "hello")
        # Exponential backoff: 1s after the first failure, 2s after
        # the second.
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list],
                         [1.0, 2.0])

    def test_url_error_retries(self):
        ok = _Resp({"choices": [{"message": {"content": "hello"}}]})
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=[urllib.error.URLError("reset"), ok]):
            self.assertEqual(self._chat(), "hello")

    def test_incomplete_read_retries(self):
        # IncompleteRead comes from resp.read(), outside urlopen,
        # so it is not wrapped in URLError — it used to escape
        # with no retry at all (the 04-02 diary rewrite failed 8
        # straight times on it). A response whose first read()
        # raises and whose second read succeeds must be retried.
        import http.client
        ok = _Resp({"choices": [{"message": {"content": "hello"}}]})

        class _FlakyResp(_Resp):
            def read(self):
                raise http.client.IncompleteRead(b"", 100)

        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=[_FlakyResp({}), ok]) as urlopen:
            self.assertEqual(self._chat(), "hello")
        self.assertEqual(urlopen.call_count, 2)

    def test_remote_disconnected_retries(self):
        import http.client
        ok = _Resp({"choices": [{"message": {"content": "hello"}}]})

        class _DroppedResp(_Resp):
            def read(self):
                raise http.client.RemoteDisconnected(
                    "Remote end closed connection without response")

        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=[_DroppedResp({}), ok]):
            self.assertEqual(self._chat(), "hello")

    def test_persistent_incomplete_read_gives_up(self):
        import http.client
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=http.client.IncompleteRead(
                    b"", 100)) as urlopen:
            with self.assertRaises(RuntimeError):
                self._chat()
        self.assertEqual(urlopen.call_count, freepi.MAX_ATTEMPTS)

    def test_401_raises_at_once_without_retry(self):
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=_http_error(401)) as urlopen:
            with self.assertRaises(RuntimeError):
                self._chat()
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(self.sleep.call_count, 0)

    def test_persistent_429_gives_up_after_max_attempts(self):
        with mock.patch.object(
                freepi.urllib.request, "urlopen",
                side_effect=_http_error(429)) as urlopen:
            with self.assertRaises(RuntimeError):
                self._chat()
        self.assertEqual(urlopen.call_count, freepi.MAX_ATTEMPTS)
        self.assertEqual(self.sleep.call_count, freepi.MAX_ATTEMPTS - 1)

    def test_retry_wait_table(self):
        self.assertEqual(freepi._retry_wait(None, 1), 1.0)
        self.assertEqual(freepi._retry_wait(None, 2), 2.0)
        self.assertEqual(freepi._retry_wait(None, 3), 4.0)
        self.assertEqual(freepi._retry_wait(None, 99), 30.0)
        err = _http_error(429, {"Retry-After": "not-a-number"})
        self.assertEqual(freepi._retry_wait(err, 1), 1.0)
        # A negative Retry-After must not reach time.sleep (it
        # raises ValueError there) — it clamps to an immediate retry.
        neg = _http_error(429, {"Retry-After": "-5"})
        self.assertEqual(freepi._retry_wait(neg, 1), 0.0)


if __name__ == "__main__":
    unittest.main()

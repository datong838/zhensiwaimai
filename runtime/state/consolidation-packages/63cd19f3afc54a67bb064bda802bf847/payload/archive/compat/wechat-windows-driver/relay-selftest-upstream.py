#!/usr/bin/env python3
"""Relay slow-path self-test fixture: a fake Windows driver whose /health is fast
but /slow sleeps. Used by relay-selftest.sh to prove the relay does NOT drop
upstream responses that take longer than the connect timeout.

Hermetic: binds 127.0.0.1 only, never touches WeChat, never sends anything.
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18731
SLOW = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def _send(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            # Must carry the driver identity signature so the relay's
            # discover_target() accepts this host.
            return self._send({"ok": True, "msg": "agent up",
                               "uiautomation": True, "worker": True})
        if self.path == "/slow":
            time.sleep(SLOW)
            return self._send({"ok": True, "msg": "slow-done",
                               "sleptMs": int(SLOW * 1000)})
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        if self.path == "/slow":
            time.sleep(SLOW)
            return self._send({"ok": True, "msg": "slow-post-done"})
        return self._send({"ok": True, "msg": "post-ok"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

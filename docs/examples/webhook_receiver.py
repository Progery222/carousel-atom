"""Reference webhook receiver — stdlib only, verifies the HMAC signature.

Carousel POSTs here when an async job finishes (success or failure). It must be
reachable over https from the Carousel host (SSRF guard rejects private IPs
unless its hostname is in CAROUSEL_WEBHOOK_ALLOW_HOSTS).

    CAROUSEL_WEBHOOK_SECRET=s3cret python webhook_receiver.py   # listens on :9000

Then submit a job with:  "webhook_url": "https://your-host:9000/carousel"
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("CAROUSEL_WEBHOOK_SECRET", "")


def signature_ok(raw: bytes, header: str) -> bool:
    if not SECRET:
        return True  # unsigned mode (not recommended)
    expected = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not signature_ok(raw, self.headers.get("X-Carousel-Signature", "")):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"bad signature"}')
            return

        event = json.loads(raw or b"{}")
        status = event.get("status")
        if status == "succeeded":
            run = event["result"]
            print(f"✅ job {event['job_id']} → run {run['run_id']} "
                  f"({len(run['slides'])} slides)")
            # … hand off run['slides'] / run['caption'] to your pipeline here …
        else:
            print(f"❌ job {event['job_id']} failed: {event.get('error')}")

        # Respond 2xx fast; do heavy work asynchronously.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):  # quieter logs
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    print(f"webhook receiver on :{port} (signed={'yes' if SECRET else 'no'})")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

"""Tiny stateful collections world used by both local and Solari runs."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
STATE = {"payment": "unpaid", "crm": "overdue", "messages": [], "webhook_scheduled": False, "trace": []}


def reset():
    STATE.update(payment="unpaid", crm="overdue", messages=[], webhook_scheduled=False, trace=[])


class Handler(BaseHTTPRequestHandler):
    def send_body(self, body, status=200, content_type="application/json"):
        raw = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/state":
            self.send_body(json.dumps(STATE))
        elif path == "/":
            self.send_body((ROOT / "index.html").read_bytes(), content_type="text/html")
        else:
            self.send_body(b"not found", 404, "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/reset":
            reset()
        elif path == "/pay":
            STATE["payment"] = "paid"
            STATE["webhook_scheduled"] = True
            STATE["trace"].append({"action": "pay", "payment": STATE["payment"], "crm": STATE["crm"]})
        elif path == "/webhook":
            STATE["crm"] = "paid"
            STATE["trace"].append({"action": "webhook", "payment": STATE["payment"], "crm": STATE["crm"]})
        elif path == "/agent/original":
            sent = STATE["crm"] == "overdue"
            if sent:
                STATE["messages"].append("Your payment remains overdue.")
            STATE["trace"].append({
                "action": "agent/original", "sent": sent,
                "payment": STATE["payment"], "crm": STATE["crm"],
            })
        elif path == "/agent/fixed":
            sent = STATE["crm"] == "overdue" and STATE["payment"] != "paid"
            if sent:
                STATE["messages"].append("Your payment remains overdue.")
            STATE["trace"].append({
                "action": "agent/fixed", "sent": sent,
                "payment": STATE["payment"], "crm": STATE["crm"],
            })
        else:
            self.send_body(b"not found", 404, "text/plain")
            return
        self.send_body(json.dumps(STATE))

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    reset()
    ThreadingHTTPServer(("0.0.0.0", 8765), Handler).serve_forever()

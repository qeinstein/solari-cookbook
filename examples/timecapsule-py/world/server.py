"""Tiny stateful collections world used by both local and Solari runs."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
STATE = {
    "payment": "unpaid",
    "crm": "overdue",
    "dispute": "none",
    "crm_dispute": "none",
    "messages": [],
    "webhook_scheduled": False,
    "dispute_webhook_scheduled": False,
    "trace": [],
}


def reset():
    STATE.update(
        payment="unpaid",
        crm="overdue",
        dispute="none",
        crm_dispute="none",
        messages=[],
        webhook_scheduled=False,
        dispute_webhook_scheduled=False,
        trace=[],
    )


def snapshot(action, **extra):
    return {
        "action": action,
        "payment": STATE["payment"],
        "crm": STATE["crm"],
        "dispute": STATE["dispute"],
        "crm_dispute": STATE["crm_dispute"],
        "webhook_scheduled": STATE["webhook_scheduled"],
        "dispute_webhook_scheduled": STATE["dispute_webhook_scheduled"],
        **extra,
    }


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
            STATE["trace"].append(snapshot("pay"))
        elif path == "/webhook":
            STATE["crm"] = "paid"
            STATE["trace"].append(snapshot("webhook"))
        elif path == "/dispute":
            STATE["dispute"] = "open"
            STATE["dispute_webhook_scheduled"] = True
            STATE["trace"].append(snapshot("dispute"))
        elif path == "/dispute-webhook":
            STATE["crm_dispute"] = "open"
            STATE["trace"].append(snapshot("dispute-webhook"))
        elif path == "/agent/original":
            sent = STATE["crm"] == "overdue" and STATE["crm_dispute"] != "open"
            if sent:
                STATE["messages"].append("Your payment remains overdue.")
            STATE["trace"].append(snapshot("agent/original", sent=sent))
        elif path == "/agent/fixed":
            sent = (
                STATE["crm"] == "overdue"
                and STATE["crm_dispute"] != "open"
                and STATE["payment"] != "paid"
                and STATE["dispute"] != "open"
            )
            if sent:
                STATE["messages"].append("Your payment remains overdue.")
            STATE["trace"].append(snapshot("agent/fixed", sent=sent))
        elif path in {"/agent/model/send", "/agent/model/suppress"}:
            sent = path.endswith("/send")
            if sent:
                STATE["messages"].append("Your payment remains overdue.")
            STATE["trace"].append(snapshot(
                path.lstrip("/"),
                sent=sent,
                agent_mode="model",
                model_action="send_reminder" if sent else "suppress",
            ))
        else:
            self.send_body(b"not found", 404, "text/plain")
            return
        self.send_body(json.dumps(STATE))

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    reset()
    ThreadingHTTPServer(("0.0.0.0", 8765), Handler).serve_forever()

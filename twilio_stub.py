#!/usr/bin/env python3
"""Local Twilio-shaped stub for Eclipse Trunk v0.1.

Serves the shipped fixture logs at Twilio-shaped REST paths:
  GET /2010-04-01/Accounts/<AccountSid>/Calls.json
  GET /2010-04-01/Accounts/<AccountSid>/Messages.json
It is a fixture server for the adapter's READ path only: it
accepts no writes, holds no credentials, and reaches no carrier.
Run: python3 twilio_stub.py [port]   (default 8791)
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "twilio_logs.json").read_text())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/Calls.json"):
            body = {"calls": FIXTURES["calls"],
                    "page_size": len(FIXTURES["calls"])}
        elif self.path.endswith("/Messages.json"):
            body = {"messages": FIXTURES["messages"],
                    "page_size": len(FIXTURES["messages"])}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # keep the stub quiet
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), Handler)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    server = make_server(port)
    print(f"twilio stub on 127.0.0.1:{server.server_address[1]}")
    server.serve_forever()


if __name__ == "__main__":
    main()

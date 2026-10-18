"""Deterministic HTTP fixture for Compose acceptance; no real model or credentials."""

import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BEFORE = "    return cur.execute(f\"SELECT * FROM users WHERE name = '{name}'\")\n"
AFTER = '    return cur.execute("SELECT * FROM users WHERE name = ?", (name,))\n'
TEST = """from query import query
from helper import label

def test_regression():
    class Cursor:
        def execute(self, sql, params=()):
            assert '?' in sql and params == ('Alice',)
    query(Cursor(), 'Alice')
    assert label() == 'safe'
"""


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        fixing = "edits" in request.get("format", {}).get("properties", {})
        payload = {"findings": []}
        if fixing:
            payload = {
                "summary": "Parameterize the query, update its helper and add a regression test",
                "edits": [
                    {"file": "query.py", "search": BEFORE, "replace": AFTER},
                    {"file": "helper.py", "search": "'unsafe'", "replace": "'safe'"},
                    {
                        "file": "test_query_regression.py",
                        "search": "",
                        "replace": TEST,
                        "operation": "create",
                    },
                ],
            }
        response = json.dumps({"message": {"content": json.dumps(payload)}, "done": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


ThreadingHTTPServer((socket.gethostbyname(socket.gethostname()), 11434), Handler).serve_forever()

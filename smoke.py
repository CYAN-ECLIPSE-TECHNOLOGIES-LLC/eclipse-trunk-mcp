#!/usr/bin/env python3
"""End-to-end stdio smoke for Eclipse Trunk v0.1 (V0).

Three processes, one shared family state file: the Voice Core
server writes consent; Trunk reads fixture logs through the
local Twilio stub over HTTP and places a gated simulated send;
the Core revokes; Trunk's next send is refused — revocation
propagated across processes at check time (spec 5.3).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
CORE = HERE.parent / "eclipse-voice-core-mcp" / "server.py"
AT = "2026-10-25T17:00:00Z"
STUB_PORT = 18799


def rpc(proc, rid, method, params=None):
    req = {"jsonrpc": "2.0", "id": rid, "method": method,
           "params": params or {}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def call(proc, rid, name, args):
    response = rpc(proc, rid, "tools/call",
                   {"name": name, "arguments": args})
    return json.loads(response["result"]["content"][0]["text"])


def spawn(script, env):
    return subprocess.Popen(
        [sys.executable, str(script)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, text=True, cwd=str(HERE), env=env)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env["ECLIPSE_VOICE_CORE_STATE"] = str(
            Path(tmp) / "core-state.json")
        env["ECLIPSE_TRUNK_STATE"] = str(Path(tmp) / "trunk-state.json")
        env["ECLIPSE_TRUNK_STUB_URL"] = f"http://127.0.0.1:{STUB_PORT}"
        stub = subprocess.Popen(
            [sys.executable, str(HERE / "twilio_stub.py"),
             str(STUB_PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        core = spawn(CORE, env)
        trunk = spawn(HERE / "server.py", env)
        try:
            time.sleep(0.5)
            init = rpc(trunk, 1, "initialize",
                       {"protocolVersion": "2025-03-26"})
            assert init["result"]["serverInfo"]["name"] == \
                "eclipse-trunk"
            print("initialize OK")

            logs = call(trunk, 2, "logs_read", {})
            assert logs["count"] == 6
            assert all(log["source"] == "twilio_stub"
                       for log in logs["logs"])
            assert "+14155550132" not in json.dumps(logs)
            print("logs_read OK; 6 fixture logs via stub, masked")

            call(core, 1, "consent_record_write", {
                "subject": "contact_smoke", "channel": "voice+sms",
                "scope": "marketing",
                "purpose": "Updates, per the signup form",
                "source": "web_form",
                "captured_at": "2026-10-01T00:00:00Z",
                "provenance": {"form_id": "signup-2026-10"},
                "jurisdiction_hint": "US-CA"})
            print("core consent_record_write OK")

            mandate = {"mandate_id": "m-smoke", "cap": 5.0,
                       "platforms": ["twilio"],
                       "approval_threshold": 1.0,
                       "expires_at": "2026-12-31T00:00:00Z"}
            sent = call(trunk, 3, "send_sms_sim", {
                "from_ref": "num_cetech_main",
                "subject": "contact_smoke",
                "to_number": "+14155550132", "scope": "marketing",
                "body": "Fixture smoke message",
                "mandate": mandate, "estimated_cost": 0.01,
                "at_time": AT})
            assert sent["send"]["simulated"] is True
            assert sent["consent_record_id"]
            print("send_sms_sim OK; simulated, consent proof carried")

            call(core, 2, "consent_revoke", {
                "subject": "contact_smoke",
                "revocation_source": "opt_out_keyword"})
            refused = call(trunk, 4, "send_sms_sim", {
                "from_ref": "num_cetech_main",
                "subject": "contact_smoke",
                "to_number": "+14155550132", "scope": "marketing",
                "body": "Fixture smoke message",
                "mandate": mandate, "estimated_cost": 0.01,
                "at_time": AT})
            assert "SEND_REFUSED[consent:consent_revoked]" in \
                refused["error"]
            print("post-revoke send OK; refused across processes")

            receipts = call(trunk, 5, "receipt_list", {})
            assert receipts["chain_valid"] is True
            kinds = [r["type"] for r in receipts["receipts"]]
            assert "violation" in kinds
            print(f"receipts OK; {receipts['count']} entries, "
                  "chain valid, violation recorded")
            print("SMOKE PASSED")
        finally:
            for proc in (core, trunk, stub):
                proc.stdin.close() if proc.stdin else None
                proc.terminate()


if __name__ == "__main__":
    main()

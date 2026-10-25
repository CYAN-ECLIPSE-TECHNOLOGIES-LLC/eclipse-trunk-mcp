"""Eclipse Trunk v0.1 tests — gated simulated sends, PII masking,
recording-policy T3, the denylist, the stub read path, and the
spec 5.3 / V0 ACCEPTANCE test: one revocation refuses sends on
TWO adapter surfaces sharing the Voice Core state."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent.parent
CORE_DIR = HERE.parent / "eclipse-voice-core-mcp"
sys.path.insert(0, str(CORE_DIR))
sys.path.insert(0, str(HERE))

import core_engine as eng  # noqa: E402
import server as srv  # noqa: E402
import twilio_stub  # noqa: E402

AT = "2026-10-25T17:00:00Z"
MANDATE = {"mandate_id": "m-trunk-1", "cap": 5.0,
           "platforms": ["twilio", "relay-fixture"],
           "approval_threshold": 1.0,
           "expires_at": "2026-12-31T00:00:00Z"}


class RelayFixtureAdapter:
    """The second minimal fixture adapter of the V0 acceptance
    test: a separate surface that holds NO consent state of its
    own and reaches consent only through core_engine against the
    shared family state file — the same seam Trunk uses."""

    def __init__(self, state_path):
        self.state_path = Path(state_path)

    def attempt_send(self, subject):
        state = json.loads(self.state_path.read_text())
        verdict = eng.send_evaluate(
            state, channel="sms", from_ref="num_cetech_main",
            subject=subject, scope="marketing",
            platform="relay-fixture", mandate=dict(MANDATE),
            estimated_cost=0.01, at_time=AT)
        self.state_path.write_text(json.dumps(state, indent=1))
        return verdict


class TrunkCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core_path = Path(self.tmp.name) / "core-state.json"
        self.trunk_path = Path(self.tmp.name) / "trunk-state.json"
        self._env = dict(os.environ)
        os.environ["ECLIPSE_VOICE_CORE_STATE"] = str(self.core_path)
        os.environ["ECLIPSE_TRUNK_STATE"] = str(self.trunk_path)
        os.environ.pop("ECLIPSE_TRUNK_STUB_URL", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def core(self):
        return srv.load_core_state()

    def save(self, state):
        srv.save_core_state(state)

    def consent(self, subject="contact_ada", **over):
        state = self.core()
        args = {"subject": subject, "channel": "voice+sms",
                "scope": "marketing",
                "purpose": "Updates, per the signup form",
                "source": "web_form",
                "captured_at": "2026-10-01T00:00:00Z",
                "provenance": {"form_id": "signup-2026-10"},
                "jurisdiction_hint": "US-CA"}
        args.update(over)
        out = eng.consent_record_write(state, args)
        self.save(state)
        return out["consent"]

    def sms_args(self, **over):
        args = {"from_ref": "num_cetech_main",
                "subject": "contact_ada",
                "to_number": "+14155550132", "scope": "marketing",
                "body": "Fixture message body",
                "mandate": dict(MANDATE), "estimated_cost": 0.01,
                "at_time": AT}
        args.update(over)
        return args


class MaskingAndLogs(TrunkCase):
    def test_logs_masked_beyond_last4(self):
        out = srv.t_logs_read({})
        self.assertEqual(out["count"], 6)
        blob = json.dumps(out)
        for full in ("+14155550132", "+14155550101", "+14155550198",
                     "+18005550102", "+13055550177"):
            self.assertNotIn(full, blob)
        self.assertIn("0132", blob)
        self.assertIn("***", blob)

    def test_logs_via_stub_http(self):
        server = twilio_stub.make_server(0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever,
                                  daemon=True)
        thread.start()
        try:
            os.environ["ECLIPSE_TRUNK_STUB_URL"] = \
                f"http://127.0.0.1:{port}"
            out = srv.t_logs_read({})
            self.assertEqual(out["count"], 6)
            self.assertTrue(all(log["source"] == "twilio_stub"
                                for log in out["logs"]))
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/2010-04-01/Accounts/"
                    "ACx/Calls.json", timeout=5) as resp:
                self.assertEqual(len(json.loads(resp.read())
                                     ["calls"]), 3)
        finally:
            server.shutdown()


class GatedSends(TrunkCase):
    def test_valid_path_sends_simulated_with_consent_proof(self):
        consent = self.consent()
        out = srv.t_send_sms_sim(self.sms_args())
        self.assertTrue(out["send"]["simulated"])
        self.assertEqual(out["send"]["consent_record_id"],
                         consent["consent_id"])
        self.assertTrue(out["send"]["sid"].startswith("SM"))
        # Body is hashed, never stored.
        blob = json.dumps(srv.load_trunk_state())
        self.assertNotIn("Fixture message body", blob)
        core = self.core()
        receipt = core["receipts"][-1]
        self.assertEqual(receipt["type"], "sms_sent_simulated")
        self.assertEqual(receipt["detail"]["consent_record_id"],
                         consent["consent_id"])
        self.assertTrue(eng.verify_receipt_chain(core["receipts"]))

    def test_unregistered_from_number_refused(self):
        self.consent()
        with self.assertRaises(eng.ToolError) as ctx:
            srv.t_send_sms_sim(
                self.sms_args(from_ref="num_campaign_broken"))
        self.assertIn("SEND_REFUSED[number:registration_broken]",
                      str(ctx.exception))
        with self.assertRaises(eng.ToolError) as ctx:
            srv.t_send_sms_sim(
                self.sms_args(from_ref="+19995550100"))
        self.assertIn("number_not_enrolled", str(ctx.exception))

    def test_place_call_requires_named_human(self):
        self.consent()
        args = self.sms_args()
        args.pop("body")
        with self.assertRaises(eng.ToolError) as ctx:
            srv.t_place_call_sim(args)
        self.assertIn("HUMAN_SPEAKER_REQUIRED", str(ctx.exception))
        args["human_speaker"] = "Steven (owner)"
        out = srv.t_place_call_sim(args)
        self.assertTrue(out["send"]["sid"].startswith("CA"))
        self.assertEqual(out["send"]["human_speaker"],
                         "Steven (owner)")

    def test_no_consent_no_send(self):
        with self.assertRaises(eng.ToolError) as ctx:
            srv.t_send_sms_sim(self.sms_args())
        self.assertIn("SEND_REFUSED[consent:no_consent]",
                      str(ctx.exception))
        self.assertEqual(srv.load_trunk_state()["sends"], [])


class V0Acceptance(TrunkCase):
    def test_one_revocation_refuses_two_adapter_surfaces(self):
        # Spec 5.3 + the V0 acceptance test, verbatim: revoke a
        # contact, then within the same test prove BOTH the
        # Trunk adapter and a second fixture adapter surface
        # refuse sends to that contact via check-time core calls.
        self.consent(subject="contact_accept")
        relay = RelayFixtureAdapter(self.core_path)
        # Baseline: both surfaces may send while consent stands.
        self.assertEqual(relay.attempt_send("contact_accept")
                         ["decision"], "ALLOW")
        out = srv.t_send_sms_sim(
            self.sms_args(subject="contact_accept"))
        self.assertIn("send", out)
        # One revocation, written through the core.
        state = self.core()
        eng.consent_revoke(state, {
            "subject": "contact_accept",
            "revocation_source": "opt_out_keyword"})
        self.save(state)
        # Surface one (the relay fixture adapter) refuses.
        verdict = relay.attempt_send("contact_accept")
        self.assertEqual(verdict["decision"], "DENY")
        self.assertEqual(verdict["stage"], "consent")
        self.assertEqual(verdict["reason"], "consent_revoked")
        # Surface two (Trunk) refuses, by name.
        with self.assertRaises(eng.ToolError) as ctx:
            srv.t_send_sms_sim(
                self.sms_args(subject="contact_accept"))
        self.assertIn("SEND_REFUSED[consent:consent_revoked]",
                      str(ctx.exception))
        # The ledger tells the whole truth: two violation records
        # for the two refused attempts, and no new sends.
        core = self.core()
        violations = [r for r in core["receipts"]
                      if r["type"] == "violation"]
        self.assertEqual(len(violations), 2)
        self.assertTrue(all(
            v["detail"]["kind"] == "send_without_consent"
            for v in violations))
        self.assertEqual(len(srv.load_trunk_state()["sends"]), 1)
        self.assertTrue(eng.verify_receipt_chain(core["receipts"]))


class RecordingPolicy(TrunkCase):
    def test_policy_change_is_t3(self):
        with self.assertRaises(eng.ToolError) as ctx:
            srv.t_recording_policy_set(
                {"number_ref": "num_cetech_main",
                 "recording_enabled": True})
        self.assertIn("CONFIRMATION_REQUIRED", str(ctx.exception))
        out = srv.t_recording_policy_set({
            "number_ref": "num_cetech_main",
            "recording_enabled": True,
            "confirm_token": "confirm-recording-policy-num_cetech_main"})
        self.assertTrue(out["policy"]["recording_enabled"])
        core = self.core()
        self.assertEqual(core["receipts"][-1]["type"],
                         "recording_policy_changed")
        got = srv.t_recording_policy_get(
            {"number_ref": "num_cetech_main"})
        self.assertTrue(got["policy"]["recording_enabled"])

    def test_registration_status_reports_broken_state(self):
        out = srv.t_registration_status(
            {"number_ref": "num_campaign_broken"})
        matrix = out["number"]["sendable_matrix"]
        self.assertFalse(matrix["sms/marketing"]["sendable"])
        self.assertIn("a2p_campaign_suspended",
                      matrix["sms/marketing"]["reasons"])
        with self.assertRaises(eng.ToolError):
            srv.t_registration_status({"number_ref": "+19995550100"})


class Surface(TrunkCase):
    def test_tools_list_exact_and_denylist_refused(self):
        names = {t["name"] for t in srv.tool_list()}
        self.assertEqual(names, {
            "logs_read", "send_sms_sim", "place_call_sim",
            "number_search", "registration_status",
            "recording_policy_get", "recording_policy_set",
            "receipt_list"})
        for forbidden in ("e911_config", "e911_address_write",
                          "caller_id_spoof", "caller_id_override",
                          "number_release", "emergency_call_config"):
            resp = srv.handle({"jsonrpc": "2.0", "id": 1,
                               "method": "tools/call",
                               "params": {"name": forbidden,
                                          "arguments": {}}})
            self.assertEqual(resp["error"]["code"], -32602, forbidden)

    def test_number_search_provisions_nothing(self):
        out = srv.t_number_search({"area_code": "415"})
        self.assertEqual(out["count"], 1)
        self.assertEqual(self.core()["receipts"], [])

    def test_receipt_list_detects_tamper(self):
        self.consent()
        srv.t_send_sms_sim(self.sms_args())
        out = srv.t_receipt_list({})
        self.assertTrue(out["chain_valid"])
        state = self.core()
        state["receipts"][0]["detail"]["x"] = "forged"
        self.save(state)
        self.assertFalse(srv.t_receipt_list({})["chain_valid"])


if __name__ == "__main__":
    unittest.main()

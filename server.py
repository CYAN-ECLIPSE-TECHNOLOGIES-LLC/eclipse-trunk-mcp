#!/usr/bin/env python3
"""Eclipse Trunk MCP — v0.1.0, phase V0 (Twilio fixture adapter).

Powered by Cyan Eclipse Technologies (cetech.ai).

Descriptor: Eclipse Trunk — the governed Twilio adapter: every
call and text under consent + mandate.

Family descriptor: one Consent Registry and Number Registry
govern every call and text across carriers, business phone systems,
and AI voice platforms. No adapter dials or sends without a
consent record with provenance and an Agent Wallet mandate;
revocation propagates to every adapter instantly. It never
touches emergency services, never spoofs a caller ID, never
fabricates consent, and never lets an AI voice pretend to be a
human.

Posture (spec eclipse-voice-family-spec-20261025 section 12):
WRAP — Twilio ships official MCP surfaces (a discovery-only
docs server and the Labs execution server, Public Beta); at V1
the governor fronts the vendor surface. V0 proves the governed
shape against Twilio-shaped fixtures and a local stub: raw
carrier operations are never exposed here, only the classified
subset — reads, simulated SMS, simulated human calls,
registration status, recording policy — each mapped to a family
tier, and every send gated through Eclipse Voice Core's
send_evaluate. Vendor operations with no tier mapping are
unavailable, not defaulted.

CONSENT SEAM (stated plainly): Trunk imports core_engine from
the sibling eclipse-voice-core-mcp directory and evaluates
against the SHARED family state file ($ECLIPSE_VOICE_CORE_STATE
or the core's data/state.json), loaded fresh at every call.
Trunk holds NO consent copies: a revocation written through the
core refuses Trunk's very next send, in the same process or any
other (spec 5.3; the V0 acceptance test proves it across two
adapter surfaces sharing the state).

V0 SCOPE: no live Twilio account, no real numbers, sends are
SIMULATED records only, and no certification is claimed — bench
pending. Live wiring sits behind the owner Twilio account + the
counsel gate (V1).

Transport: MCP over stdio, stdlib only. Trunk-local state
(simulated sends, recording policies): $ECLIPSE_TRUNK_STATE or
./data/state.json. Fixture logs: fixtures/twilio_logs.json, or
a local twilio_stub.py over HTTP when $ECLIPSE_TRUNK_STUB_URL
is set.
"""
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CORE_DIR = HERE.parent / "eclipse-voice-core-mcp"
sys.path.insert(0, str(CORE_DIR))

import core_engine as eng  # noqa: E402
from core_engine import ToolError  # noqa: E402

FIXTURE_LOGS = HERE / "fixtures" / "twilio_logs.json"
PLATFORM = "twilio"
ACCOUNT_SID_FIXTURE = "ACfixture00000000000000000000000000"


def core_state_path() -> Path:
    return Path(os.environ.get(
        "ECLIPSE_VOICE_CORE_STATE", CORE_DIR / "data" / "state.json"))


def trunk_state_path() -> Path:
    return Path(os.environ.get(
        "ECLIPSE_TRUNK_STATE", HERE / "data" / "state.json"))


def load_core_state() -> dict:
    path = core_state_path()
    if path.exists():
        return json.loads(path.read_text())
    state = eng.empty_state()
    seed = json.loads((CORE_DIR / "fixtures.json").read_text())
    state["config"].update(seed.get("config", {}))
    state["dnc_lists"] = seed.get("dnc_lists", [])
    state["windows"] = seed.get("windows", [])
    for rec in seed.get("numbers", []):
        state["numbers"][rec["number_id"]] = rec
    save_core_state(state)
    return state


def save_core_state(state: dict) -> None:
    path = core_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))


def load_trunk_state() -> dict:
    path = trunk_state_path()
    if path.exists():
        return json.loads(path.read_text())
    return {"sends": [], "recording_policies": {
        "num_cetech_main": {"recording_enabled": False,
                            "announce": True}}}


def save_trunk_state(state: dict) -> None:
    path = trunk_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))


def mask_number(e164) -> str:
    """PII rule for every Trunk output: numbers are masked beyond
    the last four digits. The full number never leaves in a log,
    a send record, or a receipt view."""
    text = str(e164 or "")
    last4 = text[-4:] if len(text) >= 4 else text
    if text.startswith("+1") and len(text) == 12:
        return f"+1 ***-***-{last4}"
    return f"***{last4}"


def _fixture_logs() -> dict:
    stub = os.environ.get("ECLIPSE_TRUNK_STUB_URL")
    if stub:
        out = {}
        for kind, key in (("Calls", "calls"), ("Messages", "messages")):
            url = (f"{stub.rstrip('/')}/2010-04-01/Accounts/"
                   f"{ACCOUNT_SID_FIXTURE}/{kind}.json")
            with urllib.request.urlopen(url, timeout=5) as resp:
                out[key] = json.loads(resp.read())["messages" if key == "messages" else "calls"]
        return out
    data = json.loads(FIXTURE_LOGS.read_text())
    return {"calls": data["calls"], "messages": data["messages"]}


def _masked_log(entry: dict, kind: str, numbers: dict) -> dict:
    def number_id(e164):
        for rec in numbers.values():
            if rec["e164"] == e164:
                return rec["number_id"]
        return None
    return {
        "sid": entry["sid"], "kind": kind,
        "direction": entry["direction"], "status": entry["status"],
        "from": mask_number(entry["from"]),
        "to": mask_number(entry["to"]),
        "from_number_id": number_id(entry["from"]),
        "to_number_id": number_id(entry["to"]),
        "duration_s": entry.get("duration"),
        "date_created": entry["date_created"],
        "price": entry.get("price"),
        "source": "twilio_stub" if os.environ.get(
            "ECLIPSE_TRUNK_STUB_URL") else "fixture_file",
    }


# ------------------------------------------------------------------- tools
def t_logs_read(args):
    core = load_core_state()
    logs = _fixture_logs()
    kind = args.get("kind", "all")
    limit = int(args.get("limit", 50))
    out = []
    if kind in ("all", "calls"):
        out += [_masked_log(e, "call", core["numbers"])
                for e in logs["calls"]]
    if kind in ("all", "messages"):
        out += [_masked_log(e, "message", core["numbers"])
                for e in logs["messages"]]
    out.sort(key=lambda e: e["date_created"])
    return {"logs": out[-limit:], "count": min(len(out), limit),
            "pii": "numbers masked beyond last-4 in all outputs"}


def _gated_send(args, channel):
    """The only road out of this adapter: Voice Core's
    send_evaluate, consent first, mandate second (spec 8)."""
    core = load_core_state()
    verdict = eng.send_evaluate(
        core, channel=channel, from_ref=args["from_ref"],
        subject=args["subject"], scope=args["scope"],
        platform=PLATFORM, mandate=args.get("mandate"),
        estimated_cost=args.get("estimated_cost", 0.01),
        at_time=args.get("at_time"),
        confirm_token=args.get("confirm_token"))
    save_core_state(core)
    if verdict["decision"] == "DENY":
        raise ToolError(
            f"SEND_REFUSED[{verdict['stage']}:{verdict['reason']}] "
            "the send did not happen; see the family ledger "
            "(a violation record exists when consent denied)")
    if verdict["decision"] == "APPROVAL_REQUIRED":
        return {"decision": "APPROVAL_REQUIRED",
                "send_ref": verdict["send_ref"],
                "confirm_token_form": verdict["confirm_token_form"],
                "consent_record_id": verdict["consent_record_id"],
                "note": "re-call with confirm_token set to "
                        "confirm_token_form to complete this send"}
    return core, verdict


def _record_send(channel, args, verdict, extra):
    trunk = load_trunk_state()
    prefix = "SM" if channel == "sms" else "CA"
    sid = prefix + eng.sha(eng.canon({
        "send_ref": verdict["send_ref"],
        "seq": len(trunk["sends"])}))[:32]
    record = {"sid": sid, "simulated": True, "channel": channel,
              "status": "simulated-sent" if channel == "sms"
                        else "simulated-placed",
              "from_number_id": verdict["number_id"],
              "to": mask_number(args.get("to_number")),
              "subject": args["subject"], "scope": args["scope"],
              "consent_record_id": verdict["consent_record_id"],
              "send_ref": verdict["send_ref"],
              "at_time": args.get("at_time")}
    record.update(extra)
    trunk["sends"].append(record)
    save_trunk_state(trunk)
    core = load_core_state()
    receipt = eng.emit_receipt(core, f"{channel}_sent_simulated", {
        "sid": sid, "consent_record_id": verdict["consent_record_id"],
        "consent_scope": args["scope"],
        "number_id": verdict["number_id"],
        "mandate_id": (args.get("mandate") or {}).get("mandate_id"),
        "send_ref": verdict["send_ref"], "platform": PLATFORM,
        "simulated": True})
    save_core_state(core)
    return {"send": record, "receipt_seq": receipt["seq"],
            "consent_record_id": verdict["consent_record_id"]}


def t_send_sms_sim(args):
    body = args.get("body") or ""
    if not body:
        raise ToolError("body is required (its content is hashed, "
                        "never stored)")
    gate = _gated_send(args, "sms")
    if isinstance(gate, dict):
        return gate
    _, verdict = gate
    return _record_send("sms", args, verdict, {
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "body_chars": len(body)})


def t_place_call_sim(args):
    # Spec 8.1: a "human call" means a named human will speak on
    # it. No named human, no call — an answered phone never meets
    # silence where a human call was represented.
    if not args.get("human_speaker"):
        raise ToolError(
            "HUMAN_SPEAKER_REQUIRED: a T2 human call names the "
            "human who will speak on it (spec 8.1)")
    gate = _gated_send(args, "voice")
    if isinstance(gate, dict):
        return gate
    _, verdict = gate
    return _record_send("voice", args, verdict, {
        "human_speaker": args["human_speaker"]})


def t_number_search(args):
    data = json.loads(FIXTURE_LOGS.read_text())
    area = str(args.get("area_code") or "")
    out = [n for n in data["available_numbers"]
           if not area or n["phone_number"].startswith(f"+1{area}")]
    return {"available": out, "count": len(out),
            "note": "fixture inventory (Twilio-shaped); searching "
                    "provisions nothing — provisioning is T2 at V1"}


def t_registration_status(args):
    core = load_core_state()
    rec = eng.find_number(core, args["number_ref"])
    if rec is None:
        raise ToolError(
            f"NUMBER_NOT_ENROLLED: {args['number_ref']} does not "
            "exist to this family (spec 6)")
    trunk = load_trunk_state()
    return {"number": eng.number_public(rec),
            "recording_policy": trunk["recording_policies"].get(
                rec["number_id"])}


def t_recording_policy_get(args):
    core = load_core_state()
    rec = eng.find_number(core, args["number_ref"])
    if rec is None:
        raise ToolError(f"NUMBER_NOT_ENROLLED: {args['number_ref']}")
    trunk = load_trunk_state()
    policy = trunk["recording_policies"].get(
        rec["number_id"], {"recording_enabled": False,
                           "announce": True})
    return {"number_id": rec["number_id"], "policy": policy,
            "tier": "T3 to change (human confirm every time)"}


def t_recording_policy_set(args):
    # T3 (spec 8): recording-policy changes confirm every time.
    core = load_core_state()
    rec = eng.find_number(core, args["number_ref"])
    if rec is None:
        raise ToolError(f"NUMBER_NOT_ENROLLED: {args['number_ref']}")
    number_id = rec["number_id"]
    expected = "confirm-recording-policy-" + number_id
    if args.get("confirm_token") != expected:
        raise ToolError(
            "CONFIRMATION_REQUIRED: recording-policy changes are "
            f"T3; confirm_token must be {expected}")
    trunk = load_trunk_state()
    policy = trunk["recording_policies"].get(
        number_id, {"recording_enabled": False, "announce": True})
    if "recording_enabled" in args:
        policy["recording_enabled"] = bool(args["recording_enabled"])
    if "announce" in args:
        policy["announce"] = bool(args["announce"])
    trunk["recording_policies"][number_id] = policy
    save_trunk_state(trunk)
    receipt = eng.emit_receipt(core, "recording_policy_changed", {
        "number_id": number_id, "policy": policy, "platform": PLATFORM})
    save_core_state(core)
    return {"number_id": number_id, "policy": policy,
            "receipt_seq": receipt["seq"]}


def t_receipt_list(args):
    core = load_core_state()
    limit = args.get("limit")
    receipts = core["receipts"]
    if limit is not None:
        receipts = receipts[-int(limit):]
    return {"receipts": receipts, "count": len(core["receipts"]),
            "chain_valid": eng.verify_receipt_chain(core["receipts"])}


TOOLS = {
    "logs_read": (
        t_logs_read,
        "T0. Twilio-shaped call/message logs (fixture file, or "
        "the local twilio_stub over HTTP when "
        "ECLIPSE_TRUNK_STUB_URL is set). Numbers are masked "
        "beyond last-4 in every output.",
        {"kind": {"type": "string"}, "limit": {"type": "integer"}},
        []),
    "send_sms_sim": (
        t_send_sms_sim,
        "T2 SIMULATED SMS send. Gated through Eclipse Voice "
        "Core: live consent check, then mandate, then number "
        "registration state. A refusal names its gate; an "
        "unconsented attempt writes a violation record in the "
        "family ledger. On ALLOW, a simulated send record is "
        "written (body hashed, never stored) and the family "
        "receipt carries the consent_record_id. Nothing reaches "
        "a carrier in V0.",
        {"from_ref": {"type": "string"},
         "subject": {"type": "string"},
         "to_number": {"type": "string"},
         "scope": {"type": "string"}, "body": {"type": "string"},
         "mandate": {"type": "object"},
         "estimated_cost": {"type": "number"},
         "at_time": {"type": "string"},
         "confirm_token": {"type": "string"}},
        ["from_ref", "subject", "scope", "body"]),
    "place_call_sim": (
        t_place_call_sim,
        "T2 SIMULATED human call. human_speaker is REQUIRED "
        "(spec 8.1: a named human speaks on a human call). Same "
        "Voice Core gate as send_sms_sim; the simulated record "
        "and its receipt carry the consent_record_id. No AI "
        "voice exists in this adapter; AI-voice outbound is T3 "
        "and belongs to Eclipse Ward (V3).",
        {"from_ref": {"type": "string"},
         "subject": {"type": "string"},
         "to_number": {"type": "string"},
         "scope": {"type": "string"},
         "human_speaker": {"type": "string"},
         "mandate": {"type": "object"},
         "estimated_cost": {"type": "number"},
         "at_time": {"type": "string"},
         "confirm_token": {"type": "string"}},
        ["from_ref", "subject", "scope", "human_speaker"]),
    "number_search": (
        t_number_search,
        "T0. Search fixture carrier inventory (Twilio-shaped). "
        "Search only — provisioning is a separate T2 surface "
        "at V1.",
        {"area_code": {"type": "string"}}, []),
    "registration_status": (
        t_registration_status,
        "T0. A registry number's registration state (10DLC, "
        "toll-free verification, STIR/SHAKEN as carrier-"
        "reported, branded ID), its sendability matrix, and "
        "its recording policy (spec 5.6).",
        {"number_ref": {"type": "string"}}, ["number_ref"]),
    "recording_policy_get": (
        t_recording_policy_get,
        "T0. The recording policy in force for a number.",
        {"number_ref": {"type": "string"}}, ["number_ref"]),
    "recording_policy_set": (
        t_recording_policy_set,
        "T3. Change a number's recording policy. Requires the "
        "human-confirm token for that number on EVERY call "
        "(confirm-recording-policy-<number_id>). Receipted in "
        "the family ledger.",
        {"number_ref": {"type": "string"},
         "recording_enabled": {"type": "boolean"},
         "announce": {"type": "boolean"},
         "confirm_token": {"type": "string"}},
        ["number_ref", "confirm_token"]),
    "receipt_list": (
        t_receipt_list,
        "T0. The family ledger (held by Eclipse Voice Core): "
        "append-only, hash-chained; verifies the chain.",
        {"limit": {"type": "integer"}}, []),
}

# Capability denylist, stated in code (spec 10/12): no
# emergency-services surface, no caller-ID mutation, no number
# release, and no unclassified vendor operation exists here.
# Vendor operations with no tier mapping are unavailable, not
# defaulted — 1,800 endpoints arrive guilty until classified.
FORBIDDEN_TOOL_NAMES = {
    "e911_config", "e911_address_write", "emergency_call_config",
    "caller_id_set", "caller_id_override", "caller_id_spoof",
    "display_name_set", "number_release", "number_provision",
    "consent_edit", "raw_vendor_call", "send_sms", "place_call",
}


def tool_list():
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": props,
                             "required": required}}
            for name, (_, description, props, required) in TOOLS.items()]


def handle(req: dict):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get(
                "protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-trunk",
                           "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        if name in FORBIDDEN_TOOL_NAMES or name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602,
                "message": f"unknown or line-forbidden tool {name}"}}
        try:
            out = TOOLS[name][0](args)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(out, indent=1)}]}}
        except ToolError as exc:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(exc)})}],
                "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:  # never crash the transport
            response = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32603, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

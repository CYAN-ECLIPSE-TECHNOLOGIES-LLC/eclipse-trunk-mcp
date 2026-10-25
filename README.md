# Eclipse Trunk MCP

**Powered by Cyan Eclipse Technologies** — https://cetech.ai

**Eclipse Trunk — the governed Twilio adapter: every call and text under consent + mandate.**

**The Eclipse voice & telephony family — one Consent Registry and Number Registry govern every call and text across carriers, business phone systems, and AI voice platforms. No adapter dials or sends without a consent record with provenance and an Agent Wallet mandate; revocation propagates to every adapter instantly. It never touches emergency services, never spoofs a caller ID, never fabricates consent, and never lets an AI voice pretend to be a human.**

## Why this exists

Twilio has already shipped the pipes — 1,800+ API endpoints and official MCP surfaces of its own. A second, worse copy of Twilio's API is not a product. What Twilio does not ship is governance that survives contact with a second carrier: one consent registry, one mandate pattern, one receipt ledger, one kill switch. Trunk is the Twilio chapter of that layer — the governed trunk into Twilio (a trunk is telephony's own word for the bundled connection between systems; the adapter *is* the connection, and it is not a carrier).

## Status — honest labels

v0.1.0, phase **V0 (fixture adapter)**. Local stdio transport, Python stdlib only. **No Twilio account is connected, no number is provisioned, sends are simulated records only, and no certification is claimed — bench pending.** The live form (V1, behind the owner's own Twilio account and the counsel gate) *wraps* the vendor's official MCP surface behind this same governor; V0 proves the governed shape against Twilio-shaped fixtures and a local stub.

## The governed surface

Raw vendor operations are never exposed. Vendor operations with no tier mapping are **unavailable, not defaulted** — the classified V0 subset is:

| Tool | Tier | What it does |
|---|---|---|
| `logs_read` | T0 | Twilio-shaped call/message logs (fixture file, or the local stub over HTTP); **numbers masked beyond last-4 in every output**. |
| `send_sms_sim` | T2 | **Simulated** SMS send, gated through Voice Core (below). Body hashed, never stored. |
| `place_call_sim` | T2 | **Simulated** human call; a named `human_speaker` is required (spec §8.1). |
| `number_search` | T0 | Fixture carrier inventory search. Search only — provisioning is T2 at V1. |
| `registration_status` | T0 | A registry number's §5.6 registration state + sendability matrix + recording policy. |
| `recording_policy_get` / `recording_policy_set` | T0 / **T3** | Policy changes require the per-number human-confirm token on **every** call. |
| `receipt_list` | T0 | The family ledger, held by Voice Core. |

There is **no AI voice in this adapter**. AI-voice outbound is T3 family-wide and belongs to Eclipse Ward (V3); `send_sms` / `place_call` without the `_sim` suffix do not exist here, and neither do emergency-configuration tools or caller-ID mutation tools — the denylist is stated in code (spec §10): outbound identity is only numbers in the Number Registry, owned or formally verified for the owner's use.

## The gate, on every send

`send_sms_sim` and `place_call_sim` have exactly one road out: **Eclipse Voice Core's `send_evaluate`** — live consent check first, then the Agent Wallet-shaped mandate (cap, allowlists, threshold, expiry), with Number Registry sendability between them. A refusal names its gate (`SEND_REFUSED[consent:consent_revoked]`, `SEND_REFUSED[number:registration_broken]`…); an unconsented attempt writes a **violation record** in the family ledger and no send. On ALLOW, the simulated send record and its family receipt carry the `consent_record_id` and the mandate verdict — consent proof travels with the act (spec §8.3).

**Trunk holds no consent copies.** It imports `core_engine` from the sibling `eclipse-voice-core-mcp` directory and evaluates against the **shared family state file**, loaded fresh at every call (the V0 fixture seam, stated in both READMEs). The V0 acceptance test is spec §5.3 executed: one revocation, written through the core, then **both** Trunk and a second minimal fixture adapter surface refuse sends to that contact via check-time core calls — the test suite runs exactly that, and the smoke runs it across three separate processes.

## Run it

```bash
python3 server.py            # MCP over stdio, stdlib only, no dependencies
python3 twilio_stub.py 8791  # optional: local Twilio-shaped stub
ECLIPSE_TRUNK_STUB_URL=http://127.0.0.1:8791 python3 server.py
python3 smoke.py             # core + trunk + stub, one shared state
python3 -m unittest discover tests
python3 make_icon.py         # regenerate icon-512.png
```

State: Trunk-local data (simulated sends, recording policies) in `data/state.json` (`ECLIPSE_TRUNK_STATE`); the family state is Voice Core's (`ECLIPSE_VOICE_CORE_STATE` or the core's `data/state.json`). `data/` is gitignored.

## Roadmap (per spec)

- **V0** — this fixture adapter + Eclipse Voice Core.
- **V1** — wrap the vendor's executing MCP surface behind the governor, on the owner's Twilio account; one registered dogfood number (the CETech business line); number provisioning (T2) and release (T3) classified and receipted.
- **V2** — sibling wraps (Uplink/Telnyx, Wavelength/Bandwidth, Dialtone/Vonage) on the same core; nothing about the consent law changes.

## License / attribution

A Cyan Eclipse Technologies product. The "Powered by Cyan Eclipse Technologies" attribution travels with it.

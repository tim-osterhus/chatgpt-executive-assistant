# Optional outbound assistant calls

An assistant or Dot can prepare context, ask a connected local task to call your configured phone, and review the result. A separate voice agent delivers the relevant update, discusses it, and captures confirmed follow-up. The coordinating assistant keeps project ownership and performs any separately authorized follow-up.

Use calls when you request them or for a specific notification rule you choose. Connecting this add-on does not start background monitoring or invent an urgency threshold. The core assistant and phone access through Remote work without this add-on. Context Mill is unnecessary.

Follow [setup](SETUP.md). The included code is a local skill and command runner. No published MCP plugin is required. Initial support is experimental and limited to Apple Silicon macOS 15 or later, configured +1 phone numbers, a voice-enabled Twilio line, and a ChatGPT account whose isolated Codex login supports the tested voice route. Verify availability in the actual account.

## What the call can do

The assistant supplies a `focus` and prepared `briefing`. The voice agent can discuss those facts, ask useful questions, acknowledge uncertainty, and confirm decisions or requests. It has no project tools or mid-call retrieval. A question outside the supplied context becomes follow-up for the coordinator.

The personal default is a useful conversation about the update. There is no required priority-and-blocker questionnaire. A request without `briefing` retains the imported check-in mode for compatibility.

Calls have a configurable 45-minute safety limit by default. They can end earlier when the user hangs up, the conversation closes, or the transport fails. Ringing and connection timeouts remain separate. Set `max_call_seconds` in the installation config to change the safety limit. Spoken recording/transcription disclosure is enabled by default and can be configured for the installation. Raw audio and transcripts are saved locally even when carrier recording is disabled.

## Request and receipt

```sh
./run validate < examples/request.json
```

`validate` checks syntax only. `diagnose` checks local configuration, credentials, login, and runtime imports without dialing. For a user-authorized call, invoke `call` once with a fresh request ID. Use `result` with identical JSON to retrieve its saved receipt.

The request ID binds to the entire accepted request. Replaying it cannot redial. Changing the briefing under that ID is rejected. A per-installation lock prevents overlapping calls. An uncertain or missing result never authorizes a fresh ID or another dial.

The runner returns the exact carrier Call SID, status, end reason, transcript turns, and evidence path. `review_required` means transport completed and the conversation still needs review. `partial_or_failed` can still contain a useful conversation. The coordinator checks the exact transcript and caller confirmation before accepting facts. See the [synthetic request](examples/request.json) and [synthetic receipt](examples/receipt.json).

## Compatibility and evidence

| Component | Tested baseline |
| --- | --- |
| Host | Apple Silicon macOS; a personal call ran on macOS 15.7.7 |
| Python | 3.12 with the included dependency lock |
| Codex CLI | Installation-specific 0.160.0, isolated ChatGPT login |
| Voice route | App Server experimental realtime v3, `gpt-live-1-codex`, `sol` voice |
| Local media | LiveKit server 1.13.6, loopback-only room |
| Phone transport | Twilio Media Streams through per-call Cloudflared 2026.10.4 tunnel |

The upstream local-task/Dot route was validated on a Mac Mini. The personal deployment completed one dial and a two-way prepared-context conversation on November 5, 2026. Its old two-minute timer ended that call. The caller accepted the route and selected a 45-minute safety cap with spoken disclosure disabled for that installation. Those settings have offline regression coverage. That call does not prove a 45-minute session or a new public download's account access.

The voice had an intermittent audible catch reported by the caller. No general audio-quality or availability guarantee follows. Other platforms, non-+1 destinations, automatic triggers, and live retrieval are unqualified.

## Costs and private state

Twilio line and call charges are separate from the assistant subscription. This implementation uses a ChatGPT-authenticated voice route. It does not silently switch to a paid OpenAI API key. Actual account entitlement and provider charges require verification.

Settings, isolated login, downloads, and call evidence live in ignored `.state/`. The Python environment and downloaded executables are also ignored. Release tracked source files only. Configure retention deliberately; the runner does not automatically delete recordings or transcripts.

Third-party notices are in [licenses](licenses/LiveKit-NOTICE). The installer downloads checksum-pinned LiveKit and Cloudflared binaries from Homebrew's public registry and Cloudflare's release assets. Original code uses the repository's [MIT license](../../LICENSE).

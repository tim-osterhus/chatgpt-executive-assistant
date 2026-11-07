# Optional outbound assistant calls

This add-on lets your assistant call your phone, talk through a prepared update, and save an exact receipt for review.

The core assistant works without it. You opt in after the first useful assistant task, and nothing calls, watches, or connects until you set it up and ask. A coordinating assistant or Dot prepares a `focus` and `briefing`. A separate voice agent discusses them on the call and captures confirmed follow-up. The coordinator keeps project ownership and reviews the receipt afterward.

Status: experimental. Setup supports Apple Silicon macOS 15 or later, `+1` phone numbers, a voice-enabled Twilio line, and a ChatGPT account whose isolated Codex login supports the tested voice route. Follow [setup](SETUP.md).

## Runtime outside the checkout

`./setup.sh` copies an explicit allowlist of 42 source files to a runtime directory you own. The default is `~/Library/Application Support/Executive Assistant Calls`. Python and Node dependencies, the pinned Codex CLI 0.160.0, its ChatGPT login, configuration, call journals, audio, and transcripts stay under that runtime directory, never in this checkout.

Setup never logs in, reads secrets, places a call, or starts a service. A re-run refreshes managed source and keeps private state. Setup refuses a non-empty directory that it did not create, a path inside this checkout, and an update while a request is being submitted, a call is running, or a submitted request lacks a terminal receipt. Setup also writes a generated local skill with the runtime's actual path.

## How a call works

The coordinator saves one JSON request and runs the installed runner once:

```sh
RUNTIME="$HOME/Library/Application Support/Executive Assistant Calls"
"$RUNTIME/run" validate < examples/request.json
```

| Field | Required | Meaning |
| --- | --- | --- |
| `request_id` | yes | Fresh slug. It binds to the whole request. |
| `focus` | yes | Short subject for the call. |
| `briefing` | for current use | Prepared facts, uncertainty, and the useful question or decision. |
| `outcome` | no | `complete`, `still_running`, `failed_or_blocked`, or `unclear`. Selects framing and reasoning profile. |
| `recipient_number` | no | Full `+1` E.164 number for this request only. Omit it for the configured default. |
| `recipient_name` | no | Greeting name. Requires `recipient_number`. |

`validate` checks syntax. `diagnose` checks configuration, Keychain items, login, CLI version, imports, and transport readiness without dialing. `call` dials once. `result` with identical JSON reads the saved receipt.

Replaying a request ID cannot redial. Changing any field under that ID is rejected. The resolved destination is saved before dialing, and recovery uses that saved number, not today's default. One per-installation lock prevents overlapping calls. Missing or uncertain results never authorize a new ID or another dial.

The voice agent has the supplied briefing and a tool-free reasoning backend. It has no project tools, retrieval, or authority to act. A question outside the briefing becomes follow-up. Calls to an explicit recipient omit the configured owner's name and check-in purpose.

## Receipts

| Status | Meaning |
| --- | --- |
| `review_required` | The transport completed. Review the transcript before accepting facts. |
| `partial_or_failed` | The call or transport did not finish cleanly. It can still hold a useful conversation. |
| `voicemail_played` | Media Streams only. The carrier confirmed playback of the submitted message audio. |
| `voicemail_submitted` | SDK only. Local message audio was drained into the live call. Provider playback stays unconfirmed. |
| `result_unavailable` | No receipt exists yet. Inspect the exact run before any further action. |

Receipts carry the exact Call SID, carrier status, `answered_by`, end reason, transcript turns, the destination's last four digits, and SDK parent/child leg states. See the [synthetic request](examples/request.json) and [synthetic receipt](examples/receipt.json).

Neither voicemail status proves that a mailbox saved the message or that a person heard it. Answering-machine detection pauses briefly at pickup and can misclassify. With the SDK transport, an `unknown` result opens the normal conversation, but the receipt keeps `answered_by: unknown` and never claims a confirmed person.

## Phone transports

`phone_transport` in the private config selects the transport. Setup writes `sdk` for new installations. A config without the field keeps the earlier `media_streams` behavior.

| Transport | What runs locally | Notes |
| --- | --- | --- |
| `sdk` (default) | Your installed Google Chrome as a headless renderer, the pinned Twilio Voice SDK, and a per-call callback tunnel | Opus at 48 kHz. Requires an owned TwiML App and API key, created only by an explicit setup command. |
| `media_streams` | A loopback LiveKit room and a per-call Media Streams tunnel | Legacy route. Selectable with `--transport media_streams`. |

The SDK renderer uses a temporary profile with no microphone permission and no speaker output. Setup never downloads a browser. It records the Chrome path and version it detects, or the path you pass with `--chrome`. Each call mints a short-lived token for the configured limit, journals the SDK parent leg and phone child leg separately, and restores admission only after both legs end and local processes stop. There is no transport fallback or automatic redial.

`voicemail_enabled: true` turns on answering-machine detection. A detected beep or greeting-end silence gets one short message from the same voice, built from the briefing and `outcome`, then the call hangs up. Fax and `machine_end_other` hang up without a message. Media Streams also hangs up on `unknown`. Ringing defaults to 60 seconds with voicemail on and 20 seconds with it off.

## Outcome profiles

Each `outcome` selects a reasoning profile and call framing. Defaults live in [call_profiles.py](runtime/call_profiles.py). Override `model`, `effort`, or `service_tier` per outcome under `call_profiles` in the private config. Only the listed values are accepted. The backend must start with the exact profile, or the call fails before dialing.

## Optional layers

| Layer | Opt in with | Needs |
| --- | --- | --- |
| Completion watcher | [watcher setup](watcher/README.md) | Local MCP dependencies (`--local-mcp`) and a configured Jev classifier key. No cloud connection. |
| Private Dot connector | [private connector setup](PRIVATE-PLUGIN.md) | Your own Secure MCP Tunnel and workspace association. |

Local calling needs neither layer. Neither layer arms a watch or places a call when installed. Context Mill is [deferred](../context-mill/README.md) and unrelated to calling.

## Compatibility and evidence

| Component | Tested baseline |
| --- | --- |
| Host | Apple Silicon macOS 15 |
| Python | 3.12 with the included lock |
| Codex CLI | Installation-specific 0.160.0, isolated ChatGPT login |
| Voice route | App Server experimental realtime v3, `gpt-live-1-codex`, `sol` voice |
| SDK transport | Node.js 23.11.0, Google Chrome 156.0.8078.81, `@twilio/voice-sdk` 2.18.5, `playwright-core` 1.65.0, `twilio` 6.2.0 |
| Media Streams | LiveKit server 1.13.6 |
| Callback tunnel | Cloudflared 2026.10.4 |

One personal installation of this code completed real SDK calls answered by a person and by voicemail. The `unknown` detection path, the per-request recipient path, and this public installer are covered only by offline tests. Setup records Node and Chrome versions and flags a mismatch with the tested baseline. Chrome updates itself, so a match is evidence, not a pin.

These results do not prove that a new Mac, account, or line works. Each installation needs its own diagnostics and one authorized test call. Account entitlement, provider charges, audio quality, tunnel availability, and behavior while the Mac sleeps remain unverified. [Quick Tunnels have no uptime guarantee](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Costs and private state

Twilio line and call charges are separate from your assistant subscription. The voice route uses the isolated ChatGPT login. It does not switch to a paid OpenAI API key.

Calls have a 45-minute safety limit by default (`max_call_seconds`). Spoken recording disclosure is on by default (`spoken_disclosure`). Local audio and transcripts are saved either way. Nothing deletes them automatically, so choose a retention practice.

## Maintainers

Run the offline tests from this folder with the runtime's Python and Node. The [source check](scripts/check_source_package.py) rejects dependencies, state, binaries, recordings, personal paths, real-looking numbers and IDs, and an add-on over 1 MiB. CI runs it on every pull request. Release with `git archive` after it passes.

Setup downloads checksum-pinned LiveKit and Cloudflared binaries, and npm packages from the lockfile. Third-party notices for distributed binaries are in [licenses](licenses/LiveKit-NOTICE). Original code uses the repository's [MIT license](../../LICENSE).

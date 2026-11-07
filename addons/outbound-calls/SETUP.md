# Set up outbound calls

Agent guide. This add-on is optional. Complete core assistant setup and one useful task first. Do not run login, access secrets, place a call, install the watcher, or create a notification rule merely because this guide was opened. Apply the user's existing choices and ask one question at a time.

## 1. Check the selected computer

Use an Apple Silicon Mac running macOS 15 or later. It must stay awake and connected during calls. Choose a connected-computer/local-task route or the optional private Dot connector. Verify the actual selected route. Do not assume a cloud task can use this Mac's files or login.

Confirm these are available. If one is missing, guide installation after checking current instructions. Do not install unrelated global tools.

- [uv](https://docs.astral.sh/uv/getting-started/installation/).
- [Node.js](https://nodejs.org/en/download) 20 or later with npm. The tested version is 23.11.0.
- Google Chrome, installed normally, for the default SDK transport. Setup uses it and never downloads a browser.

## 2. Install the runtime

From this add-on folder in the checkout, preview and then install:

```sh
./setup.sh --plan
./setup.sh
```

`--plan` changes nothing. If Python 3.12 is missing, the preview says so instead of installing it.

| Option | Effect |
| --- | --- |
| `--runtime-dir DIR` | Install somewhere other than `~/Library/Application Support/Executive Assistant Calls`. Paths with spaces work. |
| `--transport media_streams` | Install the legacy Media Streams dependencies instead of the SDK ones. |
| `--chrome PATH` | Use this installed Chrome executable instead of the detected one. |
| `--local-mcp` | Also install local MCP dependencies, needed by the watcher and the private connector. |

Setup copies the allowlisted source, then creates a Python 3.12 environment and installs the pinned Codex CLI 0.160.0 inside the runtime. It downloads a checksum-pinned Cloudflared binary (plus LiveKit for Media Streams). For SDK it runs `npm ci` from the lockfile and records Node and Chrome versions in `.state/sdk-transport/readiness.json`. It generates an English disclosure WAV with macOS speech tools. It does not change the global CLI, its login, Node, or Chrome.

Run setup again to update the runtime. It replaces managed source and keeps `.state`, environments, and installed packages. It refuses a directory it did not create and a path inside this checkout. It defers an update while a request is being submitted, a call is running, or a submitted request has no terminal receipt. It holds the runtime's admission and call locks for the whole update. Earlier versions installed into the checkout. That ignored state stays where it is and is not migrated.

The remaining commands run from the runtime directory:

```sh
cd "$HOME/Library/Application Support/Executive Assistant Calls"
```

## 3. Configure the personal connection

Edit `.state/config.json`, created from [the example](config.example.json). Set the Twilio calling line (`from_number`) and the default receiving number (`to_number`) in `+1` E.164 format. They must differ. Choose a Keychain account label, assistant identity, participant name, and check-in purpose. Keep actual numbers and labels out of tracked files.

Spoken disclosure defaults to `true`. The default `max_call_seconds` is `2700`, a 45-minute safety limit enforced by the carrier request and the runtime. `voicemail_enabled` defaults to `false`. Apply the user's choices. Local audio and transcripts are retained regardless of disclosure. Record the user's retention choice.

Store Twilio credentials through an interactive local terminal:

```sh
.venv/bin/python -I -B scripts/store_twilio_credentials.py
```

The helper asks for the Account SID and Auth Token without echoing them. It stores and verifies two Keychain items under the configured prefix and account. It does not send them to a model or place them in config. Use the user's own Twilio account. Do not copy another installation's secrets or change its number routing.

## 4. Create owned SDK resources

Skip this step for `media_streams`. With the user's approval, run once:

```sh
.venv/bin/python -I -B scripts/sdk_setup.py install
```

This creates one TwiML App and one Standard API key named for this installation. The key secret goes to Keychain under `<prefix>.voice-sdk.<installation-id>`. The private `.state/sdk-transport/installation.json` holds only ownership and resource IDs. A repeated `install` verifies and reuses those exact resources. An interrupted create requires reconciliation and is never retried automatically. The command never changes the phone number's webhook.

`scripts/sdk_setup.py cleanup` deletes only the journaled App, key, and secret, and refuses while a call is active.

## 5. Complete isolated ChatGPT sign-in

```sh
./run login
./run login-status
./run diagnose
```

The user completes browser sign-in. The profile is private to this runtime. Never copy an OAuth profile from another computer or reuse an unrelated task's credentials. `diagnose` checks local readiness without dialing or contacting the provider. It does not prove end-to-end calling or realtime entitlement.

If sign-in, voice access, Chrome, or dependencies fail, record the actual blocker and keep the core assistant usable. Do not change the account, shared CLI, or model silently.

## 6. Connect the selected calling route

For the local skill/CLI route, copy the generated `generated/outbound-assistant-call/SKILL.md` into `.agents/skills/outbound-assistant-call/SKILL.md` in the selected assistant workspace. It already contains this runtime's runner path. Record the coordinator and originating Dot/chat route in private `local/` records. No additional manager or Voice task is required.

For direct calls from a Dot, follow [private connector setup](PRIVATE-PLUGIN.md). For a call when one job finishes, follow the optional [watcher setup](watcher/README.md). Both are separate choices.

The coordinator prepares context before each call. For targeted alerts, include the triggering fact, source/date, uncertainty, and the useful decision or question. Do not use the synthetic example as real project news.

## 7. Verify one requested call

Confirm the purpose, recipient, recording/retention choice, and applicable authorization. Use the configured default recipient unless the user names another number for this call. Explain provider charges and the safety limit. Start only when the recipient is available.

Create a fresh request ID and save the actual request privately. Validate it, then invoke `call` once. For the private connector, invoke `request_call` once with the same fields. Retrieve the terminal receipt in the originating conversation.

Check the Call SID, carrier status, `answered_by`, audio, supplied context, caller corrections, confirmed decisions or follow-up, and clean close. Verify no second dial. A carrier-completed call without a confirmed conversation remains partial. A voicemail receipt is delivery evidence only. Record the tested version, date, transport, evidence location, and remaining limitations. Mark only that exact route verified.

## 8. Add notification rules only when selected

Keep calls on demand unless the user selects a concrete automatic condition. For a rule, record the selected projects/sources, condition, freshness, timezone/window, repeat policy, and authorized destination. Use a supported scheduler or event mechanism and keep its actual identifier. Calling tools do not register rules.

Check admission before invoking the runner. Persist a stable event-to-request mapping and expiry so repeated events, restarts, and stale work cannot cause fresh calls. An uncertain placement stays pending for reconciliation. The optional watcher covers only jobs explicitly registered with it.

## Troubleshooting, recovery, and removal

Run `diagnose` for configuration, Keychain, login, version, Chrome, and import failures. Provider reachability, account entitlement, and the per-call tunnel still need separate verification. Keep raw logs and evidence private.

`result` reads saved evidence only. If an SDK call crashed, run `result` with the identical request first. If it still needs reconciliation, run `.venv/bin/python -I -B scripts/sdk_recover.py EXACT_REQUEST_ID`. Recovery closes admission, clears only the owned route, ends the exact recorded calls and processes, and never dials. Do not redial as a recovery shortcut.

To disable calling, disable its triggers and remove the installed skill. For the private connector, remove the dialing gate and stop its connection. For the watcher, use its uninstall command.

Reconcile any active or uncertain call before removal. Preserve receipts and request IDs until resolved. Run SDK `cleanup`, then delete the runtime directory and its Keychain items only as a separate deliberate action. The core assistant continues to work.

Context Mill is [deferred](../context-mill/README.md) and never required for these steps.

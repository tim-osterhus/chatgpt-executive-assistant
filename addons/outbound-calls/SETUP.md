# Set up outbound calls

Agent guide. This add-on is optional. Apply existing user choices and complete core assistant setup first. Do not run login, access secrets, place a call, or create a notification rule merely because this guide was opened.

## 1. Check the selected computer

Use an Apple Silicon Mac running macOS 15 or later. It must stay awake and connected during calls. A Dot needs its actual connected-computer/local-task route verified. Do not assume a cloud task can use this Mac's files or login.

Confirm Node.js with npm and `uv` are available. If missing, guide installation from [Node.js](https://nodejs.org/en/download) and [uv](https://docs.astral.sh/uv/getting-started/installation/) after checking current instructions. Do not install unrelated global tools.

From this add-on folder, run:

```sh
./setup.sh
```

Setup creates a local Python 3.12 environment, installs locked dependencies, and downloads the pinned media binaries. It installs Codex CLI 0.160.0 under `.state/tools/`, leaving the main CLI unchanged. It generates an English disclosure WAV using macOS speech tools. It never calls a phone or starts a recurring service.

## 2. Configure the personal connection

Edit `.state/config.json`, created from [the example](config.example.json). Set the Twilio calling line and the user's receiving number in +1 E.164 format. They must differ. Choose a Keychain account label, assistant identity, participant name, and check-in purpose. Keep actual numbers and account labels out of tracked files.

Spoken disclosure defaults to `true`. Apply the user's installation preference through `spoken_disclosure`. The default `max_call_seconds` is `2700`, a 45-minute safety limit enforced by the carrier request and local runtime. Local audio and transcription evidence are retained regardless of disclosure. Record the user's retention choice and use context suitable for the intended recipient and providers.

Store credentials through an interactive local terminal:

```sh
.venv/bin/python -I -B scripts/store_twilio_credentials.py
```

The helper asks for the Account SID and Auth Token without echoing them. It stores and verifies macOS Keychain items under the configured prefix/account. It does not send them to a model or place them in config. Existing items with that exact service/account are updated. Alternatively, create the two generic-password items in Keychain Access: `<prefix>.twilio-account-sid` and `<prefix>.twilio-auth-token`.

Use the user's own Twilio account. Do not copy another installation's secrets or change its number routing. Verify the selected line and voice capability with a narrow authenticated read when configuring the real account.

## 3. Complete isolated ChatGPT sign-in

```sh
./run login
./run login-status
./run diagnose
```

The user completes browser sign-in. The profile is private to this installation. Never copy an OAuth profile from another computer or reuse an unrelated task's credentials. Diagnostics check local readiness without dialing; they do not prove end-to-end calling or realtime entitlement.

If sign-in, voice access, or dependencies fail, record the actual blocker and keep the core assistant usable. Do not change the account, shared CLI, or model silently.

## 4. Install the calling skill

Copy [skill/SKILL.md](skill/SKILL.md) into `.agents/skills/outbound-assistant-call/SKILL.md` in the selected existing assistant workspace. Set its runner path to this installation's actual absolute path. Record the exact coordinator and originating Dot/chat route in private `local/` records. Reuse the existing coordinator. No additional manager or Voice task is required.

The coordinator prepares context before the call. For targeted alerts, include the exact triggering fact, source/date, uncertainty, and useful decision or question. Do not use the synthetic example as real project news.

## 5. Verify one requested call

Confirm the purpose, fixed recipient, recording/retention choice, and applicable authorization. Explain provider charges and the configured safety limit, initially 45 minutes. Start only when the recipient is available.

Create a fresh request ID and save the actual request privately. Validate it first, then invoke `call` once. Wait for the real terminal receipt in the originating task. Do not promise a background completion callback without testing it.

Check the exact Call SID, carrier status, audio, supplied context, caller corrections, confirmed decisions/follow-up, and clean close. Retrieve `result` with the same JSON and verify no second dial. Record tested version, date, evidence location, and remaining limitations.

Update the calling setup record to verified only for that exact route. A carrier-completed call without a confirmed conversational result remains partial. Preserve useful confirmed facts with the real ending reason.

## 6. Add notification rules only when selected

Keep calls on demand unless the user selects a concrete automatic condition. For a rule, record selected projects/sources, the condition, freshness, timezone/window, repeat policy, and authorized destination. Use a supported scheduler/event mechanism and retain its actual identifier.

The user can ask their Dot to arrange a rule through the existing assistant workspace. Verify the Dot's access to the selected computer and its exact existing coordinator task. The coordinator configures the rule through available native scheduling or source-event tools and reports its real registration and verification result. Do not claim that installing the skill alone connects the Dot or activates a rule.

Check admission before invoking the runner. Persist a stable event-to-request mapping and expiry so repeated events, restarts, and queued stale work cannot cause fresh calls. An uncertain placement stays pending for reconciliation. No scheduler or durable trigger adapter ships in this first calling add-on.

## Troubleshooting and removal

Run `diagnose` for local configuration, Keychain, login, version, and import failures. It may still be necessary to verify provider reachability, account entitlement, or the per-call tunnel separately. Keep raw logs and evidence private.

`result` reads saved evidence only. If the call-create response was lost, inspect the exact run and any known provider Call SID. Do not redial as a recovery shortcut.

To disable calling, disable its actual triggers and remove the installed skill reference. Reconcile an active or uncertain call before removing the runtime. Preserve receipts and request IDs until resolved. Deleting this add-on's private login and Keychain items is a separate deliberate action. The core assistant continues to work.

Context Mill is [deferred](../context-mill/README.md) and never required for these steps.

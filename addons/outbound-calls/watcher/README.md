# Assistant call watcher

This optional per-user macOS service watches only jobs explicitly registered with `assistant-watch-call`. The thin `assistant-call-when-done` skill registers the current thread and reports actual job evidence. It does not keep a conversational Codex task open.

Jev classifies the supplied evidence. The calling runtime supplies the recipient (the configured default unless a watch names another), the immutable call journal, voice configuration, and receipts. Broad alerts and emergency monitoring are outside this watcher. Context Mill is not required and is not part of this installation.

## Prerequisites

- macOS with a logged-in user session and network access.
- The calling add-on set up in its runtime root (default `~/Library/Application Support/Executive Assistant Calls`), with `.state/config.json` present.
- Local MCP dependencies installed first with the add-on setup's `--local-mcp` option. The installer changes nothing until `run-plugin`, `.plugin-venv/bin/python`, the install marker, and the watcher files are present. Its refusal names this option.

## Install

Run these from the calling runtime root:

```sh
cd "$HOME/Library/Application Support/Executive Assistant Calls"
.plugin-venv/bin/python -I -B watcher/install.py plan
.plugin-venv/bin/python -I -B watcher/install.py install
```

`plan` prints the paths and settings and writes nothing. `install` writes:

| Component | Default location |
| --- | --- |
| Watcher code | Runs in place from `watcher/` in the runtime root; not copied |
| State, config, logs | `.state/watcher/` in the runtime root (directories mode 0700) |
| Command | `~/.local/bin/assistant-watch-call` (`--bin-dir DIR` replaces `~/.local/bin`) |
| Skill | `~/.codex/skills/assistant-call-when-done/` (`--skill-dir DIR` replaces `~/.codex/skills`) |
| LaunchAgent | `~/Library/LaunchAgents/local.executive-assistant-calls.watcher.plist` |

The LaunchAgent checks registered jobs once per minute and exits after each check. Installation arms no watch and places no call. It leaves the calling runtime's login, credentials, and configuration unchanged.

Installation refuses on any system other than macOS. It also refuses to overwrite a command, skill, LaunchAgent, or configuration that this runtime did not create. The launcher and LaunchAgent record their runtime path, so another runtime's install or uninstall leaves them alone.

## Store the Jev key

```sh
.plugin-venv/bin/python -I -B watcher/install.py store-jev-key
```

Jev is an external classification API (`api.typesafe.ai`). Each due check sends that watch's job, criteria, owner reports, and check results to it. Register only jobs whose evidence the user accepts sending.

The key is read with hidden input, passed to `/usr/bin/security` on standard input, read back to confirm, and never printed. The Keychain item is `<prefix>.jev-api` with account `completion-watcher`. The prefix comes from `keychain_service_prefix` in `.state/config.json` (default `executive-assistant-calls`).

## Options and uninstall

- `--no-service` installs the command and skill but does not create, load, or remove the LaunchAgent. An existing LaunchAgent is left untouched.
- `uninstall` removes only the command, skill, and LaunchAgent that this installer created. It unloads the service first. It keeps `.state/watcher/`, the Keychain item, and unrelated files.

```sh
.plugin-venv/bin/python -I -B watcher/install.py uninstall
```

## Register and report one job

Ask the existing job-owning thread:

> Use $assistant-call-when-done. Call me when this job finishes and its acceptance checks pass.

The skill registers one concrete job and its criteria. Registration authorizes notifications for that job only. It does not authorize project changes or broad monitoring. Optional `--recipient-number` (full `+1` US/Canadian E.164) and `--recipient-name` flags direct one watch to another recipient. The recipient is fixed at arm time.

Owners send progress and completion reports through `assistant-watch-call progress` and `report`. A finished agent turn alone is not a result. A detached job needs a real completion callback from its existing owner. The service does not launch project commands.

Checkpoints are measured from registration at 24, 48, and 72 hours, and then at later multiples. Checkpoints missed while the Mac was offline coalesce into the latest one. Jev chooses `complete`, `still_running`, `failed_or_blocked`, or `unclear`. A report without passing acceptance evidence cannot support a completed-work claim. Blocked and unclear jobs stay watched unless the owner marks a failure as terminal.

The existing outcome profiles control call framing. The call voice speaks only from the supplied briefing and has no project-action authority. Call intent is saved before submission, and unknown delivery is reconciled under the original request ID. The service does not redial to resolve uncertainty.

With voicemail enabled in the calling runtime, `voicemail_played` and `voicemail_submitted` are terminal delivery receipts. They finish that notice. Neither confirms a conversation, that a mailbox saved the message, or that anyone heard it.

## Inspect or stop

If you used `--bin-dir`, use that path in place of `~/.local/bin`.

```sh
~/.local/bin/assistant-watch-call status
~/.local/bin/assistant-watch-call status <watch-id>
~/.local/bin/assistant-watch-call cancel <watch-id>
launchctl print "gui/$(id -u)/local.executive-assistant-calls.watcher"
```

Cancellation prevents new notifications for that watch. It does not hang up an active call.

To stop the service and keep its state:

```sh
launchctl bootout "gui/$(id -u)/local.executive-assistant-calls.watcher"
```

To start it again:

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.executive-assistant-calls.watcher.plist"
```

The logged-in Mac and its network connection must be available. This installation does not establish automatic reporting from other computers. Private logs and watch state stay in `.state/watcher/` in the runtime root. Review saved receipts in the originating conversation.

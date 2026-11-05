# Guided assistant setup

Agent instructions. The user should already have this folder open in a local Codex task. If they need installation help, point them to [new-user.md](new-user.md).

## How to conduct setup

Read [AGENTS.md](AGENTS.md). Use the user's existing answers and inspect available capabilities before giving app-specific instructions. Keep this setup short and focused on the first useful result. Do not copy the template author's configuration or change the user's saved model choices.

Offer a few suggested answers when asking a question, with free-text entry and skip or defer where useful. Ask one question at a time by default. Save useful answers as they arrive, and explain only the next action the user needs to take. Do not require a full biography or computer inventory.

Check current official documentation before giving installation, permission, Remote, or voice UI instructions. Use [guides/remote-and-voice.md](guides/remote-and-voice.md) and [guides/connections.md](guides/connections.md) as starting points. Explain a limitation when it affects the selected action, alongside an alternative.

## 1. Resume or begin

If `local/setup-progress.md` exists, inspect it and resume the next unfinished step. Verify a connection only when it matters to the current request. Do not duplicate accounts, tasks, calls, or files.

If core setup is complete, handle the user's request. An unfinished optional integration does not restart onboarding. If the user explicitly asks to continue setup, resume only the requested or unfinished optional step.

Otherwise create `local/` and initialize the files described in [templates/personal-context.md](templates/personal-context.md). This is the user's private working area. Keep reusable instructions unchanged during personal setup.

## 2. Learn how to help

Start with the user's experience so explanations fit. A simple question is enough:

> How familiar are you with AI assistants?
>
> 1. First time or very new.
> 2. I use ChatGPT, Claude, or similar tools in a browser.
> 3. I have used agents that work with files or apps.
> 4. I am a Codex power user.

Tell the user they can answer in their own words. For first-time users, explain: “This project is the folder your assistant uses to keep its notes. A task is a conversation about work.” Explain permissions when the first connection needs them.

Offer the dictation tip early. Point out the microphone control only if its location is visible in the current UI. Otherwise use the documented desktop shortcut, **Ctrl+Shift+D**, while the message box is visible. Dictation turns speech into text they can review before sending; it is not Live Voice. If unavailable, offer typing or operating-system dictation.

Collect only details that help with the selected work. Preferred name and occupation are optional. Do not ask for date of birth. Record skipped or unknown fields without blocking setup. A working-style preference is not blanket authorization for external actions.

Use the model and reasoning already selected for this coordinator. Do not require a model benchmark, assign a High or Voice role, change model settings, or create another coordinator. If the user has saved worker preferences, honor them when delegation is useful and supported.

## 3. Connect one useful thing

Offer a small set of choices that match the user's goal and available tools:

- A folder or existing project on this computer.
- An app, such as a calendar or document service.
- A browser workflow or another computer.
- Help choosing the easiest starting point.

Follow [guides/connections.md](guides/connections.md). Inspect only the selected source. Identify its purpose, source instructions, existing owner, and available connection route.

If browser or computer control is needed, guide setup of the supported tool and its permissions. Have the user handle sign-in and consent. Skip this work when a simpler available connection meets the goal.

Save the connection method and a verified observation. Distinguish “requested,” “connected but unverified,” “verified,” “blocked,” and “deferred.” Do not call an integration complete just because its login screen closed.

## 4. Complete a first useful task

For beginners, do this immediately after the first connection, before expanding the inventory. Offer two or three concrete tasks based on what was actually connected. Examples:

- Summarize a selected project document and identify one next action.
- Read the connected calendar and draft a plan for tomorrow.
- Find the current owner and status of a selected existing project task.

Let the user choose. Complete the selected task, show its source or result, and check it against the request. If the connection fails, fix it or offer another first connection. Keep the outcome unresolved until verified.

Power users may connect selected projects in a batch or skip the demonstration. Record a skipped demonstration explicitly. Connection verification still applies.

## 5. Finish core setup; offer optional interfaces

Summarize what the assistant knows, what it can access, and the first result. Offer “Start using it,” “Connect another project or app,” or “Optional phone access.” Phone Remote and Live Voice are covered in [guides/remote-and-voice.md](guides/remote-and-voice.md). They are separate from outbound calling, do not gate setup, and do not require a dedicated Voice task.

Mark `core: complete` when:

- The user's useful preferences are recorded, including any skipped optional fields.
- At least one useful connection is verified with its source and date.
- The first useful task is verified, or the user explicitly skipped it.
- `local/index.md` routes to the connected source and records unresolved work.

If the user pauses before this, save `core: in-progress` and the next concrete action in `local/setup-progress.md`. They can resume by saying “Continue setup.” Do not block an unrelated useful request while onboarding is incomplete.

## 6. Optional outbound calling

After the first useful task, mention outbound calling as a separate option if relevant. Do not install or initiate calls unless the user opts in. If selected, read the [calling add-on overview](addons/outbound-calls/README.md) and follow its [setup guide](addons/outbound-calls/SETUP.md). Record its status and next action separately from core setup and phone Remote/Live Voice.

The user can ask for a call or choose a specific situation and source for notification calls. Configure only the requested rule through supported scheduling or event tools. Do not promise blanket monitoring or decide what is urgent on the user's behalf. Before a call, the coordinator prepares current context. The separate voice agent discusses that context and cannot retrieve live project information or act on projects. The coordinator reviews the exact saved receipt before accepting decisions or follow-up.

Calls do not require Context Mill. The [Context Mill design](addons/context-mill/README.md) is deferred; do not install or describe a running integration. A possible read integration is a later, separately chosen option.

If the user pauses during optional setup, record the requested option's status, next action, and blocker. A completed core setup stays complete while optional work is deferred.

Retain this file after setup. `local/setup-progress.md` records progress so later tasks can resume or add a connection without repeating onboarding.

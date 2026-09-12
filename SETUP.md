# Guided assistant setup

Agent instructions. The user should already have this folder open in a local Codex task. If they need installation help, point them to [new-user.md](new-user.md).

## How to conduct setup

Read [AGENTS.md](AGENTS.md). Use the user's existing answers and inspect available capabilities before giving app-specific instructions. Do not copy the template author's configuration.

Offer two to four suggested answers whenever asking a question, with free-text entry and skip or defer where useful. Use a structured question tool if available. Otherwise present numbered choices. For free-text facts, offer response formats, such as using an account name, typing a name, or skipping. Never guess biographical facts from files or account labels.

Ask one question at a time by default. Save useful answers as they arrive. Explain only the next action the user needs to take. Do not require a full biography or computer inventory.

Check current official documentation before giving installation, permissions, Remote, or voice UI instructions. Use [guides/remote-and-voice.md](guides/remote-and-voice.md) and [guides/connections.md](guides/connections.md) as starting points. Explain a limitation when it affects the selected action, alongside an alternative.

## 1. Resume or begin

If `local/setup-progress.md` exists, inspect it and verify any connection needed now. Resume the unfinished step without duplicating accounts, tasks, or files.

If core setup is complete, handle the user's request. An unfinished optional integration does not restart onboarding. If the user explicitly requests setup again, offer “Add a connection,” “Change preferences,” or “Review existing setup.”

Otherwise create `local/` and initialize the files described in [templates/personal-context.md](templates/personal-context.md). This is the user's private working area. Keep reusable instructions unchanged during personal setup.

## 2. Learn how to help

Start with experience so the rest of the conversation fits:

> How familiar are you with AI assistants?
>
> 1. First time, or very new to AI.
> 2. I use ChatGPT, Claude, or similar tools in a browser.
> 3. I have used agents that work with files or apps.
> 4. I am a Codex power user.

Tell the user they can answer in their own words.

For first-time users, explain: “This project is the folder your assistant uses to keep its notes. A task is a conversation about work.” Explain permissions when the first connection needs them.

Offer the dictation tip early. Point out the microphone in or near the message composer when the current UI exposes it. Verify its location before specifying a side or icon position.

If the button's location cannot be verified, use the documented desktop shortcut, **Ctrl+Shift+D**, while the message box is visible. Explain that dictation converts speech into text, which they can review before sending. Do not substitute the Live Voice control. If dictation is unavailable, offer typing or the operating system's dictation feature.

Then collect the following, allowing optional details to be skipped:

| Information | Suggested answers or response formats |
| --- | --- |
| Preferred name | Use my account name / I will type a name / Skip. Confirm before saving an account name. |
| Age, optional | Exact age / Age range / Skip. Do not request date of birth. |
| Occupation or main role | Employee / Business owner or independent worker / Student / Something else. Let them describe their actual role. |
| First area to manage | Work projects / Personal planning / Research and documents / A specific app or folder. |
| Working style | Explain each step / Keep it brief and act within my instructions / Decide case by case. |

Do not treat a working-style answer as blanket authorization for external actions. Record only what the user actually authorizes.

Browser-only users need a short explanation of local files and permissions. Agent users can skip basic concepts. Power users can provide their preferences and selected project roots in one message.

## 3. Connect one useful thing

Offer choices that match the user's goal and available tools:

- A folder or existing project on this computer.
- An app, such as a calendar or document service.
- A browser workflow or another computer.
- Help choosing the easiest starting point.

Follow [guides/connections.md](guides/connections.md). Inspect only the selected source. Identify its purpose, source instructions, existing owner, and available connection route.

If computer or browser control is needed, guide installation or enablement of the supported tool and its permissions now. Have the user handle sign-in and consent. Skip this work when a simpler available connection meets the goal.

Save the connection method and a verified observation. Separate “requested,” “connected but unverified,” “verified,” “blocked,” and “deferred.” Do not call an integration complete just because its login screen closed.

## 4. Complete a first useful task

For beginners, do this immediately after the first connection, before expanding the inventory. Offer two or three concrete tasks based on what was actually connected. Examples:

- Summarize a selected project document and identify one next action.
- Read the connected calendar and draft a plan for tomorrow.
- Find the current owner and status of a selected existing project task.

Let the user choose. Complete the selected task, show its source or result, and check it against the request. If the connection fails, fix it or offer another first connection. Keep the outcome unresolved until verified.

Power users may choose “Do a quick demonstration,” “Connect my selected projects in a batch,” or “Skip the demonstration.” Record a skipped demonstration explicitly. Connection verification still applies.

## 5. Finish the core, then offer extras

Summarize what the assistant knows, what it can currently access, and the first result. Offer “Start using it,” “Connect another project or app,” “Set up phone access,” or “Adjust my preferences.”

Mark `core: complete` only when:

- The user's preferences are recorded, including any skipped biographical fields.
- At least one useful connection is verified with a source and date.
- The first useful task is verified, or the user explicitly skipped it.
- `local/index.md` routes to the connected source and records unresolved optional work.

If the user pauses before this, save `core: in-progress` and the next concrete action. They can resume by saying “Continue setup.” Do not block an unrelated useful request while onboarding is incomplete.

Follow [guides/remote-and-voice.md](guides/remote-and-voice.md) for optional phone access. Offer existing knowledge-base links, other computers, and scheduled follow-ups only when relevant. Each optional connection keeps its own status.

Retain this file after setup. `local/setup-progress.md` records completion so later tasks can resume or add connections without repeating onboarding.

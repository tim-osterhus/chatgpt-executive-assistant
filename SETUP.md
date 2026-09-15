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

### Set up the Voice and High roles

Check the runtime model catalog and available task tools. Recommend a dedicated Astra Light Voice task with model `gpt-6-astra` and reasoning `low`, plus the existing Astra High orchestration task with model `gpt-6-astra` and reasoning `high`. The desktop **Light** label maps to CLI `low`. Verify each active model and reasoning setting instead of assuming the written policy changed the task.

Explain simply: “Voice handles Live Voice and quick self-contained work. High handles substantial planning, cross-project coordination, long execution, final acceptance, and central summaries and jobs. Luna handles focused delegated work, and High checks the results.” Light owns the decision and completion check for small authorized actions. A quick browser action may stay on Voice when supported. For substantial work, route substantial browser or computer-control work to High.

Offer “Use this recommended setup,” “Keep my current model settings,” or “Help me choose.” Respect an existing explicit preference without asking again. Follow [guides/work-allocation.md](guides/work-allocation.md) to apply supported project defaults and explicit worker settings. Save the chosen policy and its requested and verified role settings in `local/preferences.md` and the generated role records.

Do not delay the first useful task to benchmark models. If High is unavailable, offer an available coordinator or keep the current setup. If Light, Live Voice, or the required Voice task tools are unavailable, record Voice setup as deferred. Keep typed requests and dictation available in either task. Do not silently route Live Voice through High. Follow an explicit user override and record it.

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

## 5. Recommend phone access and set up Voice, then finish setup

Summarize what the assistant knows, what it can currently access, and the first result. Explicitly recommend phone access now, before offering other optional integrations. For power users who skipped the demonstration, make this offer after verifying their first connection.

Explain: “I highly recommend connecting your phone. Through Remote, open the dedicated Executive Assistant Voice task in this project and use Live Voice there when available. Voice handles conversation and quick work, then sends substantial work to the existing High orchestration task. I can report verified results back through Voice.”

Offer “Create or reuse one dedicated Voice task in this project (recommended),” “Later,” or “Keep this desktop-only.” Follow [guides/remote-and-voice.md](guides/remote-and-voice.md) if selected. The user's selection to create or reuse a Voice task authorizes that one supported task-tool action. Resolve the current **Executive Assistant** local project and existing High task first. If no Voice task exists and the user selects creation, create exactly one dedicated Voice task in that same project when a supported task tool is available. Preserve the High task. Do not create more managers or replacement project tasks.

Record the choice in `local/setup-progress.md`, with separate results for Remote pairing and Live Voice verification. Record the Voice and High role identifiers, hosts, requested models and reasoning, verified models and reasoning, and verification dates. If the user already has a verified Voice task, reuse it. If the task, model, or Live Voice is unavailable, record Voice as deferred and keep typed or dictated use available. Do not automatically transfer a Live Voice session from another task. Tell the user: “Stop the current voice session, open Executive Assistant Voice, and start voice there.”

Respect a deferral without repeatedly prompting. After this choice or walkthrough, offer “Start using it,” “Connect another project or app,” or “Adjust my preferences.”

Mark `core: complete` only when:

- The user's preferences are recorded, including any skipped biographical fields.
- At least one useful connection is verified with a source and date.
- The first useful task is verified, or the user explicitly skipped it.
- `local/index.md` routes to the connected source and records unresolved optional work.
- The Voice and High role records include their task identifiers, hosts, requested settings, verified settings, and dates, or an explicit deferred status.

If the user pauses before this, save `core: in-progress` and the next concrete action. They can resume by saying “Continue setup.” Do not block an unrelated useful request while onboarding is incomplete.

Phone access and the dedicated Voice task remain optional and do not gate core completion. Keep Live Voice in the dedicated Voice task by default. Typed requests and dictation work in either task. Offer existing knowledge-base links, other computers, and scheduled follow-ups only when relevant. Each optional connection keeps its own status.

Retain this file after setup. `local/setup-progress.md` records completion so later tasks can resume or add connections without repeating onboarding.

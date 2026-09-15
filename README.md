# ChatGPT Executive Assistant

A workspace template that transforms Codex into your personal executive assistant. It includes all the instructions Codex needs for organizing your projects, remembering your preferences, and coordinating work across connected tools and apps. Open the folder in Codex and let the assistant guide setup through conversation.

**For best performance, we recommend at least the $100/month ChatGPT Pro plan.** Plus and Free have substantial usage and capability limitations for this workflow, and have not been tested. See [OpenAI’s plan breakdown](https://learn.chatgpt.com/docs/pricing) or [upgrade to Pro](https://chatgpt.com/explore/pro).

## Start here

**New to Codex?** Follow [the new-user guide](new-user.md). It covers downloading this folder, installing the app, signing in, and starting setup.

**Already use Codex?** Download this repository with **Code → Download ZIP**, extract it, and open the extracted folder as a local Codex project. Start a task in that project and send:

> Start setup. Read SETUP.md and walk me through it.

Or just point Codex at this repo and tell it to set it up.

Setup asks about you, adjusts to your experience, and helps connect your first project or app. It then offers phone access as an optional, highly recommended step, with one dedicated Voice task in this Executive Assistant project.

## Talk to your assistant from your phone

Connect your phone through Remote, open the dedicated **Executive Assistant Voice** task in this project, and use ChatGPT Voice, powered by GPT-Live, where available. Voice uses Astra Light for every Live Voice session and handles quick self-contained requests directly. For substantial work, it routes to the existing Executive Assistant High orchestration task, which can use project managers and Luna Max workers.

Keep every Live Voice session in the dedicated Voice task. Ask it for a quick lookup, draft, small edit, or browser action. High handles longer workflows and cross-project coordination. Your computer runs the work and stays awake and connected. Follow [the phone and voice guide](guides/remote-and-voice.md), or say:

> Help me set up Remote and Live Voice so I can manage my projects from my phone.

If Live Voice is active in another task, stop the current voice session, open **Executive Assistant Voice**, and start voice there. Typed requests and dictation remain usable in either task.

## One conversation, connected work

You might ask:

- “What needs my attention across my projects?”

- “Find the latest notes for my website and help me decide what to do next.”

- “Ask the existing website task to make that change and check its result.”

- “Draft tomorrow’s plan using my connected calendar and project priorities.”

The assistant keeps a small index of what you manage, where the source material lives, and which project or task owns the work. It reads the relevant context when needed. High owns central summaries and jobs. Existing project tasks keep their responsibilities.

Your preferences and project notes live in a generated `local/` folder, excluded from Git by default. You can connect an existing knowledge base without moving it here.

## Voice handles quick work, High coordinates, Luna does bounded work

The recommended setup uses Astra Light for Live Voice and quick self-contained work. Astra High handles persistent project management, decisions, final acceptance, and substantial browser or computer-control work. Luna Max handles delegated research, implementation, document work, and verification. High checks delegated results and reports back through Voice when you use your phone.

Setup checks the runtime model catalog and records requested and verified role settings. The [work allocation guide](guides/work-allocation.md) explains the split and how to keep assignments focused without creating duplicate job ownership.

## What’s in the folder

| File or folder | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Entry point and everyday operating instructions for the assistant. |
| [SETUP.md](SETUP.md) | Guided, resumable setup run by the assistant. |
| [new-user.md](new-user.md) | Short installation guide for people starting from GitHub. |
| [guides/](guides/) | Connecting projects and apps, phone access, and daily use. |
| [templates/](templates/) | Small formats for personal context, project records, and assignments. |
| [maintainers.md](maintainers.md) | Release checks and the first beginner pilot. |

No custom server, database, or coding is required to use the template. This initial version targets the Codex desktop app workflow.

Inspired by [Interpretable Context Methodology](https://arxiv.org/abs/2603.16021), by Jake Van Clief and David McDermott: use readable files and selective context to make agent work easier to inspect. This template applies that idea to a personal assistant.

Free to use and adapt under the [MIT License](LICENSE).

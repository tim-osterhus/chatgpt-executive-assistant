# ChatGPT Executive Assistant

A free Markdown workspace that gives Codex instructions for organizing your projects, remembering your preferences, and coordinating work across connected tools. Open the folder in Codex and let the assistant guide setup through conversation.

**For best performance, we recommend at least the $100/month ChatGPT Pro plan.** Plus and Free have substantial usage and capability limitations for this workflow. See [OpenAI’s plan breakdown](https://learn.chatgpt.com/docs/pricing) or [upgrade to Pro](https://chatgpt.com/explore/pro).

## Start here

**New to Codex?** Follow [the new-user guide](new-user.md). It covers downloading this folder, installing the app, signing in, and starting setup.

**Already use Codex?** Download this repository with **Code → Download ZIP**, extract it, and open the extracted folder as a local Codex project. Start a task in that project and send:

> Start setup. Read SETUP.md and walk me through it.

Setup asks about you, adjusts to your experience, and helps connect your first project or app. You can add phone access, other computers, and more integrations later.

## One conversation, connected work

You might ask:

- “What needs my attention across my projects?”

- “Find the latest notes for my website and help me decide what to do next.”

- “Ask the existing website task to make that change and check its result.”

- “Draft tomorrow’s plan using my connected calendar and project priorities.”

The assistant keeps a small index of what you manage, where the source material lives, and which project or task owns the work. It reads the relevant context when needed. Existing project tasks keep their responsibilities.

Your preferences and project notes live in a generated `local/` folder, excluded from Git by default. You can connect an existing knowledge base without moving it here.

## What’s in the folder

| File or folder | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Entry point and everyday operating instructions for the assistant. |
| [SETUP.md](SETUP.md) | Guided, resumable setup run by the assistant. |
| [new-user.md](new-user.md) | Short installation guide for people starting from GitHub. |
| [guides/](guides/) | Connecting projects and apps, phone access, and daily use. |
| [templates/](templates/) | Small formats for personal context, project records, and assignments. |
| [maintainers.md](maintainers.md) | Release checks and the first beginner pilot. |

No custom server, database, or coding is required to use the template. This initial version targets the Codex desktop workflow. A first beginner pilot is pending.

Inspired by [Interpretable Context Methodology](https://arxiv.org/abs/2603.16021), by Jake Van Clief and David McDermott: use readable files and selective context to make agent work easier to inspect. This template applies that idea to a personal assistant.

Free to use and adapt under the [MIT License](LICENSE).

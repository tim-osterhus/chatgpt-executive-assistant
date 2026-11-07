# ChatGPT Executive Assistant

A workspace template for using Codex as a personal executive assistant. It keeps a small map of your projects, your preferences, and where work belongs. Your project folders, app accounts, and existing project tasks keep their own owners.

The core assistant works from the Codex desktop app and the tools you already use. Phone access and outbound calling are optional additions. The core setup does not require a calling service, Context Mill, or a particular model plan.

## Start here

**New to Codex?** Follow [the new-user guide](new-user.md) to download this folder, open it in Codex, and start setup.

**Already use Codex?** Download this repository with **Code → Download ZIP**, extract it, and open the folder as a local Codex project. Start a task in that project and send:

> Start setup. Read SETUP.md and walk me through it.

Setup records your preferences, connects one useful project or app, and completes a first useful task with you. It can pause and resume from the private notes it creates under `local/`.

## Use the assistant

Ask the coordinator in your existing project task to:

- “What needs my attention across the projects I connected?”
- “Find the latest notes for my website and show me the source.”
- “Ask the existing website task to make this change, then check its result.”
- “Draft tomorrow’s plan using my connected calendar and priorities.”

The assistant uses the model and reasoning settings you chose. It can delegate bounded work when useful, while existing project owners keep their responsibilities. See [work allocation](guides/work-allocation.md).

Your preferences and project notes live in a generated `local/` folder, excluded from Git by default. You can link an existing knowledge base without moving it here.

## Optional ways to talk

You can type or dictate in your existing task. If you want to work from your phone, set up Remote and try Live Voice when it is available. This is optional and does not require a separate Voice task. See [phone access and Live Voice](guides/remote-and-voice.md).

You can also install the separate [optional outbound-calling add-on](addons/outbound-calls/README.md). Its runtime and private call evidence live outside this folder. Choose the local skill/CLI route or the [private MCP plugin](addons/outbound-calls/PRIVATE-PLUGIN.md) for direct Dot calls. Both use the same local voice runtime. An optional [completion watcher](addons/outbound-calls/watcher/README.md) can call when one job you register finishes.

Set it up independently after your first useful task using its [setup guide](addons/outbound-calls/SETUP.md). It supports calls you ask the assistant to make and notification calls for situations and sources you explicitly select. It does not provide blanket active monitoring.

Before a call, the coordinator prepares the relevant context. The voice agent speaks from that briefing and cannot retrieve project information or take project actions. The coordinator reviews the saved call receipt afterward. Calls do not require Context Mill.

The [Context Mill design](addons/context-mill/README.md) is deferred. An optional read integration may be considered later. This template does not install or require that integration.

## What’s in the folder

| File or folder | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Entry point and everyday operating instructions. |
| [SETUP.md](SETUP.md) | Guided, resumable core setup. |
| [new-user.md](new-user.md) | Short installation guide for people starting from GitHub. |
| [guides/](guides/) | Connecting projects and apps, daily use, work allocation, and optional phone voice. |
| [templates/](templates/) | Formats for private context, project records, and assignments. |
| [maintainers.md](maintainers.md) | Release checks and the beginner pilot. |

The core template needs no custom server or database. The optional calling add-on has its own local runtime and service requirements, described in its setup guide.

Inspired by [Interpretable Context Methodology](https://arxiv.org/abs/2603.16021), by Jake Van Clief and David McDermott: readable files and selective context make agent work easier to inspect. This template applies that idea to personal work coordination.

Free to use and adapt under the [MIT License](LICENSE).

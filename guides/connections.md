# Connect projects, apps, and other computers

Agent guide. Apply the user's existing choices and permissions. Offer suggested answers for new questions. Save results in `local/connections.md` and relevant records under `local/projects/`.

## A folder or existing project

1. Resolve the selected project using available project tools or the user-provided folder.
2. Read its top-level instructions and the minimum documents needed to understand its purpose.
3. Identify existing tasks, their exact identifiers, and current responsibility where tools allow it.
4. Save a short project record using [the project format](../templates/project.md).
5. Verify access by reading a relevant source and returning a source-backed result.

Keep the original folder and its existing owners. A connection usually needs a pointer and an access route, not a copied project.

If the user wants delegated execution, verify that route separately. Read the existing task's status before dispatching. Use native tools when available, with an exact identifier rather than title matching alone.

If task tools are unavailable, record file access as verified and task delegation as unavailable. Offer a prepared handoff or help connecting the missing capability.

## An app or browser workflow

Prefer an existing connector, plugin, or supported API. Inspect the available tools before suggesting installation. Read the selected tool's setup instructions and use its normal installation flow.

If the workflow requires computer control, follow [OpenAI's Computer Use setup](https://learn.chatgpt.com/docs/computer-use). The documented desktop route is **Plugins → Computer Use**. Install or enable the plugin and its required components as shown. Follow the app's platform-specific permission prompts.

For an external browser, follow the tool's browser connection instructions. Connect the browser and profile the user intends to use. Ask the user to complete login and consent when needed.

Verify a narrow read operation, such as retrieving one selected document or the requested day's calendar. Store the account label, method, scope, observation, and date. Keep credentials in the app or its credential store.

## Another computer

Ask whether the user wants another computer connected now or later. For a novice, connect one local source before adding a remote host.

Discover supported routes from current documentation and the installed tools. An app-native remote connection and SSH are different methods. Do not assume they expose the same tasks or use the same account.

Record the host, intended account label, chosen route, exact project location, and existing owner. Confirm which account will execute work before dispatching. Do not switch accounts or copy authentication files.

Verify reading the intended project's context. If delegation is requested, submit a small authorized task and retrieve its actual reply. A visible task list or accepted queue item alone does not verify execution.

Keep the remote desktop app and existing tasks usable by their owner. Do not add handoff tasks, transfer ownership, or close apps just to deliver a message. Verify an alternative supported transport if the native route cannot write to an existing task. Never copy a machine-specific workaround from another installation without checking its support and behavior.

## An existing knowledge base

Keep the knowledge base in its current location. Read its index and maintenance instructions, then link only relevant pages from project records. Record which source owns durable knowledge and which task may update it.

This assistant stores operational summaries. Propose durable knowledge changes through the knowledge base's established owner when one exists.

## Optional outbound calling

Outbound calling is a separately installed local skill and CLI workflow, not a published MCP plugin. It is independent of core setup, phone Remote, Live Voice, and Context Mill. Offer it after the first useful task and only set it up if the user opts in. Read the [add-on overview](../addons/outbound-calls/README.md) and follow its [setup guide](../addons/outbound-calls/SETUP.md). Keep its status separate in `local/setup-progress.md` and `local/connections.md`.

The user may request a call directly. Notification rules need a user-selected situation and source, then verified registration through supported scheduling or event tools. Do not promise general monitoring, invent urgency, or configure a schedule merely by installing calling.

Before the call, read the relevant connected source, confirm the facts needed, and prepare a briefing. The separate voice agent speaks from that briefing; it has no live retrieval or project-action route during the call. After the call, retrieve and review the exact saved receipt before reporting decisions or follow-up. Do not treat submission as completion. If a send is uncertain, inspect its saved result before any retry; never redial to resolve uncertainty.

Calls do not require Context Mill. Its design is deferred in [addons/context-mill/README.md](../addons/context-mill/README.md); a future read integration would be an optional, separate decision. Do not claim it is installed or running.

## Failure and recovery

Record a blocked connection with the last successful observation and the next concrete action. Offer reconnection, a different source, or deferral.

Before retrying an uncertain write or task submission, check whether it already happened. Avoid creating duplicate tasks or repeating external actions.

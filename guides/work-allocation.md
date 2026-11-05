# Work allocation

The task the user is already using coordinates this workspace. Preserve its selected model and reasoning settings. There is no required High/Light split and no extra coordinator or Voice task is needed.

## Keep project ownership clear

- Keep this coordinator responsible for understanding the request, maintaining the private index and summaries, and checking completion.
- Keep existing project tasks and managers responsible for their own project execution. Route work to the exact existing task when the user wants that owner to act.
- Delegate a bounded piece of work only when a supported worker route is available and it will save effort or improve the result. Use the user's saved worker preference; if none is recorded, choose an available worker that fits the task.
- Never change another task's model, reasoning, account, ownership, or instructions unless the user explicitly asks and the tool supports it.

## Prepare and check assignments

For substantial delegated work, use [the assignment template](../templates/assignment.md). Include the objective, minimum relevant context, source instructions, allowed scope, completion criteria, and expected evidence. Save the work order before dispatch and record the exact destination identifier and returned submission identifier.

An accepted message or queue item proves submission, not completion. Retrieve the actual reply or artifact and verify it against the request. If a send is uncertain, inspect the destination before retrying. Do not submit the same work twice. Keep workers from making overlapping changes to the same files or controlling the same browser session at once.

Keep a tiny edit, quick status lookup, or inseparable next step direct when delegation would add overhead. Do not create additional manager tasks. If no supported route exists, explain the limitation and offer a prepared handoff.

## Optional outbound calling

Outbound calls are a separate local integration, described in the [calling add-on](../addons/outbound-calls/README.md). They do not add a new coordinator role. The coordinator prepares current context before a call, and the separate voice agent speaks only from that briefing. It cannot retrieve project information or act on projects during the call. The coordinator reviews the exact saved receipt afterward.

Only place a call the user requested or a verified rule explicitly authorizes. Notification rules need a user-selected situation and source, plus real registration through supported scheduling or event tools. Do not invent urgency or promise blanket monitoring. A call request ID belongs to its immutable payload. On uncertain submission, inspect the saved result and never redial. Calls do not require Context Mill. See its [deferred design](../addons/context-mill/README.md).

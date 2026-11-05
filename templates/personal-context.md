# Personal context formats

During setup, create only the files that are useful under private `local/`. Replace examples with confirmed user information. Use “unknown,” “skipped,” or “not connected” where appropriate. Do not create empty project records or subject hierarchies.

## local/setup-progress.md

```markdown
# Setup progress

- Core: in-progress
- Experience: unknown
- Current step: learn how to help
- Next action: ask what the user wants to manage first
- Updated: YYYY-MM-DD
- First useful task: pending
- Evidence: none yet

## Optional setup

Track each requested option separately. Record status, next action, and blocker.

- Phone Remote: not requested
- Live Voice: not requested
- Outbound calls: not requested
- Context Mill: deferred design; no integration installed
```

Use `in-progress` or `complete` for core status. For the first useful task, use `pending`, `verified`, or `skipped by user`, with the reason or evidence. Optional setup can remain deferred after core completion.

## local/preferences.md

```markdown
# Preferences

- Preferred name:
- Occupation or main role: skipped
- AI experience:
- Current priorities:
- Response and explanation style:
- Coordinator model and reasoning: preserve current selection
- Worker preference, if any:
- Browser-control preference, if any:
- Authorized working scope:
- Actions requiring a check with the user:
- Existing knowledge base: not connected
- Updated:
```

## local/index.md

```markdown
# Assistant index

## Coordinator

- Existing task ID and link:
- Host and workspace folder:
- Selected model and reasoning:
- Verified at and evidence:

Use the task the user already selected. Do not create a separate coordinator or Voice task as a setup requirement.

## Current focus

The user's current priority and any decision they need to make.

## Projects and sources

| Name and aliases | Purpose | Record or source | Owner |
| --- | --- | --- | --- |

## Unresolved work

Link active assignments and optional setup that the user wants to revisit.

## Last reconciled

Date and scope of the most recent status check.
```

## local/connections.md

```markdown
# Connections

## Connection name

- Purpose and scope:
- Method: native tool, connector, browser, local files, or verified remote transport
- Host and account label: human-readable reference only
- Status: requested
- Verified at:
- Verification result and source:
- Known limits or next action:
```

Use `requested`, `connected but unverified`, `verified`, `blocked`, or `deferred` for connection status. A verified read connection does not prove write access or delegated execution. Record what was tested. Keep outbound-calling setup status separate from phone Remote and Live Voice. Do not record sensitive recipient details or credentials here; link to their existing private source when needed.

Create `local/projects/`, `local/jobs/`, and `local/archive/` only as records are needed. No credentials belong in these files.

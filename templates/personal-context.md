# Personal context formats

During setup, create the following files under `local/`. Replace examples with confirmed user information. Use “unknown,” “skipped,” or “not connected” where appropriate. Do not create unused project records or empty subject hierarchies.

## local/setup-progress.md

```markdown
# Setup progress

- Core: in-progress
- Experience: unknown
- Current step: learn how to help
- Next action: ask about experience
- Updated: YYYY-MM-DD
- First useful task: pending
- Evidence: none yet

## Optional setup

Record requested extras with status, next action, and any blocker.
```

Use `in-progress` or `complete` for core status. For the first useful task, use `pending`, `verified`, or `skipped by user`, with the reason or evidence. Optional setup can remain deferred after core completion.

## local/preferences.md

```markdown
# Preferences

- Preferred name:
- Age or range: skipped
- Occupation or main role:
- AI experience:
- Current priorities:
- Response and explanation style:
- Coordinator model and reasoning:
- Worker model and reasoning:
- Browser-control model:
- Model policy verification and any fallback:
- Authorized working scope:
- Actions requiring a check with the user:
- Existing knowledge base: not connected
- Updated:
```

## local/index.md

```markdown
# Assistant index

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

Use `requested`, `connected but unverified`, `verified`, `blocked`, or `deferred` for connection status. A verified read connection does not prove write access or delegated execution. Record what was tested.

Create `local/projects/`, `local/jobs/`, and `local/archive/` only as records are needed. No credentials belong in these files.

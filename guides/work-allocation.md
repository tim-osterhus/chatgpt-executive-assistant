# Model choice and work allocation

This template recommends the following division of work when the account and tools support it. Apply the user's saved preferences from `local/preferences.md`.

| Responsibility | Recommended model |
| --- | --- |
| All Live Voice sessions and quick self-contained actions | Astra Light |
| Persistent orchestration, project management, and substantial-work acceptance | Astra High |
| Planning, resolving ambiguity, and cross-project decisions | Astra High |
| Quick browser actions / substantial browser workflows | Astra Light / Astra High |
| Bounded implementation, file edits, document processing, and data extraction | Luna Max |
| Research through search tools, documentation, or APIs | Luna Max |
| Independent tests, checks, and evidence gathering | Luna Max |

Luna Max means model `gpt-5.6-luna` with reasoning effort `max`. It is the default worker choice in this template. Browser control stays with Astra by design. Research that only needs search or an API can go to Luna.

## Make the preference effective

Check the current host's model catalog and delegation tools. Set both the worker model and reasoning effort explicitly when spawning. A generic worker role alone does not select Luna.

For the main assistant, select Astra High (`gpt-6-astra`, `high`) through a supported task tool or guide the user through the model picker. Verify the active selection rather than assuming the written policy changed the running task.

For the dedicated **Executive Assistant Voice** task, select Astra Light (`gpt-6-astra`, `low`). Keep it in the same workspace folder as the existing High task. Apply these settings per task, so selecting Light does not downgrade High. The [Light label corresponds to Low](https://learn.chatgpt.com/docs/models#pick-a-reasoning-effort) in CLI settings.

Keep all Live Voice sessions in Voice, including desktop sessions. Light handles small requests directly and checks their results. Examples include a lookup, short draft, small authorized file edit, connector action, or quick browser action. It does not need High's approval for work already authorized by the user.

For substantial work, Light sends the objective, relevant context, and the user's exact authorization to the recorded High task. High owns the job record, delegates to project owners or Luna Max, and returns verified results. Light relays those results in the ongoing voice conversation. Neither task should submit the same job twice or control the same browser session concurrently.

High maintains central summaries and job files. Light can make small authorized edits elsewhere and send relevant updates to High. A trivial action does not need a delegation record. Use this division for work, not additional permission prompts.

If a tool's full-history fork inherits the parent model, use its supported bounded-context spawn mode for an explicit Luna selection. Give the worker the necessary sources and instructions. Do not invent tool arguments.

During setup, when supported and selected by the user, merge these project-scoped defaults into `.codex/config.toml`:

```toml
[agents]
default_subagent_model = "gpt-5.6-luna"
default_subagent_reasoning_effort = "max"
```

Preserve existing configuration and verify the effective settings. Explicit spawn arguments or custom-agent configuration can override defaults. Check the actual worker model when the tools expose it. Record requested settings separately from verified settings.

The generated `.codex/config.toml` is excluded from Git. These defaults apply to this local project. Keep personal context in `local/`.

Do not silently change global configuration or another project's model settings. Existing project managers keep their models and ownership. Include this allocation preference in their work orders where compatible with the user's authority and their instructions. A workspace policy does not automatically reconfigure every connected project.

If Astra or Luna Max is unavailable, offer the best available coordinator/worker pair, the current configuration, or deferral. Record the chosen fallback. Do not repeatedly attempt an unavailable model or claim it ran.

If the dedicated Light task or Live Voice is unavailable, defer voice setup and keep typing or dictation available. Do not silently start Live Voice in High or transfer an active call to a worker. Follow a user's explicit change to this preference.

## Delegate substantial work, keep assignments small

Delegate a concrete outcome with the minimum relevant context, allowed files or systems, completion criteria, and expected evidence. Reuse a suitable worker for related follow-ups. Parallelize independent work with separate write scopes.

Workers return concise findings, changed-file references, verification results, and blockers. Astra integrates their results and performs the checks needed for final acceptance. It should not repeat all the worker's research or reread every intermediate log.

Keep a tiny edit, quick status read, or inseparable next step direct when a worker would add unnecessary overhead. Do not create extra manager layers or fan out a simple request.

Escalate unresolved ambiguity, repeated failure, or a discovery that changes the plan to Astra. If a worker reaches a browser-control step, return the exact next action to Astra.

This policy aims to reduce expensive coordinator work and context load. It does not guarantee fewer total tokens. Higher reasoning effort and extra workers add usage, so delegation still needs a useful purpose.

Sources, checked 2026-09-15: [Codex subagents and model defaults](https://learn.chatgpt.com/docs/agent-configuration/subagents), [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

# Model choice and work allocation

This template recommends the following division of work when the account and tools support it. Apply the user's saved preferences from `local/preferences.md`.

| Responsibility | Recommended model |
| --- | --- |
| Persistent Executive Assistant and project-manager tasks | Astra, initially High |
| Planning, resolving ambiguity, cross-project decisions, and final acceptance | Astra |
| Browser and computer control | Astra |
| Bounded implementation, file edits, document processing, and data extraction | Luna Max |
| Research through search tools, documentation, or APIs | Luna Max |
| Independent tests, checks, and evidence gathering | Luna Max |

Luna Max means model `gpt-5.6-luna` with reasoning effort `max`. It is the default worker choice in this template. Browser control stays with Astra by design. Research that only needs search or an API can go to Luna.

## Make the preference effective

Check the current host's model catalog and delegation tools. Set both the worker model and reasoning effort explicitly when spawning. A generic worker role alone does not select Luna.

For the main assistant, select Astra High (`gpt-6-astra`, `high`) through a supported task tool or guide the user through the model picker. Verify the active selection rather than assuming the written policy changed the running task.

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

## Delegate substantial work, keep assignments small

Delegate a concrete outcome with the minimum relevant context, allowed files or systems, completion criteria, and expected evidence. Reuse a suitable worker for related follow-ups. Parallelize independent work with separate write scopes.

Workers return concise findings, changed-file references, verification results, and blockers. Astra integrates their results and performs the checks needed for final acceptance. It should not repeat all the worker's research or reread every intermediate log.

Keep a tiny edit, quick status read, or inseparable next step direct when a worker would add unnecessary overhead. Do not create extra manager layers or fan out a simple request.

Escalate unresolved ambiguity, repeated failure, or a discovery that changes the plan to Astra. If a worker reaches a browser-control step, return the exact next action to Astra.

This policy aims to reduce expensive coordinator work and context load. It does not guarantee fewer total tokens. Higher reasoning effort and extra workers add usage, so delegation still needs a useful purpose.

Sources, checked 2026-09-15: [Codex subagents and model defaults](https://learn.chatgpt.com/docs/agent-configuration/subagents), [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

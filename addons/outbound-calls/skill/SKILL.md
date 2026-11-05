---
name: outbound-assistant-call
description: Place an explicitly requested assistant phone call or deliver a specifically authorized notification through the configured local runtime, then review its exact receipt.
---

Resolve the runner path from the installation's private connection record. This skill requires the optional outbound-calls runtime on the selected connected Mac. Installing the skill does not authorize a call or create monitoring.

Prepare a short focus and a useful briefing from relevant current sources. For an alert, state the actual condition, source/date, uncertainty, and what needs attention. Calls should serve the user's requested purpose. Do not impose routine check-ins or a fixed questionnaire.

Save one JSON request with a fresh `request_id`, `focus`, and `briefing`. Record the originating conversation, authorized recipient reference, and expected result privately. Invoke the configured runner's `call` mode once with that JSON. The runner uses its fixed destination and account.

Wait for its terminal receipt. Review the exact Call SID, carrier outcome, transcript, caller corrections, recap, and confirmation. Return only the compact confirmed result and authorized follow-up to the originating conversation. Keep raw evidence private. The telephone voice cannot retrieve more project context or execute actions.

Recover with `result` and identical JSON. The ID binds to the whole request. Missing or uncertain evidence never authorizes a new ID or redial. Carrier completion alone does not prove that the caller confirmed facts.

Automatic calls require a separately configured rule with a real trigger, stable event/request identity, freshness/expiry, permitted window, and repeat policy. Do not guess urgency or claim a rule is running from a Markdown note. Context Mill is optional and deferred.

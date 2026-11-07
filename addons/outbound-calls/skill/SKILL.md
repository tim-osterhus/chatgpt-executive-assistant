---
name: outbound-assistant-call
description: Place an explicitly requested assistant phone call or deliver a specifically authorized notification through the installed local calling runtime, then review its exact receipt.
---

The runner for this installation is `CALLING_RUNNER`. Runtime setup writes that path when it generates this skill. It requires the optional outbound-calls runtime on the selected connected Mac. Installing the skill does not authorize a call or create monitoring.

Prepare a short focus and a useful briefing from relevant current sources. For an alert, state the actual condition, source/date, uncertainty, and what needs attention. Calls should serve the user's requested purpose. Do not impose routine check-ins or a fixed questionnaire.

Save one JSON request with a fresh `request_id`, `focus`, and `briefing`. Optional `outcome` (`complete`, `still_running`, `failed_or_blocked`, or `unclear`) selects the configured framing profile; it is not permission to call. Omit recipient fields to call the configured default. Add `recipient_number` (full `+1` E.164) and optionally `recipient_name` only when the user explicitly names another recipient for this call. Never infer either from project content.

Record the originating conversation, authorized recipient, and expected result privately. Run `CALLING_RUNNER validate` with the JSON on stdin, then invoke `CALLING_RUNNER call` once with the same JSON.

Wait for its terminal receipt. Review the exact Call SID, carrier outcome, `answered_by`, transcript, caller corrections, recap, and confirmation. `answered_by: unknown` opened the conversation without confirming a person answered. `voicemail_played` and `voicemail_submitted` report message delivery only; neither proves a person heard it or that a mailbox saved it. Return only the compact confirmed result and authorized follow-up to the originating conversation. Keep raw evidence private. The telephone voice cannot retrieve more project context or execute actions.

Recover with `CALLING_RUNNER result` and identical JSON. The ID binds to the whole request, including its recipient. Missing or uncertain evidence never authorizes a new ID or redial. Carrier completion alone does not prove that the caller confirmed facts.

Automatic calls require a separately configured rule with a real trigger, stable event/request identity, freshness/expiry, permitted window, and repeat policy. Do not guess urgency or claim a rule is running from a Markdown note. Context Mill is optional and deferred.

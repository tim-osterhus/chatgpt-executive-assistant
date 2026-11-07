---
name: assistant-call-when-done
description: Arm or manage a phone notification for a specific job the user asks to watch. Report actual job results to the installed watcher. Does not monitor general emergencies or all threads.
---

Use `WATCH_CALL_COMMAND` on this Mac. The background service owns waiting, Jev classification, elapsed 24-hour checkpoints, and call receipts. This skill registers the selected job and reports its evidence. It does not need another conversational task.

Resolve the job and completion criteria from the user's request and current work. Ask only if those remain materially ambiguous. A turn ending is not completion. Preserve the original project's owner, model, account, and execution permissions. Remote hosts need their own qualified reporting connection. Do not claim this Mac's installation watches remote jobs automatically.

When the user requests the completion call, register from that job's existing thread:

```sh
WATCH_CALL_COMMAND arm --job 'the selected job' --criteria 'the actual completion condition' --authorize-calls
```

The command obtains the current `CODEX_THREAD_ID`. Do not substitute a title, latest chat, or guessed identity. If the job exposes its actual local process PID, add `--pid` with that verified PID. Otherwise report progress when the owning task obtains a meaningful new observation. Do not infer that an old progress report proves a process is still running.

Add `--recipient-number` (full `+1` US/Canadian E.164) and optionally `--recipient-name` only when the user explicitly asks for another recipient for this watch; never infer either from the job or criteria. `--recipient-name` requires `--recipient-number`, and omitting it gives a neutral greeting. Omit both flags for the default recipient. The recipient is fixed at arm time and appears on the call receipt; to change it, cancel the watch and arm a new one.

```sh
WATCH_CALL_COMMAND arm --job 'the selected job' --criteria 'the actual completion condition' --authorize-calls --recipient-number '+12025550111' --recipient-name 'Alex'
```

Read the registration receipt. Tell the user the watch ID and selected job. Checkpoints are measured from registration at 24, 48, 72 hours and later multiples. Missed offline checkpoints coalesce. No watch should be armed merely because this skill was loaded. Use `--dry-run` in place of `--authorize-calls` for a requested qualification that must not dial.

At actual completion or failure, report the result before ending the work. Send bounded JSON on stdin to `WATCH_CALL_COMMAND report <watch-id>`. Supported states are `complete`, `running`, `failed_or_blocked`, and `unclear`:

```json
{
  "state": "complete",
  "summary": "The requested work finished and its acceptance checks passed.",
  "checks": [
    {"name": "the actual acceptance check", "passed": true, "detail": "the observed result"}
  ],
  "artifacts": []
}
```

Replace the example with observed facts. Include explicitly selected artifact paths when useful. The report is an owner attestation, not independent execution proof. Do not invent passing checks or report completion while required background work continues. For a long detached job, establish its real completion-report mechanism and verify it survives before promising automatic completion delivery.

For `failed_or_blocked`, leave `terminal` false or omit it when the job can resume after a decision. Set `terminal: true` only when the job has actually ended in failure. A completion report ends the watch after delivery. A nonterminal blocker or unclear result keeps the watch available for later progress and completion.

Use `WATCH_CALL_COMMAND progress <watch-id> --summary 'the latest observed progress'` for meaningful interim updates. If the service cannot verify running state at a checkpoint, it must describe the uncertainty rather than assert the job is still running.

Use `WATCH_CALL_COMMAND status <watch-id>` to inspect classification, notification, and saved call results. Submission is not completion. Keep the original watch and call IDs when recovering uncertain delivery. Never create a second watch to force a redial. Use `WATCH_CALL_COMMAND cancel <watch-id>` when the user cancels watching. Cancellation does not hang up an existing call.

The supplied evidence is sent to Jev for this opted-in job. Keep the report limited to the criteria, result, and useful evidence. The configured call profiles determine framing and reasoning. Classification does not grant project-action authority. Broad alerts and emergency monitoring are outside this skill. Context Mill is not required.

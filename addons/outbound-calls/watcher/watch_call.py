#!/usr/bin/env python3
"""Explicit owner reporting CLI; a tick never launches or scans project work."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

# The global launcher may use isolated Python, so import only these sibling modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import MAX_JSON_BYTES, Store, WatchError, Watcher, bounded_json, thread_identity


def parser():
    result = argparse.ArgumentParser(prog="assistant-watch-call", description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    arm = commands.add_parser("arm", help="Opt this exact owning thread and job into a watch")
    arm.add_argument("--job", required=True)
    arm.add_argument("--criteria", required=True)
    authorization = arm.add_mutually_exclusive_group(required=True)
    authorization.add_argument("--authorize-calls", action="store_true")
    authorization.add_argument("--dry-run", action="store_true")
    arm.add_argument("--thread-id", help="Only for a manually verified target when CODEX_THREAD_ID is absent")
    arm.add_argument("--pid", type=int, help="Existing process to observe, never a process to launch")
    arm.add_argument("--recipient-number", help="Full +1 E.164 number for this watch only; omit for the default recipient")
    arm.add_argument("--recipient-name", help="Display name for --recipient-number; omit for neutral framing")
    status = commands.add_parser("status")
    status.add_argument("watch_id", nargs="?")
    cancel = commands.add_parser("cancel")
    cancel.add_argument("watch_id")
    report = commands.add_parser("report", help="Read a bounded owner report JSON object from stdin")
    report.add_argument("watch_id")
    report.add_argument("--thread-id")
    progress = commands.add_parser("progress", help="Report fresh running progress from the owning thread")
    progress.add_argument("watch_id")
    progress.add_argument("--summary", required=True)
    progress.add_argument("--thread-id")
    commands.add_parser("tick", help="Reconcile receipts, classify due notices, and submit authorized notices")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        store = Store()
        watcher = Watcher(store)
        if args.command == "arm":
            value = watcher.arm(job=args.job, criteria=args.criteria,
                thread_id=thread_identity(args.thread_id), cwd=os.getcwd(),
                authorize_calls=args.authorize_calls, dry_run=args.dry_run, pid=args.pid,
                recipient_number=args.recipient_number, recipient_name=args.recipient_name)
        elif args.command == "status":
            value = watcher.status(args.watch_id)
        elif args.command == "cancel":
            value = watcher.cancel(args.watch_id)
        elif args.command == "report":
            report = bounded_json(sys.stdin.buffer.read(MAX_JSON_BYTES + 1))
            value = watcher.report(args.watch_id, report, thread_identity(args.thread_id))
        elif args.command == "progress":
            value = watcher.progress(args.watch_id, args.summary, thread_identity(args.thread_id))
        else:
            # An idle installation must neither access Keychain nor start the caller.
            if not any(watch["status"] == "active" or watch["active_notices"]
                       for watch in (store.read("watches", i) for i in store.watch_ids())):
                return 0
            from integrations import JevClassifier, MCPCaller, load_config
            config = load_config(store.root)
            value = Watcher(store, classify=JevClassifier(config), calls=MCPCaller(config)).tick()
            if not value["processed"]:
                return 0
        print(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return 0
    except (WatchError, OSError, ValueError) as exc:
        # Runtime exceptions carry safe descriptions; no raw provider/SDK exception is printed.
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

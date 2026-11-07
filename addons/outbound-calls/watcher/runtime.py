"""Private, opt-in completion watches. This module never executes project jobs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

DAY = 86400
FRESH_PROGRESS_SECONDS = 3600
MAX_JSON_BYTES = 65536
MAX_RECORD_BYTES = 128 * 1024
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
OUTCOMES = {"complete", "still_running", "failed_or_blocked", "unclear"}
REPORT_STATES = {"complete", "running", "failed_or_blocked", "unclear"}
WATCH_ID = re.compile(r"[a-f0-9]{32}")
REQUEST_ID = re.compile(r"watch-[a-f0-9]{32}-[cr][0-9]+")
UNSENT = {"classify_wait", "ready", "retry_wait"}
UNCERTAIN = {"submitting", "submitted", "uncertain"}
TERMINAL_RECEIPTS = {"review_required", "partial_or_failed", "voicemail_played", "voicemail_submitted"}


class WatchError(ValueError):
    pass


def bounded_json(data: bytes, maximum=MAX_JSON_BYTES):
    if len(data) > maximum:
        raise WatchError(f"JSON input exceeds {maximum} bytes")
    try:
        value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise WatchError("Invalid JSON") from exc
    if not isinstance(value, dict):
        raise WatchError("JSON input must be an object")
    return value


def _text(value, name, maximum):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(not c.isprintable() and c not in "\n\t" for c in value)):
        raise WatchError(f"{name} must be nonempty text, at most {maximum} characters")
    return value.strip()


def validate_recipient(number=None, name=None):
    """Optional per-watch destination. None keeps the caller's configured default recipient."""
    if number is None:
        if name is not None:
            raise WatchError("--recipient-name requires the full --recipient-number")
        return None
    if not isinstance(number, str) or not re.fullmatch(r"\+1[2-9]\d{9}", number):
        raise WatchError("--recipient-number must be a full +1 US or Canadian E.164 number")
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 80
                             or not name.isprintable()):
        raise WatchError("--recipient-name must be 1 to 80 printable characters")
    return {"number": number, "name": name.strip() if name is not None else None}


def recipient_fields(recipient):
    """Structured call fields; the legacy default request carries none."""
    if not recipient:
        return {}
    fields = {"recipient_number": recipient["number"]}
    if recipient.get("name") is not None:
        fields["recipient_name"] = recipient["name"]
    return fields


def thread_identity(explicit=None, environment=None):
    environment = os.environ if environment is None else environment
    current = environment.get("CODEX_THREAD_ID")
    if current and explicit and current != explicit:
        raise WatchError("--thread-id disagrees with CODEX_THREAD_ID")
    identity = current or explicit
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", identity):
        raise WatchError("CODEX_THREAD_ID is required; use --thread-id only for a manually verified target")
    return identity


def process_identity(pid):
    """Observe one PID with fixed ps arguments; start time prevents PID reuse."""
    if type(pid) is not int or pid < 1:
        raise WatchError("PID must be a positive integer")
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "stat="],
            capture_output=True, text=True, timeout=5, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = result.stdout.strip().split()
    if result.returncode or len(parts) < 6 or parts[-1].startswith("Z"):
        return None
    return {"pid": pid, "start_time": " ".join(parts[:-1])}


def validate_report(value, cwd):
    if not isinstance(value, dict) or set(value) - {"state", "summary", "checks", "artifacts", "terminal"}:
        raise WatchError("Report accepts state, summary, checks, artifacts, and terminal only")
    state = value.get("state")
    if not isinstance(state, str) or state not in REPORT_STATES:
        raise WatchError("Invalid report state")
    terminal = value.get("terminal", False)
    if type(terminal) is not bool:
        raise WatchError("terminal must be a boolean")
    if terminal and state in {"running", "unclear"}:
        raise WatchError("Running and unclear reports cannot be terminal")
    terminal = state == "complete" or terminal
    summary = _text(value.get("summary"), "summary", 4000)
    checks = value.get("checks", [])
    if not isinstance(checks, list) or len(checks) > 20:
        raise WatchError("checks must be an array of at most 20 objects")
    normalized = []
    for check in checks:
        if (not isinstance(check, dict) or set(check) - {"name", "passed", "detail"}
                or type(check.get("passed")) is not bool):
            raise WatchError("Each check requires name and boolean passed")
        item = {"name": _text(check.get("name"), "check name", 200), "passed": check["passed"]}
        if "detail" in check:
            item["detail"] = _text(check["detail"], "check detail", 500)
        normalized.append(item)
    if state == "complete" and (not normalized or not all(c["passed"] for c in normalized)):
        raise WatchError("Complete requires nonempty owner-reported checks that all passed")
    artifacts = value.get("artifacts", [])
    if not isinstance(artifacts, list) or len(artifacts) > 20:
        raise WatchError("artifacts must be an array of at most 20 absolute paths")
    paths = []
    root = Path(cwd).resolve()
    for artifact in artifacts:
        if not isinstance(artifact, str) or len(artifact) > 2048 or not Path(artifact).is_absolute():
            raise WatchError("Artifact paths must be absolute")
        path = Path(artifact).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise WatchError("Artifacts must exist within the registered working directory")
        paths.append(str(path))
    report = {"state": state, "summary": summary, "checks": normalized,
              "artifacts": paths, "terminal": terminal}
    if len(json.dumps(report, ensure_ascii=False, allow_nan=False).encode()) > MAX_JSON_BYTES:
        raise WatchError("Normalized report exceeds 65536 bytes")
    return report


class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("WATCH_CALL_STATE_DIR") or
                         Path(__file__).resolve().parents[1] / ".state" / "watcher").expanduser()
        for path in (self.root, self.root / "watches", self.root / "notices", self.root / "receipts"):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.is_symlink():
                raise WatchError("State directories cannot be symlinks")
            path.chmod(0o700)

    @contextmanager
    def transaction(self, blocking=True):
        fd = os.open(self.root / "transaction.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            os.close(fd)

    def _path(self, kind, identifier):
        pattern = WATCH_ID if kind == "watches" else REQUEST_ID
        if not isinstance(identifier, str) or not pattern.fullmatch(identifier):
            raise WatchError("Invalid watch or notice ID")
        return self.root / kind / f"{identifier}.json"

    def read(self, kind, identifier):
        path = self._path(kind, identifier)
        maximum = MAX_RECEIPT_BYTES if kind == "receipts" else MAX_RECORD_BYTES
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                return bounded_json(stream.read(maximum + 1), maximum)
        except FileNotFoundError as exc:
            raise WatchError(f"Unknown {kind[:-1]} ID") from exc

    def write(self, kind, identifier, value):
        path = self._path(kind, identifier)
        data = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()
        maximum = MAX_RECEIPT_BYTES if kind == "receipts" else MAX_RECORD_BYTES
        if len(data) > maximum:
            raise WatchError(f"Saved record exceeds {maximum} bytes")
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def watch_ids(self):
        return sorted(p.stem for p in (self.root / "watches").glob("*.json") if WATCH_ID.fullmatch(p.stem))


class Watcher:
    def __init__(self, store, classify=None, calls=None, now=time.time, observe=process_identity):
        self.store, self.classify, self.calls = store, classify, calls
        self.now, self.observe = now, observe

    def arm(self, *, job, criteria, thread_id, cwd, authorize_calls=False, dry_run=False, pid=None,
            recipient_number=None, recipient_name=None):
        if authorize_calls == dry_run:
            raise WatchError("Choose exactly one of --authorize-calls or --dry-run")
        job, criteria = _text(job, "job", 240), _text(criteria, "criteria", 4000)
        recipient = validate_recipient(recipient_number, recipient_name)
        thread_id = thread_identity(thread_id, {})
        cwd = str(Path(cwd).resolve(strict=True))
        if not Path(cwd).is_dir():
            raise WatchError("Working directory must be a directory")
        process = self.observe(pid) if pid is not None else None
        if pid is not None and process is None:
            raise WatchError("Cannot establish the supplied PID's live identity")
        now, identifier = self.now(), uuid.uuid4().hex
        watch = {"schema": 1, "watch_id": identifier, "job": job, "criteria": criteria,
                 "thread_id": thread_id, "cwd": cwd, "created_at": now, "updated_at": now,
                 "authorize_calls": authorize_calls, "dry_run": dry_run, "process": process,
                 "status": "active", "revision": 0, "handled_revision": 0,
                 "last_checkpoint": 0, "active_notices": [], "last_notice_id": None,
                 "report": None, "report_at": None}
        if recipient:
            watch["recipient"] = recipient  # Fixed at registration; no command changes it.
        with self.store.transaction():
            self.store.write("watches", identifier, watch)
        return {"watch_id": identifier, "registration": watch, "next_checkpoint_at": now + DAY}

    def _owner(self, watch, thread_id):
        if watch["thread_id"] != thread_id:
            raise WatchError("This watch belongs to a different thread")

    def _supersede_unsent(self, watch, reason, rewind_checkpoints=False):
        keep = []
        for identifier in watch["active_notices"]:
            notice = self.store.read("notices", identifier)
            if notice["status"] in UNSENT:
                if rewind_checkpoints and notice["kind"] == "c":
                    watch["last_checkpoint"] = min(watch["last_checkpoint"], notice["checkpoint"] - 1)
                notice.update(status="cancelled", cancellation_reason=reason, updated_at=self.now())
                self.store.write("notices", identifier, notice)
            else:
                keep.append(identifier)
        watch["active_notices"] = keep

    def report(self, identifier, value, thread_id):
        with self.store.transaction():
            watch = self.store.read("watches", identifier)
            self._owner(watch, thread_id)
            if watch["status"] != "active":
                raise WatchError("Watch is no longer active")
            report = validate_report(value, watch["cwd"])
            process = watch["process"]
            if report["state"] == "complete" and process and self.observe(process["pid"]) == process:
                raise WatchError("Registered job process is still alive; report completion after it exits")
            same_terminal = watch["report"] == report and report["state"] != "running"
            if not same_terminal:
                self._supersede_unsent(watch, "owner_report_updated", rewind_checkpoints=report["state"] == "running")
                watch["revision"] += 1
            watch.update(report=report, report_at=self.now(), updated_at=self.now(), source="owner_report")
            self.store.write("watches", identifier, watch)
            return watch

    def progress(self, identifier, summary, thread_id):
        return self.report(identifier, {"state": "running", "summary": summary}, thread_id)

    def cancel(self, identifier):
        with self.store.transaction():
            watch = self.store.read("watches", identifier)
            self._supersede_unsent(watch, "watch_cancelled")
            watch.update(status="cancelled", updated_at=self.now())
            self.store.write("watches", identifier, watch)
            return watch

    def status(self, identifier=None):
        with self.store.transaction():
            if identifier:
                watch = self.store.read("watches", identifier)
                paths = sorted((self.store.root / "notices").glob(f"watch-{identifier}-*.json"),
                               key=lambda p: p.stat().st_mtime, reverse=True)[:50]
                notices = [self.store.read("notices", p.stem) for p in paths]
                return {"watch": watch, "notices": notices,
                        "next_checkpoint_at": watch["created_at"] + (watch["last_checkpoint"] + 1) * DAY}
            return {"watches": [self.store.read("watches", i) for i in self.store.watch_ids()]}

    def _evidence(self, watch, checkpoint):
        report = watch["report"]
        process = watch["process"]
        observed = self.observe(process["pid"]) if process else None
        process_live = bool(process and observed == process)
        progress_age = self.now() - watch["report_at"] if report else None
        fresh_progress = bool(report and report["state"] == "running"
                              and 0 <= progress_age <= FRESH_PROGRESS_SECONDS)
        return {"job": watch["job"], "criteria": watch["criteria"], "source": "owner_report",
                "owner_report": report, "owner_report_age_seconds": progress_age,
                "owner_report_at": watch["report_at"], "observed_at": self.now(),
                "elapsed_seconds": max(0, self.now() - watch["created_at"]),
                "checkpoint": checkpoint, "process_identity_matches": process_live,
                "fresh_running_progress": fresh_progress,
                "evidence_limits": "Checks are owner reports. Process identity proves only that the registered process is alive."}

    def _make_notice(self, watch, kind, number):
        identifier = f"watch-{watch['watch_id']}-{kind}{number}"
        evidence = self._evidence(watch, number if kind == "c" else None)
        notice = {"request_id": identifier, "watch_id": watch["watch_id"], "kind": kind,
                  "revision": watch["revision"], "checkpoint": number if kind == "c" else None,
                  "created_at": self.now(), "updated_at": self.now(), "status": "classify_wait",
                  "classification_attempts": 0, "submit_attempts": 0, "next_attempt_at": self.now(),
                  "evidence": evidence}
        if watch.get("recipient"):
            notice["recipient"] = dict(watch["recipient"])  # Bound to this request ID.
        # Persist intent before advancing the watch cursor or contacting any provider.
        self.store.write("notices", identifier, notice)
        watch["active_notices"].append(identifier)
        watch["last_notice_id"] = identifier
        if kind == "c":
            watch["last_checkpoint"] = number
        else:
            watch["handled_revision"] = watch["revision"]
        self.store.write("watches", watch["watch_id"], watch)
        return notice

    def _guard_outcome(self, outcome, evidence):
        report = evidence["owner_report"]
        if outcome == "complete" and not (report and report["state"] == "complete"
                                           and report["checks"] and all(c["passed"] for c in report["checks"])
                                           and not evidence["process_identity_matches"]):
            return "unclear"
        if outcome == "still_running" and not (evidence["process_identity_matches"] or evidence["fresh_running_progress"]):
            return "unclear"
        if outcome == "failed_or_blocked" and not (report and report["state"] == "failed_or_blocked"):
            return "unclear"
        return outcome

    def _briefing(self, watch, notice):
        evidence, report = notice["evidence"], notice["evidence"]["owner_report"]
        text = [f"Opted-in job: {watch['job']}", f"Watch: {watch['watch_id']}",
                f"Owning thread: {watch['thread_id']}", f"Working directory: {watch['cwd']}",
                f"Completion criteria: {watch['criteria']}", f"Assessed outcome: {notice['outcome']}",
                f"Elapsed hours: {evidence['elapsed_seconds'] / 3600:.2f}",
                f"Assessment timestamp UTC: {datetime.fromtimestamp(evidence['observed_at'], timezone.utc).isoformat()}",
                f"Evidence source: owner_report; checkpoint: {notice['checkpoint']}",
                f"Owner report age at assessment in seconds: {evidence['owner_report_age_seconds']}",
                f"Owner reported state: {report['state'] if report else 'none'}; job terminal: {report.get('terminal', report['state'] == 'complete') if report else False}",
                f"Owner summary: {report['summary'] if report else 'No owner report supplied.'}",
                f"Registered process identity currently matches: {evidence['process_identity_matches']}",
                f"Fresh running progress: {evidence['fresh_running_progress']}", evidence["evidence_limits"],
                "Discuss this opted-in job only. This watch does not cover broad build, security, or data emergency monitoring.",
                "A completed phone receipt does not prove that the configured recipient confirmed the job outcome." if not notice.get("recipient") else
                "This watch's call goes to its explicitly selected recipient. A completed phone receipt does not prove that the recipient confirmed the job outcome."]
        if report:
            text.extend(f"Check {c['name']}: {'passed' if c['passed'] else 'failed'}; {c.get('detail', '')}"
                        for c in report["checks"])
            text.extend(f"Artifact source pointer: {p}" for p in report["artifacts"])
        return "\n".join(text)

    def _bound_briefing(self, notice):
        original = notice["briefing"]
        note = "\n[Briefing truncated to caller request limit.]"
        def fits(briefing):
            payload = {"request_id": notice["request_id"], "focus": notice["focus"],
                       "briefing": briefing, "outcome": notice["outcome"], **recipient_fields(notice.get("recipient"))}
            return (len(briefing) <= 8000 and len(json.dumps(payload).encode()) <= 16384
                    and len(json.dumps(payload, ensure_ascii=False,
                        separators=(",", ":")).encode("utf-8") + b"\n") <= 16384)
        if fits(original):
            return
        lower, upper = 0, min(8000 - len(note), len(original))
        while lower < upper:
            middle = (lower + upper + 1) // 2
            if fits(original[:middle] + note):
                lower = middle
            else:
                upper = middle - 1
        notice["briefing"] = original[:lower] + note
        if not fits(notice["briefing"]):
            raise WatchError("Call identity fields exceed caller request limit")

    def _save_receipt(self, notice, result):
        self.store.write("receipts", notice["request_id"], result)
        notice["receipt"] = {"path": str(self.store._path("receipts", notice["request_id"])),
                             **self._response_summary(result)}

    @staticmethod
    def _response_summary(result):
        summary = {}
        for key in ("request_id", "status", "call_id", "carrier_status", "duration_seconds",
                    "voice_authentication", "reason", "answered_by",'transport','parent_call_id','child_call_id',
                    "recipient_name", "destination_last4"):
            if key not in result:
                continue
            value = result[key]
            if isinstance(value, str):
                summary[key] = value[:1000]
            elif value is None or type(value) in (int, float, bool):
                summary[key] = value
        if isinstance(result.get("delivery"), dict):
            summary["delivery"] = {key: result["delivery"][key] for key in
                                   ("kind", "status", "playback_completed", "human_conversation_confirmed",
                                    "source_completion", "playback_evidence", "finite_pcm_sealed",
                                    "sender_queue_drained", "matching_final_mark", "no_clear_during_playback",
                                    'local_queue_drained','local_rendered_source_samples','local_rendered_padding_samples',
                                    'provider_playback_confirmed','sdk_codec')
                                   if key in result["delivery"]}
        return summary

    def _save_notice(self, notice):
        notice["updated_at"] = self.now()
        self.store.write("notices", notice["request_id"], notice)

    def _finish(self, watch, notice):
        if notice["request_id"] in watch["active_notices"]:
            watch["active_notices"].remove(notice["request_id"])
        report = notice["evidence"]["owner_report"]
        terminal_outcome = notice.get("outcome") == "complete" or (
            notice.get("outcome") == "failed_or_blocked" and report and report.get("terminal", False))
        if (notice["status"] in {"finished", "dry_run"} and terminal_outcome
                and notice["revision"] == watch["revision"] and watch["status"] == "active"):
            watch["status"] = "settled_dry_run" if watch["dry_run"] else "settled"
        watch["updated_at"] = self.now()
        self.store.write("watches", watch["watch_id"], watch)

    def _response(self, notice, result):
        if not isinstance(result, dict) or result.get("request_id") != notice["request_id"]:
            raise WatchError("Caller returned an unbound receipt")
        if len(json.dumps(result, allow_nan=False, ensure_ascii=False).encode()) > MAX_RECEIPT_BYTES:
            raise WatchError("Caller receipt is too large")
        # A terminal receipt echoes its request: it must be the destination bound to this notice.
        expected = recipient_fields(notice.get("recipient"))
        if result.get("status") in TERMINAL_RECEIPTS and any(
                result.get(key) != expected.get(key) for key in ("recipient_number", "recipient_name")):
            raise WatchError("Caller receipt belongs to a different recipient")
        return result

    def _reconcile(self, watch, notice):
        try:
            result = self._response(notice, self.calls.get_call_status(notice["request_id"]))
            notice["last_status"] = self._response_summary(result)
            if result.get("status") in TERMINAL_RECEIPTS:
                self._save_receipt(notice, result)
                notice["status"] = "finished"
                self._save_notice(notice)
                self._finish(watch, notice)
                return
            notice["status"] = "uncertain" if result.get("status") in {"request_not_found", "submission_uncertain"} else "submitted"
            if notice["status"] == "uncertain":
                notice["manual_reconciliation_required"] = True
        except Exception as exc:
            notice.update(status="uncertain", last_error=type(exc).__name__, manual_reconciliation_required=True)
        self._save_notice(notice)

    def _advance(self, watch, notice):
        if notice["status"] in UNCERTAIN:
            if self.calls is not None:
                self._reconcile(watch, notice)
            return
        if notice["status"] not in UNSENT or self.now() < notice["next_attempt_at"]:
            return
        if notice["status"] == "classify_wait":
            notice["classification_attempts"] += 1
            try:
                if self.classify is None:
                    raise WatchError("Jev classification is not configured")
                result = self.classify(notice["evidence"])
                if not isinstance(result, dict) or result.get("outcome") not in OUTCOMES:
                    raise WatchError("Invalid classifier result")
                notice["classification"] = result
                notice["outcome"] = self._guard_outcome(result["outcome"], notice["evidence"])
                notice["guard_applied"] = notice["outcome"] != result["outcome"]
                notice["briefing"] = self._briefing(watch, notice)
                notice["focus"] = " ".join(watch["job"].split())
                self._bound_briefing(notice)
                notice["status"] = "ready"
            except Exception as exc:
                notice["last_error"] = type(exc).__name__
                notice["next_attempt_at"] = self.now() + min(3600, 60 * 2 ** min(notice["classification_attempts"], 6))
                if notice["classification_attempts"] >= 5:
                    notice.update(status="classification_failed", manual_reconciliation_required=True)
                    self._finish(watch, notice)
                self._save_notice(notice)
                return
            self._save_notice(notice)
        if watch["dry_run"]:
            notice["status"] = "dry_run"
            self._save_notice(notice)
            self._finish(watch, notice)
            return
        if not watch["authorize_calls"] or self.calls is None:
            return
        # A pre-dial busy retry may be delayed: do not reuse stale running proof.
        current_evidence = self._evidence(watch, notice["checkpoint"])
        current_outcome = self._guard_outcome(notice["outcome"], current_evidence)
        if current_outcome != notice["outcome"]:
            notice.update(evidence=current_evidence, outcome=current_outcome, guard_applied=True)
            notice["briefing"] = self._briefing(watch, notice)
            self._bound_briefing(notice)
        if notice.get("recipient") and not self._recipients_supported():
            # An older caller silently ignores unknown fields and would dial its default recipient.
            notice.update(submit_attempts=notice["submit_attempts"] + 1, last_error="recipient_unsupported")
            self._defer(watch, notice)
            self._save_notice(notice)
            return
        notice.update(status="submitting", submit_attempts=notice["submit_attempts"] + 1)
        self._save_notice(notice)  # A crash after this point must never cause a blind replay.
        try:
            result = self._response(notice, self.calls.request_call(
                request_id=notice["request_id"], focus=notice["focus"],
                briefing=notice["briefing"], outcome=notice["outcome"],
                **recipient_fields(notice.get("recipient"))))
            notice["submission"] = self._response_summary(result)
            status = result.get("status")
            if status in TERMINAL_RECEIPTS:
                self._save_receipt(notice, result)
                notice["status"] = "finished"
                self._save_notice(notice)
                self._finish(watch, notice)
                return
            safe_rejection = status == "rejected" and result.get("reason") in {
                "Dialing is disabled", "Call configuration is not ready"}
            if status == "busy" or safe_rejection:
                self._defer(watch, notice)
            else:
                notice["status"] = "submitted" if status == "accepted" else "uncertain"
                if notice["status"] == "uncertain":
                    notice["manual_reconciliation_required"] = True
        except Exception as exc:
            notice.update(status="uncertain", last_error=type(exc).__name__, manual_reconciliation_required=True)
        self._save_notice(notice)

    def _defer(self, watch, notice):
        notice["status"] = "retry_wait" if notice["submit_attempts"] < 8 else "retry_exhausted"
        notice["next_attempt_at"] = self.now() + min(3600, 60 * 2 ** min(notice["submit_attempts"], 6))
        if notice["status"] == "retry_exhausted":
            notice["manual_reconciliation_required"] = True
            self._finish(watch, notice)

    def _recipients_supported(self):
        try:
            return self.calls.calling_health().get("per_request_recipients") is True
        except Exception:
            return False

    def tick(self):
        touched = []
        with self.store.transaction(blocking=False) as acquired:
            if not acquired:
                return {"status": "tick_already_running", "processed": []}
            for identifier in self.store.watch_ids():
                watch = self.store.read("watches", identifier)
                for notice_id in list(watch["active_notices"]):
                    self._advance(watch, self.store.read("notices", notice_id))
                    touched.append(notice_id)
                if watch["status"] != "active":
                    continue
                # Preserve the cursor while any existing notice is unresolved.
                # In particular, a fresh report must never escape an uncertain
                # submission by producing another request ID.
                if watch["active_notices"]:
                    continue
                report = watch["report"]
                notice = None
                if report and report["state"] != "running" and watch["revision"] > watch["handled_revision"]:
                    notice = self._make_notice(watch, "r", watch["revision"])
                else:
                    checkpoint = math.floor(max(0, self.now() - watch["created_at"]) / DAY)
                    if checkpoint > watch["last_checkpoint"]:
                        notice = self._make_notice(watch, "c", checkpoint)
                if notice:
                    self._advance(watch, notice)
                    touched.append(notice["request_id"])
        return {"status": "ok", "processed": touched}

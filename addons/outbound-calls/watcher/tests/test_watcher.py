import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import DAY, FRESH_PROGRESS_SECONDS, Store, WatchError, Watcher, bounded_json, thread_identity
from integrations import JevClassifier, mcp_environment, parse_classification, parse_mcp_result, read_keychain


class Clock:
    def __init__(self):
        self.value = 1000000.0
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += seconds


class Calls:
    def __init__(self, mode="accepted"):
        self.mode, self.requests, self.statuses, self.queries = mode, [], {}, []
    def request_call(self, **request):
        self.requests.append(request)
        if self.mode == "raise":
            raise TimeoutError("an intentionally uncertain fake submission")
        return {"request_id": request["request_id"], "status": self.mode}
    def get_call_status(self, request_id):
        self.queries.append(request_id)
        return self.statuses.get(request_id, {"request_id": request_id, "status": "request_not_found"})


def classification(outcome):
    return {"outcome": outcome, "resolved_model": "jev-test", "confidence": .8,
            "probabilities": {x: .8 if x == outcome else .2 / 3 for x in
                              ("complete", "still_running", "failed_or_blocked", "unclear")},
            "usage": {"input_tokens": 3, "output_tokens": 2}}


def classify(evidence):
    report = evidence["owner_report"]
    outcome = report["state"] if report else "unclear"
    return classification("still_running" if outcome == "running" else outcome)


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.clock, self.calls = Clock(), Calls()
        self.observed = {"pid": 42, "start_time": "Mon Nov 2 01:02:03 2026"}
        self.store = Store(self.root / "state")
        self.watcher = Watcher(self.store, classify, self.calls, self.clock,
                               lambda pid: self.observed.copy() if self.observed else None)
    def tearDown(self):
        self.temp.cleanup()
    def arm(self, dry_run=False, pid=None):
        return self.watcher.arm(job="Build opted-in fixture", criteria="Checks pass and output exists",
                    thread_id="thread-fixture", cwd=self.cwd, authorize_calls=not dry_run,
                    dry_run=dry_run, pid=pid)["watch_id"]
    def report(self, identifier, state="complete", **extra):
        value = {"state": state, "summary": "The owner reports the observed result.",
                 "checks": [{"name": "fixture check", "passed": True}]}
        value.update(extra)
        return self.watcher.report(identifier, value, "thread-fixture")
    def notice(self, identifier):
        return self.watcher.status(identifier)["notices"][0]

    def test_24_48_72_hours_dedup_and_coalescing(self):
        identifier = self.arm(dry_run=True, pid=42)
        self.watcher.progress(identifier, "Owner observes work running", "thread-fixture")
        self.clock.advance(DAY - 1)
        self.assertEqual(self.watcher.tick()["processed"], [])
        for checkpoint in (1, 2, 3):
            self.clock.advance(1 if checkpoint == 1 else DAY)
            self.watcher.tick()
            self.assertEqual(self.notice(identifier)["checkpoint"], checkpoint)
            self.assertEqual(self.notice(identifier)["outcome"], "still_running")
            self.assertEqual(self.watcher.tick()["processed"], [])
        self.clock.advance(4 * DAY)
        self.watcher.tick()
        notices = self.watcher.status(identifier)["notices"]
        self.assertEqual({n["checkpoint"] for n in notices}, {1, 2, 3, 7})
        self.assertEqual(self.calls.requests, [])

    def test_voicemail_receipt_finishes_notice_without_repeating_or_confirming_human(self):
        for immediate in (False, True):
            identifier = self.arm()
            self.report(identifier)
            if immediate:
                self.calls.mode = 'voicemail_played'
            self.watcher.tick()
            notice = self.notice(identifier)
            request_id = notice['request_id']
            if not immediate:
                self.calls.statuses[request_id] = {'request_id': request_id, 'status': 'voicemail_played',
                    'answered_by': 'machine_end_beep', 'delivery': {'kind': 'voicemail', 'status': 'played',
                        'playback_completed': True, 'human_conversation_confirmed': False,
                        'source_completion': 'inferred_turn_done_and_receiver_quiet',
                        'playback_evidence': 'twilio_final_mark'}}
                self.watcher.tick()
            saved = self.watcher.status(identifier)
            self.assertEqual(saved['watch']['status'], 'settled')
            self.assertEqual(saved['watch']['active_notices'], [])
            self.assertEqual(saved['notices'][0]['status'], 'finished')
            self.assertEqual(saved['notices'][0]['receipt']['status'], 'voicemail_played')
            if not immediate:
                self.assertFalse(saved['notices'][0]['receipt']['delivery']['human_conversation_confirmed'])
                self.assertEqual(saved['notices'][0]['receipt']['delivery']['source_completion'],
                                 'inferred_turn_done_and_receiver_quiet')
            count = len(self.calls.requests)
            self.watcher.tick()
            self.assertEqual(len(self.calls.requests), count)

    def test_missing_or_stale_running_evidence_is_unclear(self):
        identifier = self.arm(dry_run=True)
        self.watcher.progress(identifier, "Running yesterday", "thread-fixture")
        self.clock.advance(DAY)
        self.watcher.tick()
        self.assertEqual(self.notice(identifier)["outcome"], "unclear")
        self.assertTrue(self.notice(identifier)["guard_applied"])
        self.assertIn("Owner report age at assessment in seconds: 86400.0", self.notice(identifier)["briefing"])
        self.assertIn("Assessment timestamp UTC:", self.notice(identifier)["briefing"])
        self.clock.advance(DAY - 1)
        self.watcher.progress(identifier, "Fresh owner progress", "thread-fixture")
        self.clock.advance(1)
        self.watcher.tick()
        self.assertEqual(self.notice(identifier)["outcome"], "still_running")

    def test_sdk_submitted_receipt_settles_exact_notice_without_claiming_remote_playback(self):
        identifier=self.arm();self.report(identifier);self.watcher.tick()
        request_id=self.notice(identifier)['request_id']
        result={'request_id':request_id,'status':'voicemail_submitted','transport':'sdk',
            'delivery':{'kind':'voicemail','local_queue_drained':True,
                'provider_playback_confirmed':False,'human_conversation_confirmed':False,'sdk_codec':'opus'}}
        self.calls.statuses[request_id]=result;self.watcher.tick()
        saved=self.watcher.status(identifier)
        self.assertEqual(saved['watch']['status'],'settled')
        self.assertEqual(saved['watch']['active_notices'],[])
        self.assertFalse(self.notice(identifier)['receipt']['delivery']['provider_playback_confirmed'])
        self.assertEqual(self.store.read('receipts',request_id),result)
        count=len(self.calls.requests);self.watcher.tick();self.assertEqual(len(self.calls.requests),count)

    def test_pid_reuse_does_not_establish_running(self):
        identifier = self.arm(dry_run=True, pid=42)
        self.observed["start_time"] = "different process start"
        self.clock.advance(DAY)
        self.watcher.tick()
        self.assertEqual(self.notice(identifier)["outcome"], "unclear")
        self.assertFalse(self.notice(identifier)["evidence"]["process_identity_matches"])

    def test_owner_identity_and_authorization_are_required(self):
        with self.assertRaises(WatchError):
            thread_identity(environment={})
        with self.assertRaises(WatchError):
            thread_identity("different-thread", {"CODEX_THREAD_ID": "original-thread"})
        identifier = self.arm()
        with self.assertRaises(WatchError):
            self.watcher.progress(identifier, "Wrong owner", "different-thread")
        with self.assertRaises(WatchError):
            self.watcher.arm(job="x", criteria="y", thread_id="thread", cwd=self.cwd)
        self.assertEqual(self.watcher.status(identifier)["watch"]["thread_id"], "thread-fixture")

    def test_terminal_checks_and_artifacts_are_guarded(self):
        identifier = self.arm()
        with self.assertRaises(WatchError):
            self.report(identifier, state={})
        for checks in ([], [{"name": "failed", "passed": False}], [{"name": "bad", "passed": 1}]):
            with self.assertRaises(WatchError):
                self.report(identifier, checks=checks)
        with self.assertRaises(WatchError):
            self.report(identifier, artifacts=[str(self.root)])
        artifact = self.cwd / "output.txt"
        artifact.write_text("Contents are never read by this watcher")
        result = self.report(identifier, artifacts=[str(artifact)])
        self.assertEqual(result["report"]["artifacts"], [str(artifact.resolve())])
        self.watcher.tick()
        self.assertNotIn("Contents are never read", self.calls.requests[0]["briefing"])

    def test_classifier_cannot_invent_completion(self):
        identifier = self.arm(dry_run=True)
        self.watcher.classify = lambda evidence: classification("complete")
        self.clock.advance(DAY)
        self.watcher.tick()
        self.assertEqual(self.notice(identifier)["outcome"], "unclear")

    def test_live_registered_job_process_contradicts_owner_completion(self):
        identifier = self.arm(dry_run=True, pid=42)
        registered = self.observed
        self.observed = None
        self.report(identifier, "complete")
        # A transient observation failure at report time must not bypass the
        # independent process check when the notice is classified/submitted.
        self.observed = registered
        self.watcher.tick()
        notice = self.notice(identifier)
        self.assertEqual(notice["classification"]["outcome"], "complete")
        self.assertEqual(notice["outcome"], "unclear")
        self.assertTrue(notice["guard_applied"])
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "active")
        self.clock.advance(3 * DAY)
        self.watcher.tick()
        self.assertEqual({n["request_id"] for n in self.watcher.status(identifier)["notices"]},
                         {f"watch-{identifier}-r1", f"watch-{identifier}-c3"})

    def test_live_pid_completion_report_rejected_then_same_payload_accepted_after_exit(self):
        identifier = self.arm(dry_run=True, pid=42)
        payload = {"state": "complete", "summary": "Output is ready and its check passed",
                   "checks": [{"name": "output check", "passed": True}]}
        with self.assertRaisesRegex(WatchError, "process is still alive"):
            self.watcher.report(identifier, payload, "thread-fixture")
        watch = self.watcher.status(identifier)["watch"]
        self.assertIsNone(watch["report"])
        self.assertEqual(watch["revision"], 0)
        self.assertEqual(watch["handled_revision"], 0)
        self.assertEqual(self.watcher.status(identifier)["notices"], [])
        self.observed = None
        self.watcher.report(identifier, payload, "thread-fixture")
        self.watcher.tick()
        self.assertEqual(self.notice(identifier)["outcome"], "complete")
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "settled_dry_run")

    def test_acceptance_is_not_completion_receipt_recovery_is_exact(self):
        identifier = self.arm()
        self.report(identifier)
        self.watcher.tick()
        request_id = self.calls.requests[0]["request_id"]
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "active")
        receipt = {"request_id": request_id, "status": "review_required", "call_id": "CA" + "a" * 32,
                   "carrier_status": "completed", "voice_authentication": "not_confirmed", "turns": []}
        self.calls.statuses[request_id] = receipt
        restarted = Watcher(Store(self.store.root), classify, self.calls, self.clock)
        restarted.tick()
        saved = restarted.status(identifier)
        self.assertEqual(saved["watch"]["status"], "settled")
        self.assertEqual(self.store.read("receipts", request_id), receipt)
        self.assertEqual(saved["notices"][0]["receipt"]["voice_authentication"], "not_confirmed")
        self.assertEqual(len(self.calls.requests), 1)

    def test_unknown_submission_and_restart_never_redial(self):
        identifier = self.arm()
        self.report(identifier)
        self.calls.mode = "raise"
        self.watcher.tick()
        request_id = self.calls.requests[0]["request_id"]
        self.assertEqual(self.notice(identifier)["status"], "uncertain")
        restarted = Watcher(Store(self.store.root), classify, self.calls, self.clock)
        for _ in range(3):
            self.clock.advance(121)
            restarted.tick()
        self.assertEqual(len(self.calls.requests), 1)
        self.assertEqual(set(self.calls.queries), {request_id})
        self.assertTrue(self.notice(identifier)["manual_reconciliation_required"])

    def test_uncertain_notice_blocks_new_reports_and_checkpoints(self):
        identifier = self.arm(pid=42)
        self.report(identifier, "failed_or_blocked")
        self.calls.mode = "raise"
        self.watcher.tick()
        self.watcher.progress(identifier, "Now owner reports additional running work", "thread-fixture")
        self.clock.advance(3 * DAY)
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 1)
        self.assertEqual(self.watcher.status(identifier)["watch"]["last_checkpoint"], 0)
        request_id = self.calls.requests[0]["request_id"]
        self.calls.statuses[request_id] = {"request_id": request_id, "status": "review_required"}
        self.calls.mode = "accepted"
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 2)
        self.assertTrue(self.calls.requests[1]["request_id"].endswith("-c3"))

    def test_long_exact_receipt_uses_separate_private_file(self):
        identifier = self.arm()
        self.report(identifier)
        self.watcher.tick()
        request_id = self.calls.requests[0]["request_id"]
        receipt = {"request_id": request_id, "status": "review_required", "carrier_status": "completed",
                   "turns": [{"role": "assistant", "text": "long conversation " * 20000}]}
        self.calls.statuses[request_id] = receipt
        self.watcher.tick()
        notice = self.notice(identifier)
        self.assertEqual(self.store.read("receipts", request_id), receipt)
        self.assertLess(len(json.dumps(notice)), 65536)
        self.assertEqual(stat.S_IMODE(Path(notice["receipt"]["path"]).stat().st_mode), 0o600)

    def test_unicode_briefing_fits_exact_call_request_byte_limit(self):
        identifier = self.watcher.arm(job="Unicode fixture", criteria="界" * 4000,
                    thread_id="thread-fixture", cwd=self.cwd, authorize_calls=True)["watch_id"]
        self.report(identifier, summary="界" * 4000)
        self.watcher.tick()
        request = self.calls.requests[0]
        encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        self.assertLessEqual(len(encoded), 16384)
        self.assertLessEqual(len(json.dumps(request).encode()), 16384)
        self.assertLessEqual(len(request["briefing"]), 8000)
        self.assertTrue(request["briefing"].endswith("[Briefing truncated to caller request limit.]"))
        self.assertIn(identifier, request["briefing"])

    def test_saved_submitting_intent_without_response_never_redials(self):
        identifier = self.arm()
        self.report(identifier)
        self.watcher.tick()
        notice = self.notice(identifier)
        notice["status"] = "submitting"
        with self.store.transaction():
            self.store.write("notices", notice["request_id"], notice)
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 1)
        self.assertEqual(self.notice(identifier)["status"], "uncertain")

    def test_busy_retries_same_id_and_bounded_attempts(self):
        identifier = self.arm()
        self.report(identifier)
        self.calls.mode = "busy"
        self.watcher.tick()
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 1)
        for _ in range(10):
            self.clock.advance(3601)
            self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 8)
        self.assertEqual(len({r["request_id"] for r in self.calls.requests}), 1)
        self.assertEqual(self.notice(identifier)["status"], "retry_exhausted")

    def test_busy_running_retry_does_not_reuse_stale_progress(self):
        identifier = self.arm()
        self.clock.advance(DAY)
        self.watcher.progress(identifier, "Fresh running evidence", "thread-fixture")
        self.calls.mode = "busy"
        self.watcher.tick()
        self.assertEqual(self.calls.requests[0]["outcome"], "still_running")
        self.clock.advance(FRESH_PROGRESS_SECONDS + 1)
        self.calls.mode = "accepted"
        self.watcher.tick()
        self.assertEqual(self.calls.requests[1]["outcome"], "unclear")
        self.assertEqual(self.calls.requests[0]["request_id"], self.calls.requests[1]["request_id"])

    def test_running_progress_preserves_busy_checkpoint_with_same_id_and_fresh_brief(self):
        identifier = self.arm()
        self.clock.advance(DAY)
        self.watcher.progress(identifier, "Initial running progress", "thread-fixture")
        self.calls.mode = "busy"
        self.watcher.tick()
        request_id = self.calls.requests[0]["request_id"]
        self.assertEqual(request_id, f"watch-{identifier}-c1")
        self.assertEqual(self.notice(identifier)["status"], "retry_wait")
        self.clock.advance(3600)
        self.watcher.progress(identifier, "Updated progress at twenty-five hours", "thread-fixture")
        self.assertEqual(self.watcher.status(identifier)["watch"]["last_checkpoint"], 0)
        self.calls.mode = "accepted"
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 2)
        self.assertEqual(self.calls.requests[1]["request_id"], request_id)
        self.assertIn("Updated progress at twenty-five hours", self.calls.requests[1]["briefing"])
        self.assertNotIn("Initial running progress", self.calls.requests[1]["briefing"])
        self.assertEqual(self.notice(identifier)["status"], "submitted")
        self.assertEqual(self.watcher.status(identifier)["watch"]["last_checkpoint"], 1)
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 2)

    def test_cancel_survives_restart_and_blocks_pending_retry(self):
        identifier = self.arm()
        self.report(identifier)
        self.calls.mode = "busy"
        self.watcher.tick()
        self.watcher.cancel(identifier)
        self.clock.advance(3 * DAY)
        Watcher(Store(self.store.root), classify, self.calls, self.clock).tick()
        self.assertEqual(len(self.calls.requests), 1)
        self.assertEqual(self.notice(identifier)["status"], "cancelled")
        with self.assertRaises(WatchError):
            self.report(identifier)

    def test_terminal_report_dedup_and_unclear_stays_open(self):
        identifier = self.arm(dry_run=True)
        self.report(identifier, "unclear")
        self.watcher.tick()
        self.report(identifier, "unclear")
        self.watcher.tick()
        self.assertEqual(len(self.watcher.status(identifier)["notices"]), 1)
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "active")
        self.report(identifier, "complete", summary="Now checks prove owner-reported completion")
        self.watcher.tick()
        self.assertEqual(len(self.watcher.status(identifier)["notices"]), 2)
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "settled_dry_run")

    def test_unclear_report_retains_coalesced_daily_checkpoints(self):
        identifier = self.arm(dry_run=True)
        self.report(identifier, "unclear")
        self.watcher.tick()
        self.clock.advance(3 * DAY)
        self.watcher.tick()
        status = self.watcher.status(identifier)
        self.assertEqual({n["request_id"] for n in status["notices"]},
                         {f"watch-{identifier}-r1", f"watch-{identifier}-c3"})
        self.assertEqual(status["watch"]["status"], "active")
        self.assertEqual(status["next_checkpoint_at"], status["watch"]["created_at"] + 4 * DAY)
        self.assertEqual(self.watcher.tick()["processed"], [])

    def test_nonterminal_blocked_report_can_resume_and_complete_after_receipt(self):
        identifier = self.arm()
        report = self.report(identifier, "failed_or_blocked", summary="Waiting for dependency")
        self.assertFalse(report["report"]["terminal"])
        self.watcher.tick()
        request_id = self.calls.requests[0]["request_id"]
        self.calls.statuses[request_id] = {"request_id": request_id, "status": "review_required"}
        self.watcher.tick()
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "active")
        self.watcher.progress(identifier, "Dependency available; work resumed", "thread-fixture")
        self.report(identifier, "complete", summary="Resumed work now passes all checks")
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 2)
        request_id = self.calls.requests[1]["request_id"]
        self.calls.statuses[request_id] = {"request_id": request_id, "status": "review_required"}
        self.watcher.tick()
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "settled")

    def test_nonterminal_blocked_report_retains_daily_checkpoints(self):
        identifier = self.arm(dry_run=True)
        self.report(identifier, "failed_or_blocked")
        self.watcher.tick()
        self.clock.advance(3 * DAY)
        self.watcher.tick()
        status = self.watcher.status(identifier)
        self.assertEqual({n["request_id"] for n in status["notices"]},
                         {f"watch-{identifier}-r1", f"watch-{identifier}-c3"})
        self.assertEqual(status["watch"]["status"], "active")

    def test_explicit_terminal_failure_settles_only_after_notice_finishes(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                identifier = self.arm(dry_run=dry_run)
                self.report(identifier, "failed_or_blocked", terminal=True,
                            summary="Job ended unsuccessfully; no further work will run")
                self.watcher.tick()
                if not dry_run:
                    self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "active")
                    request_id = self.calls.requests[-1]["request_id"]
                    self.calls.statuses[request_id] = {"request_id": request_id, "status": "review_required"}
                    self.watcher.tick()
                self.assertEqual(self.watcher.status(identifier)["watch"]["status"],
                                 "settled_dry_run" if dry_run else "settled")

    def test_terminal_flag_is_typed_and_cannot_end_running_or_unclear(self):
        identifier = self.arm(dry_run=True)
        for state, terminal in (("running", True), ("unclear", True), ("failed_or_blocked", 1)):
            with self.subTest(state=state, terminal=terminal), self.assertRaises(WatchError):
                self.report(identifier, state, terminal=terminal)
        report = self.report(identifier, "complete", terminal=False)
        self.assertTrue(report["report"]["terminal"])

    def test_classifier_failure_bounded_without_call(self):
        identifier = self.arm()
        self.report(identifier)
        def broken(evidence):
            raise OSError("fake key must never appear in saved diagnostics")
        self.watcher.classify = broken
        for _ in range(8):
            self.watcher.tick()
            self.clock.advance(3601)
        notice = self.notice(identifier)
        self.assertEqual(notice["classification_attempts"], 5)
        self.assertEqual(notice["status"], "classification_failed")
        self.assertNotIn("fake key", json.dumps(notice))
        self.assertEqual(self.calls.requests, [])

    def test_unarmed_jobs_are_untouched_and_private_permissions(self):
        unrelated = self.cwd / "unarmed.json"
        unrelated.write_text('{"complete":true}')
        self.clock.advance(3 * DAY)
        self.assertEqual(self.watcher.tick()["processed"], [])
        self.assertEqual(self.calls.requests, [])
        identifier = self.arm(dry_run=True)
        for path in (self.store.root, self.store.root / "watches", self.store.root / "notices"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.store.root / "watches" / f"{identifier}.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.store.root / "transaction.lock").stat().st_mode), 0o600)

    def test_concurrent_owner_report_waits_without_losing_tick_update(self):
        identifier = self.arm()
        self.report(identifier)
        entered, release = threading.Event(), threading.Event()
        errors = []
        def delayed(evidence):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test release missing")
            return classify(evidence)
        self.watcher.classify = delayed
        def run(function):
            try:
                function()
            except Exception as exc:
                errors.append(exc)
        ticker = threading.Thread(target=run, args=(self.watcher.tick,))
        ticker.start()
        self.assertTrue(entered.wait(5))
        reporter = threading.Thread(target=run, args=(lambda: self.watcher.progress(
            identifier, "Owner reports new running work", "thread-fixture"),))
        reporter.start()
        self.assertTrue(reporter.is_alive())
        self.assertEqual(self.watcher.tick()["status"], "tick_already_running")
        release.set()
        ticker.join(5)
        reporter.join(5)
        self.assertEqual(errors, [])
        watch = self.watcher.status(identifier)["watch"]
        self.assertEqual(watch["revision"], 2)
        self.assertEqual(watch["report"]["state"], "running")
        self.assertEqual(len(watch["active_notices"]), 1)
        request_id = watch["active_notices"][0]
        self.calls.statuses[request_id] = {"request_id": request_id, "status": "review_required"}
        self.watcher.tick()
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "active")


class IntegrationTests(unittest.TestCase):
    def response(self):
        value = classification("complete")
        return {"model": value["resolved_model"], "answers": {"outcome": {
            "type": "choice", "choice": value["outcome"], "confidence": value["confidence"],
            "probabilities": value["probabilities"]}}, "usage": value["usage"]}

    def test_jev_contract_and_bounded_validation(self):
        seen = []
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        def opener(request, timeout):
            seen.append(request)
            self.assertEqual(timeout, 30)
            return Response(json.dumps(self.response()).encode())
        classifier = JevClassifier({"jev_keychain_service": "fake-service", "jev_keychain_account": "fake-account"},
                                   key_reader=lambda *args: "fake-not-a-real-key", opener=opener)
        result = classifier({"job": "bounded fixture", "criteria": "pass", "owner_report": None})
        request = seen[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(set(body["questions"]["outcome"]["criteria"]),
                         {"complete", "still_running", "failed_or_blocked", "unclear"})
        self.assertEqual(result["resolved_model"], "jev-test")
        bad = self.response()
        bad["answers"]["outcome"]["confidence"] = 1.1
        with self.assertRaises(WatchError): parse_classification(bad)
        bad = self.response()
        bad["answers"]["outcome"]["choice"] = "not_complete"
        with self.assertRaises(WatchError): parse_classification(bad)

    def test_keychain_read_never_places_key_in_process_arguments(self):
        fake = "fake-key-only-in-captured-output"
        with patch("integrations.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=fake + "\n")) as run:
            self.assertEqual(read_keychain("fake-service", "fake-account"), fake)
            self.assertEqual(run.call_args.args[0], ["/usr/bin/security", "find-generic-password",
                "-s", "fake-service", "-a", "fake-account", "-w"])
            self.assertNotIn(fake, str(run.call_args))
            self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_mcp_structured_content_and_environment_whitelist(self):
        result = SimpleNamespace(isError=False, structuredContent={"status": "accepted", "request_id": "fixture"})
        self.assertEqual(parse_mcp_result(result)["status"], "accepted")
        with self.assertRaises(WatchError):
            parse_mcp_result(SimpleNamespace(isError=True))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-secret", "JEV_API_KEY": "fake-secret"}):
            environment = mcp_environment()
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("JEV_API_KEY", environment)
        self.assertLessEqual(set(environment), {"PATH", "HOME", "LANG", "TMPDIR"})

    def test_malformed_json_is_rejected(self):
        for value in (b"[]", b"{", b'{"x":NaN}', b"x" * 65537):
            with self.assertRaises(WatchError): bounded_json(value)

    def test_cli_idle_tick_requires_no_config_and_does_not_arm(self):
        with tempfile.TemporaryDirectory() as root:
            environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "WATCH_CALL_STATE_DIR": root}
            script = str(Path(__file__).resolve().parents[1] / "watch_call.py")
            result = subprocess.run([sys.executable, "-I", "-B", script, "tick"], env=environment,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            result = subprocess.run([sys.executable, "-I", "-B", script, "arm", "--job", "fixture",
                "--criteria", "fixture passes", "--dry-run"], env=environment,
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(list((Path(root) / "watches").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()

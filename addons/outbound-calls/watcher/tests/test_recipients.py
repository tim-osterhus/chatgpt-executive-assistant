"""Per-watch recipient behavior through the public Watcher, CLI, and MCPCaller APIs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import MCPCaller
from runtime import Store, WatchError, Watcher

SCRIPT = Path(__file__).resolve().parents[1] / "watch_call.py"
ALEX, OTHER = "+12025550111", "+13125550122"
BOUND_ALEX = {"number": ALEX, "name": "Alex"}
CONFIGURED_SENTENCE = "A completed phone receipt does not prove that the configured recipient confirmed the job outcome."
REQUEST = "watch-" + "a" * 32 + "-r1"


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
        self.health, self.health_calls = {"status": "configured", "per_request_recipients": True}, 0
    def calling_health(self):
        self.health_calls += 1
        return self.health
    def request_call(self, **request):
        self.requests.append(request)
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


class RecipientWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.clock, self.calls = Clock(), Calls()
        self.store = Store(self.root / "state")
        self.watcher = Watcher(self.store, classify, self.calls, self.clock, lambda pid: None)

    def tearDown(self):
        self.temp.cleanup()

    def arm(self, number=None, name=None, dry_run=False):
        return self.watcher.arm(job="Build opted-in fixture", criteria="Checks pass and output exists",
                                thread_id="thread-fixture", cwd=self.cwd, authorize_calls=not dry_run,
                                dry_run=dry_run, recipient_number=number, recipient_name=name)["watch_id"]

    def report(self, identifier, state="complete"):
        value = {"state": state, "summary": "The owner reports the observed result.",
                 "checks": [{"name": "fixture check", "passed": True}]}
        return self.watcher.report(identifier, value, "thread-fixture")

    def notice(self, identifier):
        return self.watcher.status(identifier)["notices"][0]

    def watch_files(self):
        return list((self.store.root / "watches").glob("*.json"))

    def test_each_watch_submits_only_its_own_recipient_fields(self):
        default, alex, number_only = self.arm(), self.arm(ALEX, "Alex"), self.arm(OTHER)
        for identifier in (default, alex, number_only):
            self.report(identifier)
        self.watcher.tick()
        by_id = {r["request_id"]: r for r in self.calls.requests}
        self.assertEqual(len(self.calls.requests), 3)
        self.assertEqual(self.calls.health_calls, 2)  # Only the two explicit recipients probe support.
        self.assertEqual(set(by_id), {f"watch-{i}-r1" for i in (default, alex, number_only)})
        self.assertNotIn("recipient_number", by_id[f"watch-{default}-r1"])
        self.assertNotIn("recipient_name", by_id[f"watch-{default}-r1"])
        self.assertEqual(by_id[f"watch-{alex}-r1"]["recipient_number"], ALEX)
        self.assertEqual(by_id[f"watch-{alex}-r1"]["recipient_name"], "Alex")
        self.assertEqual(by_id[f"watch-{number_only}-r1"]["recipient_number"], OTHER)
        self.assertNotIn("recipient_name", by_id[f"watch-{number_only}-r1"])
        self.assertEqual({r["outcome"] for r in self.calls.requests}, {"complete"})
        self.assertEqual(self.notice(alex)["status"], "submitted")

    def test_invalid_recipients_are_rejected_before_any_watch_is_written(self):
        with self.assertRaises(WatchError):
            self.arm(name="Alex")
        self.assertEqual(self.watch_files(), [])
        for number in ("2025550111", "+44 20 7946 0958", "+12025550111\n", "+10025550111",
                       "+1202555011", 12025550111):
            with self.subTest(number=number), self.assertRaises(WatchError):
                self.arm(number)
        for name in ("\n", "\t", "\x1b", "", "   ", "A" * 81):
            with self.subTest(name=name), self.assertRaises(WatchError):
                self.arm(ALEX, name)
        self.assertEqual(self.watch_files(), [])
        identifier = self.arm(ALEX, "  Alex  ")
        self.assertEqual(self.store.read("watches", identifier)["recipient"], BOUND_ALEX)
        self.assertEqual(len(self.watch_files()), 1)
        self.assertIsNotNone(self.arm(OTHER, "A" * 80))

    def test_binding_survives_reports_and_resubmits_same_id_with_same_recipient(self):
        identifier = self.arm(ALEX, "Alex")
        self.watcher.progress(identifier, "Owner observes work running", "thread-fixture")
        self.report(identifier, "running")
        self.report(identifier)
        self.calls.mode = "busy"
        self.watcher.tick()
        self.assertEqual(self.notice(identifier)["status"], "retry_wait")
        self.report(identifier)  # Identical terminal report keeps the pending notice.
        self.assertEqual(self.notice(identifier)["status"], "retry_wait")
        self.clock.advance(3601)
        self.calls.mode = "accepted"
        self.watcher.tick()
        first, second = self.calls.requests
        self.assertEqual(first["request_id"], second["request_id"])
        for request in (first, second):
            self.assertEqual(request["recipient_number"], ALEX)
            self.assertEqual(request["recipient_name"], "Alex")
        self.assertEqual(self.store.read("watches", identifier)["recipient"], BOUND_ALEX)
        self.assertEqual(self.notice(identifier)["recipient"], BOUND_ALEX)
        self.assertEqual(self.notice(identifier)["status"], "submitted")

    def test_dry_run_records_binding_without_dialing(self):
        identifier = self.arm(ALEX, "Alex", dry_run=True)
        self.report(identifier)
        self.watcher.tick()
        self.assertEqual(self.notice(identifier)["status"], "dry_run")
        self.assertEqual(self.notice(identifier)["recipient"], BOUND_ALEX)
        self.assertEqual(self.calls.requests, [])
        self.assertEqual(self.calls.queries, [])
        self.assertEqual(self.watcher.status(identifier)["watch"]["status"], "settled_dry_run")

    def test_explicit_terminal_receipt_must_echo_the_bound_recipient(self):
        identifier = self.arm(ALEX, "Alex")
        self.report(identifier)
        self.watcher.tick()
        request_id = self.calls.requests[0]["request_id"]
        self.calls.statuses[request_id] = {"request_id": request_id, "status": "review_required",
                                           "recipient_number": OTHER}
        self.watcher.tick()
        notice = self.notice(identifier)
        self.assertEqual(notice["status"], "uncertain")
        self.assertTrue(notice["manual_reconciliation_required"])
        self.assertNotIn("receipt", notice)
        self.assertFalse((self.store.root / "receipts" / f"{request_id}.json").exists())
        self.assertEqual(len(self.calls.requests), 1)
        self.calls.statuses[request_id] = {"request_id": request_id, "status": "review_required",
                                           "recipient_number": ALEX, "recipient_name": "Alex"}
        self.watcher.tick()
        saved = self.watcher.status(identifier)
        self.assertEqual(saved["notices"][0]["status"], "finished")
        self.assertEqual(saved["watch"]["status"], "settled")
        self.assertEqual(self.store.read("receipts", request_id)["recipient_number"], ALEX)
        self.assertEqual(len(self.calls.requests), 1)

    def test_default_watch_settles_without_recipient_fields_and_rejects_a_named_recipient(self):
        legacy, bearing = self.arm(), self.arm()
        for identifier in (legacy, bearing):
            self.report(identifier)
        self.watcher.tick()
        legacy_id, bearing_id = f"watch-{legacy}-r1", f"watch-{bearing}-r1"
        self.calls.statuses[legacy_id] = {"request_id": legacy_id, "status": "review_required",
                                          "carrier_status": "completed"}
        self.calls.statuses[bearing_id] = {"request_id": bearing_id, "status": "review_required",
                                           "recipient_number": ALEX}
        self.watcher.tick()
        self.assertEqual(self.watcher.status(legacy)["watch"]["status"], "settled")
        self.assertEqual(self.notice(legacy)["status"], "finished")
        self.assertEqual(self.notice(bearing)["status"], "uncertain")
        self.assertNotIn("receipt", self.notice(bearing))
        self.assertEqual(len(self.calls.requests), 2)

    def test_briefing_for_explicit_recipient_omits_configured_recipient_sentence(self):
        explicit, default = self.arm(ALEX, "Alex"), self.arm()
        for identifier in (explicit, default):
            self.report(identifier)
        self.watcher.tick()
        explicit_briefing = self.notice(explicit)["briefing"]
        submitted = {r["request_id"]: r["briefing"] for r in self.calls.requests}
        self.assertEqual(submitted[f"watch-{explicit}-r1"], explicit_briefing)
        self.assertNotIn(CONFIGURED_SENTENCE, explicit_briefing)
        self.assertIn("explicitly selected recipient", explicit_briefing)
        self.assertIn(CONFIGURED_SENTENCE, self.notice(default)["briefing"])

    def test_explicit_recipient_waits_until_caller_advertises_per_request_recipients(self):
        identifier = self.arm(ALEX, "Alex")
        self.report(identifier)
        self.calls.health = {"status": "configured"}
        self.watcher.tick()
        notice = self.notice(identifier)
        self.assertEqual(self.calls.requests, [])
        self.assertEqual(notice["status"], "retry_wait")
        self.assertEqual(notice["last_error"], "recipient_unsupported")
        self.assertGreaterEqual(self.calls.health_calls, 1)
        self.calls.health = {"status": "configured", "per_request_recipients": True}
        self.clock.advance(3601)
        self.watcher.tick()
        self.assertEqual(len(self.calls.requests), 1)
        self.assertEqual(self.calls.requests[0]["recipient_number"], ALEX)
        self.assertEqual(self.calls.requests[0]["recipient_name"], "Alex")
        self.assertEqual(self.notice(identifier)["status"], "submitted")

    def test_default_watch_never_probes_recipient_support(self):
        identifier = self.arm()
        self.report(identifier)
        self.calls.health = {"status": "configured"}  # Would block an explicit recipient.
        self.watcher.tick()
        self.assertEqual(self.calls.health_calls, 0)
        self.assertEqual(len(self.calls.requests), 1)
        self.assertNotIn("recipient_number", self.calls.requests[0])
        self.assertEqual(self.notice(identifier)["status"], "submitted")


class CliRecipientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                       "WATCH_CALL_STATE_DIR": str(self.state), "CODEX_THREAD_ID": "thread-cli"}
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *args], env=environment,
                              cwd=str(self.project), capture_output=True, text=True, timeout=20)

    def watch_files(self):
        return list((self.state / "watches").glob("*.json"))

    def test_arm_dry_run_with_recipient_is_reported_by_status(self):
        result = self.cli("arm", "--job", "fixture", "--criteria", "fixture passes", "--dry-run",
                          "--recipient-number", ALEX, "--recipient-name", "Alex")
        self.assertEqual(result.returncode, 0, result.stderr)
        registration = json.loads(result.stdout)
        self.assertEqual(registration["registration"]["recipient"], BOUND_ALEX)
        self.assertEqual(registration["registration"]["thread_id"], "thread-cli")
        status = self.cli("status", registration["watch_id"])
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["watch"]["recipient"], BOUND_ALEX)

    def test_name_without_number_and_missing_criteria_exit_two_without_writing(self):
        result = self.cli("arm", "--job", "fixture", "--criteria", "fixture passes", "--dry-run",
                          "--recipient-name", "Alex")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--recipient-number", json.loads(result.stderr)["error"])
        missing = self.cli("arm", "--job", "fixture", "--dry-run", "--recipient-number", ALEX)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--criteria", missing.stderr)
        self.assertEqual(self.watch_files(), [])


class MCPCallerRecipientTests(unittest.TestCase):
    def setUp(self):
        self.caller = MCPCaller({"calling_root": "/nonexistent"})
        self.sent = []

        def fake_run(name, arguments):
            self.sent.append((name, arguments))
            return {"request_id": arguments["request_id"], "status": "accepted"}

        self.caller._run = fake_run

    def request(self, outcome="complete", **recipient):
        return self.caller.request_call(request_id=REQUEST, focus="Focus", briefing="Briefing",
                                        outcome=outcome, **recipient)

    def test_request_arguments_carry_recipient_fields_only_when_selected(self):
        self.request()
        self.request(recipient_number=ALEX, recipient_name="Alex")
        self.request(recipient_number=OTHER)
        (name0, default), (name1, both), (name2, number_only) = self.sent
        self.assertEqual(name0, "request_call")
        self.assertEqual(set(default), {"request_id", "focus", "briefing", "outcome"})
        self.assertEqual(name1, "request_call")
        self.assertEqual(both["recipient_number"], ALEX)
        self.assertEqual(both["recipient_name"], "Alex")
        self.assertEqual(number_only["recipient_number"], OTHER)
        self.assertNotIn("recipient_name", number_only)

    def test_invalid_outcome_raises_before_any_call(self):
        with self.assertRaises(WatchError):
            self.request(outcome="done")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()

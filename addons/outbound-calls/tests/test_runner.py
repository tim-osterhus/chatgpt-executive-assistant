"""Offline request/receipt checks. No provider requests or phone calls."""
import contextlib
import asyncio
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
import call_runner as runner
from voice_session import CheckinApp, claim_slot, open_spoken_media, is_closing_utterance
from phone_call import call_parameters
from app_server import AppServer


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.config = {"from_number": "+12025550101", "to_number": "+12025550102",
                       "keychain_account": "test", "keychain_service_prefix": "test-only",
                       "assistant_name": "Test assistant", "participant_name": "Test participant",
                       "checkin_purpose": "a personal check-in"}
        (self.state / "config.json").write_text(json.dumps(self.config))
        self.addCleanup(patch.stopall)
        patch.object(runner, "STATE", self.state).start()
        patch.object(runner, "RUNS", self.state / "runs").start()
        self.place = patch.object(runner, "place_call", new_callable=AsyncMock).start()
        self.request = {"request_id": "offline-test-01", "focus": "a synthetic project"}

    def invoke(self, mode, request=None):
        output = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request or self.request).encode()))
        with patch.object(sys, "argv", ["runner", mode]), patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(output):
            runner.main()
        return json.loads(output.getvalue())

    def test_validation_has_no_call_or_run(self):
        self.assertEqual(self.invoke("validate")["status"], "validated")
        self.place.assert_not_called()
        self.assertFalse(runner.RUNS.exists())

    def test_unknown_result_never_calls(self):
        self.assertEqual(self.invoke("result")["status"], "request_not_found")
        self.place.assert_not_called()

    def test_replay_retrieves_first_attempt_without_dial(self):
        self.assertEqual(self.invoke("call")["status"], "result_unavailable")
        self.assertEqual(self.invoke("call")["status"], "result_unavailable")
        self.assertEqual(self.invoke("result")["status"], "result_unavailable")
        self.assertEqual(self.place.await_count, 1)

    def test_changed_focus_under_spent_id_is_rejected(self):
        self.invoke("call")
        changed = {**self.request, "focus": "a different project"}
        self.assertEqual(self.invoke("call", changed)["status"], "rejected")
        self.assertEqual(self.place.await_count, 1)

    def test_briefing_is_bound_to_the_original_request(self):
        request = {**self.request, "briefing": "A prepared factual update."}
        self.invoke("call", request)
        changed = {**request, "briefing": "Changed facts must not reuse the same request ID."}
        self.assertEqual(self.invoke("call", changed)["status"], "rejected")
        self.assertEqual(self.place.await_count, 1)
        accepted = self.place.call_args.args[1]
        self.assertEqual(accepted["briefing"], request["briefing"])

    def test_invalid_briefing_cannot_reach_call(self):
        self.assertEqual(self.invoke("call", {**self.request, "briefing": " "})["status"], "rejected")
        self.place.assert_not_called()

    def test_single_dial_slot_survives_replay(self):
        slot = self.state / "dial.slot"
        claim_slot(slot)
        with self.assertRaises(FileExistsError):
            claim_slot(slot)
        self.assertTrue(slot.exists())

    def test_mismatched_call_evidence_does_not_release_transcript(self):
        run = self.state / "receipt"
        evidence = run / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "result.json").write_text(json.dumps({
            "twilio_call_sid": "CA" + "1" * 32, "checkin_status": "review_required",
            "transcripts": [{"role": "user", "text": "private synthetic content"}]}))
        (evidence / "phone-summary.json").write_text(json.dumps({"call_sid": "CA" + "2" * 32}))
        receipt = runner.receipt(run, self.request)
        self.assertEqual(receipt["status"], "partial_or_failed")
        self.assertEqual(receipt["turns"], [])
        self.assertIsNone(receipt["call_id"])

    def test_invalid_destination_cannot_reach_call(self):
        self.config["to_number"] = self.config["from_number"]
        (self.state / "config.json").write_text(json.dumps(self.config))
        self.assertEqual(self.invoke("call")["status"], "rejected")
        self.place.assert_not_called()

    def test_personal_identity_replaces_mini_identity(self):
        app = CheckinApp({}, self.request["focus"], runner.load_config())
        self.assertIn('"assistant_name": "Test assistant"', app.brief["text"])
        self.assertNotIn("Kindly Loans", app.brief["text"])
        self.assertNotIn("Cortana", app.brief["text"])

    def test_legacy_configuration_remains_supported(self):
        legacy = {k: self.config[k] for k in ("from_number", "to_number", "keychain_account")}
        (self.state / "config.json").write_text(json.dumps(legacy))
        self.assertEqual(runner.load_config(), legacy)

    def test_personal_disclosure_can_be_disabled_without_blocking_audio(self):
        from types import SimpleNamespace
        adapter = SimpleNamespace(disclose=AsyncMock(), input_ready=asyncio.Event())
        asyncio.run(open_spoken_media(adapter, False))
        adapter.disclose.assert_not_awaited()
        self.assertTrue(adapter.input_ready.is_set())

    def test_enabled_disclosure_plays_before_audio(self):
        from types import SimpleNamespace
        adapter = SimpleNamespace(disclose=AsyncMock(), input_ready=asyncio.Event())
        asyncio.run(open_spoken_media(adapter, True))
        adapter.disclose.assert_awaited_once()
        self.assertTrue(adapter.input_ready.is_set())

    def test_carrier_request_uses_45_minute_default_and_configured_limit(self):
        params = call_parameters('https://synthetic.trycloudflare.com', 'n' * 32,
                                 self.config['from_number'], target=self.config['to_number'])
        self.assertEqual(params['TimeLimit'], '2700')
        self.assertEqual(params['Timeout'], '20')
        configured = call_parameters('https://synthetic.trycloudflare.com', 'n' * 32,
                                     self.config['from_number'], target=self.config['to_number'], max_call_seconds=900)
        self.assertEqual(configured['TimeLimit'], '900')

    def test_incidental_farewell_does_not_end_the_call(self):
        self.assertFalse(is_closing_utterance('The customer said goodbye before confirming.'))
        self.assertFalse(is_closing_utterance('Do you want to say goodbye?'))
        self.assertFalse(is_closing_utterance('They said "bye".'))
        self.assertTrue(is_closing_utterance('I will pass that request along. Goodbye.'))
        self.assertTrue(is_closing_utterance('Bye!'))
        self.assertTrue(is_closing_utterance('Goodbye, Tim.'))
        self.assertTrue(is_closing_utterance('Thanks, goodbye.'))

    def test_voice_process_eof_signals_failure_for_call_cleanup(self):
        from types import SimpleNamespace
        async def probe():
            app = AppServer({})
            reader = SimpleNamespace(readline=AsyncMock(return_value=b''))
            app.process = SimpleNamespace(stdout=reader)
            await app.read()
            self.assertTrue(app.failed.is_set())
            self.assertEqual(app.result['provider_error_category'], 'app_server_stream_closed')
        asyncio.run(probe())


if __name__ == "__main__":
    unittest.main()

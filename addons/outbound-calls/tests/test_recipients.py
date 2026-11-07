"""Per-request recipients: runner destination, framing, SDK legs, and exact recovery. Offline only."""
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientSession
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
import call_runner as runner  # noqa: E402
from phone_bridge import signature  # noqa: E402
from phone_call import call_parameters  # noqa: E402
from sdk_call_state import unresolved  # noqa: E402
from sdk_phone import SdkPhone, listen  # noqa: E402
from sdk_recovery import recover  # noqa: E402
from voice_session import CheckinApp  # noqa: E402
from voicemail import instruction_for  # noqa: E402

OWNER, FRIEND, OTHER, SOURCE = "+12025550102", "+13125550123", "+14155550144", "+12025550101"
AC = "AC" + "1" * 32; AP = "AP" + "2" * 32; PARENT = "CA" + "3" * 32; CHILD = "CA" + "4" * 32


class RunnerRecipientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.config = {"from_number": SOURCE, "to_number": OWNER, "keychain_account": "test",
                       "assistant_name": "Test assistant", "participant_name": "Jordan",
                       "checkin_purpose": "a personal check-in"}
        self.write_config()
        self.addCleanup(patch.stopall)
        patch.object(runner, "STATE", self.state).start()
        patch.object(runner, "RUNS", self.state / "runs").start()
        self.seen = []

        async def place(run, request, config, destination):
            # Proves the destination is durably recorded before any provider work begins.
            self.seen.append((json.loads((run / "destination.json").read_text()), dict(request)))
        self.place = patch.object(runner, "place_call", side_effect=place).start()
        self.base = {"request_id": "watch-offline-01", "focus": "Build", "briefing": "All checks passed."}

    def write_config(self):
        (self.state / "config.json").write_text(json.dumps(self.config))

    def invoke(self, mode, request):
        output = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode()))
        with patch.object(sys, "argv", ["runner", mode]), patch.object(sys, "stdin", stdin), \
                contextlib.redirect_stdout(output):
            runner.main()
        return json.loads(output.getvalue())

    def test_two_explicit_recipients_and_default_each_resolve_their_own_destination(self):
        requests = [dict(self.base, request_id="watch-default-01"),
                    dict(self.base, request_id="watch-friend-01", recipient_number=FRIEND, recipient_name="Alex"),
                    dict(self.base, request_id="watch-other-01", recipient_number=OTHER)]
        for request in requests:
            self.invoke("call", request)
        destinations = {d["request_id"]: d for d, _ in self.seen}
        self.assertEqual(destinations["watch-default-01"],
                         {"request_id": "watch-default-01", "number": OWNER, "name": None, "source": "configured_default"})
        self.assertEqual(destinations["watch-friend-01"]["number"], FRIEND)
        self.assertEqual(destinations["watch-friend-01"]["name"], "Alex")
        self.assertEqual(destinations["watch-other-01"], {"request_id": "watch-other-01", "number": OTHER,
                                                          "name": None, "source": "request"})
        # The default request keeps its legacy identity: no recipient fields are added.
        self.assertEqual(json.loads((runner.RUNS / "watch-default-01/request.json").read_text()), requests[0])

    def test_changed_recipient_under_spent_id_is_rejected_without_second_call(self):
        request = dict(self.base, recipient_number=FRIEND, recipient_name="Alex")
        self.invoke("call", request)
        for changed in (dict(request, recipient_number=OTHER), dict(request, recipient_name="Sam"),
                        {k: v for k, v in request.items() if k != "recipient_number" and k != "recipient_name"}):
            self.assertEqual(self.invoke("call", changed)["status"], "rejected")
        self.assertEqual(self.place.call_count, 1)
        replay = self.invoke("call", request)
        self.assertEqual((replay["recipient_number"], replay["recipient_name"]), (FRIEND, "Alex"))
        self.assertEqual(self.place.call_count, 1)

    def test_boundary_validation_rejects_before_any_run(self):
        invalid = [
            {"recipient_name": "Alex"},  # A name alone must never fall through to the default recipient.
            {"recipient_number": "3125550123"}, {"recipient_number": "+443125550123"},
            {"recipient_number": "+10125550123"}, {"recipient_number": FRIEND + "\n"},
            {"recipient_number": 13125550123}, {"recipient_number": FRIEND, "recipient_name": "Al\nex"},
            {"recipient_number": FRIEND, "recipient_name": "\x1b[31m"}, {"recipient_number": FRIEND, "recipient_name": " "},
            {"recipient_number": FRIEND, "recipient_name": "x" * 81}, {"recipient_number": SOURCE},
        ]
        for extra in invalid:
            with self.subTest(extra=extra):
                self.assertEqual(self.invoke("call", {**self.base, **extra})["status"], "rejected")
        no_briefing = {"request_id": "legacy-two-field", "focus": "Build", "recipient_number": FRIEND}
        self.assertEqual(self.invoke("call", no_briefing)["status"], "rejected")
        self.place.assert_not_called()
        self.assertFalse(runner.RUNS.exists() and any(runner.RUNS.iterdir()))
        self.assertEqual(runner.validate_request({**self.base, "recipient_number": FRIEND,
                                                  "recipient_name": "  Alex  "})["recipient_name"], "Alex")

    def test_receipt_reports_actual_destination_and_old_receipt_is_unchanged(self):
        request = dict(self.base, recipient_number=FRIEND)
        receipt = self.invoke("call", request)
        self.assertEqual((receipt["recipient_number"], receipt["destination_last4"]), (FRIEND, "0123"))
        legacy_run = self.state / "runs/legacy-old-run"
        legacy_run.mkdir(parents=True)
        legacy = {"request_id": "legacy-old-run", "focus": "Old"}
        (legacy_run / "request.json").write_text(json.dumps(legacy))
        old = self.invoke("result", legacy)
        self.assertNotIn("destination_last4", old)
        self.assertNotIn("recipient_number", old)
        self.assertEqual(old["status"], "result_unavailable")

    def test_recorded_destination_survives_default_change_and_legacy_falls_back(self):
        self.invoke("call", dict(self.base, request_id="watch-default-02"))
        self.invoke("call", dict(self.base, request_id="watch-friend-02", recipient_number=FRIEND))
        self.config["to_number"] = OTHER  # The configured default later changes.
        self.write_config()
        config = runner.load_config()
        for request_id, expected in (("watch-default-02", OWNER), ("watch-friend-02", FRIEND)):
            run = runner.RUNS / request_id
            request = json.loads((run / "request.json").read_text())
            self.assertEqual(runner.recorded_destination(run, request, config)["number"], expected)
        legacy = self.state / "runs/legacy-sdk"
        legacy.mkdir(parents=True)
        self.assertEqual(runner.recorded_destination(legacy, {"request_id": "legacy-sdk", "focus": "x"}, config)["number"], OTHER)
        tampered = runner.RUNS / "watch-friend-02"
        (tampered / "destination.json").write_text(json.dumps({"request_id": "watch-friend-02", "number": OWNER}))
        with self.assertRaises(ValueError):
            runner.recorded_destination(tampered, json.loads((tampered / "request.json").read_text()), config)

    def test_place_call_passes_explicit_target_and_recipient_to_live_runtime(self):
        patch.stopall()  # Exercise the real place_call with a fake Live runtime and keychain.
        patch.object(runner, "STATE", self.state).start()
        conduct = AsyncMock()
        fake = type(sys)("voice_session")
        fake.conduct = conduct
        keys = {"twilio-account-sid": AC, "twilio-auth-token": "token"}
        run = self.state / "runs/explicit"
        run.mkdir(parents=True)
        request = dict(self.base, recipient_number=FRIEND, recipient_name="Alex")
        with patch.dict(sys.modules, {"voice_session": fake}), \
                patch.object(runner, "read_keychain", side_effect=lambda service, *_: keys[service]), \
                patch.dict("os.environ", {"PATH": "/usr/bin:/bin"}, clear=True):
            asyncio.run(runner.place_call(run, request, self.config, runner.resolve_destination(request, self.config)))
            asyncio.run(runner.place_call(run, self.base, self.config, runner.resolve_destination(self.base, self.config)))
        explicit, default = conduct.await_args_list
        self.assertEqual(explicit.args[3], FRIEND)
        self.assertEqual(explicit.kwargs["recipient"], {"name": "Alex"})
        self.assertEqual(default.args[3], OWNER)
        self.assertIsNone(default.kwargs["recipient"])

    def test_media_streams_fallback_dials_only_the_explicit_target(self):
        params = call_parameters("https://example.trycloudflare.com", "n" * 32, SOURCE, target=FRIEND)
        self.assertEqual(params["To"], FRIEND)


class FramingTests(unittest.TestCase):
    settings = {"assistant_name": "Nova", "participant_name": "Jordan", "checkin_purpose": "Example Co internal check-in"}

    def test_friend_call_addresses_recipient_without_owner_context(self):
        for name in ("Alex", None):
            app = CheckinApp({}, "Build", self.settings, "The build finished.", "complete", {"name": name})
            supplied = json.loads(app.brief["text"].rsplit("Supplied context:\n", 1)[1])
            self.assertEqual(supplied, {"assistant_name": "Nova", "recipient_name": name,
                                        "focus": "Build", "briefing": "The build finished."})
            self.assertNotIn("Jordan", app.brief["text"])
            self.assertNotIn("Example Co", app.brief["text"])
            self.assertIn("configured assistant name", app.brief["text"])
            self.assertNotIn("automated", app.brief["text"])  # No forced opening disclaimer.
            self.assertIn("address the recipient by the supplied recipient_name", app.brief["text"])
            self.assertEqual(app.backend_profile["model"], "gpt-6.1-terra")  # Outcome profile is unchanged.
            self.assertIn("Do not use external tools or perform project actions", __import__("voice_session").PROMPT)

    def test_default_call_framing_is_unchanged(self):
        default = CheckinApp({}, "Build", self.settings, "The build finished.", "complete")
        supplied = json.loads(default.brief["text"].rsplit("Supplied context:\n", 1)[1])
        self.assertEqual(supplied["participant_name"], "Jordan")
        self.assertEqual(supplied["checkin_purpose"], "Example Co internal check-in")
        self.assertNotIn("explicitly selected", default.brief["text"])

    def test_explicit_recipient_requires_briefing(self):
        with self.assertRaises(ValueError):
            CheckinApp({}, "Build", self.settings, None, None, {"name": "Alex"})

    def test_voicemail_identifies_assistant_and_keeps_default_text(self):
        self.assertEqual(instruction_for("Build", "Done.", "complete"),
                         instruction_for("Build", "Done.", "complete", None, "Other name"))
        named = instruction_for("Build", "Done.", "complete", {"name": "Alex"}, "Nova")
        data = json.loads(named.rsplit("\n", 1)[1])
        self.assertEqual(data["recipient_name"], "Alex")
        self.assertIn('Address the recipient by the supplied recipient_name and identify yourself as "Nova"', named)
        self.assertNotIn("automated", named)
        neutral = instruction_for("Build", "Done.", "complete", {"name": None}, "Nova")
        self.assertIsNone(json.loads(neutral.rsplit("\n", 1)[1])["recipient_name"])
        self.assertIn('Do not guess a name for the recipient and identify yourself as "Nova"', neutral)
        self.assertNotIn("Address the recipient", neutral)
        self.assertNotIn("automated", neutral)
        self.assertNotIn("recipient_name", instruction_for("Build", "Done.", "complete"))


class SdkRecipientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "runs/friend-sdk/evidence"
        self.output.mkdir(parents=True)
        self.state = Path(self.temp.name) / "state"
        (self.state / "plugin").mkdir(parents=True)
        (self.state / "plugin-requests").mkdir()
        (self.state / "plugin/dial-enabled").write_bytes(b"gate")
        self.phone = SdkPhone(state_root=self.state, output=self.output, request_id="friend-sdk",
            account=AC, token="test-auth-token", credentials={"app_sid": AP, "key_sid": "SK" + "5" * 32, "key_secret": "t"},
            source=SOURCE, target=FRIEND, adapter=Mock(), max_seconds=2700, ringing=60,
            voicemail_enabled=True, on_connected=AsyncMock(), on_voicemail=AsyncMock())
        self.phone.journal.claim()
        self.phone.public_base = "https://example.trycloudflare.com"
        self.client = ClientSession(); self.runners = []

    async def asyncTearDown(self):
        await self.client.close()
        for item in self.runners:
            await item.cleanup()
        self.phone.wav_in.close(); self.phone.wav_out.close(); self.phone.events.close(); self.temp.cleanup()

    def api(self, child_to):
        api = Mock()
        async def call(sid):
            if sid == CHILD:
                return {"sid": sid, "parent_call_sid": PARENT, "to": child_to, "status": "completed"}
            return {"sid": sid, "from": "client:" + self.phone.identity, "status": "completed"}
        api.call = call
        api.stop = AsyncMock(side_effect=lambda sid: {"sid": sid, "status": "completed", "duration": "4"})
        api.request = AsyncMock(side_effect=lambda method, resource, data=None, params=None:
            {"calls": [{"sid": CHILD, "to": child_to, "parent_call_sid": PARENT}]} if resource == "Calls"
            else {"sid": AP, "account_sid": AC, "voice_url": ""})
        return api

    async def test_journal_records_target_and_single_dial_uses_it(self):
        self.assertEqual(json.loads(self.phone.journal.path.read_text())["target"], FRIEND)
        runner_, port = await listen(self.phone.public_app()); self.runners.append(runner_)
        path = "/voice/" + self.phone.nonce
        self.phone.journal.update(status="claimed", dial_attempted=True)
        data = {"AccountSid": AC, "CallSid": PARENT, "From": "client:" + self.phone.identity, "Intent": "friend-sdk"}
        headers = {"X-Twilio-Signature": signature("test-auth-token", self.phone.public_base + path, data)}
        async with self.client.post("http://127.0.0.1:%d%s" % (port, path), data=data, headers=headers) as response:
            xml = await response.text()
        self.assertIn(">" + FRIEND + "</Number>", xml)
        self.assertNotIn(OWNER, xml)
        self.assertEqual(xml.count("<Dial"), 1)

    async def test_child_leg_to_default_number_is_not_the_friend_call(self):
        self.phone.journal.update(parent_sid=PARENT, child_sid=CHILD, dial_returned=True)
        self.phone.api = self.api(OWNER)
        with self.assertRaisesRegex(RuntimeError, "relationship_mismatch"):
            await self.phone.reconcile_calls()
        self.phone.api = self.api(FRIEND)
        self.assertTrue(await self.phone.reconcile_calls())

    async def test_recovery_uses_recorded_target_after_default_changes(self):
        self.phone.journal.update(parent_sid=PARENT, child_sid=CHILD, dial_returned=True)
        options = dict(state_root=self.state, output=self.output, request_id="friend-sdk", account=AC,
                       token="t", credentials={"app_sid": AP})
        stale = self.api(FRIEND)
        with self.assertRaisesRegex(RuntimeError, "target_mismatch"):
            await recover(**options, target=OWNER, api=stale)  # Today's default is not this call's destination.
        stale.request.assert_not_awaited()
        self.assertTrue(unresolved(self.state))
        with patch("sdk_recovery.stop_recorded", new_callable=AsyncMock), \
                patch.object(SdkPhone, "stop_renderer", new_callable=AsyncMock):
            result = await recover(**options, target=FRIEND, api=self.api(FRIEND))
        self.assertEqual(result["status"], "reconciled")
        self.assertFalse(unresolved(self.state))
        saved = json.loads((self.output / "phone-summary.recovery.json").read_text())
        self.assertEqual({row["sid"] for row in saved["sdk_leg_states"]}, {PARENT, CHILD})


class RecoveryScriptTests(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location("sdk_recover_under_test", ROOT / "scripts/sdk_recover.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_script_passes_original_recipient_not_current_default(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            config = {"from_number": SOURCE, "to_number": OTHER, "keychain_account": "test"}
            cases = {"friend-run": ({"request_id": "friend-run", "focus": "x", "briefing": "y", "recipient_number": FRIEND},
                                    {"request_id": "friend-run", "number": FRIEND, "name": None, "source": "request"}),
                     "default-run": ({"request_id": "default-run", "focus": "x", "briefing": "y"},
                                     {"request_id": "default-run", "number": OWNER, "name": None, "source": "configured_default"}),
                     "legacy-run": ({"request_id": "legacy-run", "focus": "x"}, None)}
            for name, (request, destination) in cases.items():
                run = state / "runs" / name; run.mkdir(parents=True)
                (run / "request.json").write_text(json.dumps(request))
                if destination:
                    (run / "destination.json").write_text(json.dumps(destination))
            seen = {}
            async def fake_recover(**kwargs):
                seen[kwargs["request_id"]] = kwargs["target"]
                return {"status": "reconciled"}
            with patch.object(module, "STATE", state), patch.object(module, "load_config", return_value=config), \
                    patch.object(module, "read_keychain", return_value="secret"), \
                    patch.object(module, "load_credentials", return_value={"app_sid": AP}), \
                    patch.object(module, "recover", side_effect=fake_recover), contextlib.redirect_stdout(io.StringIO()):
                for name in cases:
                    with patch.object(sys, "argv", ["sdk_recover.py", name]):
                        self.assertEqual(module.main(), 0)
        self.assertEqual(seen, {"friend-run": FRIEND, "default-run": OWNER, "legacy-run": OTHER})


if __name__ == "__main__":
    unittest.main()

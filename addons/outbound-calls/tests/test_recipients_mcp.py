"""MCP request_call recipient fields, request identity, and exact receipts. No launch or provider."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
try:
    import calling_mcp as calling  # noqa: E402
except ModuleNotFoundError as exc:
    if exc.name != "mcp":
        raise
    raise unittest.SkipTest("Optional MCP tests require .plugin-venv; install requirements-plugin.lock") from exc

FRIEND, OTHER = "+13125550123", "+14155550144"
SID = "CA" + "7" * 32


class RecipientMcpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.config = {"from_number": "+15551112222", "to_number": "+15553334444", "keychain_account": "test-only"}
        for patcher in (
            mock.patch.object(calling, "PLUGIN_STATE", self.base / "plugin"),
            mock.patch.object(calling, "DIAL_ENABLED", self.base / "plugin/dial-enabled"),
            mock.patch.object(calling, "LEDGER", self.base / "plugin-requests"),
            mock.patch.object(calling, "STATE", self.base / ".state"),
            mock.patch.object(calling, "RUNNER", self.base / "run"),
            mock.patch.object(calling, "ROOT", self.base),
            mock.patch.object(calling, "load_config", return_value=self.config),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.base / "plugin").mkdir()
        (self.base / "plugin/dial-enabled").touch()
        self.popen = mock.patch.object(calling.subprocess, "Popen").start()
        self.addCleanup(mock.patch.stopall)

    def call(self, request_id="watch-recipient-1", **fields):
        return calling.request_call(request_id, "Build", "The build finished.", "complete", **fields)

    def saved(self, request_id):
        return json.loads((self.base / "plugin-requests" / request_id / "request.json").read_text())

    def finish(self, request_id, request, **extra):
        receipt = {**request, "status": "review_required", "call_id": SID, "carrier_status": "completed", **extra}
        (self.base / "plugin-requests" / request_id / "runner.stdout.json").write_text(json.dumps(receipt))

    def test_schema_exposes_optional_recipient_fields(self):
        tools = asyncio.run(calling.app.list_tools())
        schema = next(tool for tool in tools if tool.name == "request_call").inputSchema
        self.assertTrue({"recipient_number", "recipient_name"} <= schema["properties"].keys())
        self.assertNotIn("recipient_number", schema.get("required", []))
        self.assertNotIn("recipient_name", schema.get("required", []))

    def test_health_advertises_recipient_support_without_full_number(self):
        health = calling.calling_health()
        self.assertIs(health["per_request_recipients"], True)
        self.assertEqual(health["recipient_last4"], "4444")
        self.assertNotIn(self.config["to_number"], json.dumps(health))

    def test_default_request_identity_is_unchanged_and_explicit_fields_are_bound(self):
        self.assertEqual(self.call("watch-default-1")["status"], "accepted")
        self.assertEqual(self.saved("watch-default-1"), {"request_id": "watch-default-1", "focus": "Build",
                                                         "briefing": "The build finished.", "outcome": "complete"})
        self.finish("watch-default-1", self.saved("watch-default-1"))
        self.assertEqual(self.call("watch-friend-1", recipient_number=FRIEND, recipient_name="Alex")["status"], "accepted")
        self.assertEqual((self.saved("watch-friend-1")["recipient_number"], self.saved("watch-friend-1")["recipient_name"]),
                         (FRIEND, "Alex"))
        self.assertEqual(self.popen.call_count, 2)

    def test_same_id_cannot_be_retargeted_and_exact_replay_does_not_relaunch(self):
        self.assertEqual(self.call(recipient_number=FRIEND, recipient_name="Alex")["status"], "accepted")
        for fields in ({"recipient_number": OTHER, "recipient_name": "Alex"}, {"recipient_number": FRIEND},
                       {"recipient_number": FRIEND, "recipient_name": "Sam"}, {}):
            result = self.call(**fields)
            self.assertEqual((result["status"], result["reason"]),
                             ("rejected", "Request ID already belongs to a different brief"))
        self.assertEqual(self.call(recipient_number=FRIEND, recipient_name="Alex")["status"], "pending_or_uncertain")
        self.assertEqual(self.popen.call_count, 1)

    def test_invalid_recipient_is_rejected_before_ledger_or_launch(self):
        for fields in ({"recipient_name": "Alex"}, {"recipient_number": "3125550123"},
                       {"recipient_number": "+443125550123"}, {"recipient_number": FRIEND, "recipient_name": "A\tB"},
                       {"recipient_number": self.config["from_number"]}):
            with self.subTest(fields=fields):
                self.assertEqual(self.call(**fields)["status"], "rejected")
        self.assertFalse((self.base / "plugin-requests").exists() and any((self.base / "plugin-requests").iterdir()))
        self.popen.assert_not_called()

    def test_receipt_must_echo_the_bound_recipient(self):
        self.call(recipient_number=FRIEND)
        request = self.saved("watch-recipient-1")
        self.finish("watch-recipient-1", {**request, "recipient_number": OTHER})
        self.assertEqual(calling.get_call_status("watch-recipient-1")["status"], "pending_or_uncertain")
        self.finish("watch-recipient-1", request, destination_last4="0123")
        status = calling.get_call_status("watch-recipient-1")
        self.assertEqual((status["status"], status["recipient_number"], status["destination_last4"]),
                         ("review_required", FRIEND, "0123"))

    def test_old_absent_field_ledger_and_receipt_still_recover(self):
        request_dir = self.base / "plugin-requests/legacy-call-1"
        request_dir.mkdir(parents=True)
        legacy = {"request_id": "legacy-call-1", "focus": "Old", "briefing": "Old receipt."}
        (request_dir / "request.json").write_text(json.dumps(legacy))
        self.finish("legacy-call-1", legacy)
        status = calling.get_call_status("legacy-call-1")
        self.assertEqual(status["status"], "review_required")
        self.assertNotIn("recipient_number", status)
        replay = calling.request_call("legacy-call-1", "Old", "Old receipt.")
        self.assertEqual(replay["status"], "review_required")
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

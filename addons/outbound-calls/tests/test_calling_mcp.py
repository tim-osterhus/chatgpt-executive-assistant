import asyncio
import json
import os
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


class CallingMcpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.plugin_state = base / "plugin"
        self.ledger = base / "plugin-requests"
        self.runner = base / "run"
        self.config = {
            "from_number": "+15551112222",
            "to_number": "+15553334444",
            "keychain_account": "test-only",
            "max_call_seconds": 321,
            "spoken_disclosure": True,
        }
        self.patches = [
            mock.patch.object(calling, "PLUGIN_STATE", self.plugin_state),
            mock.patch.object(calling, "DIAL_ENABLED", self.plugin_state / "dial-enabled"),
            mock.patch.object(calling, "LEDGER", self.ledger),
            mock.patch.object(calling, "RUNNER", self.runner),
            mock.patch.object(calling, "ROOT", base),
            mock.patch.object(calling, "load_config", return_value=self.config),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def enable_dialing(self):
        self.plugin_state.mkdir(parents=True, exist_ok=True)
        (self.plugin_state / "dial-enabled").touch()

    def request(self, request_id="call-001", briefing="Speak with the recipient about today's plan"):
        return calling.request_call(request_id, "Discuss the requested topic", briefing)

    def fake_spawn(self, *_args, **_kwargs):
        return mock.Mock(pid=12345)

    def test_disabled_gate_rejects_without_ledger_or_launch(self):
        with mock.patch.object(calling.subprocess, "Popen") as popen:
            result = self.request()
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(self.ledger.exists())
        popen.assert_not_called()

    def test_multibyte_briefing_over_runner_byte_limit_cannot_launch(self):
        self.enable_dialing()
        with mock.patch.object(calling.subprocess, "Popen") as popen:
            result = self.request(briefing="文" * 6000)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(self.ledger.exists())
        popen.assert_not_called()

    def test_same_id_same_payload_never_relaunches(self):
        self.enable_dialing()
        with mock.patch.object(calling.subprocess, "Popen", side_effect=self.fake_spawn) as popen:
            first = self.request()
            second = self.request()
        self.assertEqual(first["status"], "accepted")
        self.assertEqual(second["status"], "pending_or_uncertain")
        popen.assert_called_once()

    def test_same_id_changed_briefing_is_rejected(self):
        self.enable_dialing()
        with mock.patch.object(calling.subprocess, "Popen", side_effect=self.fake_spawn) as popen:
            self.request()
            result = self.request(briefing="A changed request")
        self.assertEqual(result["status"], "rejected")
        popen.assert_called_once()

    def test_unknown_status_is_read_only(self):
        result = calling.get_call_status("unknown-001")
        self.assertEqual(result, {"request_id": "unknown-001", "status": "request_not_found"})
        self.assertFalse(self.ledger.exists())

    def test_unresolved_request_blocks_a_different_id(self):
        self.enable_dialing()
        with mock.patch.object(calling.subprocess, "Popen", side_effect=self.fake_spawn) as popen:
            self.request("call-001")
            second = self.request("call-002")
        self.assertEqual(second["status"], "busy")
        popen.assert_called_once()

    def test_terminal_receipt_is_exact_id_bound_and_host_paths_are_stripped(self):
        self.ledger.mkdir(mode=0o700)
        request_dir = self.ledger / "call-001"
        request_dir.mkdir(mode=0o700)
        request = {
            "request_id": "call-001",
            "focus": "Discuss the requested topic",
            "briefing": "Speak with the recipient about today's plan",
        }
        (request_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
        receipt = {
            **request,
            "status": "review_required",
            "call_id": "CA" + "1" * 32,
            "carrier_status": "completed",
            "turns": [{"speaker": "assistant", "text": "Hello"}],
            "evidence_path": "/private/host/path/result.json",
        }
        (request_dir / "runner.stdout.json").write_text(json.dumps(receipt), encoding="utf-8")
        result = calling.get_call_status("call-001")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["turns"], receipt["turns"])
        self.assertNotIn("evidence_path", result)
        self.assertNotIn("/private/host/path", json.dumps(result))

    def test_mismatched_receipt_cannot_complete_original_request(self):
        self.enable_dialing()
        with mock.patch.object(calling.subprocess, "Popen", side_effect=self.fake_spawn):
            self.request()
        folder = self.ledger / "call-001"
        request = json.loads((folder / "request.json").read_text())
        (folder / "runner.stdout.json").write_text(json.dumps({
            **request, "request_id": "other-001", "status": "review_required",
            "call_id": "CA" + "1" * 32, "carrier_status": "completed",
        }))
        self.assertEqual(calling.get_call_status("call-001")["status"], "pending_or_uncertain")

    def test_unavailable_or_unresolved_dial_does_not_release_admission(self):
        self.enable_dialing()
        with mock.patch.object(calling.subprocess, "Popen", side_effect=self.fake_spawn) as popen:
            self.request()
            request_dir = self.ledger / "call-001"
            request = json.loads((request_dir / "request.json").read_text())
            for fields in ({}, {"status": "result_unavailable", "dial_attempt_recorded": True},
                           {"status": "partial_or_failed", "call_id": None, "carrier_status": None}):
                (request_dir / "runner.stdout.json").write_text(json.dumps({**request, **fields}))
                self.assertEqual(calling.get_call_status("call-001")["status"], "pending_or_uncertain")
                self.assertEqual(self.request("call-002")["status"], "busy")
            popen.assert_called_once()

    def test_spawn_is_detached_and_receives_only_sanitized_environment(self):
        self.enable_dialing()
        with mock.patch.dict(os.environ, {
            "CONTROL_PLANE_API_KEY": "tunnel-secret",
            "OPENAI_API_KEY": "openai-secret",
            "CODEX_ACCESS_TOKEN": "codex-secret",
            "TEST_OTHER_SECRET": "other-secret",
        }), mock.patch.object(calling.subprocess, "Popen", side_effect=self.fake_spawn) as popen:
            result = self.request()
        self.assertEqual(result["status"], "accepted")
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [str(self.runner), "call"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(set(kwargs["env"]), {"PATH", "HOME", "LANG", "TMPDIR"})
        self.assertNotIn("tunnel-secret", json.dumps(kwargs["env"]))

    def test_request_is_durable_before_spawn(self):
        self.enable_dialing()

        def inspect_ledger(*_args, **kwargs):
            request_file = Path(kwargs["stdin"].name)
            saved = json.loads(request_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["request_id"], "call-001")
            self.assertTrue(request_file.is_file())
            return mock.Mock(pid=12345)

        with mock.patch.object(calling.subprocess, "Popen", side_effect=inspect_ledger):
            result = self.request()
        self.assertEqual(result["status"], "accepted")

    def test_sdk_client_can_list_tools_and_read_health(self):
        self.enable_dialing()

        async def exercise():
            from mcp.shared.memory import create_connected_server_and_client_session

            async with create_connected_server_and_client_session(calling.app) as client:
                tools = await client.list_tools()
                health = await client.call_tool("calling_health", {})
                return tools, health

        tools, health = asyncio.run(exercise())
        tools = tools.tools
        self.assertEqual({tool.name for tool in tools}, {"calling_health", "request_call", "get_call_status"})
        self.assertTrue(next(tool for tool in tools if tool.name == "calling_health").annotations.readOnlyHint)
        self.assertTrue(health.structuredContent["config_ready"])
        self.assertEqual(health.structuredContent["recipient_last4"], "4444")
        self.assertNotIn(self.config["to_number"], json.dumps(health.structuredContent))


class PrivatePluginSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("private_plugin", ROOT / "scripts/private_plugin.py")
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def archive(self, symlink=False):
        import io
        import zipfile
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            member = zipfile.ZipInfo("nested/tunnel-client")
            member.external_attr = (0o120777 if symlink else 0o100700) << 16
            archive.writestr(member, b"fixture")
            archive.writestr("../outside", b"outside")
        return output.getvalue()

    def test_installer_writes_only_verified_binary(self):
        import hashlib
        data = self.archive()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bin/tunnel-client"
            self.helper.install_archive(data, hashlib.sha256(data).hexdigest(), target)
            self.assertEqual(target.read_bytes(), b"fixture")
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertFalse((Path(directory) / "outside").exists())

    def test_invalid_checksum_and_symlink_are_rejected(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tunnel-client"
            with self.assertRaises(ValueError):
                self.helper.install_archive(self.archive(), "0" * 64, target)
            data = self.archive(symlink=True)
            with self.assertRaises(ValueError):
                self.helper.install_archive(data, hashlib.sha256(data).hexdigest(), target)
            self.assertFalse(target.exists())

    def test_install_is_bounded_and_pinned_without_real_network(self):
        import io
        data = b"synthetic-archive"
        with mock.patch.object(self.helper.sys, "version_info", (3, 12)), \
             mock.patch.object(self.helper.platform, "system", return_value="Darwin"), \
             mock.patch.object(self.helper.platform, "machine", return_value="arm64"), \
             mock.patch.object(self.helper.urllib.request, "urlopen", return_value=io.BytesIO(data)) as fetch, \
             mock.patch.object(self.helper, "install_archive") as unpack, \
             mock.patch.object(self.helper.subprocess, "run") as run:
            self.helper.install()
        fetch.assert_called_once_with(self.helper.CLIENT_URL, timeout=60)
        unpack.assert_called_once_with(data, self.helper.CLIENT_SHA256, self.helper.CLIENT)
        self.assertEqual(run.call_count, 2)
        self.assertIn(".plugin-venv", str(run.call_args_list))

    def test_keychain_store_uses_stdin_and_readback(self):
        secret = "sk-synthetic-only-test-secret"
        with mock.patch.object(self.helper.getpass, "getpass", return_value=secret), \
             mock.patch.object(self.helper.subprocess, "run", return_value=mock.Mock(returncode=0)) as run, \
             mock.patch.object(self.helper, "keychain_key", return_value=secret):
            self.helper.store_key()
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/security", "-i"])
        self.assertNotIn(secret, str(args))
        self.assertIn(secret, kwargs["input"])

    def test_connection_rejects_placeholders(self):
        for tunnel, workspace in (("<tunnel-id>", "<workspace-id>"), ("tunnel_valid", "-" * 36)):
            with self.assertRaises(ValueError):
                self.helper.validate_connection({"tunnel_id": tunnel, "workspace_id": workspace})


if __name__ == "__main__":
    unittest.main()

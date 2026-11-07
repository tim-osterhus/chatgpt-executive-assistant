"""Offline runtime installer tests: temporary roots, recorded commands, no network or real tools."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_runtime", ROOT / "scripts" / "install_runtime.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
PRIVATE = (".state", ".venv", ".plugin-venv", "bin", "runtime/sdk/node_modules", "runtime/fixtures/disclosure.wav",
           "generated", installer.MARKER)


class Recorder:
    """Stands in for uv, npm, say and afconvert, creating only what each would create."""
    def __init__(self, target):
        self.target, self.commands = target, []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        t = self.target
        if command[:2] == ["uv", "venv"]:
            python = Path(command[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("")
        elif command[:2] == ["npm", "install"]:
            codex = t / ".state/tools/node_modules/.bin/codex"
            codex.parent.mkdir(parents=True)
            codex.write_text("")
        elif command[:2] == ["npm", "ci"]:
            (t / "runtime/sdk/node_modules/twilio").mkdir(parents=True, exist_ok=True)
        elif command[0] == "/usr/bin/afconvert":
            Path(command[-1]).write_bytes(b"RIFF")
        return subprocess.CompletedProcess(command, 0, "v23.11.0\n", "")


REAL_SDK = installer.load_sdk(ROOT)


def readiness(ready=True):
    # Version probing is faked; ledger admission keeps the real check.
    return types.SimpleNamespace(caller_ready=REAL_SDK.caller_ready, sdk_readiness=lambda root, chrome: {
        "ready": ready, "chrome_executable": chrome, "node_version": "23.11.0"})


class RuntimeInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="calls install ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.target = installer.resolve_target(str(self.base / "Application Support" / "Executive Assistant Calls"))
        for value in (patch.object(installer.shutil, "which", return_value="/fake/bin/node"),
                      patch.object(installer, "load_sdk", return_value=readiness())):
            value.start()
            self.addCleanup(value.stop)

    def install(self, transport="sdk", local_mcp=False, chrome=None):
        recorder = Recorder(self.target)
        result = installer.install(self.target, transport, local_mcp, chrome, run=recorder)
        return result, recorder.commands

    def managed(self):
        files = {str(path.relative_to(self.target)) for path in self.target.rglob("*") if path.is_file()}
        return {name for name in files if not any(name == item or name.startswith(item + "/") for item in PRIVATE)}

    def test_plan_changes_nothing(self):
        result = installer.plan(self.target, "sdk", False)
        self.assertFalse(result["runtime_exists"] or result["places_call"] or result["starts_service"])
        self.assertFalse(self.target.exists())
        self.assertLess(result["source_bytes"], 512 * 1024)

    def test_fresh_install_copies_only_the_allowlist_outside_the_checkout(self):
        result, commands = self.install(chrome="/Applications/Example Chrome.app/Contents/MacOS/Google Chrome")
        self.assertEqual(self.managed(), set(installer.RUNTIME_FILES))
        self.assertFalse(any((self.target / name).exists() for name in ("tests", "README.md", "setup.sh", "examples")))
        for name in installer.RUNTIME_FILES:
            self.assertEqual((self.target / name).read_bytes(), (ROOT / name).read_bytes())
        self.assertTrue(os.access(self.target / "run", os.X_OK))
        self.assertEqual((self.target / "runtime/call_runner.py").stat().st_mode & 0o777, 0o600)
        marker = json.loads((self.target / installer.MARKER).read_text())
        self.assertEqual((marker["namespace"], marker["status"]), ("executive-assistant-calls", "installed"))
        config = json.loads((self.target / ".state/config.json").read_text())
        self.assertEqual(config["phone_transport"], "sdk")
        self.assertEqual(config["chrome_executable"], "/Applications/Example Chrome.app/Contents/MacOS/Google Chrome")
        self.assertEqual((config["from_number"], config["to_number"]), ("", ""))
        skill = (self.target / installer.GENERATED_SKILL).read_text()
        self.assertNotIn("CALLING_RUNNER", skill)
        self.assertIn("'" + str(self.target / "run") + "' call", skill)
        self.assertTrue(result["installed"] and not result["places_call"] and not result["starts_service"])
        flat = [" ".join(command) for command in commands]
        self.assertIn("npm ci --prefix " + str(self.target / "runtime/sdk") + " --ignore-scripts --no-audit --no-fund", flat)
        self.assertTrue(any(command.endswith("install_tools.py --only cloudflared") for command in flat))
        self.assertTrue(any("@openai/codex@0.160.0" in command for command in flat))
        self.assertFalse(any("install-mcp-deps" in command or "launchctl" in command or "security" in command
                             or "playwright" in command for command in flat))
        for command in commands:
            for part in command:
                if part.startswith("/") and not part.startswith(("/usr/bin/", "/fake/")):
                    self.assertTrue(part.startswith(str(self.target)), part)
        self.assertTrue(json.loads((self.target / ".state/sdk-transport/readiness.json").read_text())["ready"])

    def test_rerun_preserves_private_state_and_refreshes_only_managed_source(self):
        self.install()
        private = {".state/config.json": b'{"to_number": "kept"}', ".state/runs/r1/request.json": b"{}",
                   ".venv/lib/marker": b"env", "runtime/sdk/node_modules/twilio/package.json": b"{}",
                   "runtime/fixtures/disclosure.wav": b"RIFF-kept", ".plugin-venv/bin/python": b""}
        for name, data in private.items():
            (self.target / name).parent.mkdir(parents=True, exist_ok=True)
            (self.target / name).write_bytes(data)
        (self.target / "runtime/call_runner.py").write_text("locally modified")
        marker = json.loads((self.target / installer.MARKER).read_text())
        marker["files"]["runtime/retired_module.py"] = "0" * 64
        (self.target / "runtime/retired_module.py").write_text("old")
        (self.target / installer.MARKER).write_text(json.dumps(marker))
        result, commands = self.install(transport="media_streams")
        self.assertTrue(result["updated"])
        for name, data in private.items():
            self.assertEqual((self.target / name).read_bytes(), data, name)
        self.assertEqual((self.target / "runtime/call_runner.py").read_bytes(), (ROOT / "runtime/call_runner.py").read_bytes())
        self.assertFalse((self.target / "runtime/retired_module.py").exists())
        self.assertFalse(any(command[:2] in (["uv", "venv"], ["npm", "install"]) for command in commands))
        self.assertFalse(any(command[0] == "/usr/bin/say" or command[:2] == ["npm", "ci"] for command in commands))
        self.assertTrue(any(command[-1].endswith("install_tools.py") for command in commands))  # Both legacy tools.
        self.assertEqual(result["notes"], [])  # The kept config has no transport field: legacy media_streams.
        (self.target / ".state/config.json").write_text('{"phone_transport": "sdk"}')
        self.assertIn("keeps phone_transport=sdk", " ".join(self.install(transport="media_streams")[0]["notes"]))

    def test_local_mcp_is_a_separate_opt_in_without_tunnel_client(self):
        _, commands = self.install(local_mcp=True)
        selected = [command for command in commands if "private_plugin.py" in " ".join(command)]
        self.assertEqual([command[-1] for command in selected], ["install-mcp-deps"])

    def test_unrelated_or_foreign_directories_are_never_clobbered(self):
        self.target.mkdir(parents=True)
        (self.target / "notes.txt").write_text("someone else's")
        with self.assertRaisesRegex(installer.InstallError, "not empty"):
            self.install()
        self.assertEqual(os.listdir(self.target), ["notes.txt"])
        (self.target / installer.MARKER).write_text(json.dumps({"namespace": "another-tool", "files": {}}))
        with self.assertRaisesRegex(installer.InstallError, "another installation"):
            self.install()
        self.assertEqual(sorted(os.listdir(self.target)), sorted(["notes.txt", installer.MARKER]))

    def test_runtime_inside_checkout_or_symlinked_is_refused(self):
        for value in (str(ROOT / "runtime-copy"), str(ROOT.parents[1]), str(ROOT.parents[1].parent)):
            with self.assertRaisesRegex(installer.InstallError, "outside this checkout"):
                installer.resolve_target(value)
        link = self.base / "link"
        link.symlink_to(self.base)
        with self.assertRaisesRegex(installer.InstallError, "symlink"):
            installer.resolve_target(str(link))
        with self.assertRaisesRegex(installer.InstallError, "absolute"):
            installer.resolve_target("relative/runtime")

    def test_running_or_unresolved_call_blocks_update(self):
        self.install()
        lock_path = self.target / ".state/runs/.call.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(installer.InstallError, "call is running"):
                self.install()
        active = self.target / ".state/sdk-transport/active.json"
        active.write_text("{}")
        with self.assertRaisesRegex(installer.InstallError, "reconciliation"):
            self.install()

    def locks(self):
        return (self.target / ".state/plugin-requests/.admission.lock", self.target / ".state/runs/.call.lock")

    def assert_locks_free(self):
        for path in filter(Path.exists, self.locks()):
            with path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Raises if the installer leaked a hold.

    def stale_source(self):
        """Mark one managed file so a refused update is visible as an unchanged file."""
        (self.target / "runtime/call_runner.py").write_text("installed earlier")
        return lambda: (self.target / "runtime/call_runner.py").read_text() == "installed earlier"

    def test_held_mcp_admission_defers_update_before_any_copy(self):
        self.install()
        unchanged = self.stale_source()
        admission = self.locks()[0]
        admission.parent.mkdir(parents=True)  # As calling_mcp creates it for a submission.
        with admission.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(installer.InstallError, "being submitted"):
                self.install()
        self.assertTrue(unchanged())
        self.assertFalse(self.locks()[1].exists())  # Refused before the call lock was taken.
        self.assert_locks_free()

    def test_update_creates_and_holds_both_locks_without_an_earlier_call(self):
        self.install()  # A fresh runtime: no call has ever created .call.lock.
        for path in self.locks():
            path.unlink(missing_ok=True)
        held = []
        class Probe(Recorder):
            def __call__(probe, command, **kwargs):
                for path in self.locks():
                    with path.open("a") as lock:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            held.append(False)
                        except BlockingIOError:
                            held.append(True)
                return Recorder.__call__(probe, command, **kwargs)
        installer.install(self.target, "sdk", False, run=Probe(self.target))
        self.assertTrue(held and all(held))  # Every dependency command ran under both locks.
        self.assert_locks_free()
        self.assertEqual(json.loads((self.target / ".state/config.json").read_text())["phone_transport"], "sdk")

    def test_pending_mcp_submission_without_receipt_refuses_update(self):
        self.install()
        unchanged = self.stale_source()
        receipt = self.target / ".state/runs/r0/receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text('{"kept": true}')
        pending = self.target / ".state/plugin-requests/uncertain-call"
        pending.mkdir(parents=True)
        (pending / "request.json").write_text(json.dumps({"request_id": "uncertain-call", "focus": "f", "briefing": "b"}))
        # No lock is held and no runner started yet; the immutable ledger alone blocks the update.
        with self.assertRaisesRegex(installer.InstallError, "no terminal receipt"):
            self.install()
        self.assertTrue(unchanged())
        self.assertEqual(receipt.read_text(), '{"kept": true}')
        self.assertTrue((pending / "request.json").is_file())
        self.assert_locks_free()
        resolved = types.SimpleNamespace(caller_ready=lambda directory: None,
                                         sdk_readiness=readiness().sdk_readiness)
        with patch.object(installer, "load_sdk", return_value=resolved):
            self.assertTrue(self.install()[0]["updated"])  # Once the installed MCP reports it terminal.
        self.assertFalse(unchanged())

    def test_missing_chrome_is_reported_after_install_without_downloading_a_browser(self):
        with patch.object(installer, "load_sdk", return_value=readiness(False)):
            with self.assertRaisesRegex(installer.InstallError, "Install Google Chrome or pass --chrome"):
                self.install()

    def test_old_node_is_rejected_before_sdk_packages(self):
        recorder = Recorder(self.target)
        def old(command, **kwargs):
            result = recorder(command, **kwargs)
            return subprocess.CompletedProcess(command, 0, "v18.20.0\n", "") if command[-1] == "--version" else result
        with self.assertRaisesRegex(installer.InstallError, "Node.js 20 or later"):
            installer.install(self.target, "sdk", False, run=old)
        self.assertFalse(any(command[:2] == ["npm", "ci"] for command in recorder.commands))

    def test_cli_reports_refusal_without_traceback(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(installer.main(["--runtime-dir", str(ROOT / "inside"), "--plan"]), 1)
        self.assertIn("outside this checkout", json.loads(errors.getvalue())["error"])


class SourceAllowlistTests(unittest.TestCase):
    def test_allowlist_is_small_regular_source_without_tests_docs_or_dependencies(self):
        total = 0
        for name in installer.RUNTIME_FILES:
            path = ROOT / name
            self.assertTrue(path.is_file() and not path.is_symlink(), name)
            self.assertFalse(name.startswith("tests/") or "/tests/" in name or name.endswith(".wav"), name)
            self.assertTrue(not name.endswith(".md") or name.endswith("/SKILL.md"), name)
            self.assertFalse(any(part in {"node_modules", ".state", ".venv", "bin"} for part in Path(name).parts))
            total += path.stat().st_size
        self.assertLess(total, 512 * 1024)
        runtime_modules = {path.relative_to(ROOT).as_posix() for path in (ROOT / "runtime").glob("*.py")}
        self.assertLessEqual(runtime_modules, set(installer.RUNTIME_FILES))

    def run_wrapper(self, home, python_present, *options):
        """Run setup.sh with fake uv/npm/Python on a temporary HOME; return the result and recorded events."""
        tools = Path(home) / ".local" / "bin"
        tools.mkdir(parents=True)
        log = Path(home) / "events"
        fake_python = tools / "python 3.12"
        fake_python.write_text('#!/bin/sh\necho forwarded >> "$CALLS_TEST_LOG"\nprintf "%s\\n" "$@" >> "$CALLS_TEST_LOG"\n')
        (tools / "uv").write_text(
            '#!/bin/sh\n'
            'if [ "$1 $2 $3" = "python find 3.12" ]; then [ -n "$CALLS_TEST_PYTHON" ] && echo "$CALLS_TEST_PYTHON"; exit 0; fi\n'
            'echo "uv $*" >> "$CALLS_TEST_LOG"\nexit 0\n')
        (tools / "npm").write_text("#!/bin/sh\nexit 9\n")
        for tool in tools.iterdir():
            tool.chmod(0o700)
        environment = {"HOME": home, "PATH": "/usr/bin:/bin", "CALLS_TEST_LOG": str(log),
                       "CALLS_TEST_PYTHON": str(fake_python) if python_present else ""}
        result = subprocess.run([str(ROOT / "setup.sh"), *options], env=environment,
                                capture_output=True, text=True, timeout=10)
        return result, log.read_text().splitlines() if log.exists() else []

    @unittest.skipUnless(os.uname().sysname == "Darwin" and os.uname().machine == "arm64", "Apple Silicon wrapper")
    def test_setup_wrapper_uses_a_located_python_and_passes_options(self):
        with tempfile.TemporaryDirectory(prefix="setup home ") as home:
            options = ("--plan", "--runtime-dir", home + "/Calls Runtime")
            result, events = self.run_wrapper(home, True, *options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(events, ["forwarded", "-I", "-B", str(ROOT / "scripts/install_runtime.py"), *options])
            self.assertFalse((Path(home) / "Calls Runtime").exists())

    @unittest.skipUnless(os.uname().sysname == "Darwin" and os.uname().machine == "arm64", "Apple Silicon wrapper")
    def test_setup_preview_never_installs_missing_python(self):
        with tempfile.TemporaryDirectory(prefix="setup home ") as home:
            result, events = self.run_wrapper(home, False, "--runtime-dir", home + "/Calls Runtime", "--plan")
            self.assertEqual(result.returncode, 1)
            self.assertIn("Preview needs Python 3.12", result.stderr)
            self.assertEqual(events, [])  # Neither `uv python install` nor the installer ran.
            self.assertFalse((Path(home) / "Calls Runtime").exists())
            # Without --plan, the same missing Python is bootstrapped through uv as before.
            result, events = self.run_wrapper(str(Path(home) / "install"), False, "--runtime-dir", home + "/Calls Runtime")
            self.assertIn("uv python install 3.12", events)

    def test_watcher_local_mcp_path_has_no_cloud_tunnel_dependency(self):
        for name in ("run-plugin", "runtime/calling_mcp.py", "watcher/integrations.py", "watcher/install.py"):
            text = (ROOT / name).read_text()
            for cloud in ("tunnel-client", "plugin-tools", "CONTROL_PLANE_API_KEY =", "runtimes connect"):
                self.assertNotIn(cloud, text, name)

    def test_core_checkout_runner_is_inert_without_setup(self):
        with tempfile.TemporaryDirectory(prefix="core only ") as temporary:
            copy = Path(temporary) / "run"
            copy.write_bytes((ROOT / "run").read_bytes())
            copy.chmod(0o700)
            result = subprocess.run([str(copy), "validate"], input="{}", capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("setup.sh", result.stderr)
            self.assertEqual(os.listdir(temporary), ["run"])


if __name__ == "__main__":
    unittest.main()

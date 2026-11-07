"""Installer tests run with a temporary HOME and a fake macOS platform.

launchctl, plutil, security, and getpass are mocked, so these tests change only temporary files.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

WATCHER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WATCHER_DIR))
import install  # noqa: E402

LABEL = "local.executive-assistant-calls.watcher"
PREFIX = "example-assistant-calls"
SECRET = "fake-EXAMPLE-key'with$quote"
WATCHER_FILES = ("runtime.py", "integrations.py", "watch_call.py")
SKILL_FILES = ("SKILL.md", "agents/openai.yaml")
REQUIRED = (
    ".executive-assistant-calls-install.json",
    "run-plugin",
    ".plugin-venv/bin/python",
    ".state/config.json",
    *("watcher/" + name for name in WATCHER_FILES),
    *("watcher/skill/" + name for name in SKILL_FILES),
)


def succeed(argv, **kwargs):
    return subprocess.CompletedProcess(argv, 0, "", "")


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)


def make_runtime(runtime):
    """Build a minimal installed calls runtime that carries the real watcher sources."""
    write(runtime / ".executive-assistant-calls-install.json", '{"schema": 1}\n')
    write(runtime / "run-plugin", "#!/bin/sh\nexit 0\n")
    write(runtime / ".plugin-venv/bin/python", "#!/bin/sh\nexit 0\n")
    write(runtime / ".state/config.json", json.dumps({"keychain_service_prefix": PREFIX}))
    for name in WATCHER_FILES:
        write(runtime / "watcher" / name, (WATCHER_DIR / name).read_bytes())
    for name in SKILL_FILES:
        write(runtime / "watcher" / "skill" / name, (WATCHER_DIR / "skill" / name).read_bytes())


def snapshot(root):
    """Map every path under root to its kind and content, without following symbolic links."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                found[path] = ("link", os.readlink(path))
            elif os.path.isdir(path):
                found[path] = ("dir", stat.S_IMODE(os.stat(path).st_mode))
            else:
                found[path] = ("file", Path(path).read_bytes())
    return found


class InstallerCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.home = self.temp / "Fake Home"
        self.runtime = self.home / "Library" / "Application Support" / "Executive Assistant Calls"
        make_runtime(self.runtime)
        self.bin_dir = self.home / ".local" / "bin"
        self.skill_dir = self.home / ".codex" / "skills"
        self.launcher = self.bin_dir / "assistant-watch-call"
        self.skill = self.skill_dir / "assistant-call-when-done"
        self.service = self.home / "Library" / "LaunchAgents" / (LABEL + ".plist")
        self.state = self.runtime / ".state" / "watcher"
        self.uid = os.getuid()
        self.start_patch(patch.dict(os.environ, {"HOME": str(self.home)}))
        self.start_patch(patch.object(sys, "platform", "darwin"))
        self.run_mock = self.start_patch(patch.object(install, "run", side_effect=succeed))
        # An unexpected key prompt fails loudly instead of waiting for input.
        self.getpass_mock = self.start_patch(
            patch.object(install.getpass, "getpass", side_effect=AssertionError("unexpected key prompt")))

    def start_patch(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def invoke(self, *argv):
        """Run main() with temporary install directories; return its result and printed text."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                result = install.main(["--bin-dir", str(self.bin_dir), "--skill-dir", str(self.skill_dir), *argv],
                                      runtime=self.runtime)
            except SystemExit as exc:
                result = exc.code
        return result, output.getvalue()

    def refusal(self, *argv):
        result, _ = self.invoke(*argv)
        self.assertIsInstance(result, str)
        self.assertTrue(result.endswith("Nothing changed."), result)
        return result

    def argvs(self):
        return [args[0] for args, _ in self.run_mock.call_args_list]

    def expected_new_paths(self, service_enabled=True):
        paths = [
            self.home / ".local", self.bin_dir, self.launcher,
            self.home / ".codex", self.skill_dir, self.skill,
            self.skill / "SKILL.md", self.skill / "agents", self.skill / "agents" / "openai.yaml",
            self.skill / ".executive-assistant-calls-watcher",
            self.state, self.state / "logs", self.state / "config.json", self.state / "installed-source.json",
        ]
        if service_enabled:
            paths += [self.home / "Library" / "LaunchAgents", self.service]
        return {str(path) for path in paths}


class PlanTests(InstallerCase):
    def test_plan_reports_settings_and_writes_nothing(self):
        before = snapshot(self.temp)
        result, text = self.invoke("plan")
        self.assertEqual(result, 0)
        self.assertEqual(snapshot(self.temp), before)
        self.run_mock.assert_not_called()
        self.assertEqual(json.loads(text), {
            "runtime": str(self.runtime),
            "state": str(self.state),
            "command": str(self.launcher),
            "skill": str(self.skill),
            "service": True,
            "service_path": str(self.service),
            "label": LABEL,
            "calling_root": str(self.runtime),
            "jev_keychain_service": PREFIX + ".jev-api",
            "jev_keychain_account": "completion-watcher",
            "service_interval_seconds": 60,
            "checkpoint_hours": 24,
            "arms_a_watch": False,
        })

    def test_default_locations_are_under_home(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = install.main(["plan", "--no-service"], runtime=self.runtime)
        plan = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(plan["command"], str(self.home / ".local" / "bin" / "assistant-watch-call"))
        self.assertEqual(plan["skill"], str(self.home / ".codex" / "skills" / "assistant-call-when-done"))
        self.assertIs(plan["service"], False)
        self.run_mock.assert_not_called()

    def test_relative_directory_options_are_refused(self):
        before = snapshot(self.temp)
        for argv in (("--bin-dir", "relative/bin"), ("--skill-dir", "relative/skills")):
            with self.subTest(argv=argv):
                self.assertIn("absolute", self.refusal("plan", *argv))
        self.assertEqual(snapshot(self.temp), before)

    def test_each_missing_prerequisite_refuses_before_any_change(self):
        for name in REQUIRED:
            with self.subTest(missing=name):
                path = self.runtime / name
                original = path.read_bytes()
                path.unlink()
                before = snapshot(self.temp)
                message = self.refusal("install")
                self.assertIn(name, message)
                self.assertIn("--local-mcp", message)
                self.assertEqual(snapshot(self.temp), before)
                path.write_bytes(original)
        self.run_mock.assert_not_called()

    def test_non_macos_refuses_every_command(self):
        before = snapshot(self.temp)
        with patch.object(sys, "platform", "linux"):
            for command in ("plan", "install", "store-jev-key", "uninstall"):
                with self.subTest(command=command):
                    self.assertIn("macOS", self.refusal(command))
        self.assertEqual(snapshot(self.temp), before)
        self.run_mock.assert_not_called()
        self.getpass_mock.assert_not_called()

    def test_keychain_prefix_defaults_and_rejects_invalid_values(self):
        config = self.runtime / ".state" / "config.json"
        for text, expected in (("{}", "executive-assistant-calls"),
                               ('{"keychain_service_prefix": "custom-calls"}', "custom-calls")):
            with self.subTest(config=text):
                config.write_text(text)
                self.assertEqual(install.keychain_prefix(self.runtime), expected)
        for text in ('{"keychain_service_prefix": ""}', '{"keychain_service_prefix": 7}', "[]", "{broken"):
            with self.subTest(config=text):
                config.write_text(text)
                with self.assertRaises(SystemExit) as caught:
                    install.keychain_prefix(self.runtime)
                self.assertTrue(str(caught.exception.code).endswith("Nothing changed."))


class InstallTests(InstallerCase):
    def test_install_creates_only_expected_paths(self):
        before = snapshot(self.temp)
        result, _ = self.invoke("install")
        self.assertEqual(result, 0)
        created = {path for path in snapshot(self.temp) if path not in before}
        self.assertEqual(created, self.expected_new_paths())

    def test_launcher_is_private_and_quotes_paths_with_spaces(self):
        self.invoke("install")
        self.assertEqual(stat.S_IMODE(self.launcher.stat().st_mode), 0o700)
        for directory in (self.state, self.state / "logs"):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        lines = self.launcher.read_text().splitlines()
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertIn("# Executive Assistant Calls watcher managed launcher", lines)
        self.assertIn("umask 077", lines)
        export = next(line for line in lines if line.startswith("export "))
        self.assertEqual(shlex.split(export[len("export "):]), ["WATCH_CALL_STATE_DIR=" + str(self.state)])
        exec_line = next(line for line in lines if line.startswith("exec "))
        self.assertEqual(shlex.split(exec_line[len("exec "):]), [
            str(self.runtime / ".plugin-venv" / "bin" / "python"), "-I", "-B",
            str(self.runtime / "watcher" / "watch_call.py"), "$@"])

    def test_skill_placeholder_is_replaced_with_the_quoted_command(self):
        self.invoke("install")
        quoted = shlex.quote(str(self.launcher)).encode()
        for name in SKILL_FILES:
            with self.subTest(name=name):
                source = (self.runtime / "watcher" / "skill" / name).read_bytes()
                installed = (self.skill / name).read_bytes()
                self.assertEqual(installed, source.replace(b"WATCH_CALL_COMMAND", quoted))
                self.assertNotIn(b"WATCH_CALL_COMMAND", installed)
        self.assertIn(b"WATCH_CALL_COMMAND", (self.runtime / "watcher" / "skill" / "SKILL.md").read_bytes())
        self.assertEqual((self.skill / ".executive-assistant-calls-watcher").read_bytes(),
                         str(self.runtime).encode())

    def test_plist_is_linted_before_bootstrap(self):
        result, _ = self.invoke("install")
        self.assertEqual(result, 0)
        self.assertEqual(plistlib.loads(self.service.read_bytes()), {
            "Label": LABEL,
            "ProgramArguments": [str(self.launcher), "tick"],
            "RunAtLoad": True,
            "StartInterval": 60,
            "Umask": 0o77,
            "ProcessType": "Background",
            "EnvironmentVariables": {"HOME": str(self.home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                                     "EXECUTIVE_ASSISTANT_CALLS_RUNTIME": str(self.runtime)},
            "StandardOutPath": str(self.state / "logs" / "service.stdout.log"),
            "StandardErrorPath": str(self.state / "logs" / "service.stderr.log"),
        })
        bootout = ["/bin/launchctl", "bootout", f"gui/{self.uid}/{LABEL}"]
        lint = ["/usr/bin/plutil", "-lint", str(self.service)]
        bootstrap = ["/bin/launchctl", "bootstrap", f"gui/{self.uid}", str(self.service)]
        # A first install has no plist of its own, so it unloads nothing.
        self.assertEqual(self.argvs(), [lint, bootstrap])
        self.assertTrue(all(call[1]["check"] is True for call in self.run_mock.call_args_list))
        self.run_mock.reset_mock()
        self.assertEqual(self.invoke("install")[0], 0)
        self.assertEqual(self.argvs(), [bootout, lint, bootstrap])
        self.assertIs(self.run_mock.call_args_list[0][1]["check"], False)

    def test_config_manifest_and_output_record_no_armed_watch(self):
        result, text = self.invoke("install")
        self.assertEqual(result, 0)
        self.assertEqual(json.loads((self.state / "config.json").read_text()), {
            "calling_root": str(self.runtime),
            "jev_keychain_service": PREFIX + ".jev-api",
            "jev_keychain_account": "completion-watcher",
            "jev_model": "jev-latest",
        })
        manifest = json.loads((self.state / "installed-source.json").read_text())
        self.assertEqual(manifest, {
            name: hashlib.sha256((self.runtime / "watcher" / name).read_bytes()).hexdigest()
            for name in WATCHER_FILES
        })
        printed = json.loads(text)
        self.assertIs(printed["installed"], True)
        self.assertIs(printed["arms_a_watch"], False)
        self.assertFalse((self.state / "watches").exists())

    def test_umask_is_restored_after_install(self):
        original = os.umask(0o022)
        self.addCleanup(os.umask, original)
        self.invoke("install")
        self.assertEqual(os.umask(0o022), 0o022)

    def test_reinstall_over_its_own_files_succeeds(self):
        self.invoke("install")
        config = (self.state / "config.json").read_bytes()
        self.run_mock.reset_mock()
        result, _ = self.invoke("install")
        self.assertEqual(result, 0)
        self.assertEqual((self.state / "config.json").read_bytes(), config)
        self.assertEqual(len(self.argvs()), 3)

    def test_failed_lint_stops_before_bootstrap(self):
        def fail_lint(argv, **kwargs):
            if argv[0] == "/usr/bin/plutil":
                raise subprocess.CalledProcessError(1, argv)
            return succeed(argv, **kwargs)

        self.run_mock.side_effect = fail_lint
        result, _ = self.invoke("install")
        self.assertIn("LaunchAgent validation or bootstrap failed", result)
        self.assertFalse(any("bootstrap" in argv for argv in self.argvs()))


class ServiceOptionTests(InstallerCase):
    def test_no_service_writes_command_and_skill_without_launchctl(self):
        before = snapshot(self.temp)
        result, text = self.invoke("install", "--no-service")
        self.assertEqual(result, 0)
        self.run_mock.assert_not_called()
        created = {path for path in snapshot(self.temp) if path not in before}
        self.assertEqual(created, self.expected_new_paths(service_enabled=False))
        self.assertIs(json.loads(text)["service"], False)

    def test_no_service_never_touches_an_existing_launch_agent(self):
        for label in (LABEL, "com.example.other"):
            with self.subTest(label=label):
                write(self.service, plistlib.dumps({"Label": label}))
                before = self.service.read_bytes()
                result, _ = self.invoke("install", "--no-service")
                self.assertEqual(result, 0)
                self.assertEqual(self.service.read_bytes(), before)
                self.run_mock.assert_not_called()


class OwnershipTests(InstallerCase):
    def expect_refusal(self, fragment):
        before = snapshot(self.temp)
        message = self.refusal("install")
        self.assertIn(fragment, message)
        self.assertEqual(snapshot(self.temp), before)
        self.run_mock.assert_not_called()

    def test_unrelated_command_is_refused(self):
        write(self.launcher, "#!/bin/sh\necho other tool\n")
        self.expect_refusal("unrelated assistant-watch-call command")

    def test_unowned_skill_is_refused(self):
        write(self.skill / "SKILL.md", "someone else's skill\n")
        self.expect_refusal("unrelated assistant-call-when-done skill")

    def test_skill_owned_by_another_runtime_is_refused(self):
        write(self.skill / ".executive-assistant-calls-watcher", "/elsewhere/runtime")
        self.expect_refusal("unrelated assistant-call-when-done skill")

    def test_unrelated_launch_agent_is_refused(self):
        write(self.service, plistlib.dumps({"Label": "com.example.other"}))
        self.expect_refusal("unrelated LaunchAgent")

    def test_same_label_from_another_runtime_is_refused(self):
        write(self.service, plistlib.dumps({"Label": "local.executive-assistant-calls.watcher",
                                            "ProgramArguments": ["/elsewhere/bin/assistant-watch-call", "tick"]}))
        self.expect_refusal("unrelated LaunchAgent")

    def test_unparseable_launch_agent_is_refused(self):
        write(self.service, b"not a property list")
        self.expect_refusal("unrelated LaunchAgent")

    def test_config_with_other_values_is_refused(self):
        write(self.state / "config.json", json.dumps({"calling_root": "/elsewhere"}))
        self.expect_refusal("configuration differs")

    def test_unreadable_config_is_refused(self):
        write(self.state / "config.json", "{broken")
        self.expect_refusal("configuration is unreadable")

    def test_symbolic_link_state_directory_is_refused(self):
        target = self.temp / "outside"
        target.mkdir()
        self.state.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, self.state)
        self.expect_refusal("symbolic links")


class CrossRuntimeTests(InstallerCase):
    """Runtime A owns the shared command/LaunchAgent names; runtime B may not take or remove them."""
    def setUp(self):
        super().setUp()
        self.assertEqual(self.invoke("install")[0], 0)  # Runtime A, default skill directory.
        self.other = self.home / "Other Runtime"
        make_runtime(self.other)
        self.other_skills = self.home / "Other Skills"
        self.run_mock.reset_mock()

    def as_other(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                return install.main(["--bin-dir", str(self.bin_dir), "--skill-dir", str(self.other_skills), *argv],
                                    runtime=self.other), output.getvalue()
            except SystemExit as exc:
                return exc.code, output.getvalue()

    def test_other_runtime_install_is_refused_before_any_global_change(self):
        for options in ((), ("--no-service",)):
            before = snapshot(self.temp)
            result, _ = self.as_other("install", *options)
            self.assertIn("unrelated assistant-watch-call command", result)
            self.assertEqual(snapshot(self.temp), before)
            self.run_mock.assert_not_called()

    def test_other_runtime_uninstall_keeps_every_item_of_the_owner(self):
        before = snapshot(self.temp)
        result, text = self.as_other("uninstall")
        self.assertEqual(result, 0)
        report = json.loads(text)
        self.assertEqual(report["removed"], [])
        self.assertEqual(set(report["kept"]), {str(self.service), str(self.launcher)})
        self.assertEqual(snapshot(self.temp), before)
        self.run_mock.assert_not_called()  # Runtime A's service is never unloaded.

    def test_generic_marker_without_the_runtime_binding_is_not_ownership(self):
        write(self.launcher, "#!/bin/sh\n# Executive Assistant Calls watcher managed launcher\nexit 0\n")
        result, _ = self.invoke("install")
        self.assertIn("unrelated assistant-watch-call command", result)
        self.assertIn("unrelated assistant-watch-call command", self.as_other("install")[0])

    def test_owner_uninstall_still_removes_its_items(self):
        result, text = self.invoke("uninstall")
        self.assertEqual(result, 0)
        self.assertFalse(self.launcher.exists() or self.service.exists() or self.skill.exists())
        self.assertEqual(self.argvs(), [["/bin/launchctl", "bootout", f"gui/{self.uid}/{LABEL}"]])


class StoreKeyTests(InstallerCase):
    def enter_key(self, value):
        self.getpass_mock.side_effect = None
        self.getpass_mock.return_value = value

    def keychain(self, readback=SECRET, stored_code=0):
        def fake(argv, **kwargs):
            if argv[:2] == ["/usr/bin/security", "-i"]:
                return subprocess.CompletedProcess(argv, stored_code, "", "")
            return subprocess.CompletedProcess(argv, 0, readback + "\n", "")

        self.run_mock.side_effect = fake

    def test_key_travels_on_stdin_and_is_never_printed(self):
        self.enter_key(SECRET)
        self.keychain()
        before = snapshot(self.temp)
        result, text = self.invoke("store-jev-key")
        self.assertEqual(result, 0)
        self.getpass_mock.assert_called_once()
        self.assertEqual(snapshot(self.temp), before)
        self.assertNotIn(SECRET, text)
        self.assertEqual(json.loads(text), {
            "stored": True, "keychain_service": PREFIX + ".jev-api", "keychain_account": "completion-watcher"})
        (stored_args, stored_kwargs), (readback_args, _) = self.run_mock.call_args_list
        self.assertEqual(stored_args[0], ["/usr/bin/security", "-i"])
        self.assertIs(stored_kwargs["capture_output"], True)
        self.assertEqual(shlex.split(stored_kwargs["input"]), [
            "add-generic-password", "-U", "-s", PREFIX + ".jev-api", "-a", "completion-watcher", "-w", SECRET])
        self.assertEqual(readback_args[0], [
            "/usr/bin/security", "find-generic-password", "-s", PREFIX + ".jev-api",
            "-a", "completion-watcher", "-w"])
        for argv in self.argvs():
            self.assertFalse(any(SECRET in part for part in argv))

    def test_failed_write_or_readback_aborts_without_printing_the_key(self):
        for label, kwargs in (("readback differs", {"readback": "a-different-value"}),
                              ("security failed", {"stored_code": 1})):
            with self.subTest(label):
                self.enter_key(SECRET)
                self.keychain(**kwargs)
                result, text = self.invoke("store-jev-key")
                self.assertIn("did not match", result)
                self.assertNotIn(SECRET, result + text)

    def test_keychain_tool_failure_aborts_without_printing_the_key(self):
        self.enter_key(SECRET)
        self.run_mock.side_effect = OSError("security unavailable")
        result, text = self.invoke("store-jev-key")
        self.assertIn("Keychain access failed", result)
        self.assertNotIn(SECRET, result + text)

    def test_unsafe_key_values_are_refused_before_keychain_use(self):
        for value in ("", "   ", " padded value ", "line\nbreak", "carriage\rreturn", "x" * 8193):
            with self.subTest(length=len(value)):
                self.enter_key(value)
                message = self.refusal("store-jev-key")
                self.assertIn("The key was empty", message)
                if value:
                    self.assertNotIn(value, message)
        self.run_mock.assert_not_called()

    def test_store_key_requires_the_installed_runtime(self):
        self.enter_key(SECRET)
        (self.runtime / ".executive-assistant-calls-install.json").unlink()
        message = self.refusal("store-jev-key")
        self.assertIn("--local-mcp", message)
        self.getpass_mock.assert_not_called()
        self.run_mock.assert_not_called()


class UninstallTests(InstallerCase):
    def setUp(self):
        super().setUp()
        self.invoke("install")
        self.run_mock.reset_mock()

    def test_removes_only_owned_items_and_keeps_state(self):
        write(self.state / "watches" / "example.json", "{}")
        write(self.bin_dir / "other-tool", "keep")
        write(self.skill / "notes.txt", "keep")
        runtime_before = snapshot(self.runtime)
        result, text = self.invoke("uninstall")
        self.assertEqual(result, 0)
        for path in (self.launcher, self.service, self.skill / "SKILL.md",
                     self.skill / "agents" / "openai.yaml", self.skill / "agents",
                     self.skill / ".executive-assistant-calls-watcher"):
            self.assertFalse(path.exists(), str(path))
        self.assertTrue((self.skill / "notes.txt").is_file())
        self.assertEqual((self.bin_dir / "other-tool").read_text(), "keep")
        for path in (self.state / "config.json", self.state / "installed-source.json",
                     self.state / "logs", self.state / "watches" / "example.json"):
            self.assertTrue(path.exists(), str(path))
        self.assertEqual(snapshot(self.runtime), runtime_before)
        self.assertEqual(self.argvs(), [["/bin/launchctl", "bootout", f"gui/{self.uid}/{LABEL}"]])
        printed = json.loads(text)
        self.assertIn(str(self.launcher), printed["removed"])
        self.assertIn(str(self.service), printed["removed"])
        self.assertEqual(printed["keychain"], "preserved")

    def test_keeps_items_it_did_not_create(self):
        write(self.launcher, "#!/bin/sh\necho other tool\n")
        write(self.service, plistlib.dumps({"Label": "com.example.other"}))
        write(self.skill / ".executive-assistant-calls-watcher", "/elsewhere")
        result, text = self.invoke("uninstall")
        self.assertEqual(result, 0)
        self.assertEqual(self.launcher.read_text(), "#!/bin/sh\necho other tool\n")
        self.assertTrue(self.service.is_file())
        self.assertTrue((self.skill / "SKILL.md").is_file())
        self.assertEqual(self.argvs(), [])
        printed = json.loads(text)
        self.assertEqual(printed["removed"], [])
        self.assertEqual(sorted(printed["kept"]),
                         sorted([str(self.launcher), str(self.service), str(self.skill)]))

    def test_no_service_keeps_the_launch_agent(self):
        service_before = self.service.read_bytes()
        result, _ = self.invoke("uninstall", "--no-service")
        self.assertEqual(result, 0)
        self.assertEqual(self.service.read_bytes(), service_before)
        self.assertFalse(self.launcher.exists())
        self.run_mock.assert_not_called()

    def test_still_removes_items_after_runtime_files_are_deleted(self):
        # Uninstall skips the runtime preflight on purpose so a partly deleted runtime can still be cleaned up.
        shutil.rmtree(self.runtime / ".plugin-venv")
        result, _ = self.invoke("uninstall")
        self.assertEqual(result, 0)
        self.assertFalse(self.launcher.exists())


if __name__ == "__main__":
    unittest.main()

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = "node_modules/\n.state/\n.venv/\n.plugin-venv/\n__pycache__/\ndisclosure.wav\n"
CLEAN = {
    ".gitignore": GITIGNORE,
    "README.md": "Readme\n",
    "addons/outbound-calls/scripts/tool.py": "print('ok')\n",
    "tools/bin/helper.sh": "echo ok\n",
}
ADDON_CLEAN_BYTES = len("print('ok')\n")
CHUNK = b"x" * 61440
NONZERO_UUID = "-".join(["1" * 8, "2" * 4, "3" * 4, "4" * 4, "5" * 12])
ZERO_UUID = "-".join(["0" * 8, "0" * 4, "0" * 4, "0" * 4, "0" * 12])
MIXED_SID = "AC" + "0123456789abcdef" * 2
REAL_PHONE = "+1" + "3125551234"


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


source = module("check_source_package")


def write_tree(root, files):
    for rel, data in files.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return sorted(files)


class SourcePackageTests(unittest.TestCase):
    def scan(self, files, deny_terms=()):
        with tempfile.TemporaryDirectory() as tmp:
            return source.check(Path(tmp), write_tree(tmp, files), deny_terms)

    def assertFlagged(self, files, text, deny_terms=()):
        errors = self.scan(files, deny_terms)["errors"]
        self.assertTrue(any(text in error for error in errors), errors)

    def assertClean(self, files, deny_terms=()):
        self.assertEqual(self.scan(files, deny_terms)["errors"], [])

    def run_main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return source.main(argv)

    def test_clean_tree_passes(self):
        result = self.scan(CLEAN)
        self.assertEqual(result["errors"], [])
        self.assertEqual(set(result), {"files", "addon_bytes", "addon_budget_bytes", "largest", "errors"})
        self.assertEqual(result["addon_bytes"], ADDON_CLEAN_BYTES)
        self.assertEqual(result["files"], len(CLEAN))

    def test_forbidden_paths_fail(self):
        paths = [
            "node_modules/left-pad/index.js",
            "addons/outbound-calls/.venv/pyvenv.cfg",
            "addons/outbound-calls/.plugin-venv/state.txt",
            "addons/outbound-calls/.state/session.txt",
            "addons/outbound-calls/bin/tool.sh",
            "addons/outbound-calls/runtime/clip.wav",
            "addons/outbound-calls/tmp/archive.zip",
            "addons/outbound-calls/scripts/__pycache__/tool.txt",
            "addons/outbound-calls/tests/.pytest_cache/x.txt",
            "addons/outbound-calls/runs/log.txt",
            "addons/outbound-calls/venv/x.txt",
            "addons/outbound-calls/notes/plugin-requests/a.txt",
            "addons/outbound-calls/runtime/transcript.jsonl",
            "addons/outbound-calls/runtime/client.pem",
            "addons/outbound-calls/tests/.DS_Store",
            "local/notes.md",
            ".codex/config.toml",
            ".env",
            ".env.local",
        ]
        for rel in paths:
            with self.subTest(path=rel):
                self.assertFlagged({**CLEAN, rel: "x\n"}, f"{rel}: forbidden path")

    def test_forbidden_files_are_not_content_scanned(self):
        secret = "sk-" + "a" * 24
        errors = self.scan({**CLEAN, "local/notes.md": secret + "\n"})["errors"]
        self.assertEqual(errors, ["local/notes.md: forbidden path"])

    def test_binary_content_fails(self):
        self.assertFlagged({**CLEAN, "addons/outbound-calls/runtime/data.dat": b"abc\0def"}, "binary content")

    def test_size_limit(self):
        self.assertClean({**CLEAN, "addons/outbound-calls/runtime/exact.txt": b"a" * 65536})
        self.assertFlagged({**CLEAN, "addons/outbound-calls/runtime/big.txt": b"a" * 65537}, "exceeds")

    def test_addon_budget_and_license_exclusion(self):
        inside = {f"addons/outbound-calls/runtime/part{i:02}.txt": CHUNK for i in range(17)}
        self.assertClean({**CLEAN, **inside})
        over = {f"addons/outbound-calls/runtime/part{i:02}.txt": CHUNK for i in range(18)}
        result = self.scan({**CLEAN, **over})
        self.assertEqual(result["addon_bytes"], ADDON_CLEAN_BYTES + 18 * len(CHUNK))
        self.assertTrue(any("add-on budget exceeded" in error for error in result["errors"]), result["errors"])
        licensed = {f"addons/outbound-calls/licenses/part{i:02}.txt": CHUNK for i in range(18)}
        result = self.scan({**CLEAN, **licensed})
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["addon_bytes"], ADDON_CLEAN_BYTES)

    def test_gitignore_tokens_required(self):
        for token in ["node_modules/", ".state/", ".venv/", ".plugin-venv/", "__pycache__/", "disclosure.wav"]:
            with self.subTest(token=token):
                text = GITIGNORE.replace(token, "")
                self.assertFlagged({**CLEAN, ".gitignore": text}, f".gitignore: missing required entry {token}")
        self.assertFlagged({"README.md": "x\n"}, ".gitignore: missing required entry node_modules/")

    def test_phone_numbers(self):
        self.assertFlagged({**CLEAN, "addons/outbound-calls/notes.txt": REAL_PHONE + "\n"}, "unapproved phone number")
        self.assertFlagged({**CLEAN, "addons/outbound-calls/notes.txt": "+1" + "202" + "555" + "0200\n"},
                           "unapproved phone number")
        self.assertClean({**CLEAN, "addons/outbound-calls/notes.txt":
                          "+1" + "202" + "555" + "0111\n" + "+1" + "555" + "867" + "5309\n"})

    def test_provider_sids(self):
        self.assertClean({**CLEAN, "addons/outbound-calls/notes.txt": "CA" + "0" * 32 + "\n"})
        self.assertFlagged({**CLEAN, "addons/outbound-calls/notes.txt": MIXED_SID + "\n"}, "provider SID")

    def test_secrets_fail_without_echoing_values(self):
        cases = [
            ("API key", "sk-" + "a" * 24),
            ("private key", "-----BEGIN " + "RSA " + "PRIVATE KEY-----"),
            ("JWT", "eyJ" + "a" * 10 + "." + "eyJ" + "b" * 10),
            ("GitHub token", "ghp_" + "A" * 20),
            ("Slack token", "xox" + "b-" + "1" * 10),
            ("AWS key", "AKIA" + "A" * 16),
            ("tunnel identity", "tunnel_" + "a1" * 6),
            ("plugin identity", "plugin_asdk_app_" + "0" * 8),
        ]
        for label, value in cases:
            with self.subTest(label=label):
                errors = self.scan({**CLEAN, "addons/outbound-calls/notes.txt": value + "\n"})["errors"]
                self.assertTrue(any(label in error for error in errors), errors)
                self.assertFalse(any(value in error for error in errors), errors)
        for word in ["synthetic", "test"]:
            self.assertClean({**CLEAN, "addons/outbound-calls/notes.txt": "sk-" + word + "a" * 20 + "\n"})

    def test_uuid_rule(self):
        self.assertFlagged({**CLEAN, "addons/outbound-calls/notes.txt": NONZERO_UUID + "\n"}, "UUID")
        self.assertClean({**CLEAN, "addons/outbound-calls/notes.txt": ZERO_UUID + "\n"})

    def test_lockfile_skips_only_sid_and_uuid_rules(self):
        lock = NONZERO_UUID + "\n" + MIXED_SID + "\n"
        self.assertClean({**CLEAN, "package-lock.json": lock})
        self.assertFlagged({**CLEAN, "package-lock.json": REAL_PHONE + "\n"}, "unapproved phone number")

    def test_deny_terms(self):
        term = "zyxqrter"
        files = {**CLEAN, "addons/outbound-calls/notes.txt": "Ping ZYXQRTER today\n"}
        errors = self.scan(files, [term])["errors"]
        self.assertTrue(any("deny term" in error for error in errors), errors)
        self.assertNotIn(term, " ".join(errors).lower())
        self.assertClean({**CLEAN, "addons/outbound-calls/notes.txt": "zyxqrterx\n"}, [term])

    def test_load_terms_skips_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.txt"
            path.write_text("# comment\n\n  zyxqrter  \n", encoding="utf-8")
            self.assertEqual(source.load_terms(path), ["zyxqrter"])

    def test_reason_strings_and_symlinks(self):
        self.assertClean(dict(CLEAN, **{"addons/outbound-calls/runtime/x.py": "raise ValueError('tunnel_registration_timeout')\n"}))
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_tree(tmp, CLEAN)
            (Path(tmp) / "linked.md").symlink_to(Path(tmp) / "README.md")
            errors = source.check(Path(tmp), paths + ["linked.md"])["errors"]
        self.assertEqual(errors, ["linked.md: symlink"])

    def test_missing_tracked_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tree(tmp, {".gitignore": GITIGNORE})
            result = source.check(Path(tmp), ["addons/outbound-calls/.state/gone.txt"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["files"], 0)

    def test_cli_lists_git_files_and_sets_exit_code(self):
        if shutil.which("git") is None:
            self.skipTest("git unavailable")
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as terms_dir:
            write_tree(tmp, CLEAN)
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True, capture_output=True)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True, capture_output=True)
            write_tree(tmp, {"addons/outbound-calls/runtime/clip.wav": "x\n"})
            self.assertEqual(self.run_main(["--root", tmp]), 0)
            self.assertEqual(self.run_main(["--root", tmp, "--include-untracked"]), 1)
            (Path(tmp) / "addons/outbound-calls/runtime/clip.wav").unlink()
            write_tree(tmp, {"addons/outbound-calls/notes.txt": "Ping zyxqrter\n"})
            terms = Path(terms_dir) / "terms.txt"
            terms.write_text("zyxqrter\n", encoding="utf-8")
            argv = ["--root", tmp, "--include-untracked"]
            with mock.patch.dict(os.environ):
                os.environ.pop("CALLING_SOURCE_DENY_TERMS_FILE", None)
                self.assertEqual(self.run_main(argv), 0)
                self.assertEqual(self.run_main(argv + ["--deny-terms-file", str(terms)]), 1)
                os.environ["CALLING_SOURCE_DENY_TERMS_FILE"] = str(terms)
                self.assertEqual(self.run_main(argv), 1)

    def test_live_repo_smoke(self):
        try:
            paths = source.listed_files(source.ROOT)
        except (OSError, subprocess.CalledProcessError) as exc:
            self.skipTest(f"git file listing unavailable: {exc}")
        result = source.check(source.ROOT, paths)
        self.assertIsInstance(result, dict)
        self.assertIsInstance(result["addon_bytes"], int)


if __name__ == "__main__":
    unittest.main()

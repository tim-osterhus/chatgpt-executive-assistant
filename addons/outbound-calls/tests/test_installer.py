"""Offline tests for checksum installation and credential handling."""
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


installer = module("install_tools")
credentials = module("store_twilio_credentials")


class InstallationTests(unittest.TestCase):
    def archive(self, symlink=False):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            member = tarfile.TarInfo("binary")
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "/outside"
                archive.addfile(member)
            else:
                member.size = 7
                archive.addfile(member, io.BytesIO(b"fixture"))
            extra = tarfile.TarInfo("../outside")
            extra.size = 7
            archive.addfile(extra, io.BytesIO(b"outside"))
        return data.getvalue()

    def test_only_selected_verified_binary_is_written(self):
        data = self.archive()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bin" / "tool"
            installer.install_archive(data, hashlib.sha256(data).hexdigest(), "binary", target)
            self.assertEqual(target.read_bytes(), b"fixture")
            self.assertEqual(list(Path(directory).iterdir()), [target.parent])
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_tampered_archive_cannot_write_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool"
            with self.assertRaises(ValueError):
                installer.install_archive(self.archive(), "0" * 64, "binary", target)
            self.assertFalse(target.exists())

    def test_archive_symlink_cannot_be_installed(self):
        data = self.archive(symlink=True)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool"
            with self.assertRaises(ValueError):
                installer.install_archive(data, hashlib.sha256(data).hexdigest(), "binary", target)
            self.assertFalse(target.exists())

    def test_sdk_selection_installs_only_the_pinned_callback_tunnel(self):
        directory = tempfile.TemporaryDirectory(prefix="tools root ")
        self.addCleanup(directory.cleanup)
        with patch.object(installer.platform, "system", return_value="Darwin"), \
             patch.object(installer.platform, "machine", return_value="arm64"), \
             patch.object(installer.platform, "mac_ver", return_value=("15.7", ("", "", ""), "")), \
             patch.object(installer, "ROOT", Path(directory.name)), \
             patch.object(installer, "fetch", side_effect=AssertionError("network")) as fetch, \
             patch.object(installer.hashlib, "sha256") as sha, \
             patch.object(installer, "install_archive") as unpack:
            sha.return_value.hexdigest.return_value = installer.CLOUDFLARED_SHA
            cache = installer.ROOT / ".state" / "downloads"
            cache.mkdir(parents=True)
            (cache / "cloudflared.tar.gz").write_bytes(b"cached")
            installer.main(["--only", "cloudflared"])
        fetch.assert_not_called()
        self.assertEqual([call.args[2] for call in unpack.call_args_list], ["cloudflared"])

    def test_keychain_secret_uses_stdin_not_process_arguments(self):
        secret = "synthetic-only-secret"
        completed = [subprocess.CompletedProcess([], 0, "", ""),
                     subprocess.CompletedProcess([], 0, secret + "\n", "")]
        with patch.object(credentials.subprocess, "run", side_effect=completed) as run:
            credentials.store("test-only.service", "test-only-account", secret)
        for call in run.call_args_list:
            self.assertNotIn(secret, str(call.args))
        self.assertIn(secret, run.call_args_list[0].kwargs["input"])


if __name__ == "__main__":
    unittest.main()

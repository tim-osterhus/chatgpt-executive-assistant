"""Offline installation tests: fake credentials, HTTP, Keychain and temporary state."""
import argparse
import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'runtime'))
import sdk_installation as sdk

ACCOUNT = 'AC' + '1' * 32
SECRET = 'TEST-SECRET-NEVER-PERSIST-OR-PRINT'
CONFIG = {'keychain_account': 'fake-owner'}


class FakeKeychain:
    def __init__(self):
        self.values = {}
        self.fail_set = False
        self.fail_delete = False

    def get(self, service, account):
        return self.values[(service, account)]

    def set(self, service, account, secret):
        if self.fail_set:
            raise RuntimeError(SECRET)
        self.values[(service, account)] = secret

    def delete(self, service, account):
        if self.fail_delete:
            raise RuntimeError(SECRET)
        self.values.pop((service, account), None)


class FakeHTTP:
    def __init__(self):
        self.resources = {}
        self.calls = []
        self.unknown_create = None
        self.fail_delete = None

    async def request(self, method, resource, data=None):
        self.calls.append((method, resource, data))
        if method == 'POST':
            sid = ('AP' if resource == 'Applications' else 'SK') + '2' * 32
            # Real v2010 NewKey/Key resources omit account_sid.
            result = {'sid': sid, 'friendly_name': data['FriendlyName']}
            if resource == 'Applications':
                result['account_sid'] = ACCOUNT
            self.resources[resource + '/' + sid] = result
            if resource == self.unknown_create:
                raise TimeoutError(SECRET)
            return dict(result, **({'secret': SECRET} if resource == 'Keys' else {}))
        if resource not in self.resources:
            raise sdk.ResourceMissing('owned_resource_missing')
        if method == 'GET':
            return self.resources[resource]
        if resource == self.fail_delete:
            raise RuntimeError(SECRET)
        del self.resources[resource]
        return {}


class InstallationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / '.state' / 'sdk-transport'
        self.http, self.keychain = FakeHTTP(), FakeKeychain()

    def options(self):
        return dict(account_sid=ACCOUNT, request=self.http.request, state_dir=self.directory, keychain=self.keychain,
                    lock_factory=lambda directory: sdk.installation_locks(directory, readiness=lambda _: None))

    def journal(self):
        return json.loads((self.directory / 'installation.json').read_text())

    async def install(self):
        return await sdk.ensure_installed(CONFIG, **self.options())

    async def test_idempotent_owned_resources_and_secret_not_on_disk(self):
        self.assertEqual(await self.install(), {'status': 'ready', 'reused': False})
        self.assertEqual(await self.install(), {'status': 'ready', 'reused': True})
        self.assertEqual(sum(c[0] == 'POST' for c in self.http.calls), 2)
        self.assertEqual(set(self.http.calls[0][2]), {'FriendlyName'})
        credentials = sdk.load_credentials(CONFIG, account_sid=ACCOUNT, state_dir=self.directory, keychain=self.keychain)
        self.assertEqual(credentials['key_secret'], SECRET)
        self.assertNotIn(SECRET, (self.directory / 'installation.json').read_text())
        self.assertEqual((self.directory / 'installation.json').stat().st_mode & 0o777, 0o600)

    async def test_wrong_account_and_unowned_resources_never_deleted(self):
        await self.install()
        options = dict(self.options(), account_sid='AC' + '3' * 32)
        with self.assertRaisesRegex(sdk.InstallationError, 'account_mismatch'):
            await sdk.cleanup(CONFIG, **options)
        first = next(iter(self.http.resources.values()))
        first['friendly_name'] = 'somebody else'
        with self.assertRaisesRegex(sdk.InstallationError, 'no_recreation'):
            await self.install()
        with self.assertRaisesRegex(sdk.InstallationError, 'cleanup_incomplete'):
            await sdk.cleanup(CONFIG, **self.options())
        self.assertFalse(any(c[0] == 'DELETE' and c[1].startswith('Applications') for c in self.http.calls))

    async def test_keys_without_account_field_reuse_and_cleanup_but_conflict_rejected(self):
        await self.install()
        key = self.http.resources['Keys/' + self.journal()['key_sid']]
        self.assertNotIn('account_sid', key)
        self.assertEqual(await self.install(), {'status': 'ready', 'reused': True})
        key['account_sid'] = 'AC' + '3' * 32
        with self.assertRaisesRegex(sdk.InstallationError, 'no_recreation'):
            await self.install()
        with self.assertRaisesRegex(sdk.InstallationError, 'cleanup_incomplete'):
            await sdk.cleanup(CONFIG, **self.options())
        self.assertFalse(any(c[0] == 'DELETE' for c in self.http.calls))
        del key['account_sid']
        self.assertEqual(await sdk.cleanup(CONFIG, **self.options()), {'status': 'cleaned'})
        self.assertFalse(self.http.resources)

    async def test_unknown_create_stays_pending_and_never_recreates(self):
        self.http.unknown_create = 'Keys'
        with self.assertRaisesRegex(sdk.InstallationError, 'installation_incomplete') as caught:
            await self.install()
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(self.journal()['pending'], 'create_key_sid')
        before = len(self.http.calls)
        with self.assertRaisesRegex(sdk.InstallationError, 'requires_reconciliation'):
            await self.install()
        self.assertEqual(len(self.http.calls), before)
        with self.assertRaisesRegex(sdk.InstallationError, 'unknown_created_resource'):
            await sdk.cleanup(CONFIG, **self.options())
        self.assertEqual(self.journal()['pending'], 'create_key_sid')
        self.assertEqual(len(self.http.resources), 1)  # Unknown key is never guessed/adopted.

    async def test_keychain_failure_preserves_exact_ids_for_cleanup(self):
        self.keychain.fail_set = True
        with self.assertRaisesRegex(sdk.InstallationError, 'installation_incomplete'):
            await self.install()
        self.assertEqual(self.journal()['pending'], 'save_key_secret')
        self.assertIn('key_sid', self.journal())
        with self.assertRaises(sdk.InstallationError):
            await self.install()
        self.assertEqual(await sdk.cleanup(CONFIG, **self.options()), {'status': 'cleaned'})
        self.assertFalse(self.http.resources)

    async def test_partial_cleanup_retries_only_remaining_ids(self):
        await self.install()
        self.http.fail_delete = 'Applications/' + self.journal()['app_sid']
        with self.assertRaisesRegex(sdk.InstallationError, 'cleanup_incomplete'):
            await sdk.cleanup(CONFIG, **self.options())
        self.assertTrue(self.journal()['key_sid_deleted'])
        self.http.fail_delete = None
        self.keychain.fail_delete = True
        with self.assertRaisesRegex(sdk.InstallationError, 'cleanup_keychain_incomplete'):
            await sdk.cleanup(CONFIG, **self.options())
        self.keychain.fail_delete = False
        self.assertEqual(await sdk.cleanup(CONFIG, **self.options()), {'status': 'cleaned'})
        self.assertEqual(sum(c[0] == 'DELETE' and c[1].startswith('Keys/') for c in self.http.calls), 1)
        with self.assertRaises(sdk.InstallationError):
            await self.install()  # Cleaned history does not silently create another set.

    async def test_active_marker_blocks_install_and_cleanup_even_empty_or_old(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'active.json').write_text('{}')
        for operation in (sdk.ensure_installed, sdk.cleanup):
            with self.assertRaisesRegex(sdk.InstallationError, 'active_call_unresolved'):
                await operation(CONFIG, **self.options())
        self.assertEqual(self.http.calls, [])

    async def test_missing_owned_resource_is_never_recreated(self):
        await self.install()
        self.http.resources.clear()
        with self.assertRaisesRegex(sdk.InstallationError, 'no_recreation'):
            await self.install()
        self.assertEqual(sum(c[0] == 'POST' for c in self.http.calls), 2)
        self.assertEqual(await sdk.cleanup(CONFIG, **self.options()), {'status': 'cleaned'})

    async def test_journal_ownership_validation_before_keychain_read(self):
        await self.install()
        data = self.journal()
        data['keychain_service'] = 'unowned-secret'
        sdk._save(self.directory, data)
        with self.assertRaisesRegex(sdk.InstallationError, 'service_mismatch'):
            sdk.load_credentials(CONFIG, account_sid=ACCOUNT, state_dir=self.directory, keychain=self.keychain)

    async def test_unresolved_admission_blocks_before_resource_operations(self):
        def unresolved(directory):
            raise sdk.InstallationError('caller_admission_unresolved')
        options = dict(self.options(), lock_factory=lambda directory: sdk.installation_locks(directory, readiness=unresolved))
        with self.assertRaisesRegex(sdk.InstallationError, 'caller_admission_unresolved'):
            await sdk.ensure_installed(CONFIG, **options)
        self.assertFalse(self.http.calls)

    async def test_global_call_and_admission_locks_block(self):
        import fcntl
        for path in (self.directory.parent / 'runs' / '.call.lock', self.directory.parent / 'plugin-requests' / '.admission.lock'):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(sdk.InstallationError, 'caller_or_installation_busy'):
                    await self.install()
        self.assertEqual(self.http.calls, [])


class ReadinessTests(unittest.TestCase):
    def test_resolver_requires_exact_success_and_uses_target_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'runtime root'
            directory = root / '.state' / 'sdk-transport'
            (root / '.state' / 'plugin-requests' / 'earlier-call').mkdir(parents=True)
            for code, output in ((1, '1'), (0, '0'), (0, 'warning\n1'), (0, '')):
                with patch.object(sdk.subprocess, 'run', return_value=argparse.Namespace(returncode=code, stdout=output)):
                    with self.assertRaisesRegex(sdk.InstallationError, 'caller_admission_unresolved'):
                        sdk.caller_ready(directory)
            with patch.object(sdk.subprocess, 'run', return_value=argparse.Namespace(returncode=0, stdout='1\n')) as run:
                sdk.caller_ready(directory)
                command = run.call_args.args[0]
                self.assertEqual(command[0], str(root / '.plugin-venv/bin/python'))
                self.assertEqual(command[-1], str(root / 'runtime'))
                self.assertIn('if p.is_dir()', command[-2])
                self.assertNotIn('request.json', command[-2])
            with patch.object(sdk.subprocess, 'run', side_effect=FileNotFoundError(SECRET)):
                with self.assertRaisesRegex(sdk.InstallationError, '^caller_admission_unresolved$'):
                    sdk.caller_ready(directory)

    def test_core_calling_without_mcp_submissions_needs_no_plugin_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / '.state' / 'sdk-transport'
            with patch.object(sdk.subprocess, 'run', side_effect=AssertionError('plugin venv used')):
                sdk.caller_ready(directory)
                (directory.parent / 'plugin-requests').mkdir(parents=True)
                (directory.parent / 'plugin-requests' / '.admission.lock').touch()
                sdk.caller_ready(directory)

    def test_installed_chrome_is_configured_or_detected_never_downloaded(self):
        with tempfile.TemporaryDirectory() as temp:
            chrome = Path(temp) / 'My Apps' / 'Google Chrome'
            chrome.parent.mkdir()
            chrome.write_text('#!/bin/sh\n')
            self.assertRaisesRegex(sdk.InstallationError, 'installed_chrome_not_found', sdk.browser_executable, str(chrome))
            chrome.chmod(0o700)
            self.assertEqual(sdk.browser_executable(str(chrome)), str(chrome))
            self.assertRaises(sdk.InstallationError, sdk.browser_executable, 'relative/Google Chrome')
            with patch.object(sdk, 'CHROME_CANDIDATES', (str(Path(temp) / 'absent'), str(chrome))):
                self.assertEqual(sdk.browser_executable(), str(chrome))

    def test_readiness_reports_versions_against_lock_and_tested_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'runtime root'
            sdk_dir = root / 'runtime' / 'sdk'
            sdk_dir.mkdir(parents=True)
            (sdk_dir / 'package.json').write_text(json.dumps({'dependencies': {'twilio': '6.2.0', 'playwright-core': '1.65.0'}}))
            chrome = Path(temp) / 'Google Chrome'
            chrome.write_text(''); chrome.chmod(0o700)
            versions = {'node': 'v23.11.0\n', str(chrome): 'Google Chrome 156.0.8078.81 \n'}
            run = lambda command, **kwargs: argparse.Namespace(returncode=0, stdout=versions[command[0]])
            with patch.object(sdk.shutil, 'which', return_value='node'), patch.object(sdk.subprocess, 'run', run):
                missing = sdk.sdk_readiness(root, str(chrome))
                self.assertFalse(missing['ready']); self.assertFalse(missing['packages_match_lock'])
                for name, version in (('twilio', '6.2.0'), ('playwright-core', '1.65.0')):
                    (sdk_dir / 'node_modules' / name).mkdir(parents=True)
                    (sdk_dir / 'node_modules' / name / 'package.json').write_text(json.dumps({'version': version}))
                ready = sdk.sdk_readiness(root, str(chrome))
                self.assertTrue(ready['ready']); self.assertTrue(ready['matches_tested_baseline'])
                self.assertEqual((ready['node_version'], ready['chrome_version']), ('23.11.0', '156.0.8078.81'))
                versions['node'] = 'v22.22.0\n'
                newer = sdk.sdk_readiness(root, str(chrome))
                self.assertTrue(newer['ready']); self.assertFalse(newer['matches_tested_baseline'])
                versions['node'] = 'v18.20.0\n'
                self.assertFalse(sdk.sdk_readiness(root, str(chrome))['ready'])

    def test_owned_names_use_this_installation_namespace(self):
        self.assertEqual(sdk._keychain_service({'keychain_service_prefix': 'custom-calls'}, 'a' * 32),
                         'custom-calls.voice-sdk.' + 'a' * 32)
        self.assertEqual(sdk._keychain_service({}, 'b' * 32), 'executive-assistant-calls.voice-sdk.' + 'b' * 32)
        self.assertTrue(sdk.FRIENDLY_PREFIX.startswith('Executive Assistant Calls'))


class CLITests(unittest.TestCase):
    def test_redacted_failure_and_status_output(self):
        spec = importlib.util.spec_from_file_location('sdk_setup', ROOT / 'scripts' / 'sdk_setup.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        async def fail(args):
            raise sdk.InstallationError('installation_incomplete_reconcile_journal')
        output = io.StringIO()
        with patch.object(cli, 'run_command', fail), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['install']), 1)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()

"""Owned, journaled Twilio Voice SDK resources and local readiness for this calling runtime.

A pending create is deliberately never retried: its response may have been lost.
Only the exact resources recorded here can be reused or removed.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / '.state' / 'sdk-transport'
FRIENDLY_PREFIX = 'Executive Assistant Calls SDK '
# Versions that completed the accepted calls. Chrome auto-updates, so a match is evidence, not a pin.
TESTED_BASELINE = {'node': '23.11.0', 'chrome': '156.0.8078.81'}
CHROME_CANDIDATES = ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                     '~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


class InstallationError(RuntimeError):
    """Fixed reason safe to print; provider bodies and exception text are excluded."""


class ResourceMissing(InstallationError):
    pass


def _sid(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + r'[0-9a-fA-F]{32}', value) is not None


def _fingerprint(account):
    if not _sid(account, 'AC'):
        raise InstallationError('invalid_account_sid')
    return hashlib.sha256(account.encode()).hexdigest()


def _directory(state_dir):
    return Path(state_dir) if state_dir is not None else DEFAULT_STATE


def _save(directory, data):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = directory / ('.installation-' + uuid.uuid4().hex + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'installation.json')
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def _read(directory, account, config):
    try:
        data = json.loads((directory / 'installation.json').read_text())
    except FileNotFoundError:
        return None
    except Exception:
        raise InstallationError('invalid_installation_journal') from None
    if not isinstance(data, dict) or data.get('version') != 1:
        raise InstallationError('invalid_installation_journal')
    installation = data.get('installation_id')
    if not isinstance(installation, str) or not re.fullmatch(r'[0-9a-f]{32}', installation):
        raise InstallationError('invalid_installation_journal')
    if data.get('account_fingerprint') != _fingerprint(account):
        raise InstallationError('installation_account_mismatch')
    if data.get('keychain_account') != config.get('keychain_account'):
        raise InstallationError('installation_keychain_account_mismatch')
    if data.get('friendly_name') != FRIENDLY_PREFIX + installation:
        raise InstallationError('installation_ownership_mismatch')
    for field, prefix in (('app_sid', 'AP'), ('key_sid', 'SK')):
        if data.get(field) is not None and not _sid(data[field], prefix):
            raise InstallationError('invalid_installation_resource_sid')
    if data.get('keychain_service') != _keychain_service(config, installation):
        raise InstallationError('installation_keychain_service_mismatch')
    return data


def _keychain_service(config, installation):
    return config.get('keychain_service_prefix', 'executive-assistant-calls') + '.voice-sdk.' + installation


def browser_executable(configured=None):
    """The configured absolute path, else the standard installed Google Chrome locations."""
    candidates = [configured] if configured else [os.path.expanduser(value) for value in CHROME_CANDIDATES]
    for value in candidates:
        path = Path(value)
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise InstallationError('installed_chrome_not_found')


def _version(command, pattern):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(pattern, result.stdout) if result.returncode == 0 else None
    return match.group(1) if match else None


def sdk_readiness(root=ROOT, configured_browser=None):
    """Local prerequisites with observed versions. Starts no page, call, or provider request."""
    sdk = Path(root) / 'runtime' / 'sdk'
    node = shutil.which('node')
    node_version = _version([node, '--version'], r'^v(\d+\.\d+\.\d+)') if node else None
    expected = json.loads((sdk / 'package.json').read_text())['dependencies']
    installed = {}
    for name in expected:
        try:
            installed[name] = json.loads((sdk / 'node_modules' / name / 'package.json').read_text()).get('version')
        except (OSError, ValueError):
            installed[name] = None
    try:
        browser = browser_executable(configured_browser)
    except InstallationError:
        browser = None
    browser_version = _version([browser, '--version'], r'(\d+\.\d+\.\d+\.\d+)') if browser else None
    node_supported = node_version is not None and int(node_version.split('.')[0]) >= 20
    return {'ready': node_supported and installed == expected and browser_version is not None,
            'node': node, 'node_version': node_version, 'node_supported': node_supported,
            'packages': installed, 'packages_match_lock': installed == expected,
            'chrome_executable': browser, 'chrome_version': browser_version,
            'tested_baseline': TESTED_BASELINE,
            'matches_tested_baseline': (node_version, browser_version) == (TESTED_BASELINE['node'], TESTED_BASELINE['chrome'])}


class Keychain:
    def get(self, service, account):
        result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', service, '-a', account, '-w'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise InstallationError('keychain_read_failed')
        return result.stdout.strip()

    def set(self, service, account, secret):
        # Feed the interactive security command via stdin, never a secret argv.
        command = shlex.join(['add-generic-password', '-U', '-s', service, '-a', account, '-w', secret])
        result = subprocess.run(['/usr/bin/security', '-i'], input=command + '\n',
                                text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise InstallationError('keychain_write_failed')

    def delete(self, service, account):
        result = subprocess.run(['/usr/bin/security', 'delete-generic-password', '-s', service, '-a', account],
                                capture_output=True, timeout=10)
        if result.returncode not in (0, 44):
            raise InstallationError('keychain_delete_failed')


def load_credentials(config, *, account_sid, state_dir=None, keychain=None):
    directory = _directory(state_dir)
    _fingerprint(account_sid)
    data = _read(directory, account_sid, config)
    if data is None or data.get('status') != 'ready' or data.get('pending'):
        raise InstallationError('sdk_installation_not_ready')
    if not data.get('app_sid') or not data.get('key_sid') or not data.get('keychain_saved'):
        raise InstallationError('sdk_installation_not_ready')
    try:
        secret = (keychain or Keychain()).get(data['keychain_service'], data['keychain_account'])
    except Exception:
        raise InstallationError('sdk_key_secret_unavailable') from None
    if not isinstance(secret, str) or not secret.strip():
        raise InstallationError('sdk_key_secret_unavailable')
    return {'app_sid': data['app_sid'], 'key_sid': data['key_sid'], 'key_secret': secret}


def caller_ready(directory):
    root = directory.parent.parent
    ledger = root / '.state' / 'plugin-requests'
    # Without MCP submissions there is nothing for the optional plugin environment to reconcile.
    if not ledger.is_dir() or not any(path.is_dir() for path in ledger.iterdir()):
        return
    program = ("import sys;sys.path.insert(0,sys.argv[1]);import calling_mcp as c;"
               "print(int(not any(c._is_unresolved(p) for p in c.LEDGER.iterdir() if p.is_dir())))")
    try:
        result = subprocess.run([str(root / '.plugin-venv' / 'bin' / 'python'), '-I', '-c',
                                 program, str(root / 'runtime')],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15)
        if result.returncode != 0 or result.stdout.strip() != '1':
            raise InstallationError('caller_admission_unresolved')
    except Exception:
        raise InstallationError('caller_admission_unresolved') from None


@contextlib.contextmanager
def installation_locks(directory, *, readiness=None):
    """Share the runner's admission and call locks, plus installation lock."""
    state = directory.parent
    paths = (state / 'plugin-requests' / '.admission.lock', state / 'runs' / '.call.lock', directory / '.installation.lock')
    with contextlib.ExitStack() as stack:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            stream = stack.enter_context(os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), 'a+'))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InstallationError('caller_or_installation_busy') from None
        if (directory / 'active.json').exists():
            raise InstallationError('sdk_active_call_unresolved')
        (readiness or caller_ready)(directory)
        yield


class TwilioHTTP:
    """Restricted account-authenticated Applications/Standard Keys API adapter."""
    def __init__(self, session, account_sid, auth_token):
        _fingerprint(account_sid)
        self.session, self.account_sid, self.auth_token = session, account_sid, auth_token

    async def request(self, method, resource, data=None):
        import aiohttp
        if method not in {'GET', 'POST', 'DELETE'} or not re.fullmatch(r'(Applications(?:/AP[0-9a-fA-F]{32})?|Keys(?:/SK[0-9a-fA-F]{32})?)', resource):
            raise InstallationError('unsupported_installation_operation')
        url = f'https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/{resource}.json'
        try:
            async with self.session.request(method, url, data=data,
                    auth=aiohttp.BasicAuth(self.account_sid, self.auth_token), timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status == 404:
                    raise ResourceMissing('owned_resource_missing')
                if method == 'DELETE' and response.status == 204:
                    return {}
                if response.status >= 400:
                    raise InstallationError('twilio_resource_request_failed')
                return await response.json()
        except InstallationError:
            raise
        except Exception:
            raise InstallationError('twilio_resource_request_uncertain') from None


async def _owned(request, data, account, field, collection):
    result = await request('GET', collection + '/' + data[field])
    # v2010 Keys omit account_sid; the authenticated account endpoint and
    # account-bound journal establish that scope. Applications include it.
    if (result.get('sid') != data[field]
            or (result.get('account_sid') != account if collection == 'Applications'
                else result.get('account_sid', account) != account)
            or result.get('friendly_name') != data['friendly_name']):
        raise InstallationError('owned_resource_verification_failed')
    return result


async def ensure_installed(config, *, account_sid, request, state_dir=None, keychain=None, lock_factory=None):
    directory = _directory(state_dir)
    fingerprint = _fingerprint(account_sid)
    keychain = keychain or Keychain()
    with (lock_factory or installation_locks)(directory):
        data = _read(directory, account_sid, config)
        if data is not None:
            if data.get('status') != 'ready' or data.get('pending'):
                raise InstallationError('installation_requires_reconciliation')
            try:
                for field, collection in (('app_sid', 'Applications'), ('key_sid', 'Keys')):
                    await _owned(request, data, account_sid, field, collection)
                load_credentials(config, account_sid=account_sid, state_dir=directory, keychain=keychain)
            except Exception:
                raise InstallationError('existing_installation_unavailable_no_recreation') from None
            return {'status': 'ready', 'reused': True}
        if not isinstance(config.get('keychain_account'), str) or not config['keychain_account'].strip():
            raise InstallationError('invalid_keychain_account')
        installation = uuid.uuid4().hex
        data = {'version': 1, 'installation_id': installation, 'account_fingerprint': fingerprint,
                'friendly_name': FRIENDLY_PREFIX + installation, 'keychain_account': config['keychain_account'],
                'keychain_service': _keychain_service(config, installation), 'status': 'installing'}
        _save(directory, data)
        for field, collection in (('app_sid', 'Applications'), ('key_sid', 'Keys')):
            data['pending'] = 'create_' + field
            _save(directory, data)
            try:
                # No VoiceUrl: the call controller supplies an ephemeral per-call URL.
                result = await request('POST', collection, {'FriendlyName': data['friendly_name']})
                if (not _sid(result.get('sid'), 'AP' if field == 'app_sid' else 'SK')
                        or (result.get('account_sid') != account_sid if collection == 'Applications'
                            else result.get('account_sid', account_sid) != account_sid)
                        or result.get('friendly_name') != data['friendly_name']):
                    raise InstallationError('invalid_created_resource_sid')
                data[field] = result['sid']
                data.pop('pending')
                _save(directory, data)
                if field == 'key_sid':
                    data['pending'] = 'save_key_secret'
                    _save(directory, data)
                    secret = result.get('secret')
                    if not isinstance(secret, str) or not secret:
                        raise InstallationError('key_secret_missing')
                    keychain.set(data['keychain_service'], data['keychain_account'], secret)
                    if not secrets.compare_digest(keychain.get(data['keychain_service'], data['keychain_account']), secret):
                        raise InstallationError('keychain_verification_failed')
                    data['keychain_saved'] = True
                    data.pop('pending')
                    _save(directory, data)
            except Exception:
                raise InstallationError('installation_incomplete_reconcile_journal') from None
        data['status'] = 'ready'
        _save(directory, data)
        return {'status': 'ready', 'reused': False}


async def cleanup(config, *, account_sid, request, state_dir=None, keychain=None, lock_factory=None):
    directory = _directory(state_dir)
    _fingerprint(account_sid)
    keychain = keychain or Keychain()
    with (lock_factory or installation_locks)(directory):
        data = _read(directory, account_sid, config)
        if data is None:
            return {'status': 'absent'}
        if data.get('status') == 'cleaned':
            return {'status': 'cleaned'}
        unknown_create = str(data.get('pending', '')).startswith('create_')
        data['status'] = 'cleaning'
        _save(directory, data)
        for field, collection in (('key_sid', 'Keys'), ('app_sid', 'Applications')):
            if not data.get(field) or data.get(field + '_deleted'):
                continue
            try:
                try:
                    await _owned(request, data, account_sid, field, collection)
                    await request('DELETE', collection + '/' + data[field])
                except ResourceMissing:
                    pass
                data[field + '_deleted'] = True
                _save(directory, data)
            except Exception:
                raise InstallationError('cleanup_incomplete_reconcile_journal') from None
        if not data.get('keychain_deleted'):
            try:
                keychain.delete(data['keychain_service'], data['keychain_account'])
                data['keychain_deleted'] = True
                _save(directory, data)
            except Exception:
                raise InstallationError('cleanup_keychain_incomplete') from None
        if unknown_create:
            raise InstallationError('cleanup_has_unknown_created_resource')
        data.pop('pending', None)
        data['status'] = 'cleaned'
        _save(directory, data)
        return {'status': 'cleaned'}

"""One durable SDK attempt and the shared caller admission fence."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import secrets


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '-' + secrets.token_hex(8))
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(data, stream, separators=(',', ':')); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def unresolved(state_root):
    # Missing/malformed per-run receipts never implicitly clear the owner marker.
    return (Path(state_root) / 'sdk-transport' / 'active.json').exists()


class SdkCallState:
    def __init__(self, state_root, output, request_id, *, recover=False):
        self.root, self.output = Path(state_root), Path(output)
        self.marker = self.root / 'sdk-transport/active.json'
        self.path = self.output / 'sdk-state.json'
        self.gate = self.root / 'plugin/dial-enabled'
        self.gate_original = self.output / 'sdk-gate-original.json'
        if recover:
            self.data = json.loads(self.path.read_text())
            if self.data['request_id'] != request_id:
                raise RuntimeError('sdk_recovery_identity_mismatch')
        else:
            if self.path.exists(): raise RuntimeError('sdk_attempt_already_exists')
            self.data = {'request_id': request_id, 'owner': secrets.token_urlsafe(32),
                         'status': 'prepared', 'dial_attempted': False,
                         'parent_sid': None, 'child_sid': None, 'closing': False}

    def claim(self):
        self.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        save(self.path, self.data)
        self.marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'request_id': self.data['request_id'], 'owner': self.data['owner'],
                       'state_path': str(self.path)}, stream)
            stream.flush(); os.fsync(stream.fileno())

    def owns_marker(self):
        try:
            marker = json.loads(self.marker.read_text())
            return (marker.get('owner') == self.data['owner']
                    and marker.get('request_id') == self.data['request_id'])
        except (OSError, ValueError, TypeError):
            return False

    def update(self, **fields):
        self.data.update(fields)
        save(self.path, self.data)

    def before_connect(self):
        """Caller holds the shared call lock; coordinate the gate with MCP admission."""
        with (self.root / 'plugin-requests/.admission.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not self.owns_marker() or not self.gate.is_file():
                raise RuntimeError('sdk_admission_or_gate_not_ready')
            save(self.gate_original, {'bytes': self.gate.read_bytes().hex(),
                                      'mode': self.gate.stat().st_mode & 0o777})
            self.gate.unlink()
            self.update(status='claimed', dial_attempted=True)

    def close_fence(self, reason):
        # No await may precede this durable close fence in any abort path.
        self.update(closing=True, status='closing', ending_reason=reason)

    def restore_admission(self, *, physical_safe, local_stopped):
        if not physical_safe or not local_stopped or not self.owns_marker():
            raise RuntimeError('sdk_exact_reconciliation_required')
        with (self.root / 'plugin-requests/.admission.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.gate_original.exists():
                original = json.loads(self.gate_original.read_text())
                if self.gate.exists():
                    if (self.gate.read_bytes().hex() != original['bytes']
                            or self.gate.stat().st_mode & 0o777 != original['mode']):
                        raise RuntimeError('sdk_gate_changed_during_call')
                else:
                    fd = os.open(self.gate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, original['mode'])
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(bytes.fromhex(original['bytes'])); stream.flush(); os.fsync(stream.fileno())
            self.update(status='terminal', physical_calls_terminal=physical_safe,
                        local_resources_stopped=local_stopped, admission_restored=True)
            self.marker.unlink()

"""Owned renderer startup guard: staged bounds, safe persisted reasons, no dial after abort. Offline only."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientSession
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from phone_bridge import signature  # noqa: E402
import sdk_phone  # noqa: E402
from sdk_phone import SdkPhone, listen  # noqa: E402

AC = 'AC' + '1' * 32; AP = 'AP' + '2' * 32; PARENT = 'CA' + '3' * 32
CHROME = '/Applications/Example Chrome.app/Contents/MacOS/Google Chrome'
# Stands in for driver.cjs only: same stdin config and stdout events, no node, Chrome or network.
FAKE_DRIVER = '''
import json, os, sys, time
mode = sys.argv[1]; config = json.loads(sys.stdin.read())
if config.get("executable") != "/Applications/Example Chrome.app/Contents/MacOS/Google Chrome":
    sys.exit(4)  # The controller must pass its selected installed Chrome, not a bundled browser.
emit = lambda value: print(json.dumps(value), flush=True)
if mode != "silent":
    emit({"event": "renderer_process", "pid": os.getpid(), "profile": os.path.join(config["profile"], "owned")})
if mode == "exit":
    sys.exit(3)
if mode == "fail":
    emit({"event": "renderer_failed", "error_type": "Error"})
time.sleep(60)
'''
REAL_EXEC = asyncio.create_subprocess_exec


def fake_driver(mode):
    async def spawn(program, *args, **kwargs):
        if program == 'node' and args and args[0].endswith('driver.cjs'):
            return await REAL_EXEC(sys.executable, '-I', '-c', FAKE_DRIVER, mode, **kwargs)
        raise AssertionError('unexpected subprocess in startup test')
    return patch.object(sdk_phone.asyncio, 'create_subprocess_exec', side_effect=spawn)


def budgets(launch, ready):
    return patch.multiple(sdk_phone, RENDERER_LAUNCH_SECONDS=launch, RENDERER_READY_SECONDS=ready)


class StartupGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.output = Path(self.temp.name)
        self.phone = SdkPhone(state_root=self.output / 'state', output=self.output, request_id='startup-test',
            account=AC, token='test-auth-token', credentials={'app_sid': AP, 'key_sid': 'SK' + '5' * 32, 'key_secret': 'x'},
            source='+15551112222', target='+15553334444', adapter=Mock(), max_seconds=2700, ringing=60,
            voicemail_enabled=True, on_connected=AsyncMock(), on_voicemail=AsyncMock(), browser_executable=CHROME)
        self.phone.journal.claim(); self.phone.local_origin = 'http://127.0.0.1:9'
        self.phone.public_base = 'https://example.trycloudflare.com'

    async def asyncTearDown(self):
        await self.phone.stop_renderer()
        self.phone.wav_in.close(); self.phone.wav_out.close(); self.phone.events.close(); self.temp.cleanup()

    def events(self):
        return [json.loads(line) for line in (self.output / 'sdk-events.jsonl').read_text().splitlines()]

    async def fails(self, mode, reason, launch=2.0, ready=0.6, during=None):
        with fake_driver(mode), budgets(launch, ready):
            task = asyncio.create_task(self.phone.start_renderer())
            if during:
                await during()
            with self.assertRaisesRegex(RuntimeError, '^' + reason + '$'):
                await task
        saved = json.loads(self.phone.journal.path.read_text())['startup']
        self.assertEqual(saved['reason'], reason)
        last = self.events()[-1]
        self.assertEqual((last.pop('event'), last.pop('elapsed') >= 0, last), ('sdk_renderer_startup', True, saved))
        self.assertEqual({k for k in saved} - {'stage', 'reason', 'wait_started_elapsed', 'failed_elapsed', 'driver_returncode',
                          'launch_budget_seconds', 'ready_budget_seconds', 'renderer_launch_elapsed', 'renderer_ready_elapsed'}, set())
        return saved

    async def test_launch_timeout_is_named_and_cleanup_stops_driver(self):
        saved = await self.fails('silent', 'sdk_owned_renderer_launch_timeout', launch=0.5)
        self.assertEqual(saved['stage'], 'renderer_launch'); self.assertIsNone(saved['driver_returncode'])
        await self.phone.stop_renderer()
        self.assertIsNotNone(self.phone.driver.returncode); self.assertFalse(self.phone.renderer_temp.exists())

    async def test_ready_timeout_after_owned_process_records_both_stages(self):
        saved = await self.fails('process', 'sdk_owned_renderer_ready_timeout')
        self.assertEqual(saved['stage'], 'renderer_ready')
        self.assertGreater(saved['renderer_launch_elapsed'], 0); self.assertIsNone(saved['renderer_ready_elapsed'])

    async def test_driver_exit_is_distinguished_from_timeout(self):
        saved = await self.fails('exit', 'sdk_owned_renderer_driver_exited', ready=5.0)
        self.assertEqual(saved['driver_returncode'], 3)

    async def test_renderer_failure_while_waiting_is_closing_not_timeout(self):
        saved = await self.fails('fail', 'sdk_owned_renderer_closing', ready=5.0)
        self.assertEqual(self.phone.failure, 'sdk_owned_renderer_failed'); self.assertTrue(self.phone.closing)

    async def test_ready_near_deadline_succeeds_and_records_timing(self):
        async def ready_late():
            await self.phone.renderer_launched.wait(); await asyncio.sleep(0.45)
            await self.phone.media_event({'type': 'ready', 'sample_rate': 48000, 'input_requests': 1})
        with fake_driver('process'), budgets(2.0, 0.6):
            await asyncio.gather(self.phone.start_renderer(), ready_late())
        journal = json.loads(self.phone.journal.path.read_text()); saved = journal['startup']
        self.assertEqual(journal['renderer_executable'], CHROME)  # Recovery verifies this exact engine.
        self.assertEqual(saved['stage'], 'ready'); self.assertNotIn('reason', saved)
        self.assertGreaterEqual(saved['renderer_ready_elapsed'], saved['renderer_launch_elapsed'] + 0.4)

    async def test_late_ready_and_signed_voice_after_abort_cannot_dial(self):
        await self.fails('process', 'sdk_owned_renderer_ready_timeout', ready=0.3)
        self.phone.close_fence('sdk_owned_renderer_ready_timeout')  # As run() does on the raised reason.
        await self.phone.media_event({'type': 'ready', 'sample_rate': 48000, 'input_requests': 1})
        runner, port = await listen(self.phone.public_app())
        try:
            path = '/voice/' + self.phone.nonce
            data = {'AccountSid': AC, 'CallSid': PARENT, 'From': 'client:' + self.phone.identity, 'Intent': 'startup-test'}
            headers = {'X-Twilio-Signature': signature('test-auth-token', self.phone.public_base + path, data)}
            async with ClientSession() as client:
                async with client.post('http://127.0.0.1:%d%s' % (port, path), data=data, headers=headers) as response:
                    self.assertNotIn('<Dial', await response.text())
        finally:
            await runner.cleanup()
        state = json.loads(self.phone.journal.path.read_text())
        self.assertFalse(state['dial_attempted']); self.assertIsNone(state['parent_sid'])
        self.assertEqual(state['ending_reason'], 'sdk_owned_renderer_ready_timeout')


class StartupRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_persists_safe_startup_reason_and_completes_cleanup_without_connect(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'controller'; output = root / 'runs/startup-run/evidence'; output.mkdir(parents=True)
            (root / '.state/plugin-requests').mkdir(parents=True); (root / '.state/plugin').mkdir(parents=True)
            (root / '.state/plugin/dial-enabled').write_bytes(b'gate')
            public = Mock(); public.cleanup = AsyncMock(); tunnel = Mock(returncode=None)
            async def wait(): tunnel.returncode = 0; return 0
            tunnel.wait = wait; calls = []
            class API:
                def __init__(self, *args): pass
                async def request(self, method, resource, data=None, params=None):
                    calls.append((method, resource, data))
                    return {'sid': AP, 'account_sid': AC}
            before = AsyncMock(); adapter = Mock(); adapter.peer.close = AsyncMock()
            with patch.object(sdk_phone, 'ROOT', root), patch.object(sdk_phone, 'CallAPI', API), \
                    patch.object(sdk_phone, 'listen', AsyncMock(return_value=(public, 12345))), \
                    patch.object(sdk_phone, 'start_tunnel', AsyncMock(return_value=(tunnel, None, 'https://example.trycloudflare.com'))), \
                    patch.object(sdk_phone, 'wait_for_tunnel_health', AsyncMock()), fake_driver('process'), budgets(2.0, 0.3), \
                    patch.dict('os.environ', {'TWILIO_ACCOUNT_SID': AC, 'TWILIO_AUTH_TOKEN': 'test', 'TWILIO_FROM_NUMBER': '+15551112222'}):
                summary = await sdk_phone.run(adapter=adapter, credentials={'app_sid': AP}, output_dir=output, target='+15553334444',
                    on_connected=AsyncMock(), on_voicemail=AsyncMock(), before_dial=before,
                    stop_event=asyncio.Event(), before_human_drain=AsyncMock(), browser_executable=CHROME)
            saved = json.loads((output / 'phone-summary.json').read_text()); state = json.loads((output / 'sdk-state.json').read_text())
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual(saved['bridge_error_type'], 'sdk_owned_renderer_ready_timeout')
            self.assertEqual(saved['error_type'], 'RuntimeError')
            self.assertEqual(saved['startup']['reason'], 'sdk_owned_renderer_ready_timeout')
            self.assertEqual(state['ending_reason'], 'sdk_owned_renderer_ready_timeout')
            before.assert_not_awaited()  # Live prewarm and the dial slot are never reached.
            self.assertFalse(state['dial_attempted']); self.assertIsNone(state['parent_sid'])
            self.assertTrue(saved['physical_calls_terminal'] and saved['local_resources_stopped'] and saved['admission_restored'])
            self.assertTrue(saved['sdk_safe_before_phone_leg']); self.assertFalse(saved['phone_dial_returned'])
            self.assertEqual(saved['cleanup_errors'], [])
            self.assertTrue((root / '.state/plugin/dial-enabled').exists())
            self.assertFalse((root / '.state/sdk-transport/active.json').exists())
            self.assertIn(('POST', 'Applications/' + AP, {'VoiceUrl': '', 'StatusCallback': ''}), calls)
            self.assertFalse(any(resource == 'Calls' or resource.startswith('Calls/') for _, resource, _ in calls))
            self.assertNotIn('test-auth-token', (output / 'phone-summary.json').read_text())


if __name__ == '__main__':
    unittest.main()

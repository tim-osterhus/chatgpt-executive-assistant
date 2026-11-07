"""AMD "unknown" enters the interactive path without claiming a confirmed human. Offline only:
real signed callback handlers and the real conduct() handoff with fakes; no network, provider or call."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientSession
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from phone_bridge import signature  # noqa: E402
import sdk_phone  # noqa: E402
from sdk_phone import SdkPhone, listen  # noqa: E402
import voice_session  # noqa: E402

AC = 'AC' + '1' * 32; AP = 'AP' + '2' * 32; PARENT = 'CA' + '3' * 32; CHILD = 'CA' + '4' * 32; TARGET = '+15553334444'


class AmdUnknownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.output = Path(self.temp.name)
        self.connected = AsyncMock(); self.voicemail = AsyncMock()
        self.phone = SdkPhone(state_root=self.output / 'state', output=self.output, request_id='amd-unknown-test',
            account=AC, token='test-auth-token', credentials={'app_sid': AP, 'key_sid': 'SK' + '5' * 32, 'key_secret': 'x'},
            source='+15551112222', target=TARGET, adapter=Mock(), max_seconds=2700, ringing=60, voicemail_enabled=True,
            on_connected=self.connected, on_voicemail=self.voicemail)
        self.phone.journal.claim(); self.phone.public_base = 'https://example.trycloudflare.com'
        self.phone.journal.update(parent_sid=PARENT, dial_returned=True)
        self.child_status = 'in-progress'
        self.phone.api = Mock()
        self.phone.api.call = AsyncMock(side_effect=lambda sid: {'sid': sid, 'parent_call_sid': PARENT, 'to': TARGET,
                                                                  'status': self.child_status})
        self.runner, port = await listen(self.phone.public_app()); self.base = 'http://127.0.0.1:%d' % port
        self.client = ClientSession()

    async def asyncTearDown(self):
        for task in self.phone.tasks: task.cancel()
        await asyncio.gather(*self.phone.tasks, return_exceptions=True)
        await self.client.close(); await self.runner.cleanup()
        self.phone.wav_in.close(); self.phone.wav_out.close(); self.phone.events.close(); self.temp.cleanup()

    async def post(self, kind, data):
        path = '/' + kind + '/' + self.phone.nonce
        headers = {'X-Twilio-Signature': signature('test-auth-token', self.phone.public_base + path, data)}
        async with self.client.post(self.base + path, data=data, headers=headers) as response:
            return response.status, await response.text()

    async def amd(self, answered_by=None):
        data = {'AccountSid': AC, 'CallSid': CHILD}
        if answered_by is not None: data['AnsweredBy'] = answered_by
        return await self.post('amd', data)

    async def child(self, status):
        return await self.post('child', {'AccountSid': AC, 'CallSid': CHILD, 'ParentCallSid': PARENT, 'To': TARGET,
                                         'CallStatus': status, 'Caller': '+15551112222', 'ApiVersion': '2010-04-01'})

    async def codec(self):
        await self.phone.media_event({'type': 'codec', 'codec': 'opus'})

    async def settle(self):
        if self.phone.mode_task: await asyncio.gather(self.phone.mode_task, return_exceptions=True)
        await asyncio.sleep(0)

    def events(self):
        return [json.loads(line) for line in (self.output / 'sdk-events.jsonl').read_text().splitlines()]

    def state(self):
        return json.loads(self.phone.journal.path.read_text())

    async def test_unknown_before_codec_opens_interactive_path_once_when_ready(self):
        await self.child('in-progress')
        self.assertEqual((await self.amd('unknown'))[0], 204)
        self.assertIsNone(self.phone.mode); self.connected.assert_not_awaited()  # Codec not yet observed.
        await self.codec(); await self.settle()
        self.assertEqual(self.phone.mode, 'human'); self.connected.assert_awaited_once(); self.voicemail.assert_not_awaited()
        self.assertFalse(self.phone.closing)
        self.assertEqual(self.state()['answered_by'], 'unknown')  # Actual AMD value retained, not rewritten to human.
        mode = [e for e in self.events() if e['event'] == 'sdk_audio_mode']
        self.assertEqual([(e['mode'], e['answered_by']) for e in mode], [('human', 'unknown')])
        self.assertEqual(self.phone.delivery(), {'kind': 'human', 'human_conversation_confirmed': False})

    async def test_unknown_after_codec_and_child_ready_opens_immediately(self):
        await self.child('in-progress'); await self.codec()
        self.assertIsNone(self.phone.mode)  # Voicemail-enabled calls wait for AMD before any audio.
        await self.amd('unknown'); await self.settle()
        self.assertEqual(self.phone.mode, 'human'); self.connected.assert_awaited_once()

    async def test_duplicate_and_reentrant_signals_never_reopen_or_change_the_result(self):
        await self.child('in-progress'); await self.codec(); await self.amd('unknown'); await self.settle()
        await self.amd('unknown'); await self.amd('machine_end_beep'); await self.codec(); await self.child('in-progress')
        self.phone.maybe_open_audio(); await self.settle()
        self.connected.assert_awaited_once(); self.voicemail.assert_not_awaited()
        self.assertEqual(self.phone.answered_by, 'unknown'); self.assertEqual(self.state()['answered_by'], 'unknown')
        self.assertEqual(len([e for e in self.events() if e['event'] == 'authenticated_amd']), 1)

    async def test_carrier_end_before_late_amd_keeps_first_reason_and_never_opens(self):
        await self.codec(); await self.child('completed')
        for answered_by in ('unknown', 'fax'):
            await self.amd(answered_by)
        await self.settle()
        self.assertIsNone(self.phone.mode); self.connected.assert_not_awaited()
        self.assertEqual(self.state()['ending_reason'], 'carrier_ended'); self.assertEqual(self.state()['answered_by'], 'unknown')
        ordered = [(e['event'], e.get('status') or e.get('answered_by')) for e in self.events()
                   if e['event'] in ('authenticated_child_status', 'authenticated_amd')]
        self.assertEqual(ordered, [('authenticated_child_status', 'completed'), ('authenticated_amd', 'unknown')])

    async def test_late_conservative_amd_after_closing_keeps_first_reason(self):
        self.phone.close_fence('conversation_stop')
        await self.amd('machine_start')
        self.assertEqual(self.state()['ending_reason'], 'conversation_stop'); self.assertIsNone(self.phone.mode)

    async def test_cancelled_call_cannot_open_audio_or_dial_after_unknown(self):
        await self.child('in-progress'); await self.codec()
        self.phone.close_fence('sdk_cleanup')
        await self.amd('unknown'); await self.settle()
        self.assertIsNone(self.phone.mode); self.connected.assert_not_awaited()
        data = {'AccountSid': AC, 'CallSid': 'CA' + '9' * 32, 'From': 'client:' + self.phone.identity, 'Intent': 'amd-unknown-test'}
        status, body = await self.post('voice', data)
        self.assertNotIn('<Dial', body)

    async def test_unsupported_pending_and_malformed_results_still_stop_without_audio(self):
        for value in ('machine_start', 'fax', 'machine_end_other', '', 'Unknown', 'unknown ', 'HUMAN', None):
            with self.subTest(value=value):
                await self.asyncTearDown(); await self.asyncSetUp()
                await self.child('in-progress'); await self.codec(); await self.amd(value); await self.settle()
                self.assertIsNone(self.phone.mode); self.connected.assert_not_awaited(); self.voicemail.assert_not_awaited()
                self.assertTrue(self.phone.closing and self.phone.ended.is_set())
                self.assertEqual(self.state()['ending_reason'], 'amd_conservative_stop')

    async def test_human_and_confirmed_machine_paths_are_unchanged(self):
        for value, mode in (('human', 'human'), ('machine_end_beep', 'voicemail'), ('machine_end_silence', 'voicemail')):
            with self.subTest(value=value):
                await self.asyncTearDown(); await self.asyncSetUp()
                await self.child('in-progress'); await self.codec(); await self.amd(value); await self.settle()
                self.assertEqual(self.phone.mode, mode); self.assertFalse(self.phone.closing)
                (self.connected if mode == 'human' else self.voicemail).assert_awaited_once()

    async def test_child_status_event_is_sanitized_status_and_elapsed_only(self):
        for status in ('ringing', 'in-progress', 'mystery-status'):
            await self.child(status)
        rows = [e for e in self.events() if e['event'] == 'authenticated_child_status']
        self.assertEqual([r['status'] for r in rows], ['ringing', 'in-progress', 'other'])
        self.assertTrue(all(set(r) == {'event', 'elapsed', 'status'} for r in rows))
        self.assertNotIn(CHILD, (self.output / 'sdk-events.jsonl').read_text())
        self.assertEqual((await self.post('child', {'AccountSid': AC, 'CallSid': CHILD, 'CallStatus': 'ringing'}))[0], 403)
        self.assertEqual(len([e for e in self.events() if e['event'] == 'authenticated_child_status']), 3)  # Unbound: no event.


class NeutralHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_connected_signal_is_neutral_and_keeps_greeting_and_confirmation_policy(self):
        sent = []
        async def request(self, method, params):
            sent.append((method, params)); return {}
        listeners = SimpleNamespace(on=lambda *_: (lambda fn: fn))
        adapter = SimpleNamespace(input_ready=asyncio.Event(), peer=SimpleNamespace(channel=listeners, connection=listeners,
                                  emit_pcm=None, close=AsyncMock()), close=AsyncMock(), disclose=AsyncMock(),
                                  provider_audio=AsyncMock(), seal_output=Mock())
        async def fake_run(**kwargs):
            await kwargs['on_connected']()
            # The carrier's view of an answered call whose AMD result was unknown; no transcript occurred.
            (kwargs['output_dir'] / 'phone-summary.json').write_text(json.dumps({'transport': 'sdk', 'status': 'ended',
                'twilio_status': 'completed', 'call_sid': CHILD, 'sdk_child_sid': CHILD, 'answered_by': 'unknown',
                'delivery': {'kind': 'human', 'human_conversation_confirmed': False}}))
            return {}
        temp_dir = tempfile.TemporaryDirectory(); self.addCleanup(temp_dir.cleanup); temp = temp_dir.name
        with patch('phone_call.preflight'), \
                patch('sdk_adapter.SdkAdapter', return_value=adapter), patch.object(sdk_phone, 'run', fake_run), \
                patch.object(voice_session.CheckinApp, 'request', request), patch.object(voice_session.CheckinApp, 'close', AsyncMock()):
            await voice_session.conduct(Path(temp) / 'evidence', Path(temp) / 'dial.slot', '+15551112222', TARGET, 'Build',
                settings={'phone_transport': 'sdk', 'spoken_disclosure': False, 'voicemail_enabled': True, 'assistant_name': 'Nova'},
                briefing='The build finished.', outcome='complete', recipient={'name': 'Alex'})
        texts = [p['text'] for m, p in sent if m == 'thread/realtime/appendText']
        self.assertEqual(len(texts), 1); text = texts[0]
        self.assertNotIn('human', text.lower())  # The shared signal no longer asserts a human answered.
        self.assertIn('connected', text); self.assertIn('Greet the participant and begin the supplied briefing', text)
        self.assertIn('not a user statement or confirmation', text)
        self.assertTrue(adapter.input_ready.is_set())
        result = json.loads((Path(temp) / 'evidence/result.json').read_text())
        self.assertEqual(result['answered_by'], 'unknown')  # Actual AMD value, never rewritten.
        self.assertEqual(result['delivery'], {'kind': 'human', 'human_conversation_confirmed': False})
        self.assertEqual(result['checkin_status'], 'partial_or_failed')  # No real transcript: not review_required.

    def test_recipient_framing_is_unchanged(self):
        app = voice_session.CheckinApp({}, 'Build', {'assistant_name': 'Nova', 'participant_name': 'Jordan'},
                                       'The build finished.', 'complete', {'name': 'Alex'})
        supplied = json.loads(app.brief['text'].rsplit('Supplied context:\n', 1)[1])
        self.assertEqual(supplied['recipient_name'], 'Alex'); self.assertNotIn('Jordan', app.brief['text'])


if __name__ == '__main__':
    unittest.main()

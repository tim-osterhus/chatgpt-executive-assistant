"""No browser/provider: observable SDK controller HTTP, media and teardown guards."""
import asyncio
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock,Mock,patch

from aiohttp import ClientSession
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from phone_bridge import signature
from sdk_phone import SdkPhone, listen
import sdk_phone

AC='AC'+'1'*32;AP='AP'+'2'*32;PARENT='CA'+'3'*32;CHILD='CA'+'4'*32

class PhoneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.output=Path(self.temp.name)
        self.adapter=type('Adapter',(),{'phone_audio':AsyncMock()})()
        self.connected=AsyncMock();self.voicemail=AsyncMock()
        self.phone=SdkPhone(state_root=self.output/'state',output=self.output,request_id='exact-sdk-test',
            account=AC,token='test-auth-token',credentials={'app_sid':AP,'key_sid':'SK'+'5'*32,'key_secret':'test'},
            source='+15551112222',target='+15553334444',adapter=self.adapter,max_seconds=2700,ringing=60,
            voicemail_enabled=True,on_connected=self.connected,on_voicemail=self.voicemail)
        self.phone.journal.claim();self.phone.public_base='https://example.trycloudflare.com'
        self.runners=[];self.client=ClientSession()
    async def asyncTearDown(self):
        for task in self.phone.tasks:task.cancel()
        await asyncio.gather(*self.phone.tasks,return_exceptions=True)
        await self.client.close()
        for runner in self.runners:await runner.cleanup()
        self.phone.wav_in.close();self.phone.wav_out.close();self.phone.events.close();self.temp.cleanup()
    async def local(self):
        runner,port=await listen(self.phone.local_app());self.runners.append(runner)
        self.phone.local_origin='http://127.0.0.1:'+str(port);return self.phone.local_origin
    async def public(self):
        runner,port=await listen(self.phone.public_app());self.runners.append(runner)
        return 'http://127.0.0.1:'+str(port)
    def signed(self,path,data):
        return {'X-Twilio-Signature':signature('test-auth-token',self.phone.public_base+path,data)}
    async def test_config_uses_callable_access_token_not_auth_token_and_rejects_wrong_origin(self):
        origin=await self.local();self.phone.access_token=AsyncMock(return_value='local-test-jwt')
        async with self.client.post(origin+'/config',headers={'Origin':origin,'X-Renderer-Control':self.phone.control}) as response:
            self.assertEqual(response.status,200);self.assertEqual((await response.json())['token'],'local-test-jwt')
        self.phone.access_token.assert_awaited_once()
        async with self.client.post(origin+'/config',headers={'Origin':'http://elsewhere','X-Renderer-Control':self.phone.control}) as response:
            self.assertEqual(response.status,403)
        self.phone.close_fence('stop')
        async with self.client.post(origin+'/config',headers={'Origin':origin,'X-Renderer-Control':self.phone.control}) as response:self.assertEqual(response.status,409)
    async def test_early_close_signed_late_voice_cannot_dial_and_retains_parent(self):
        origin=await self.public();path='/voice/'+self.phone.nonce
        self.phone.journal.update(status='claimed',dial_attempted=True)
        self.phone.close_fence('abort')
        data={'AccountSid':AC,'CallSid':PARENT,'From':'client:'+self.phone.identity,'Intent':'exact-sdk-test'}
        async with self.client.post(origin+path,data=data,headers=self.signed(path,data)) as response:
            self.assertEqual(response.status,200);self.assertNotIn('<Dial',await response.text())
        self.assertEqual(self.phone.journal.data['parent_sid'],PARENT)
        self.assertFalse(self.phone.journal.data.get('dial_returned',False))
    async def test_voice_one_dial_and_auth_binding(self):
        origin=await self.public();path='/voice/'+self.phone.nonce;self.phone.journal.update(status='claimed')
        data={'AccountSid':AC,'CallSid':PARENT,'From':'client:'+self.phone.identity,'Intent':'exact-sdk-test'}
        async with self.client.post(origin+path,data=data) as response:self.assertEqual(response.status,403)
        for expected in (True,False):
            async with self.client.post(origin+path,data=data,headers=self.signed(path,data)) as response:
                self.assertEqual('<Dial' in await response.text(),expected)
        self.assertTrue(self.phone.journal.data['dial_returned'])
    async def test_codec_pending_then_opus_and_exact_answer_gate(self):
        self.phone.journal.update(parent_sid=PARENT,child_sid=CHILD,child_status='in-progress')
        await self.phone.media_event({'type':'codec','codec':None});self.assertIsNone(self.phone.mode)
        self.phone.answered_by='human'
        await self.phone.media_event({'type':'codec','codec':'opus'});await self.phone.mode_task
        self.connected.assert_awaited_once();self.assertEqual(self.phone.mode,'human')
        self.phone.maybe_open_audio();self.connected.assert_awaited_once()
    async def test_machine_gate_ambiguous_and_pcm_replay(self):
        self.phone.codec='opus';self.phone.journal.update(child_status='in-progress')
        for answer in ('fax','machine_end_other'):  # AMD unknown is interactive: tests/test_sdk_amd_unknown.py
            self.phone.answered_by=answer;self.phone.maybe_open_audio();self.assertIsNone(self.phone.mode)
        self.phone.answered_by='machine_end_silence';self.phone.maybe_open_audio();await self.phone.mode_task
        self.voicemail.assert_awaited_once_with(self.phone)
        packet=struct.pack('<I',1)+bytes(1920);await self.phone.media_binary(packet)
        with self.assertRaisesRegex(RuntimeError,'sequence'):await self.phone.media_binary(packet)
    async def test_explicit_pcmu_stops_without_opening_audio(self):
        await self.phone.media_event({'type':'codec','codec':'pcmu'})
        self.assertTrue(self.phone.closing);self.assertIsNone(self.phone.mode);self.assertEqual(self.phone.failure,'unsupported_sdk_codec')

    async def test_source_failure_rejects_pending_drain_instead_of_success_or_timeout(self):
        self.phone.ws=type('Socket',(),{'closed':False,'send_json':AsyncMock()})()
        task=asyncio.create_task(self.phone.drain())
        await asyncio.sleep(0)
        self.phone.fail('sdk_source_failed')
        with self.assertRaisesRegex(RuntimeError,'sdk_source_failed'):await task

    async def test_sender_does_not_accumulate_websocket_overhead_into_audio_clock(self):
        clock=[100.0];packets=[]
        async def send(packet):packets.append(packet);clock[0]+=.003
        async def sleep(delay):clock[0]+=delay
        self.phone.ws=type('Socket',(),{'closed':False,'send_bytes':staticmethod(send)})()
        self.phone.mode='human';self.phone.codec='opus'
        with patch.object(sdk_phone.time,'monotonic',lambda:clock[0]),patch.object(sdk_phone.asyncio,'sleep',sleep):
            for _ in range(100):await self.phone.send_pcm(bytes(1920))
        self.assertAlmostEqual(self.phone.next_send,102.0,places=7)
        self.assertEqual(self.phone.sent_samples,96000)
        self.assertEqual([struct.unpack('<I',p[:4])[0] for p in packets],list(range(1,101)))

    async def test_drain_ack_must_match_exact_finite_consumed_boundary(self):
        sent=asyncio.Event();commands=[]
        async def send(data):commands.append(data);sent.set()
        self.phone.ws=type('Socket',(),{'closed':False,'send_json':staticmethod(send)})()
        self.phone.sent_seq=5;self.phone.sent_samples=4800
        task=asyncio.create_task(self.phone.drain());await sent.wait();boundary=commands[0]
        bad={**boundary,'type':'drained','accepted':4800,'consumed':4799,'sampleRate':48000}
        with self.assertRaisesRegex(RuntimeError,'boundary_mismatch'):await self.phone.media_event(bad)
        good={**bad,'consumed':4800};await self.phone.media_event(good)
        self.assertEqual((await task)['consumed'],4800)
        with self.assertRaisesRegex(RuntimeError,'unexpected_sdk_drain_ack'):await self.phone.media_event(good)

    async def test_provider_and_source_cleanup_errors_do_not_skip_other_owned_teardown(self):
        root=self.output/'controller';output=root/'runs/exact/evidence';output.mkdir(parents=True)
        (root/'.state/plugin-requests').mkdir(parents=True)
        adapter=Mock();adapter.peer.close=AsyncMock(side_effect=RuntimeError('source close failed'))
        public=Mock();public.cleanup=AsyncMock()
        tunnel=Mock(returncode=None)
        async def wait():tunnel.returncode=0;return 0
        tunnel.wait=wait
        calls=[]
        class API:
            def __init__(self,*args):pass
            async def request(self,method,resource,data=None,params=None):
                calls.append((method,resource,data))
                if method=='GET':return {'sid':AP,'account_sid':AC}
                raise RuntimeError('private provider body')
        before=AsyncMock();stop_renderer=AsyncMock(side_effect=RuntimeError('renderer failure'))
        with patch.object(sdk_phone,'ROOT',root),patch.object(sdk_phone,'CallAPI',API),\
                patch.object(sdk_phone,'listen',AsyncMock(return_value=(public,12345))),\
                patch.object(sdk_phone,'start_tunnel',AsyncMock(return_value=(tunnel,None,'https://example.trycloudflare.com'))),\
                patch.object(sdk_phone,'wait_for_tunnel_health',AsyncMock()),\
                patch.object(SdkPhone,'stop_renderer',stop_renderer),\
                patch.dict('os.environ',{'TWILIO_ACCOUNT_SID':AC,'TWILIO_AUTH_TOKEN':'test','TWILIO_FROM_NUMBER':'+15551112222'}):
            summary=await sdk_phone.run(adapter=adapter,credentials={'app_sid':AP},output_dir=output,target='+15553334444',
                on_connected=AsyncMock(),on_voicemail=AsyncMock(),before_dial=before,
                stop_event=asyncio.Event(),before_human_drain=AsyncMock())
        self.assertEqual(summary['status'],'failed');self.assertFalse(summary['admission_restored'])
        self.assertTrue((root/'.state/sdk-transport/active.json').exists())
        self.assertTrue(any(data=={'VoiceUrl':'','StatusCallback':''} for _,_,data in calls))
        stop_renderer.assert_awaited_once();public.cleanup.assert_awaited_once();tunnel.terminate.assert_called_once()
        self.assertEqual(tunnel.returncode,0);before.assert_not_awaited()

    async def test_signed_dial_action_recovers_child_when_status_callback_and_list_are_missing(self):
        origin=await self.public();path='/action/'+self.phone.nonce
        self.phone.journal.update(parent_sid=PARENT,dial_returned=True)
        async def call(sid):
            return {'sid':sid,'from':'client:'+self.phone.identity,'status':'completed',
                'parent_call_sid':PARENT if sid==CHILD else None,'to':self.phone.target if sid==CHILD else 'client:'+self.phone.identity}
        self.phone.api=Mock();self.phone.api.call=call
        self.phone.api.request=AsyncMock(return_value={'calls':[]})
        self.phone.api.stop=AsyncMock(side_effect=lambda sid:{'sid':sid,'status':'completed','duration':'4'})
        data={'AccountSid':AC,'CallSid':PARENT,'CallStatus':'in-progress','DialCallSid':CHILD,'DialCallStatus':'completed'}
        async with self.client.post(origin+path,data=data,headers=self.signed(path,data)) as response:self.assertEqual(response.status,200)
        self.assertEqual(json.loads(self.phone.journal.path.read_text())['child_sid'],CHILD)
        self.assertTrue(await self.phone.reconcile_calls())
        self.assertEqual({row['sid'] for row in self.phone.journal.data['provider_calls']},{PARENT,CHILD})

    async def test_dial_returned_without_reconciled_child_keeps_owner_and_admission_closed(self):
        self.phone.journal.update(parent_sid=PARENT,dial_returned=True)
        self.phone.api=Mock()
        self.phone.api.call=AsyncMock(return_value={'sid':PARENT,'from':'client:'+self.phone.identity,'status':'completed'})
        self.phone.api.stop=AsyncMock(return_value={'sid':PARENT,'status':'completed'})
        self.phone.api.request=AsyncMock(return_value={'calls':[]})
        safe=await self.phone.reconcile_calls();self.assertFalse(safe)
        with self.assertRaises(RuntimeError):self.phone.journal.restore_admission(physical_safe=safe,local_stopped=True)
        self.assertTrue(self.phone.journal.marker.exists())

    async def test_action_child_is_saved_before_lookup_but_wrong_relationship_is_never_stopped(self):
        origin=await self.public();path='/action/'+self.phone.nonce
        self.phone.journal.update(parent_sid=PARENT,dial_returned=True)
        async def call(sid):
            if sid==CHILD:return {'sid':sid,'parent_call_sid':PARENT,'to':'some-other-recipient','status':'completed'}
            return {'sid':sid,'from':'client:'+self.phone.identity,'status':'completed'}
        self.phone.api=Mock();self.phone.api.call=call
        self.phone.api.request=AsyncMock(return_value={'calls':[]})
        self.phone.api.stop=AsyncMock(return_value={'sid':PARENT,'status':'completed'})
        data={'AccountSid':AC,'CallSid':PARENT,'DialCallSid':CHILD,'DialCallStatus':'completed'}
        async with self.client.post(origin+path,data=data,headers=self.signed(path,data)) as response:self.assertEqual(response.status,403)
        self.assertEqual(self.phone.journal.data['child_sid'],CHILD)
        with self.assertRaisesRegex(RuntimeError,'relationship_mismatch'):await self.phone.reconcile_calls()
        self.phone.api.stop.assert_awaited_once_with(PARENT)

    async def test_marker_publication_already_contains_recovery_identity(self):
        saved=json.loads(self.phone.journal.path.read_text())
        self.assertEqual(saved['app_sid'],AP);self.assertEqual(saved['identity'],self.phone.identity)
        self.assertEqual(len(saved['account_fingerprint']),64)
        from sdk_recovery import recover
        (self.phone.journal.root/'plugin-requests').mkdir()
        api=Mock();api.request=AsyncMock(return_value={'sid':AP,'account_sid':AC,'voice_url':''})
        with patch('sdk_recovery.stop_recorded',new_callable=AsyncMock),patch.object(SdkPhone,'stop_renderer',new_callable=AsyncMock):
            result=await recover(state_root=self.phone.journal.root,output=self.output,request_id='exact-sdk-test',
                account=AC,token='test',credentials={'app_sid':AP},target=self.phone.target,api=api)
        self.assertEqual(result['status'],'reconciled');self.assertFalse(self.phone.journal.marker.exists())

if __name__=='__main__':unittest.main()

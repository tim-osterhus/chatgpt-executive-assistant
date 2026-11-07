"""Crash recovery uses only recorded resources and never unlocks uncertainty."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from sdk_call_state import SdkCallState,unresolved
from sdk_recovery import recover
AC='AC'+'1'*32;AP='AP'+'2'*32;P='CA'+'3'*32;C='CA'+'4'*32
# Distinctive exception text; temp paths such as macOS /private/var never contain it.
SENTINEL='SYNTHETIC-EXCEPTION-TEXT-NEVER-IN-RECEIPTS'

class API:
    def __init__(self):self.operations=[];self.fail=False
    async def request(self,method,resource,data=None,params=None):
        self.operations.append((method,resource))
        if self.fail:raise RuntimeError(SENTINEL+'-provider-body')
        if resource.startswith('Applications/'):
            return {'sid':AP,'account_sid':AC,'voice_url':''}
        if resource=='Calls':return {'calls':[{'sid':C,'to':'fixed-target','parent_call_sid':P}]}
        raise AssertionError('unexpected operation')
    async def call(self,sid):
        self.operations.append(('GET','Calls/'+sid))
        return {'sid':sid,'account_sid':AC,'from':'client:exact-request','status':'completed'}
    async def stop(self,sid):
        return {'sid':sid,'status':'completed','duration':'3'}

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'plugin').mkdir();(self.root/'plugin-requests').mkdir();self.gate=self.root/'plugin/dial-enabled';self.gate.write_bytes(b'original')
        self.output=self.root/'runs/exact/evidence';self.call=SdkCallState(self.root,self.output,'exact-request');self.call.claim()
        self.call.before_connect();self.call.update(account_fingerprint=hashlib.sha256(AC.encode()).hexdigest(),app_sid=AP,identity='phone-exact-request',
            parent_sid=P,child_sid=C,dial_returned=True)
        self.api=API()
        # Correct SDK identity; API fixture derives it from the exact journal below.
        async def call(sid):return {'sid':sid,'account_sid':AC,'from':'client:phone-exact-request','status':'completed',
            'parent_call_sid':P if sid==C else None,'to':'fixed-target' if sid==C else 'client:phone-exact-request'}
        self.api.call=call
    def options(self):return dict(state_root=self.root,output=self.output,request_id='exact-request',account=AC,token='fake',credentials={'app_sid':AP},target='fixed-target',api=self.api)
    async def test_terminal_exact_calls_restore_gate_preserving_original_receipts(self):
        original=self.output/'phone-summary.json';original.write_text('{"original":true}')
        with patch('sdk_recovery.stop_recorded',new_callable=AsyncMock),patch('sdk_recovery.SdkPhone.stop_renderer',new_callable=AsyncMock):
            result=await recover(**self.options())
        self.assertEqual(result['status'],'reconciled');self.assertFalse(unresolved(self.root));self.assertEqual(self.gate.read_bytes(),b'original')
        self.assertEqual(original.read_text(),'{"original":true}')
        receipt=json.loads((self.output/'phone-summary.recovery.json').read_text())
        self.assertEqual({r['sid'] for r in receipt['sdk_leg_states']},{P,C});self.assertFalse(receipt['delivery']['provider_playback_confirmed'])
        self.assertFalse(any(op==('POST','Calls') for op in self.api.operations))
    async def test_provider_failure_still_attempts_every_local_cleanup_and_keeps_gate_closed(self):
        self.api.fail=True
        driver=AsyncMock(side_effect=RuntimeError(SENTINEL+'-local-detail'));renderer=AsyncMock()
        with patch('sdk_recovery.stop_recorded',driver),patch('sdk_recovery.SdkPhone.stop_renderer',renderer):result=await recover(**self.options())
        self.assertEqual(result['status'],'reconciliation_required');self.assertEqual(driver.await_count,2);renderer.assert_awaited_once()
        self.assertTrue(unresolved(self.root));self.assertFalse(self.gate.exists())
        self.assertNotIn(SENTINEL,json.dumps(result))
        self.assertNotIn(SENTINEL,(self.output/'phone-summary.recovery.json').read_text())
        # Only fixed stage names and exception class names are recorded.
        self.assertTrue(result['errors']);self.assertEqual({e['type'] for e in result['errors']},{'RuntimeError'})
        self.assertTrue({'app_route','driver','tunnel'}<={e['stage'] for e in result['errors']})
        self.assertTrue(all(set(e)=={'stage','type'} for e in result['errors']))
    async def test_wrong_account_or_owner_fails_before_any_provider_operation(self):
        options=self.options();options['account']='AC'+'9'*32
        with self.assertRaisesRegex(RuntimeError,'identity_mismatch'):await recover(**options)
        self.assertFalse(self.api.operations)

    def test_documented_cli_entrypoint_imports_and_shows_help_without_credentials(self):
        script=Path(__file__).resolve().parents[1]/'scripts/sdk_recover.py'
        result=subprocess.run([sys.executable,str(script),'--help'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('request_id',result.stdout)

if __name__=='__main__':unittest.main()

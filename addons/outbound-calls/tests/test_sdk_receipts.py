"""SDK receipt/admission semantics; no MCP/provider mutation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
try:
    import calling_mcp as mcp
except ModuleNotFoundError as exc:
    if exc.name != "mcp":
        raise
    raise unittest.SkipTest("Optional MCP tests require .plugin-venv; install requirements-plugin.lock") from exc
from call_runner import receipt
P='CA'+'1'*32;C='CA'+'2'*32
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.ledger=self.root/'ledger';self.ledger.mkdir();self.request={'request_id':'sdk-receipt','focus':'Test','briefing':'Known fact.'}
        self.run=self.root/'.state/runs/sdk-receipt';self.output=self.run/'evidence';self.output.mkdir(parents=True)
        self.good={**self.request,'transport':'sdk','status':'voicemail_submitted','call_id':C,'child_call_id':C,'parent_call_id':P,
            'carrier_status':'completed','answered_by':'machine_end_beep',
            'physical_calls_terminal':True,'local_resources_stopped':True,'admission_restored':True,
            'sdk_leg_states':[{'sid':P,'role':'sdk_parent','status':'completed'},{'sid':C,'role':'pstn_child','status':'completed'}],
            'delivery':{'kind':'voicemail','status':'submitted_local_drain','source_completion':'inferred_turn_done_and_receiver_quiet',
                'sdk_codec':'opus','finite_pcm_sealed':True,'local_queue_drained':True,'source_receiver_healthy_at_seal':True,
                'provider_playback_confirmed':False,'playback_completed':False,'submitted_pcm_samples':48000,
                'local_rendered_source_samples':48000,'local_rendered_padding_samples':96000}}
    def terminal(self,result):
        (self.ledger/'runner.stdout.json').write_text(json.dumps(result))
        with patch.object(mcp,'ROOT',self.root):return mcp._terminal_receipt(self.ledger,self.request)
    def test_submitted_is_terminal_but_never_provider_played_or_human_confirmed(self):
        result=self.terminal(self.good);self.assertEqual(result['status'],'voicemail_submitted')
        self.assertFalse(result['delivery']['provider_playback_confirmed'])
    def test_unresolved_parent_missing_drain_and_false_provider_claim_stay_pending(self):
        for change in ('parent','rows','drain','codec','proof','source','ambiguous'):
            value=copy.deepcopy(self.good)
            if change=='parent':value['sdk_leg_states'][0]['status']='in-progress'
            if change=='rows':value['sdk_leg_states']=[]
            if change=='drain':value['delivery']['local_rendered_source_samples']=47999
            if change=='codec':value['delivery']['sdk_codec']='pcmu'
            if change=='proof':value['delivery']['provider_playback_confirmed']=True
            if change=='source':value['delivery']['source_failure']='late_audio'
            if change=='ambiguous':value['answered_by']='machine_end_other'
            with self.subTest(change=change):self.assertIsNone(self.terminal(value))
    def test_recovery_overlay_releases_exact_id_without_rewriting_old_result(self):
        (self.run/'request.json').write_text(json.dumps(self.request));(self.run/'dial.slot').touch()
        original=json.dumps({'checkin_status':'partial_or_failed','phone_transport':'sdk','transcripts':[]})
        (self.output/'result.json').write_text(original)
        overlay={'transport':'sdk','request_id':'sdk-receipt','recovered':True,'call_sid':C,'sdk_child_sid':C,'sdk_parent_sid':P,
            'sdk_leg_states':self.good['sdk_leg_states'],'twilio_status':'completed','physical_calls_terminal':True,
            'local_resources_stopped':True,'admission_restored':True,'delivery':{'provider_playback_confirmed':False}}
        (self.output/'phone-summary.recovery.json').write_text(json.dumps(overlay))
        r=receipt(self.run,self.request);self.assertEqual(r['status'],'partial_or_failed');self.assertEqual(r['call_id'],C)
        self.assertEqual((self.output/'result.json').read_text(),original)
        self.assertIsNotNone(self.terminal(r))
        (self.ledger/'request.json').write_text(json.dumps(self.request))
        with patch.object(mcp,'ROOT',self.root):self.assertFalse(mcp._is_unresolved(self.ledger))
    def test_consumed_slot_before_any_dial_can_finish_only_with_safe_cleanup(self):
        value={**self.good,'status':'partial_or_failed','call_id':None,'child_call_id':None,'parent_call_id':None,
            'sdk_leg_states':[],'sdk_safe_before_phone_leg':True,'phone_dial_returned':False,'delivery':None}
        self.assertIsNotNone(self.terminal(value));value['local_resources_stopped']=False;self.assertIsNone(self.terminal(value))
if __name__=='__main__':unittest.main()

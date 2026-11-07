import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from sdk_call_state import SdkCallState, unresolved


class CallStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'plugin-requests').mkdir();(self.root/'plugin').mkdir()
        self.gate=self.root/'plugin/dial-enabled';self.gate.write_bytes(b'original\n');self.gate.chmod(0o600)
        self.call=SdkCallState(self.root,self.root/'runs/exact/evidence','exact-request');self.call.claim()
    def tearDown(self):self.temp.cleanup()
    def test_unresolved_attempt_blocks_replacement_and_close_is_durable(self):
        self.assertTrue(unresolved(self.root))
        replacement=SdkCallState(self.root,self.root/'runs/other/evidence','other-request')
        with self.assertRaises(FileExistsError):replacement.claim()
        self.call.before_connect();self.call.close_fence('stop')
        saved=json.loads(self.call.path.read_text());self.assertTrue(saved['closing']);self.assertFalse(self.gate.exists())
        restored=SdkCallState(self.root,self.call.output,'exact-request',recover=True)
        self.assertEqual(restored.data,saved)
    def test_uncertain_phone_or_local_process_never_restores_admission(self):
        self.call.before_connect();self.call.close_fence('failure')
        for physical,local in ((False,True),(True,False)):
            with self.assertRaises(RuntimeError):self.call.restore_admission(physical_safe=physical,local_stopped=local)
        self.assertFalse(self.gate.exists());self.assertTrue(unresolved(self.root))
    def test_terminal_cleanup_restores_exact_gate_and_releases_owner(self):
        self.call.before_connect();self.call.close_fence('done')
        self.call.restore_admission(physical_safe=True,local_stopped=True)
        self.assertEqual(self.gate.read_bytes(),b'original\n');self.assertEqual(self.gate.stat().st_mode&0o777,0o600)
        self.assertFalse(unresolved(self.root));self.assertEqual(self.call.data['status'],'terminal')
    def test_before_dial_failure_does_not_enable_an_originally_disabled_gate(self):
        self.gate.unlink();self.call.close_fence('setup_failure')
        self.call.restore_admission(physical_safe=True,local_stopped=True)
        self.assertFalse(self.gate.exists())


if __name__=='__main__':unittest.main()

import asyncio
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from sdk_adapter import SdkAdapter
class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_phone_capture_after_source_seal_cannot_overflow_closed_live_input(self):
        adapter=SdkAdapter();adapter.input_ready.set()
        await adapter.phone_audio(bytes(1920));self.assertEqual(adapter.peer.input.queue.qsize(),1)
        adapter.seal_output();await adapter.peer.close()
        for _ in range(30):await adapter.phone_audio(bytes(1920))
        self.assertEqual(adapter.peer.input.queue.qsize(),1);self.assertFalse(adapter.input_ready.is_set())
    async def test_active_input_overflow_remains_failure(self):
        adapter=SdkAdapter();adapter.input_ready.set()
        try:
            for _ in range(15):await adapter.phone_audio(bytes(1920))
            with self.assertRaisesRegex(RuntimeError,'backpressure'):await adapter.phone_audio(bytes(1920))
        finally:await adapter.close()
if __name__=='__main__':unittest.main()

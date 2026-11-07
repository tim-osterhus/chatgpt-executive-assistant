"""SDK-only 48 kHz PCM adapter for the existing Live MediaPeer.

The legacy RoomAdapter is independent. No microphone or LiveKit codec hop is
needed for this transport; the owned renderer supplies/consumes PCM20ms frames.
"""
import asyncio
import audioop

from app_server import FRAME_SAMPLES, MediaPeer, RATE, pcm_fixture


class SdkAdapter:
    def __init__(self):
        self.input_ready = asyncio.Event()
        self.peer = MediaPeer(self.provider_audio)
        self.bridge = None
        self.output_sealed = False

    async def provider_audio(self, pcm):
        if self.output_sealed:
            if self.bridge and not self.bridge.events.closed and audioop.rms(pcm,2)>100:
                self.bridge.fail('late_agent_audio_after_seal')
            return
        if self.input_ready.is_set() and not self.output_sealed:
            await self.capture(pcm)

    async def capture(self, pcm):
        if not self.bridge or self.output_sealed:
            raise RuntimeError('sdk_output_not_available')
        if len(pcm) != FRAME_SAMPLES * 2:
            raise RuntimeError('sdk_requires_48k_mono_pcm20ms')
        await self.bridge.send_pcm(pcm)

    async def phone_audio(self, pcm):
        if not self.input_ready.is_set():
            return  # Preserve the existing human/AMD input gate.
        if len(pcm) != FRAME_SAMPLES * 2 or self.peer.input.queue.full():
            raise RuntimeError('sdk_phone_input_backpressure_or_format')
        self.peer.input.queue.put_nowait(pcm)

    async def disclose(self, path):
        for pcm in pcm_fixture(path):
            await self.capture(pcm)
        await self.bridge.drain(finite=False, padding_samples=0)

    def seal_output(self):
        self.output_sealed = True
        # The caller capture graph keeps running while final output drains.
        # Stop feeding the now-closed Live receiver before its queue can fill.
        self.input_ready.clear()

    async def close(self):
        self.seal_output()
        await self.peer.close()

"""Connect Executive Assistant-shaped WebRTC media to the unmodified local Twilio room bridge."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets
import socket

from livekit import api, rtc

from app_server import environment, FRAME_SAMPLES, MediaPeer, pcm_fixture, RATE

SERVER = Path(__file__).resolve().parents[1] / "bin" / "livekit-server"


def local_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@asynccontextmanager
async def local_room(directory):
    """The loopback-only server and auth setup from grok-voice-3-local/run.py."""
    http_port = local_port(socket.SOCK_STREAM)
    key, secret = "local-" + secrets.token_hex(8), secrets.token_urlsafe(32)
    config = directory / "local-room.json"
    config.write_text(json.dumps({
        "port": http_port, "bind_addresses": ["127.0.0.1"], "keys": {key: secret},
        "rtc": {
            "tcp_port": 0, "udp_port": local_port(socket.SOCK_DGRAM), "node_ip": "127.0.0.1",
            "use_external_ip": False, "enable_loopback_candidate": True,
            "ips": {"includes": ["127.0.0.1/32"]}, "stun_servers": [],
        }, "turn": {"enabled": False}, "logging": {"level": "error"},
    }))
    server = None
    try:
        server = await asyncio.create_subprocess_exec(
            str(SERVER), "--config", str(config), cwd=directory, env=environment(),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        async with asyncio.timeout(10):
            while True:
                if server.returncode is not None:
                    raise RuntimeError("isolated LiveKit server exited")
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", http_port)
                    writer.close()
                    await writer.wait_closed()
                    break
                except ConnectionRefusedError:
                    await asyncio.sleep(.1)

        room_name = "codex-pilot-" + secrets.token_hex(6)

        def token(identity):
            return api.AccessToken(key, secret).with_identity(identity).with_grants(
                api.VideoGrants(room_join=True, room=room_name)
            ).to_jwt()

        yield f"ws://127.0.0.1:{http_port}", token
    finally:
        if server and server.returncode is None:
            server.terminate()
            try:
                await asyncio.wait_for(server.wait(), 3)
            except TimeoutError:
                server.kill()
                await server.wait()
        config.unlink(missing_ok=True)


class RoomAdapter:
    def __init__(self):
        self.room = rtc.Room()
        self.source = None
        self.input_ready = asyncio.Event()
        self.phone_input = None
        self.peer = MediaPeer(self.provider_audio)

        @self.room.on("track_subscribed")
        def subscribed(track, publication, participant):
            if participant.identity == "phone" and track.kind == rtc.TrackKind.KIND_AUDIO and self.phone_input is None:
                self.phone_input = asyncio.create_task(self.phone_audio(track))

    async def connect(self, url, token):
        await self.room.connect(url, token)
        self.source = rtc.AudioSource(RATE, 1, queue_size_ms=80)
        track = rtc.LocalAudioTrack.create_audio_track("codex-provider", self.source)
        await self.room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

    async def phone_audio(self, track):
        stream = rtc.AudioStream.from_track(
            track=track, sample_rate=RATE, num_channels=1, frame_size_ms=20, capacity=12
        )
        try:
            async for event in stream:
                if self.input_ready.is_set():
                    queue = self.peer.input.queue
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(event.frame.data.tobytes())
        finally:
            await stream.aclose()

    async def capture(self, pcm):
        await self.source.capture_frame(rtc.AudioFrame(pcm, RATE, 1, FRAME_SAMPLES))

    async def disclose(self, path):
        for pcm in pcm_fixture(path):
            await self.capture(pcm)
        await self.source.wait_for_playout()

    async def provider_audio(self, pcm):
        if self.input_ready.is_set():
            await self.capture(pcm)

    async def close(self):
        await self.peer.close()
        if self.phone_input:
            self.phone_input.cancel()
            await asyncio.gather(self.phone_input, return_exceptions=True)
        await self.room.disconnect()
        if self.source:
            await self.source.aclose()

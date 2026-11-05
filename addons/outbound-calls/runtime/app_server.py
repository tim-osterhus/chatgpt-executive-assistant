"""Sandboxed Codex App Server V3 WebRTC media probe. No telephone client."""
from __future__ import annotations

import asyncio
import audioop
import contextlib
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import shutil
import wave
import uuid

from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame, AudioResampler

ROOT = Path(__file__).resolve().parent
STATE = ROOT.parent / ".state"
FRAME_SAMPLES = 960
RATE = 48000
SILENCE = bytes(FRAME_SAMPLES * 2)


class PilotError(RuntimeError):
    pass


def environment():
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(STATE / "home"), "CODEX_HOME": str(STATE / "profile"),
        "TMPDIR": str(STATE / "tmp"), "XDG_CACHE_HOME": str(STATE / "cache"),
        "LANG": "en_US.UTF-8", "NO_COLOR": "1",
    }


def pcm_fixture(path):
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise PilotError("fixture_requires_48k_mono_pcm16")
        pcm = wav.readframes(wav.getnframes())
    return [pcm[i:i + len(SILENCE)].ljust(len(SILENCE), b"\0")
            for i in range(0, len(pcm), len(SILENCE))]


class InputTrack(AudioStreamTrack):
    """A paced 48k mono track with silence when no external media is queued."""

    def __init__(self):
        super().__init__()
        self.queue = asyncio.Queue(maxsize=15)
        self.fixture = iter(())
        self.frames_with_signal = 0

    async def recv(self):
        clock_frame = await super().recv()
        pcm = next(self.fixture, None)
        if pcm is None:
            pcm = self.queue.get_nowait() if not self.queue.empty() else SILENCE
        if audioop.rms(pcm, 2) > 100:
            self.frames_with_signal += 1
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.planes[0].update(pcm)
        frame.sample_rate = RATE
        frame.pts = clock_frame.pts * 6
        frame.time_base = Fraction(1, RATE)
        return frame


class MediaPeer:
    def __init__(self, emit_pcm):
        self.connection = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.input = InputTrack()
        self.connection.addTrack(self.input)
        self.channel = self.connection.createDataChannel("oai-events")
        self.connected = asyncio.Event()
        self.received_signal = asyncio.Event()
        self.frames_with_signal = 0
        self.frames_received = 0
        self.reader = None
        self.emit_pcm = emit_pcm

        @self.connection.on("connectionstatechange")
        def state_changed():
            if self.connection.connectionState == "connected":
                self.connected.set()

        @self.connection.on("track")
        def track_received(track):
            if track.kind == "audio" and self.reader is None:
                self.reader = asyncio.create_task(self.receive_audio(track))

    async def offer(self):
        await self.connection.setLocalDescription(await self.connection.createOffer())
        return self.connection.localDescription.sdp

    async def answer(self, sdp):
        await self.connection.setRemoteDescription(RTCSessionDescription(sdp, "answer"))
        await asyncio.wait_for(self.connected.wait(), 15)

    async def receive_audio(self, track):
        convert = AudioResampler(format="s16", layout="mono", rate=RATE, frame_size=FRAME_SAMPLES)
        while True:
            for frame in convert.resample(await track.recv()):
                pcm = bytes(frame.planes[0])[:len(SILENCE)]
                self.frames_received += 1
                if audioop.rms(pcm, 2) > 100:
                    self.frames_with_signal += 1
                    if self.frames_with_signal >= 10:
                        self.received_signal.set()
                await self.emit_pcm(pcm)

    async def close(self):
        if self.reader is not None:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        self.input.stop()
        await self.connection.close()


def error_category(message):
    value = message.lower()
    for words, category in (
        (("401", "unauthorized", "not logged", "authentication"), "authentication"),
        (("403", "forbidden", "permission", "entitlement"), "permission"),
        (("404", "not found"), "route_or_model_not_found"),
        (("429", "rate limit", "quota"), "rate_limit"),
        (("sdp", "webrtc", "ice", "dtls"), "webrtc_negotiation"),
        (("unsupported", "not supported", "invalid"), "unsupported_or_invalid"),
    ):
        if any(word in value for word in words):
            return category
    return "unclassified"


class AppServer:
    def __init__(self, result):
        self.result = result
        self.thread_id = None
        self.session_id = str(uuid.uuid4())
        self.pending = {}
        self.sequence = 0
        self.started = asyncio.Event()
        self.sdp_ready = asyncio.Event()
        self.closed = asyncio.Event()
        self.transcribed = asyncio.Event()
        self.failed = asyncio.Event()
        self.sdp = None
        self.transcripts = []
        self.process = None
        self.reader = None
        self.start_requested = False

    async def open(self, cwd):
        self.process = await asyncio.create_subprocess_exec(
            shutil.which("codex"), "app-server", "--listen", "stdio://", "--enable", "realtime_conversation",
            "-c", 'forced_login_method="chatgpt"', "-c", 'cli_auth_credentials_store="file"',
            "-c", "check_for_update_on_startup=false", "-c", "analytics.enabled=false",
            "-c", "feedback.enabled=false", cwd=cwd, env=environment(), limit=1_048_576,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        self.reader = asyncio.create_task(self.read())
        await self.request("initialize", {
            "clientInfo": {"name": "isolated-codex-voice-test", "version": "0.1"},
            "capabilities": {"experimentalApi": True},
        })
        await self.send({"method": "initialized"})
        account = (await self.request("account/read", {"refreshToken": False})).get("account")
        self.result["account_type"] = account["type"] if account else None
        if self.result["account_type"] != "chatgpt":
            raise PilotError("isolated_chatgpt_login_required")
        voices = (await self.request("thread/realtime/listVoices", {}))["voices"]
        self.result["sol_listed"] = "sol" in voices["v2"] or "sol" in voices["v1"]
        self.thread_id = (await self.request("thread/start", {
            "cwd": str(cwd), "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "never",
            "developerInstructions": "User-authorized assistant phone call. No tools, delegation, or other side effects.",
        }))["thread"]["id"]
        self.result.update(thread_id=self.thread_id, requested_realtime_session_id=self.session_id)

    async def send(self, message):
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        await self.process.stdin.drain()

    async def request(self, method, params):
        self.sequence += 1
        id_ = self.sequence
        waiter = self.pending[id_] = asyncio.get_running_loop().create_future()
        try:
            await self.send({"id": id_, "method": method, "params": params})
            response = await asyncio.wait_for(waiter, 22 if method == "thread/realtime/start" else 7)
        finally:
            self.pending.pop(id_, None)
        if "error" in response:
            err = response["error"]
            self.result["rpc_error"] = {
                "method": method, "code": err.get("code"),
                "category": error_category(err.get("message", "")),
            }
            raise PilotError("app_server_rpc_rejected")
        return response["result"]

    async def read(self):
        try:
            while line := await self.process.stdout.readline():
                msg = json.loads(line)
                if "id" in msg:
                    if "method" in msg:
                        await self.send({"id": msg["id"], "error": {"code": -32601, "message": "Unavailable in isolated voice test"}})
                    elif (waiter := self.pending.get(msg["id"])) is not None and not waiter.done():
                        waiter.set_result(msg)
                    continue
                p = msg.get("params") or {}
                if not self.thread_id or p.get("threadId") != self.thread_id:
                    continue
                method = msg.get("method")
                if method == "thread/realtime/started":
                    self.result["observed_realtime_session_id"] = p.get("realtimeSessionId")
                    self.result["version"] = p.get("version")
                    self.started.set()
                elif method == "thread/realtime/sdp":
                    self.sdp = p["sdp"]
                    self.sdp_ready.set()
                elif method == "thread/realtime/transcript/done":
                    self.transcripts.append({"role": p["role"], "text": p["text"]})
                    self.transcribed.set()
                elif method == "thread/realtime/closed":
                    self.closed.set()
                elif method == "thread/realtime/error":
                    self.result["provider_error_category"] = error_category(p.get("message", ""))
                    self.failed.set()
        finally:
            if not self.closed.is_set():
                self.result.setdefault("provider_error_category", "app_server_stream_closed")
                self.failed.set()
            for waiter in self.pending.values():
                if not waiter.done():
                    waiter.set_exception(PilotError("app_server_stream_closed"))

    async def until(self, condition, timeout):
        waits = [asyncio.create_task(event.wait()) for event in (condition, self.failed)]
        try:
            ready, _ = await asyncio.wait(waits, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if self.failed.is_set():
                raise PilotError("provider_realtime_error")
            if not ready:
                raise PilotError("provider_event_timeout")
        finally:
            for task in waits:
                task.cancel()
            await asyncio.gather(*waits, return_exceptions=True)

    async def start(self, peer, prompt):
        offer = await peer.offer()
        self.result["offer_created"] = True
        self.start_requested = True
        await self.request("thread/realtime/start", {
            "threadId": self.thread_id, "outputModality": "audio", "voice": "sol",
            "transport": {"type": "webrtc", "sdp": offer}, "version": "v3",
            "model": "gpt-live-1-codex", "includeStartupContext": False,
            "realtimeSessionId": self.session_id, "clientManagedHandoffs": True,
            "codexResponsesAsItems": False, "codexResponseHandoffMode": "thinking", "prompt": prompt,
        })
        self.result["realtime_start_acknowledged"] = True
        await self.until(self.started, 15)
        if self.result["version"] != "v3":
            raise PilotError("unexpected_provider_version")
        observed = self.result["observed_realtime_session_id"]
        if observed and observed != self.session_id:
            raise PilotError("unexpected_realtime_session_id")
        await self.until(self.sdp_ready, 15)
        self.result["provider_answer_received"] = True
        await peer.answer(self.sdp)
        self.result["webrtc_connected"] = True

    async def close(self):
        if self.process is None:
            return
        if self.start_requested and self.process.returncode is None and not self.closed.is_set():
            with contextlib.suppress(PilotError, OSError, TimeoutError):
                await self.request("thread/realtime/stop", {"threadId": self.thread_id})
                self.result["stop_acknowledged"] = True
                await asyncio.wait_for(self.closed.wait(), 3)
        self.result["closed_notification"] = self.closed.is_set()
        if self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 4)
            except TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
        self.result["app_server_exit_code"] = self.process.returncode
        await asyncio.gather(self.reader, return_exceptions=True)

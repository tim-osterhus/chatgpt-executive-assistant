"""Single-use authenticated Twilio Media Stream to a loopback LiveKit room.

Contracts verified against Twilio Media Streams/WebSocket/security docs and
https://docs.livekit.io/transport/media/raw-tracks/ (2026-11-03).
"""
from __future__ import annotations

import asyncio
import audioop  # This isolated experiment is pinned to Python 3.12.
import base64
import hashlib
import hmac
import json
import time
import wave
from pathlib import Path

from aiohttp import web
from livekit import rtc


def signature(token: str, url: str, params=None) -> str:
    data = url
    for key in sorted(set(params or {})):
        values = params.getall(key) if hasattr(params, 'getall') else [params[key]]
        for value in sorted(set(values)):
            data += key + value
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def valid_signature(token: str, public_url: str, supplied: str, params=None) -> bool:
    # Twilio documents trailing-slash normalization for WebSocket handshakes.
    urls = [public_url, public_url.rstrip('/') + '/']
    if public_url.startswith('wss://'):
        urls += [u.replace('wss://', 'https://', 1) for u in urls]
    return bool(supplied) and any(hmac.compare_digest(signature(token, u, params), supplied) for u in urls)


class PhoneBridge:
    def __init__(self, *, auth_token, account_sid, nonce, output_dir, agent_identity='agent', on_connected=None):
        self.auth_token = auth_token
        self.account_sid = account_sid
        self.nonce = nonce
        self.output_dir = Path(output_dir)
        self.agent_identity = agent_identity
        self.on_connected = on_connected
        self.public_base = None
        self.call_sid = None
        self.sid_ready = asyncio.Event()
        self.started = asyncio.Event()
        self.ended = asyncio.Event()
        self.consumed = False
        self.failure = None
        self.clear_count = 0
        self.ws = None
        self.stream_sid = None
        self.room = rtc.Room()
        self.source = None
        self.tasks = set()
        self.track_seen = False
        self.t0 = time.monotonic()
        self.events = (self.output_dir / 'phone-events.jsonl').open('x')
        self.wav_in = self._wav('phone-caller.wav')
        self.wav_out = self._wav('phone-agent-submitted.wav')
        self.in_samples = self.out_samples = 0
        self.marks = {}
        self.mark_seq = 0
        self.drain_acks = {}
        self.runner = None

    def _wav(self, name):
        wav = wave.open(str(self.output_dir / name), 'wb')
        wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        return wav

    def log(self, event, **fields):
        self.events.write(json.dumps({'event': event, 'elapsed': round(time.monotonic()-self.t0, 4), **fields})+'\n')
        self.events.flush()

    def task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                self.failure = type(t.exception()).__name__
                self.log('bridge_task_failed', error_type=self.failure)
                self.ended.set()
        task.add_done_callback(done)
        return task

    async def prepare(self, room_url, room_token):
        if not room_url.startswith('ws://127.0.0.1:'):
            raise ValueError('Phone bridge requires loopback LiveKit')
        @self.room.on('track_subscribed')
        def subscribed(track, publication, participant):
            if participant.identity == self.agent_identity and track.kind == rtc.TrackKind.KIND_AUDIO:
                if self.track_seen:
                    self.failure = 'second_agent_track'; self.log('second_agent_track_rejected'); self.ended.set(); return
                self.track_seen = True
                self.task(self.send_audio(track))
        @self.room.on('reconnecting')
        def reconnecting():
            self.failure = 'rtc_reconnect'; self.log('rtc_reconnect_rejected'); self.ended.set()
        await self.room.connect(room_url, room_token)
        self.source = rtc.AudioSource(8000, 1, queue_size_ms=100)
        track = rtc.LocalAudioTrack.create_audio_track('phone-microphone', self.source)
        await self.room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        app = web.Application(client_max_size=16384)
        app.router.add_get('/media/'+self.nonce, self.websocket)
        app.router.add_post('/status/'+self.nonce, self.status)
        app.router.add_get('/health/'+self.nonce, lambda r: web.Response(text='ready'))
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        return site._server.sockets[0].getsockname()[1]

    def set_call_sid(self, sid):
        if self.call_sid is not None:
            raise RuntimeError('Single call already assigned')
        self.call_sid = sid
        self.sid_ready.set()
        self.log('call_created', call_sid=sid)

    async def status(self, request):
        params = await request.post()
        url = self.public_base + request.path
        if not valid_signature(self.auth_token, url, request.headers.get('X-Twilio-Signature', ''), params):
            raise web.HTTPForbidden()
        try:
            await asyncio.wait_for(self.sid_ready.wait(), 5)
        except TimeoutError:
            raise web.HTTPForbidden()
        if params.get('CallSid') != self.call_sid or params.get('AccountSid') != self.account_sid:
            raise web.HTTPForbidden()
        state = params.get('CallStatus', '')
        self.log('call_status', status=state)
        if state in {'completed', 'failed', 'busy', 'no-answer', 'canceled'}:
            self.ended.set()
        return web.Response(status=204)

    async def websocket(self, request):
        if not self.public_base or self.consumed:
            raise web.HTTPForbidden()
        url = self.public_base.replace('https://', 'wss://', 1) + request.path
        if not valid_signature(self.auth_token, url, request.headers.get('X-Twilio-Signature', '')):
            self.log('websocket_signature_rejected'); raise web.HTTPForbidden()
        self.consumed = True
        ws = web.WebSocketResponse(max_msg_size=16384, heartbeat=20)
        await ws.prepare(request)
        self.ws = ws
        self.log('websocket_authenticated')
        try:
            while not self.ended.is_set():
                message = await ws.receive(timeout=15 if not self.started.is_set() else 30)
                if message.type != web.WSMsgType.TEXT:
                    break
                data = json.loads(message.data)
                event = data.get('event')
                if event == 'connected':
                    continue
                if event == 'start':
                    if self.started.is_set(): raise ValueError('Duplicate start')
                    await asyncio.wait_for(self.sid_ready.wait(), 5)
                    start = data['start']
                    fmt = start['mediaFormat']
                    if (start.get('callSid') != self.call_sid or start.get('accountSid') != self.account_sid
                        or fmt != {'encoding': 'audio/x-mulaw', 'sampleRate': 8000, 'channels': 1}):
                        raise ValueError('Unexpected call or media format')
                    self.stream_sid = start['streamSid']
                    self.started.set(); self.log('stream_started', stream_sid=self.stream_sid)
                    if self.on_connected: await self.on_connected()
                    continue
                if not self.started.is_set() or data.get('streamSid') != self.stream_sid:
                    raise ValueError('Unexpected stream')
                if event == 'media':
                    if data['media'].get('track') != 'inbound': raise ValueError('Unexpected track')
                    pcm = audioop.ulaw2lin(base64.b64decode(data['media']['payload'], validate=True), 2)
                    if not pcm or len(pcm) > 16384: raise ValueError('Unexpected media size')
                    self.wav_in.writeframes(pcm)
                    if not self.in_samples: self.log('first_caller_audio')
                    self.in_samples += len(pcm)//2
                    await asyncio.wait_for(self.source.capture_frame(rtc.AudioFrame(pcm, 8000, 1, len(pcm)//2)), 2)
                elif event == 'mark':
                    name = data['mark']['name']
                    sent = self.marks.pop(name, None)
                    if name in self.drain_acks: self.drain_acks[name].set()
                    self.log('playout_mark_ack', name=name, roundtrip_seconds=None if sent is None else round(time.monotonic()-sent,4))
                elif event == 'stop':
                    self.log('stream_stopped'); break
                elif event == 'dtmf':
                    self.log('dtmf_received')  # Do not retain keypad digits.
        except Exception as exc:
            self.failure = type(exc).__name__
            self.log('stream_failed', error_type=self.failure)
        finally:
            self.ended.set()
            await ws.close()
        return ws

    async def send_audio(self, track):
        stream = rtc.AudioStream.from_track(track=track, sample_rate=8000, num_channels=1, frame_size_ms=20, capacity=10)
        frames = 0
        try:
            async for event in stream:
                if self.ended.is_set(): break
                if not self.started.is_set() or not self.ws or self.ws.closed: continue
                pcm = event.frame.data.tobytes()
                self.wav_out.writeframes(pcm)
                self.out_samples += len(pcm)//2
                if not frames: self.log('first_agent_audio_submitted')
                payload = base64.b64encode(audioop.lin2ulaw(pcm, 2)).decode()
                await asyncio.wait_for(self.ws.send_json({'event':'media', 'streamSid':self.stream_sid, 'media':{'payload':payload}}), 2)
                frames += 1
                if frames % 50 == 0:
                    self.mark_seq += 1; name = str(self.mark_seq)
                    self.marks[name] = time.monotonic()
                    await self.ws.send_json({'event':'mark', 'streamSid':self.stream_sid, 'mark':{'name':name}})
        finally:
            await stream.aclose()

    async def drain_playout(self):
        if not self.ws or self.ws.closed or not self.stream_sid: return False
        name = 'final-' + str(self.mark_seq + 1)
        ack = asyncio.Event()
        clear_count = self.clear_count
        self.drain_acks[name] = ack
        self.marks[name] = time.monotonic()
        await self.ws.send_json({'event':'mark', 'streamSid':self.stream_sid, 'mark':{'name':name}})
        try:
            await asyncio.wait_for(ack.wait(), 3)
            confirmed = clear_count == self.clear_count
            self.log('final_playout_mark_acknowledged', no_clear_since_mark=confirmed)
            return confirmed
        except TimeoutError:
            self.log('final_playout_mark_unconfirmed')
            return False
        finally:
            self.drain_acks.pop(name, None)

    async def clear(self):
        if self.ws and not self.ws.closed and self.stream_sid:
            self.clear_count += 1
            await self.ws.send_json({'event':'clear', 'streamSid':self.stream_sid})
            self.log('playout_clear_sent')

    async def close(self):
        self.ended.set()
        if self.ws: await self.ws.close()
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.runner: await self.runner.cleanup()
        await self.room.disconnect()
        if self.source: await self.source.aclose()
        self.wav_in.close(); self.wav_out.close()
        self.log('bridge_closed', caller_audio_seconds=self.in_samples/8000, submitted_agent_audio_seconds=self.out_samples/8000)
        self.events.close()

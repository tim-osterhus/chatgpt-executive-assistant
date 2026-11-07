"""Single owned SDK/PSTN call controller; the legacy transport is independent."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import struct
import time
import wave
from xml.sax.saxutils import escape, quoteattr

import aiohttp
from aiohttp import web

from phone_bridge import signature
from phone_call import start_tunnel, wait_for_tunnel_health
from sdk_call_state import SdkCallState, save
from sdk_installation import browser_executable as default_browser
from voicemail import AMD_TIMEOUT_SECONDS, PLAYABLE_MACHINE_RESULTS, SOURCE_RATE, VOICEMAIL_MAX_SECONDS

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(__file__).resolve().parent / 'sdk'
SID = re.compile(r'CA[0-9a-fA-F]{32}')
TERMINAL = {'completed', 'busy', 'no-answer', 'failed', 'canceled'}
PADDING_SAMPLES = SOURCE_RATE * 2
# Owned headless renderer startup, per stage. The first scheduled call reached ready about 32 to
# 38 seconds after driver spawn, past the former single 30-second wait. Each stage keeps a bound.
RENDERER_LAUNCH_SECONDS = 60  # driver spawn -> owned Chrome process reported
RENDERER_READY_SECONDS = 60   # owned Chrome process -> page reports generated audio ready
SAFE_REASON = re.compile(r'(?:sdk_|unexpected_sdk_)[a-z_]+')
# AMD "unknown" is inconclusive (for example initial silence after pickup): it enters the interactive
# path like "human", but the receipt keeps answered_by="unknown" and never claims a confirmed human.
INTERACTIVE_AMD_RESULTS = {'human', 'unknown'}
CHILD_STATUSES = {'queued', 'initiated', 'ringing', 'in-progress', 'answered', 'completed', 'busy', 'no-answer', 'failed', 'canceled'}


class CallAPI:
    """Only this owned App and exact Call resources; never REST call-create."""
    def __init__(self, session, account, token, app_sid):
        self.session, self.account, self.token, self.app_sid = session, account, token, app_sid

    async def request(self, method, resource, data=None, params=None):
        exact_call = re.fullmatch(r'Calls/CA[0-9a-fA-F]{32}', resource)
        if resource == 'Calls':
            allowed = method == 'GET' and params and SID.fullmatch(params.get('ParentCallSid', ''))
        elif exact_call:
            allowed = method == 'GET' or (method == 'POST' and data and set(data) == {'Status'}
                                         and data['Status'] in {'completed', 'canceled'})
        else:
            allowed = resource == 'Applications/' + self.app_sid and method in {'GET', 'POST'}
        if not allowed: raise RuntimeError('unsupported_sdk_provider_operation')
        url = f'https://api.twilio.com/2010-04-01/Accounts/{self.account}/{resource}.json'
        try:
            async with self.session.request(method, url, data=data, params=params,
                    auth=aiohttp.BasicAuth(self.account, self.token), timeout=aiohttp.ClientTimeout(total=15)) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400: raise RuntimeError('sdk_provider_request_failed')
                return payload
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise RuntimeError('sdk_provider_request_uncertain') from None

    async def call(self, sid):
        if not SID.fullmatch(sid): raise RuntimeError('exact_sdk_call_sid_required')
        value = await self.request('GET', 'Calls/' + sid)
        if value.get('account_sid') != self.account or value.get('sid') != sid:
            raise RuntimeError('sdk_call_account_or_identity_mismatch')
        return value

    async def stop(self, sid):
        value = await self.call(sid)
        if value['status'] not in TERMINAL:
            await self.request('POST', 'Calls/' + sid,
                               {'Status': 'completed' if value['status'] == 'in-progress' else 'canceled'})
        return await self.call(sid)


class SdkPhone:
    transport = 'sdk'
    def __init__(self, *, state_root, output, request_id, account, token, credentials,
                 source, target, adapter, max_seconds, ringing, voicemail_enabled,
                 on_connected, on_voicemail, browser_executable=None):
        self.output = Path(output)
        self.journal = SdkCallState(state_root, output, request_id)
        self.identity = 'phone-' + request_id
        # claim() durably saves this complete recovery identity BEFORE it
        # publishes active.json. A crash at that boundary remains recoverable.
        # The exact PSTN destination is part of that identity: recovery must not use a later default.
        self.journal.data.update(account_fingerprint=hashlib.sha256(account.encode()).hexdigest(),
                                 app_sid=credentials['app_sid'],identity=self.identity,target=target)
        self.nonce, self.control = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.account, self.token, self.credentials = account, token, credentials
        self.source, self.target, self.adapter = source, target, adapter
        self.max_seconds, self.ringing = max_seconds, ringing
        self.voicemail_enabled = voicemail_enabled
        self.on_connected, self.on_voicemail = on_connected, on_voicemail
        self.public_base = self.local_origin = None
        self.api = self.ws = None
        self.started = asyncio.Event(); self.ended = asyncio.Event(); self.renderer_ready = asyncio.Event()
        self.voicemail_started = asyncio.Event()
        self.closing = False; self.failure = None; self.mode = None; self.mode_task = None
        self.codec = None; self.answered_by = None; self.voicemail_capture = None
        self.voicemail_submitted = False; self.output_sealed = False
        self.sent_samples = 0; self.sent_seq = 0; self.received_seq = 0; self.rendered_samples = 0
        self.send_lock = asyncio.Lock(); self.progress = asyncio.Event(); self.drains = {}
        self.tasks = set(); self.t0 = time.monotonic()
        self.events = (self.output / 'sdk-events.jsonl').open('x')
        self.wav_in = self.wav('sdk-phone-in.wav'); self.wav_out = self.wav('sdk-agent-submitted.wav')
        self.local_drain = None
        self.next_send = None; self.last_clock = time.monotonic()
        self.driver = self.driver_reader = None; self.renderer_pid = self.renderer_profile = None
        self.renderer_launched = asyncio.Event(); self.startup = None
        self.renderer_temp = self.output / 'renderer-temp'
        self.browser_executable = browser_executable

    def wav(self, name):
        audio = wave.open(str(self.output / name), 'wb')
        audio.setparams((1, 2, SOURCE_RATE, 0, 'NONE', 'not compressed')); return audio

    def log(self, event, **fields):
        self.events.write(json.dumps({'event': event, 'elapsed': round(time.monotonic()-self.t0, 4), **fields})+'\n')
        self.events.flush()

    def task(self, coroutine):
        task = asyncio.create_task(coroutine); self.tasks.add(task)
        def finished(value):
            self.tasks.discard(value)
            if not value.cancelled() and value.exception(): self.fail(type(value.exception()).__name__)
        task.add_done_callback(finished); return task

    def close_fence(self, reason):
        self.closing = True; self.output_sealed = True
        self.journal.close_fence(reason)

    def fail(self, reason):
        if self.failure is None:
            self.failure = reason; self.log('sdk_failed', reason=reason)
        self.close_fence(reason); self.ended.set(); self.progress.set()
        for future,_ in self.drains.values():
            if not future.done():future.set_exception(RuntimeError(reason))

    def request_hangup(self, reason):
        self.close_fence(reason); self.ended.set()

    async def authenticated(self, request):
        if not self.public_base or request.query_string: raise web.HTTPForbidden()
        p = await request.post()
        if any(len(p.getall(key)) != 1 for key in p): raise web.HTTPForbidden()
        expected = signature(self.token, self.public_base + request.path, p)
        if (not secrets.compare_digest(expected, request.headers.get('X-Twilio-Signature', ''))
                or p.get('AccountSid') != self.account): raise web.HTTPForbidden()
        return p

    def remember_parent(self, sid):
        if not SID.fullmatch(sid): raise web.HTTPForbidden()
        state = self.journal.data
        if not state['parent_sid']: self.journal.update(parent_sid=sid)
        elif state['parent_sid'] != sid:
            extra = set(state.get('rejected_parent_sids', [])); extra.add(sid)
            self.journal.update(rejected_parent_sids=sorted(extra))

    async def voice(self, request):
        p = await self.authenticated(request)
        exact = (p.get('Intent') == self.journal.data['request_id']
                 and p.get('From') == 'client:' + self.identity and SID.fullmatch(p.get('CallSid', '')))
        if self.closing:
            if exact and self.journal.data['dial_attempted']: self.remember_parent(p['CallSid'])
            return web.Response(text='<Response><Hangup/></Response>', content_type='text/xml')
        if not exact or self.journal.data['status'] != 'claimed' or self.journal.data['parent_sid']:
            return web.Response(text='<Response><Hangup/></Response>', content_type='text/xml')
        self.journal.update(parent_sid=p['CallSid'], status='dialing', dial_returned=True)
        self.log('one_dial_returned', parent_sid=p['CallSid'])
        attrs = {'statusCallback': self.public_base+'/child/'+self.nonce,
                 'statusCallbackMethod': 'POST', 'statusCallbackEvent': 'initiated ringing answered completed'}
        if self.voicemail_enabled:
            attrs.update(machineDetection='DetectMessageEnd', machineDetectionTimeout=str(AMD_TIMEOUT_SECONDS),
                         amdStatusCallback=self.public_base+'/amd/'+self.nonce, amdStatusCallbackMethod='POST')
        xml = ('<Response><Dial callerId='+quoteattr(self.source)+' timeout='+quoteattr(str(self.ringing))
               +' timeLimit='+quoteattr(str(self.max_seconds))+' record="do-not-record" action='
               +quoteattr(self.public_base+'/action/'+self.nonce)+' method="POST"><Number '
               +' '.join(key+'='+quoteattr(value) for key,value in attrs.items())+'>'
               +escape(self.target)+'</Number></Dial><Hangup/></Response>')
        return web.Response(text=xml, content_type='text/xml')

    async def bind_child(self, p, *, amd=False):
        sid = p.get('CallSid', ''); state = self.journal.data
        if not SID.fullmatch(sid) or not state['parent_sid'] or sid == state['parent_sid']:
            raise web.HTTPForbidden()
        if state['child_sid'] and sid != state['child_sid']: raise web.HTTPForbidden()
        if amd:
            value = await self.api.call(sid)
            if value.get('parent_call_sid') != state['parent_sid'] or value.get('to') != self.target:
                raise web.HTTPForbidden()
            status = value['status']
        else:
            if p.get('ParentCallSid') != state['parent_sid'] or p.get('To') != self.target:
                raise web.HTTPForbidden()
            status = p.get('CallStatus')
        fields = {'child_sid': sid}
        if state.get('child_status') not in TERMINAL: fields['child_status'] = status
        self.journal.update(**fields)

    async def callback(self, request):
        p = await self.authenticated(request); kind = request.match_info['kind']
        if kind == 'child':
            await self.bind_child(p)
            # Status and elapsed only, so AMD versus carrier ordering is provable; no provider payload.
            status = p.get('CallStatus')
            self.log('authenticated_child_status', status=status if status in CHILD_STATUSES else 'other')
            if self.journal.data.get('child_status') in TERMINAL:
                if not self.closing: self.close_fence('carrier_ended')
                self.ended.set()
        elif kind == 'amd':
            if not self.voicemail_enabled: raise web.HTTPForbidden()
            await self.bind_child(p, amd=True)
            if self.answered_by is None:
                self.answered_by = p.get('AnsweredBy'); self.journal.update(answered_by=self.answered_by)
                self.log('authenticated_amd', answered_by=self.answered_by)
                if self.answered_by not in {*INTERACTIVE_AMD_RESULTS, *PLAYABLE_MACHINE_RESULTS}:
                    # A late result never replaces the first ending reason (for example carrier_ended).
                    if not self.closing: self.close_fence('amd_conservative_stop')
                    self.ended.set()
        elif kind in {'parent', 'action'}:
            if p.get('CallSid') != self.journal.data['parent_sid']: raise web.HTTPForbidden()
            if kind=='action' and p.get('DialCallSid'):
                sid=p['DialCallSid']
                if (not SID.fullmatch(sid) or sid==self.journal.data['parent_sid']
                        or self.journal.data['child_sid'] not in {None,sid}):raise web.HTTPForbidden()
                # Preserve the authenticated exact ID before a REST await can
                # fail. Reconciliation validates the relationship before stop.
                self.journal.update(child_sid=sid)
                value=await self.api.call(sid)
                if value.get('parent_call_sid')!=self.journal.data['parent_sid'] or value.get('to')!=self.target:
                    raise web.HTTPForbidden()
                self.journal.update(child_status=value['status'])
            self.journal.update(parent_status=p.get('CallStatus'))
            if p.get('CallStatus') in TERMINAL or (kind=='action' and p.get('DialCallStatus') in TERMINAL):
                if not self.closing: self.close_fence('carrier_ended')
                self.ended.set()
        else: raise web.HTTPNotFound()
        self.maybe_open_audio()
        if kind == 'action': return web.Response(text='<Response><Hangup/></Response>', content_type='text/xml')
        return web.Response(status=204)

    def maybe_open_audio(self):
        if (self.closing or self.mode is not None or self.codec != 'opus'
                or self.journal.data.get('child_status') != 'in-progress'): return
        answer = self.answered_by if self.voicemail_enabled else 'human'
        if answer in INTERACTIVE_AMD_RESULTS:
            self.mode = 'human'; self.started.set(); self.mode_task = self.task(self.on_connected())
        elif answer in PLAYABLE_MACHINE_RESULTS:
            self.mode = 'voicemail'; self.voicemail_started.set()
            self.mode_task = self.task(self.on_voicemail(self))
        if self.mode: self.log('sdk_audio_mode', mode=self.mode, codec=self.codec, answered_by=self.answered_by)

    def public_app(self):
        app = web.Application(client_max_size=16384)
        app.router.add_post('/voice/'+self.nonce, self.voice)
        app.router.add_post('/{kind:child|amd|parent|action}/'+self.nonce, self.callback)
        async def health(_): return web.Response(text='ready')
        app.router.add_get('/health/'+self.nonce, health)
        return app

    async def send_pcm(self, pcm):
        if len(pcm) != 1920: raise RuntimeError('sdk_requires_pcm16_mono_48k_20ms')
        async with self.send_lock:
            if self.output_sealed or self.failure or not self.ws or self.ws.closed:
                raise RuntimeError('sdk_output_closed')
            if self.mode not in {'human', 'voicemail'} or self.codec != 'opus':
                raise RuntimeError('sdk_audio_gate_not_ready')
            # Pace accepted source frames, including prerecorded disclosure. This
            # is a send clock, never evidence of drain or provider playback.
            now = time.monotonic()
            if self.next_send is not None and self.next_send > now:
                await asyncio.sleep(self.next_send-now)
            if self.closing or self.failure: raise RuntimeError('sdk_output_closing')
            self.sent_seq += 1
            await asyncio.wait_for(self.ws.send_bytes(struct.pack('<I', self.sent_seq)+pcm), 2)
            self.sent_samples += 960; self.wav_out.writeframesraw(pcm)
            # Advance the media timeline, not completion time: adding each
            # send/scheduler overhead starves the browser's exact48k clock.
            self.next_send = (self.next_send if self.next_send is not None else now) + .02

    async def drain(self, *, finite=True, padding_samples=PADDING_SAMPLES):
        if self.failure or not self.ws or self.ws.closed:
            raise RuntimeError('sdk_local_drain_not_available')
        async with self.send_lock:
            if finite: self.output_sealed = True
            identifier = secrets.token_hex(16)
            future = asyncio.get_running_loop().create_future()
            boundary = {'id': identifier, 'seq': self.sent_seq, 'samples': self.sent_samples,
                        'finite': finite, 'padding': padding_samples}
            self.drains[identifier] = (future, boundary)
            await self.ws.send_json({'type': 'drain', **boundary})
        try:
            # Maximum renderer queue1s + padding2s + bounded local scheduling3s.
            ack = await asyncio.wait_for(future, 6)
            if self.failure: raise RuntimeError(self.failure)
            self.local_drain = ack
            self.log('local_audio_consumed', source_samples=ack['consumed'], padding_samples=ack['padding'])
            return ack
        finally:
            self.drains.pop(identifier, None)

    async def media_event(self, data):
        kind = data.get('type')
        if kind == 'ready':
            if data.get('sample_rate') != 48000 or data.get('input_requests', 0) < 1:
                raise RuntimeError('sdk_renderer_format_or_generated_input_invalid')
            self.renderer_ready.set(); self.log('sdk_renderer_ready', sample_rate=48000)
        elif kind == 'codec':
            codec = data.get('codec')
            if not codec: return # Missing at accept is pending, not PCMU.
            if codec != 'opus': self.fail('unsupported_sdk_codec'); return
            self.codec = codec; self.journal.update(sdk_codec=codec); self.maybe_open_audio()
        elif kind == 'clock':
            if data.get('sampleRate') != 48000: raise RuntimeError('sdk_renderer_clock_rate_invalid')
            self.last_clock = time.monotonic()
        elif kind == 'drained':
            item = self.drains.get(data.get('id'))
            if item is None: raise RuntimeError('unexpected_sdk_drain_ack')
            future, boundary = item
            if (data.get('seq') != boundary['seq'] or data.get('accepted') != boundary['samples']
                    or data.get('consumed') != boundary['samples'] or data.get('padding') != boundary['padding']
                    or data.get('finite') != boundary['finite'] or data.get('sampleRate') != 48000):
                raise RuntimeError('sdk_drain_boundary_mismatch')
            if future.done(): raise RuntimeError('replayed_sdk_drain_ack')
            future.set_result(data)
        elif kind == 'failure':
            self.fail('sdk_renderer_failed')
        elif kind == 'disconnected':
            if not self.closing: self.close_fence('sdk_disconnected')
            self.ended.set()
        else:
            raise RuntimeError('unexpected_sdk_media_event')

    async def media_binary(self, packet):
        if len(packet) != 1924: raise RuntimeError('sdk_remote_pcm_format')
        seq = struct.unpack('<I', packet[:4])[0]
        if seq != self.received_seq + 1: raise RuntimeError('sdk_remote_pcm_sequence')
        self.received_seq = seq; self.wav_in.writeframesraw(packet[4:])
        if not self.closing: await self.adapter.phone_audio(packet[4:])

    async def media_socket(self, request):
        protocols = [value.strip() for value in request.headers.get('Sec-WebSocket-Protocol', '').split(',')]
        if (request.headers.get('Origin') != self.local_origin or self.control not in protocols
                or self.ws is not None): raise web.HTTPForbidden()
        self.ws = web.WebSocketResponse(protocols=('sdk-pcm',), max_msg_size=16384)
        await self.ws.prepare(request)
        try:
            async for message in self.ws:
                if message.type == aiohttp.WSMsgType.BINARY: await self.media_binary(message.data)
                elif message.type == aiohttp.WSMsgType.TEXT: await self.media_event(json.loads(message.data))
                elif message.type == aiohttp.WSMsgType.ERROR: raise RuntimeError('sdk_socket_transport_failed')
        except Exception as exc:
            reason=str(exc)
            self.fail(reason if re.fullmatch(r'(?:sdk_|unexpected_sdk_)[a-z_]+',reason) else type(exc).__name__)
        finally:
            if not self.closing: self.fail('sdk_renderer_socket_ended')
        return self.ws

    async def access_token(self):
        ttl = self.max_seconds + self.ringing + AMD_TIMEOUT_SECONDS + 60
        if ttl > 86400: raise RuntimeError('sdk_call_limit_exceeds_token_expiry')
        payload = {'account': self.account, 'key': self.credentials['key_sid'],
                   'secret': self.credentials['key_secret'], 'app': self.credentials['app_sid'],
                   'identity': self.identity, 'ttl': ttl}
        child = await asyncio.create_subprocess_exec('node', str(SDK/'token.cjs'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={key: os.environ[key] for key in ('PATH','HOME','TMPDIR','LANG') if key in os.environ})
        output, _ = await child.communicate(json.dumps(payload).encode())
        if child.returncode or not re.fullmatch(rb'[\w-]+\.[\w-]+\.[\w-]+', output):
            raise RuntimeError('sdk_token_helper_failed')
        self.log('sdk_token_created', lifetime_seconds=ttl)
        return output.decode()

    def local_app(self):
        @web.middleware
        async def guard(request, handler):
            if request.host != self.local_origin.removeprefix('http://'):
                raise web.HTTPForbidden()
            if request.method == 'POST' and (request.headers.get('Origin') != self.local_origin
                    or not secrets.compare_digest(request.headers.get('X-Renderer-Control',''), self.control)):
                raise web.HTTPForbidden()
            response = await handler(request)
            response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
            return response
        app = web.Application(middlewares=[guard], client_max_size=16384)
        async def index(_):
            return web.Response(text='<script src="/voice-sdk.js"></script><script type="module" src="/client.js"></script>',content_type='text/html')
        async def config(_):
            if self.closing: raise web.HTTPConflict()
            return web.json_response({'token': await self.access_token(), 'request_id': self.journal.data['request_id']})
        async def vendor(_): return web.FileResponse(SDK/'node_modules/@twilio/voice-sdk/dist/twilio.min.js')
        app.router.add_get('/', index); app.router.add_post('/config', config); app.router.add_get('/voice-sdk.js', vendor)
        for name in ('client.js','media.js','pcm-worklet.js'):
            async def asset(_, path=SDK/name): return web.FileResponse(path)
            app.router.add_get('/'+name, asset)
        app.router.add_get('/pcm', self.media_socket)
        return app

    async def play_voicemail(self, capture):
        self.voicemail_capture = capture
        while True:
            if self.closing or self.failure or capture.failure: raise RuntimeError('sdk_voicemail_interrupted')
            pcm = await capture.queue.get()
            if pcm is None: break
            await self.send_pcm(pcm)
        if not capture.sealed or capture.failure or self.sent_samples != capture.samples:
            raise RuntimeError('sdk_voicemail_boundary_invalid')
        await self.drain()
        if self.closing or self.failure or capture.failure: raise RuntimeError('sdk_voicemail_source_failed')
        self.voicemail_submitted = True

    def delivery(self):
        if not self.voicemail_started.is_set(): return {'kind':'human','human_conversation_confirmed':False}
        capture = self.voicemail_capture
        source = (capture.metadata or {}) if capture is not None else {}
        complete = bool(self.voicemail_submitted and self.local_drain and not self.failure
                        and capture is not None and not capture.failure)
        return {**source,'kind':'voicemail','status':'submitted_local_drain' if complete else 'partial',
                'local_queue_drained':complete,'local_rendered_source_samples':self.local_drain.get('consumed') if self.local_drain else None,
                'local_rendered_padding_samples':self.local_drain.get('padding') if self.local_drain else None,
                'submitted_pcm_samples':self.sent_samples,'source_sample_rate':48000,'sdk_codec':self.codec,
                'playback_completed':False,'provider_playback_confirmed':False,
                'playback_evidence':'owned_renderer_local_consumption_only',
                'human_conversation_confirmed':False,'source_failure':capture.failure if capture is not None else None}

    async def reconcile_calls(self):
        state = self.journal.data
        parents = [sid for sid in (state['parent_sid'], *state.get('rejected_parent_sids', [])) if sid]
        rows = []
        for parent in parents:
            value = await self.api.call(parent)
            if value.get('from') != 'client:' + self.identity: raise RuntimeError('sdk_parent_identity_mismatch')
            value = await self.api.stop(parent)
            children = (await self.api.request('GET','Calls',params={'ParentCallSid':parent,'PageSize':2}))['calls']
            if len(children)>1 or (parent != state['parent_sid'] and children):
                raise RuntimeError('sdk_unexpected_multiple_children')
            if children:
                child = children[0]
                if child.get('to') != self.target or child.get('parent_call_sid') != parent:
                    raise RuntimeError('sdk_child_relationship_mismatch')
                if state['child_sid'] and state['child_sid'] != child['sid']: raise RuntimeError('sdk_child_sid_changed')
                self.journal.update(child_sid=child['sid'])
            rows.append({'sid':parent,'status':value['status'],'duration':value.get('duration'),'role':'sdk_parent'})
            if parent == state['parent_sid'] and state['child_sid']:
                child=await self.api.call(state['child_sid'])
                if child.get('parent_call_sid')!=parent or child.get('to')!=self.target:
                    raise RuntimeError('sdk_child_relationship_mismatch')
                value = await self.api.stop(state['child_sid'])
                rows.append({'sid':value['sid'],'status':value['status'],'duration':value.get('duration'),
                             'answered_by':value.get('answered_by'),'role':'pstn_child'})
        self.journal.update(provider_calls=rows)
        return (all(row['status'] in TERMINAL for row in rows)
                and (not state.get('dial_returned') or bool(state['child_sid']))
                and (bool(parents) or not state.get('dial_returned')))

    async def start_renderer(self):
        self.renderer_temp.mkdir(mode=0o700)
        self.browser_executable = self.browser_executable or default_browser()
        self.journal.update(renderer_executable=self.browser_executable)
        self.driver = await asyncio.create_subprocess_exec('node', str(SDK/'driver.cjs'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={**{key:os.environ[key] for key in ('PATH','HOME','LANG') if key in os.environ},
                 'TMPDIR':str(self.renderer_temp)})
        self.journal.update(driver_pid=self.driver.pid)
        self.driver.stdin.write(json.dumps({'origin':self.local_origin,'control':self.control,
                                            'profile':str(self.renderer_temp),
                                            'executable':self.browser_executable}).encode())
        await self.driver.stdin.drain(); self.driver.stdin.close()
        async def read():
            async for line in self.driver.stdout:
                data = json.loads(line)
                if data.get('event') == 'renderer_process':
                    profile = Path(data['profile']).resolve()
                    if (type(data.get('pid')) is not int or data['pid']<=0
                            or not profile.is_relative_to(self.renderer_temp.resolve())):
                        raise RuntimeError('sdk_renderer_ownership_invalid')
                    self.renderer_pid, self.renderer_profile = data['pid'], profile
                    self.journal.update(renderer_pid=self.renderer_pid,renderer_profile=str(profile))
                    self.log('owned_renderer_process',pid=self.renderer_pid); self.renderer_launched.set()
                elif data.get('event') == 'renderer_started':
                    self.journal.update(renderer_version=data.get('browser_version'))
                elif data.get('event') in {'renderer_failed','renderer_page_error'} and not self.closing:
                    self.fail('sdk_owned_renderer_failed')
        self.driver_reader = self.task(read())
        began = time.monotonic()
        self.startup = {'stage': 'renderer_launch', 'wait_started_elapsed': round(began-self.t0, 4),
                        'launch_budget_seconds': RENDERER_LAUNCH_SECONDS, 'ready_budget_seconds': RENDERER_READY_SECONDS}
        ended=asyncio.create_task(self.ended.wait()); exited=asyncio.create_task(self.driver.wait())
        try:
            for stage, reached, budget in (('renderer_launch', self.renderer_launched, RENDERER_LAUNCH_SECONDS),
                                           ('renderer_ready', self.renderer_ready, RENDERER_READY_SECONDS)):
                self.startup['stage'] = stage
                waiter = asyncio.create_task(reached.wait())
                try:
                    await asyncio.wait((waiter,ended,exited),timeout=budget,return_when=asyncio.FIRST_COMPLETED)
                finally:
                    waiter.cancel(); await asyncio.gather(waiter,return_exceptions=True)
                self.startup[stage+'_elapsed'] = round(time.monotonic()-began, 4) if reached.is_set() else None
                # Closing/exit outrank a stage reached at the same moment; nothing proceeds after either.
                if self.failure or self.closing or self.ended.is_set():
                    self.startup_failed('sdk_owned_renderer_closing')
                if self.driver.returncode is not None:
                    self.startup_failed('sdk_owned_renderer_driver_exited')
                if not reached.is_set():
                    self.startup_failed('sdk_owned_renderer_'+stage.removeprefix('renderer_')+'_timeout')
            if not self.renderer_pid:
                self.startup_failed('sdk_owned_renderer_not_ready')
            self.startup['stage'] = 'ready'
            self.journal.update(startup=self.startup); self.log('sdk_renderer_startup', **self.startup)
        finally:
            for task in (ended,exited):task.cancel()
            await asyncio.gather(ended,exited,return_exceptions=True)

    def startup_failed(self, reason):
        """Persist only allowlisted stage/timing/exit metadata, then stop this startup."""
        self.startup.update(reason=reason, failed_elapsed=round(time.monotonic()-self.t0, 4),
                            driver_returncode=self.driver.returncode if self.driver else None)
        self.journal.update(startup=self.startup); self.log('sdk_renderer_startup', **self.startup)
        raise RuntimeError(reason)

    def owned_renderer_alive(self):
        if not self.renderer_pid:return False
        import subprocess
        command=subprocess.run(['/bin/ps','-p',str(self.renderer_pid),'-o','command='],
                               capture_output=True,text=True,timeout=3)
        return (command.returncode==0 and self.renderer_profile is not None
                and str(self.renderer_profile) in command.stdout and str(self.browser_executable) in command.stdout)

    async def stop_renderer(self):
        if self.ws and not self.ws.closed:
            with contextlib.suppress(Exception):await self.ws.send_json({'type':'stop'})
        if self.driver and self.driver.returncode is None:
            try:await asyncio.wait_for(self.driver.wait(),5)
            except TimeoutError:
                self.driver.terminate()
                try:await asyncio.wait_for(self.driver.wait(),5)
                except TimeoutError:self.driver.kill();await self.driver.wait()
        if self.owned_renderer_alive():
            # Only the exact recorded owned Chrome/profile, never another browser.
            if os.getpgid(self.renderer_pid)==self.renderer_pid:os.killpg(self.renderer_pid,signal.SIGTERM)
            else:os.kill(self.renderer_pid,signal.SIGTERM)
            for _ in range(20):
                if not self.owned_renderer_alive():break
                await asyncio.sleep(.1)
            if self.owned_renderer_alive():raise RuntimeError('sdk_owned_renderer_cleanup_unconfirmed')
        if self.driver_reader:
            await asyncio.gather(self.driver_reader,return_exceptions=True)
        if self.renderer_temp.exists():shutil.rmtree(self.renderer_temp)

    async def watchdog(self):
        connected=time.monotonic()
        while not self.ended.is_set():
            if time.monotonic()-self.last_clock>3:
                self.fail('sdk_renderer_clock_stalled');return
            if self.codec is None and time.monotonic()-connected>20:
                self.fail('sdk_codec_observation_timeout');return
            await asyncio.sleep(.25)


async def listen(app):
    runner=web.AppRunner(app,access_log=None);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    return runner,site._server.sockets[0].getsockname()[1]


async def run(*, adapter, credentials, output_dir, target, on_connected, on_voicemail,
              before_dial, stop_event, before_human_drain, max_call_seconds=2700,
              ring_timeout_seconds=60, voicemail_enabled=False, browser_executable=None):
    """One SDK connect. Existing runner owns call lock and immutable request slot."""
    output=Path(output_dir);account=os.environ['TWILIO_ACCOUNT_SID'];token=os.environ['TWILIO_AUTH_TOKEN']
    bridge=SdkPhone(state_root=ROOT/'.state',output=output,request_id=output.parent.name,
        account=account,token=token,credentials=credentials,source=os.environ['TWILIO_FROM_NUMBER'],
        target=target,adapter=adapter,max_seconds=max_call_seconds,ringing=ring_timeout_seconds,
        voicemail_enabled=voicemail_enabled,on_connected=on_connected,on_voicemail=on_voicemail,
        browser_executable=browser_executable)
    adapter.bridge=bridge
    try:
        bridge.journal.claim()
    except BaseException:
        bridge.wav_in.close();bridge.wav_out.close();bridge.events.close()
        raise
    runners=[];tunnel=tunnel_reader=None;app_updated=False;watchers=[]
    summary={'transport':'sdk','request_id':output.parent.name,'status':'not_created','call_limit_seconds':max_call_seconds,
             'ring_timeout_seconds':ring_timeout_seconds,'voicemail_enabled':voicemail_enabled,
             'tunnel_diagnostics':{},'provider_playback_confirmed':False}
    errors=[];local_stopped=True;physical_safe=False
    async with aiohttp.ClientSession() as http:
        bridge.api=CallAPI(http,account,token,credentials['app_sid'])
        try:
            public,port=await listen(bridge.public_app());runners.append(public)
            tunnel,tunnel_reader,bridge.public_base=await start_tunnel(port,summary['tunnel_diagnostics'],
                on_started=lambda process:bridge.journal.update(tunnel_pid=process.pid,tunnel_port=port))
            await wait_for_tunnel_health(http,bridge.public_base,bridge.nonce,diagnostics=summary['tunnel_diagnostics'])
            app=await bridge.api.request('GET','Applications/'+credentials['app_sid'])
            if app.get('account_sid')!=account or app.get('sid')!=credentials['app_sid']:
                raise RuntimeError('sdk_owned_app_identity_mismatch')
            app_updated=True
            bridge.journal.update(app_voice_url=bridge.public_base+'/voice/'+bridge.nonce)
            await bridge.api.request('POST','Applications/'+credentials['app_sid'],{
                'VoiceUrl':bridge.public_base+'/voice/'+bridge.nonce,'VoiceMethod':'POST',
                'StatusCallback':bridge.public_base+'/parent/'+bridge.nonce,'StatusCallbackMethod':'POST'})
            local,port=await listen(bridge.local_app());runners.append(local)
            bridge.local_origin='http://127.0.0.1:'+str(port)
            await bridge.start_renderer()
            await before_dial() # Existing Live prewarm and immutable one-attempt slot.
            bridge.journal.before_connect()
            summary['status']='connect_attempted';bridge.log('single_sdk_connect_command')
            await bridge.ws.send_json({'type':'connect'})
            watchers=[asyncio.create_task(bridge.ended.wait()),asyncio.create_task(stop_event.wait()),
                      asyncio.create_task(bridge.driver.wait()),asyncio.create_task(tunnel.wait()),
                      asyncio.create_task(bridge.watchdog())]
            async def vm_limit():
                await bridge.voicemail_started.wait()
                try:await asyncio.wait_for(bridge.ended.wait(),VOICEMAIL_MAX_SECONDS+6)
                except TimeoutError:bridge.fail('sdk_voicemail_watchdog')
            if voicemail_enabled:watchers.append(asyncio.create_task(vm_limit()))
            done,_=await asyncio.wait(watchers,timeout=max_call_seconds+ring_timeout_seconds+5+AMD_TIMEOUT_SECONDS,
                                      return_when=asyncio.FIRST_COMPLETED)
            if stop_event.is_set() and bridge.mode=='human' and not bridge.closing:
                bridge.close_fence('conversation_stop')
                await before_human_drain()
                await bridge.drain()
            elif not bridge.closing:
                bridge.fail('sdk_transport_ended' if done else 'sdk_call_watchdog')
        except BaseException as exc:
            reason=str(exc) if isinstance(exc,RuntimeError) else ''
            bridge.failure=bridge.failure or (reason if SAFE_REASON.fullmatch(reason) else type(exc).__name__)
            if not bridge.closing:bridge.close_fence(bridge.failure)
            summary['error_type']=type(exc).__name__
            if isinstance(exc,asyncio.CancelledError):raise
        finally:
            if not bridge.closing:bridge.close_fence('sdk_cleanup')
            adapter.seal_output()
            for task in watchers:task.cancel()
            await asyncio.gather(*watchers,return_exceptions=True)
            if bridge.mode_task and not bridge.mode_task.done():bridge.mode_task.cancel()
            if bridge.mode_task:await asyncio.gather(bridge.mode_task,return_exceptions=True)
            try:await adapter.peer.close() # No Live PCM callback may outlive final receipt snapshot.
            except Exception as exc:errors.append({'stage':'live_source_receiver','type':type(exc).__name__})
            if app_updated:
                try:await bridge.api.request('POST','Applications/'+credentials['app_sid'],{'VoiceUrl':'','StatusCallback':''})
                except Exception as exc:errors.append({'stage':'app_route_clear','type':type(exc).__name__})
            try:
                while True:
                    before=(bridge.journal.data['parent_sid'],bridge.journal.data['child_sid'],
                            tuple(bridge.journal.data.get('rejected_parent_sids',[])))
                    physical_safe=await bridge.reconcile_calls()
                    after=(bridge.journal.data['parent_sid'],bridge.journal.data['child_sid'],
                           tuple(bridge.journal.data.get('rejected_parent_sids',[])))
                    if before==after:break
            except Exception as exc:errors.append({'stage':'physical_reconciliation','type':type(exc).__name__})
            try:await bridge.stop_renderer()
            except Exception as exc:
                local_stopped=False;errors.append({'stage':'renderer','type':type(exc).__name__})
            for runner in reversed(runners):
                try:await runner.cleanup()
                except Exception as exc:
                    local_stopped=False;errors.append({'stage':'loopback_server','type':type(exc).__name__})
            try:
                if tunnel:
                    if tunnel.returncode is None:tunnel.terminate()
                    try:await asyncio.wait_for(tunnel.wait(),3)
                    except TimeoutError:tunnel.kill();await tunnel.wait()
                if tunnel_reader:tunnel_reader.cancel();await asyncio.gather(tunnel_reader,return_exceptions=True)
            except Exception as exc:
                local_stopped=False;errors.append({'stage':'callback_tunnel','type':type(exc).__name__})
            # Reconcile any authentic IDs learned during asynchronous teardown.
            if physical_safe:
                rows={row['sid'] for row in bridge.journal.data.get('provider_calls',[])}
                known=set(filter(None,(bridge.journal.data['parent_sid'],bridge.journal.data['child_sid'],
                                      *bridge.journal.data.get('rejected_parent_sids',[]))))
                if known-rows:
                    try:physical_safe=await bridge.reconcile_calls()
                    except Exception as exc:
                        physical_safe=False;errors.append({'stage':'late_physical_reconciliation','type':type(exc).__name__})
            try:bridge.journal.restore_admission(physical_safe=physical_safe,local_stopped=local_stopped)
            except Exception as exc:errors.append({'stage':'admission_restore','type':type(exc).__name__})
            rows=bridge.journal.data.get('provider_calls',[])
            child=next((row for row in rows if row['role']=='pstn_child'),{})
            delivery=bridge.delivery()
            summary.update(call_sid=bridge.journal.data['child_sid'],sdk_parent_sid=bridge.journal.data['parent_sid'],
                sdk_child_sid=bridge.journal.data['child_sid'],sdk_leg_states=rows,twilio_status=child.get('status'),
                duration_seconds=int(child['duration']) if str(child.get('duration','')).isdigit() else None,
                sdk_codec=bridge.codec,answered_by=bridge.answered_by,delivery=delivery,startup=bridge.startup,
                physical_calls_terminal=physical_safe,local_resources_stopped=local_stopped,
                phone_dial_returned=bridge.journal.data.get('dial_returned',False),
                sdk_safe_before_phone_leg=physical_safe and local_stopped and not bridge.journal.data.get('dial_returned'),
                cleanup_errors=errors,bridge_error_type=bridge.failure,
                admission_restored=bridge.journal.data.get('admission_restored',False))
            summary['status']=('voicemail_submitted' if delivery.get('local_queue_drained')
                               else 'ended' if bridge.started.is_set() else 'not_answered')
            if bridge.failure or errors or not summary['admission_restored']:summary['status']='failed'
            save(output/'phone-summary.json',summary)
            bridge.wav_in.close();bridge.wav_out.close();bridge.events.close()
    return summary

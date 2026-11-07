"""Bounded single-call launcher; import run() from the experiment coordinator.

No Twilio phone-number, webhook, trunk, SIP or deployed-worker configuration is
changed. Only this single Call resource is created and then ended.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from phone_bridge import PhoneBridge, stream_twiml
from voicemail import AMD_TIMEOUT_SECONDS, VOICEMAIL_MAX_SECONDS, call_settings

ENV_NAMES = {'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER', 'TWILIO_API_KEY_SID', 'TWILIO_API_KEY_SECRET'}


def validate_target(target):
    if not isinstance(target, str) or not re.fullmatch(r'\+1[2-9]\d{9}', target):
        raise ValueError('An explicit authorized US E.164 target is required; there is no default destination')
    return target


def preflight(target=None, max_call_seconds=2700):
    """Validate injected settings without contacting any service or printing secrets."""
    validate_target(target)
    if not isinstance(max_call_seconds, int) or isinstance(max_call_seconds, bool) or max_call_seconds <= 0:
        raise ValueError('Call duration limit must be a positive integer')
    for name in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER'):
        if not os.environ.get(name): raise ValueError(f'{name} must be injected for the authorized phone experiment')
    if not re.fullmatch(r'AC[0-9a-fA-F]{32}', os.environ['TWILIO_ACCOUNT_SID']):
        raise ValueError('Invalid Twilio account SID format')
    if not re.fullmatch(r'\+1\d{10}', os.environ['TWILIO_FROM_NUMBER']):
        raise ValueError('Caller ID must be a US E.164 number')
    key, secret = os.environ.get('TWILIO_API_KEY_SID'), os.environ.get('TWILIO_API_KEY_SECRET')
    if bool(key) != bool(secret): raise ValueError('Inject both Twilio API key SID and secret')
    if key and not re.fullmatch(r'SK[0-9a-fA-F]{32}', key): raise ValueError('Invalid Twilio API key SID format')
    if not shutil.which('cloudflared'): raise ValueError('cloudflared is required')
    return {'destination_last4':target[-4:], 'maximum_call_seconds':max_call_seconds, 'single_call':True}


def call_parameters(public_base, nonce, from_number, *, target, max_call_seconds=2700, voicemail_enabled=False, ring_timeout_seconds=None):
    validate_target(target)
    if not re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com', public_base):
        raise ValueError('Only the ephemeral Cloudflare tunnel is permitted')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{32,}', nonce): raise ValueError('Invalid ephemeral nonce')
    config = {'voicemail_enabled': voicemail_enabled}
    if ring_timeout_seconds is not None: config['ring_timeout_seconds'] = ring_timeout_seconds
    _, ringing = call_settings(config)
    params = {'To':target, 'From':from_number,
            'TimeLimit':str(max_call_seconds), 'Timeout':str(ringing), 'Record':'false',
            'StatusCallback':public_base+'/status/'+nonce, 'StatusCallbackEvent':'completed', 'StatusCallbackMethod':'POST'}
    if voicemail_enabled:
        params.update(Url=public_base+'/answer/'+nonce, Method='POST', MachineDetection='DetectMessageEnd',
                      AsyncAmd='false', MachineDetectionTimeout=str(AMD_TIMEOUT_SECONDS))
    else:
        params['Twiml'] = stream_twiml(public_base, nonce)
    return params


class TunnelSetupError(RuntimeError):
    """Fixed, redacted setup reason safe to retain in local evidence."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def inspect_tunnel_log(data, diagnostics):
    """Retain categories only; raw logs contain ephemeral URLs and edge IPs."""
    lower = data.lower()
    if b'Registered tunnel connection' in data: diagnostics['connection_registered'] = True
    if b'ERR' in data: diagnostics['error_log_seen'] = True
    if b'origin certificate' in lower: diagnostics['origin_certificate_notice'] = True
    if b'unable to establish connection' in lower or b'failed to dial' in lower:
        diagnostics['edge_connection_failure'] = True
    if b'timeout' in lower or b'timed out' in lower: diagnostics['timeout_log_seen'] = True
    if b'tls' in lower and (b'failed' in lower or b'error' in lower): diagnostics['tls_error_seen'] = True
    if b'dial tcp [' in lower: diagnostics['ipv6_dial_failure'] = True


async def start_tunnel(port, diagnostics=None, registration_timeout=45, on_started=None):
    # No saved cloudflared credentials/configuration; no ingress is persisted.
    diagnostics = diagnostics if diagnostics is not None else {}
    started = time.monotonic()
    diagnostics['phase'] = 'starting'
    process = await asyncio.create_subprocess_exec(
        shutil.which('cloudflared'), 'tunnel', '--config', '/dev/null', '--url', f'http://127.0.0.1:{port}',
        '--no-autoupdate', '--protocol', 'http2', '--loglevel', 'info',
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR'}})
    if on_started is not None:
        try:
            on_started(process)
        except BaseException:
            if process.returncode is None:process.terminate()
            try:await asyncio.wait_for(process.wait(),3)
            except TimeoutError:process.kill();await process.wait()
            raise
    ready = asyncio.Event()
    public_url = None
    async def read_logs():
        nonlocal public_url
        while line := await process.stderr.readline():
            inspect_tunnel_log(line, diagnostics)
            match = re.search(rb'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if match and public_url is None:
                candidate = match.group().decode()
                label = urlsplit(candidate).hostname.split('.')[0]
                # The current cloudflared emits the assigned URL inside its box banner.
                # Ignore API/placeholder URLs and all error-line URLs.
                if b'|' not in line or b'ERR' in line or label in {'api','www','example','test','your-tunnel'}:
                    diagnostics['non_banner_or_reserved_url_ignored'] = True
                    continue
                public_url = candidate
                diagnostics.update(hostname_assigned=True, url_from_creation_banner=True, reserved_hostname_selected=False)
            if public_url and diagnostics.get('connection_registered'):
                if not ready.is_set():
                    diagnostics.update(phase='edge_registered', registered_elapsed_seconds=round(time.monotonic()-started,3))
                    ready.set()
        if not ready.is_set():
            diagnostics['process_exited_before_registration'] = True
            ready.set()  # Wake startup so it can fail immediately on EOF.
    task = asyncio.create_task(read_logs())
    try:
        await asyncio.wait_for(ready.wait(), registration_timeout)
        if diagnostics.get('process_exited_before_registration'):
            raise TunnelSetupError('tunnel_exited_before_registration')
        return process, task, public_url
    except BaseException as exc:
        reason = 'tunnel_registration_timeout' if isinstance(exc, TimeoutError) else getattr(exc, 'reason', 'tunnel_start_failed')
        diagnostics.update(phase='failed', failure_reason=reason)
        if process.returncode is None: process.terminate()
        try: await asyncio.wait_for(process.wait(), 3)
        except TimeoutError: process.kill(); await process.wait()
        task.cancel(); await asyncio.gather(task, return_exceptions=True)
        if isinstance(exc, TimeoutError): raise TunnelSetupError(reason) from None
        raise


async def wait_for_tunnel_health(http, public_url, nonce, timeout=60, diagnostics=None):
    """Gate the first OS lookup on public DNS publication to avoid negative caching.

    DoH is a readiness signal only. The public HTTPS request still uses ordinary
    OS resolution and certificate verification; no DNS/IP override is installed.
    """
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics['phase'] = 'dns_publication'
    started = time.monotonic()
    deadline = started + timeout
    published = False
    attempts = 0
    while time.monotonic() < deadline:
        request_timeout = aiohttp.ClientTimeout(total=min(3, max(.1, deadline-time.monotonic())))
        if not published:
            diagnostics['public_dns_attempts'] = diagnostics.get('public_dns_attempts', 0) + 1
            try:
                async with http.get('https://dns.google/resolve', params={'name':urlsplit(public_url).hostname, 'type':'A'},
                                    headers={'Accept':'application/dns-json'}, timeout=request_timeout) as response:
                    diagnostics['public_dns_http_status'] = response.status
                    data = await response.json(content_type=None)
                    if not isinstance(data, dict): raise ValueError('Unexpected DNS JSON shape')
                    status = data.get('Status')
                    diagnostics['public_dns_status'] = status if isinstance(status, int) else None
                    published = response.status == 200 and status == 0 and any(
                        isinstance(answer, dict) and answer.get('type') in {1,28} for answer in data.get('Answer', []))
                    if published:
                        diagnostics.update(public_dns_published=True, public_dns_wait_seconds=round(time.monotonic()-started,3), phase='public_health')
                    else: diagnostics['last_public_dns_error_type'] = 'NXDOMAIN' if status == 3 else 'not_published'
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as exc:
                diagnostics['last_public_dns_error_type'] = type(exc).__name__
            if not published:
                await asyncio.sleep(min(1, max(0, deadline-time.monotonic())))
                continue
        attempts += 1
        try:
            async with http.get(public_url+'/health/'+nonce, allow_redirects=False,
                                timeout=aiohttp.ClientTimeout(total=min(3, max(.1, deadline-time.monotonic())))) as response:
                diagnostics['last_health_http_status'] = response.status
                if response.status == 200 and await response.text() == 'ready':
                    diagnostics.update(phase='public_ready', health_attempts=attempts)
                    return response.status
                last_error = 'HTTP'+str(response.status)
        except (aiohttp.ClientError, TimeoutError) as exc:
            last_error = type(exc).__name__
        diagnostics.update(last_health_error_type=last_error, health_attempts=attempts)
        await asyncio.sleep(min(1, max(0, deadline-time.monotonic())))
    reason = 'public_health_timeout' if published else 'dns_publication_timeout'
    diagnostics.update(phase='failed', failure_reason=reason)
    raise TunnelSetupError(reason)


async def prepare_dial(http, public_url, nonce, before_dial=None, diagnostics=None):
    """Gate paid session startup and dialing on a successful public health check."""
    await wait_for_tunnel_health(http, public_url, nonce, diagnostics=diagnostics)
    if before_dial is not None:
        await before_dial()


async def hangup_and_reconcile(http, call_url, auth, summary):
    """A failed status lookup must never prevent this call's hangup attempt."""
    state = None
    try:
        async with http.get(call_url, auth=auth) as response:
            summary['pre_hangup_http_status'] = response.status
            state = (await response.json(content_type=None)).get('status')
    except Exception as exc:
        summary['pre_hangup_error_type'] = type(exc).__name__
    hangup_status = 'canceled' if state in {'queued', 'ringing', 'initiated'} else 'completed'
    try:
        async with http.post(call_url, auth=auth, data={'Status':hangup_status}) as response:
            summary['hangup_http_status'] = response.status
    except Exception as exc:
        summary['hangup_error_type'] = type(exc).__name__
    try:
        async with http.get(call_url, auth=auth) as response:
            summary['billing_http_status'] = response.status
            data = await response.json(content_type=None)
            summary['twilio_status'] = data.get('status')
            summary['duration_seconds'] = data.get('duration')
            summary['twilio_call_price'] = data.get('price')
            summary['twilio_price_unit'] = data.get('price_unit')
            summary['billing'] = 'connectivity_price_only_media_stream_usage_separate'
    except Exception as exc:
        summary['billing_error_type'] = type(exc).__name__


async def run(*, room_url, room_token, agent_identity='agent', output_dir, target, on_connected=None, session=None, stop_event=None, before_dial=None, max_call_seconds=2700, voicemail_enabled=False, on_voicemail=None, ring_timeout_seconds=None):
    """Place exactly one authorized call after all local and tunnel setup succeeds.

    This function is an execution surface. Its caller must enforce user
    authorization and the one-attempt slot. The configured carrier and local limits apply.
    """
    preflight(target, max_call_seconds)
    settings = {'voicemail_enabled': voicemail_enabled}
    if ring_timeout_seconds is not None: settings['ring_timeout_seconds'] = ring_timeout_seconds
    _, ringing = call_settings(settings)
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    account = os.environ['TWILIO_ACCOUNT_SID']
    auth_token = os.environ['TWILIO_AUTH_TOKEN']
    auth = aiohttp.BasicAuth(os.environ.get('TWILIO_API_KEY_SID') or account,
                             os.environ.get('TWILIO_API_KEY_SECRET') or auth_token)
    base = f'https://api.twilio.com/2010-04-01/Accounts/{account}/Calls'
    bridge = PhoneBridge(auth_token=auth_token, account_sid=account, nonce=secrets.token_urlsafe(32),
                         output_dir=output, agent_identity=agent_identity, on_connected=on_connected,
                         voicemail_enabled=voicemail_enabled, on_voicemail=on_voicemail)
    tunnel = drain = None
    created = False
    summary = {'status':'not_created', 'call_limit_seconds':max_call_seconds, 'ring_timeout_seconds':ringing,
               'voicemail_enabled':voicemail_enabled, 'voicemail_limit_seconds':VOICEMAIL_MAX_SECONDS,
               'destination_last4':target[-4:], 'billing':'pending', 'tunnel_diagnostics':{}}
    started = time.monotonic()
    handler = None
    try:
        port = await bridge.prepare(room_url, room_token)
        tunnel, drain, public_url = await start_tunnel(port, diagnostics=summary['tunnel_diagnostics'])
        bridge.public_base = public_url
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, raise_for_status=False) as http:
            await prepare_dial(http, public_url, bridge.nonce, before_dial, diagnostics=summary['tunnel_diagnostics'])
            if session:
                def user_state(event):
                    if event.new_state == 'speaking': bridge.task(bridge.clear())
                handler = user_state
                session.on('user_state_changed', handler)
            bridge.log('single_call_create_attempt')
            summary['status'] = 'create_attempted'
            # No retries: an ambiguous timeout must never initiate a second call.
            async with http.post(base+'.json', auth=auth, data=call_parameters(public_url, bridge.nonce, os.environ['TWILIO_FROM_NUMBER'], target=target, max_call_seconds=max_call_seconds, voicemail_enabled=voicemail_enabled, ring_timeout_seconds=ringing)) as response:
                payload = await response.json(content_type=None)
                if response.status != 201:
                    summary['twilio_error_code'] = payload.get('code')
                    raise RuntimeError('Twilio single-call creation rejected')
                sid = payload.get('sid', '')
                if not re.fullmatch(r'CA[0-9a-fA-F]{32}', sid): raise RuntimeError('Invalid returned CallSid')
                bridge.set_call_sid(sid)
                created = True
                summary.update(status='created', call_sid=sid)
            # Allow configured ringing, Twilio's possible 5-second buffer and AMD.
            waits = [asyncio.create_task(bridge.ended.wait()), asyncio.create_task(tunnel.wait())]
            stop_waiter = asyncio.create_task(stop_event.wait()) if stop_event is not None else None
            if stop_waiter is not None: waits.append(stop_waiter)
            voicemail_watchdog = asyncio.create_task(bridge.voicemail_watchdog()) if voicemail_enabled else None
            try:
                done, pending = await asyncio.wait(waits, timeout=max_call_seconds+ringing+5+(AMD_TIMEOUT_SECONDS if voicemail_enabled else 0), return_when=asyncio.FIRST_COMPLETED)
                if not done: bridge.log('phone_watchdog_expired')
                elif stop_waiter is not None and stop_waiter in done and stop_event.is_set():
                    if not bridge.voicemail_started.is_set():
                        await bridge.drain_playout()
                    bridge.log('coordinator_stop_received')
                elif waits[1] in done: bridge.log('temporary_tunnel_exited')
            finally:
                if voicemail_watchdog is not None: waits.append(voicemail_watchdog)
                for waiter in waits: waiter.cancel()
                await asyncio.gather(*waits, return_exceptions=True)
            summary['status'] = 'ended' if bridge.started.is_set() else 'no_media_stream'
            if bridge.voicemail_started.is_set():
                summary['status'] = 'voicemail_played' if bridge.voicemail_played else 'voicemail_attempted'
            if bridge.failure:
                summary.update(status='failed', bridge_error_type=bridge.failure)
    except BaseException as exc:
        summary['error_type'] = type(exc).__name__
        if isinstance(exc, TunnelSetupError): summary['setup_failure_reason'] = exc.reason
        if isinstance(exc, asyncio.CancelledError): summary['status'] = 'canceled'
        else: summary['status'] = 'failed'
        raise
    finally:
        if handler and session:
            with contextlib.suppress(Exception): session.off('user_state_changed', handler)
        # Cancellation, provider failure, stream disconnect and success all end THIS call.
        if created:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as http:
                    await hangup_and_reconcile(http, base+'/'+bridge.call_sid+'.json', auth, summary)
            except Exception as exc:
                summary['hangup_or_billing_error_type'] = type(exc).__name__
        try: await bridge.close()
        except Exception as exc: summary['bridge_cleanup_error_type'] = type(exc).__name__
        summary['answered_by'] = bridge.answered_by
        summary['delivery'] = bridge.delivery()
        if summary['status'] == 'voicemail_played' and not summary['delivery'].get('playback_completed'):
            summary['status'] = 'voicemail_attempted'
        if tunnel and tunnel.returncode is None:
            tunnel.terminate()
            try: await asyncio.wait_for(tunnel.wait(), 3)
            except TimeoutError: tunnel.kill(); await tunnel.wait()
        if drain:
            drain.cancel(); await asyncio.gather(drain, return_exceptions=True)
        summary['elapsed_seconds'] = round(time.monotonic()-started, 3)
        path = output/'phone-summary.json'
        path.write_text(json.dumps(summary, indent=2)+'\n'); path.chmod(0o600)
    return summary

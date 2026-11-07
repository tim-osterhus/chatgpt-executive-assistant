"""Exact-ID SDK crash cleanup; no reconnect, dial, or replacement request."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import aiohttp
from sdk_call_state import SdkCallState, save
from sdk_installation import CHROME_CANDIDATES
from sdk_phone import CallAPI, SdkPhone, SDK


def command(pid):
    if type(pid) is not int or pid<=0:raise RuntimeError('invalid_recorded_process')
    result=subprocess.run(['/bin/ps','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=3)
    if result.returncode==1:return None
    if result.returncode:raise RuntimeError('recorded_process_lookup_failed')
    return result.stdout.strip()


async def stop_recorded(pid, *required):
    if pid is None:return
    current=command(pid)
    if current is None:return
    if not all(value in current for value in required):raise RuntimeError('recorded_process_ownership_changed')
    os.kill(pid,signal.SIGTERM)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        current=command(pid)
        if current is None:return
        if not all(value in current for value in required):raise RuntimeError('recorded_process_ownership_changed')
        await asyncio.sleep(.1)
    os.kill(pid,signal.SIGKILL)
    for _ in range(20):
        if command(pid) is None:return
        await asyncio.sleep(.1)
    raise RuntimeError('recorded_process_cleanup_unconfirmed')


async def recover(*, state_root, output, request_id, account, token, credentials, target, api=None):
    """Caller holds the existing call lock. Preserve original call/audio receipts."""
    output=Path(output);journal=SdkCallState(state_root,output,request_id,recover=True)
    state=journal.data
    if (state.get('account_fingerprint')!=hashlib.sha256(account.encode()).hexdigest()
            or state.get('app_sid')!=credentials['app_sid'] or state.get('identity')!='phone-'+request_id):
        raise RuntimeError('sdk_recovery_account_or_identity_mismatch')
    # Journals since per-request recipients record their exact target; older ones use the caller's fallback.
    if state.get('target') is not None and state['target']!=target:raise RuntimeError('sdk_recovery_target_mismatch')
    if not journal.marker.exists() and state.get('status')=='terminal':return {'status':'already_terminal','request_id':request_id}
    if not journal.owns_marker():raise RuntimeError('sdk_recovery_owner_mismatch')
    journal.close_fence('exact_id_recovery') # Before any provider/local awaits.
    # Reuse the controller's exact parent/child reconciliation and owned renderer cleanup.
    bridge=SdkPhone.__new__(SdkPhone)
    bridge.journal=journal;bridge.identity=state['identity'];bridge.target=target
    bridge.ws=bridge.driver=bridge.driver_reader=None
    bridge.renderer_pid=state.get('renderer_pid')
    bridge.renderer_profile=Path(state['renderer_profile']) if state.get('renderer_profile') else None
    bridge.renderer_temp=output/'renderer-temp'
    # Journals before configurable Chrome used the standard application path.
    bridge.browser_executable=state.get('renderer_executable') or CHROME_CANDIDATES[0]
    errors=[];physical=False;local=True
    async with aiohttp.ClientSession() as session:
        bridge.api=api or CallAPI(session,account,token,credentials['app_sid'])
        try:
            owned=await bridge.api.request('GET','Applications/'+credentials['app_sid'])
            if owned.get('account_sid')!=account or owned.get('sid')!=credentials['app_sid']:
                raise RuntimeError('sdk_recovery_app_identity_mismatch')
            if owned.get('voice_url'):
                if owned['voice_url']!=state.get('app_voice_url'):raise RuntimeError('sdk_recovery_app_route_changed')
                await bridge.api.request('POST','Applications/'+credentials['app_sid'],{'VoiceUrl':'','StatusCallback':''})
        except Exception as exc:errors.append({'stage':'app_route','type':type(exc).__name__})
        try:physical=await bridge.reconcile_calls()
        except Exception as exc:errors.append({'stage':'physical','type':type(exc).__name__})
        for stage,operation in (
            ('driver',lambda:stop_recorded(state.get('driver_pid'),str(SDK/'driver.cjs'))),
            ('renderer',bridge.stop_renderer),
            ('tunnel',lambda:stop_recorded(state.get('tunnel_pid'),'cloudflared','--url http://127.0.0.1:'+str(state.get('tunnel_port'))))):
            try:await operation()
            except Exception as exc:local=False;errors.append({'stage':stage,'type':type(exc).__name__})
        # A failed route-clear is retained as unresolved even when known calls ended.
        if any(item['stage']=='app_route' for item in errors):physical=False
        try:journal.restore_admission(physical_safe=physical,local_stopped=local)
        except Exception as exc:errors.append({'stage':'admission','type':type(exc).__name__})
    rows=journal.data.get('provider_calls',[])
    child=next((row for row in rows if row['role']=='pstn_child'),{})
    result={'transport':'sdk','request_id':request_id,'status':'failed',
        'call_sid':journal.data['child_sid'],'sdk_parent_sid':journal.data['parent_sid'],'sdk_child_sid':journal.data['child_sid'],
        'sdk_leg_states':rows,'twilio_status':child.get('status'),'duration_seconds':int(child['duration']) if str(child.get('duration','')).isdigit() else None,
        'physical_calls_terminal':physical,'local_resources_stopped':local,'admission_restored':journal.data.get('admission_restored',False),
        'phone_dial_returned':state.get('dial_returned',False),
        'sdk_safe_before_phone_leg':physical and local and not state.get('dial_returned',False),
        'cleanup_errors':errors,'recovered':True,'delivery':{'kind':'unknown','provider_playback_confirmed':False,'human_conversation_confirmed':False}}
    save(output/'phone-summary.recovery.json',result)
    return {'request_id':request_id,'status':'reconciled' if not errors else 'reconciliation_required',
            'physical_calls_terminal':physical,'local_resources_stopped':local,'admission_restored':result['admission_restored'],
            'receipt':str(output/'phone-summary.recovery.json'),'errors':errors}

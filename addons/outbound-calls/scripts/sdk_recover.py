#!/usr/bin/env python3
"""Explicit exact-ID recovery for a crashed SDK call; never dials."""
import argparse
import asyncio
import fcntl
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from call_runner import STATE,load_config,read_keychain,recorded_destination
from sdk_installation import load_credentials
from sdk_recovery import recover


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('request_id');args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',args.request_id):parser.error('invalid exact request ID')
    try:
        run=STATE/'runs'/args.request_id
        request=json.loads((run/'request.json').read_text())
        if request['request_id']!=args.request_id:raise RuntimeError('saved_request_identity_mismatch')
        config=load_config();prefix=config.get('keychain_service_prefix','executive-assistant-calls')
        target=recorded_destination(run,request,config)['number'] # Never today's default for a recorded call.
        account=read_keychain('twilio-account-sid',config['keychain_account'],prefix)
        token=read_keychain('twilio-auth-token',config['keychain_account'],prefix)
        credentials=load_credentials(config,account_sid=account)
        with (STATE/'runs/.call.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=asyncio.run(recover(state_root=STATE,output=run/'evidence',request_id=args.request_id,
                account=account,token=token,credentials=credentials,target=target))
        print(json.dumps(result));return 0 if result['status'] in {'reconciled','already_terminal'} else 1
    except Exception as exc:
        print(json.dumps({'request_id':args.request_id,'status':'reconciliation_required','error_type':type(exc).__name__}));return 1

if __name__=='__main__':raise SystemExit(main())

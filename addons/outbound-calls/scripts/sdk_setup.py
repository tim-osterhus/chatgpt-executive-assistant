#!/usr/bin/env python3
"""Explicit SDK installation/cleanup for this runtime; outputs redacted status only."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runtime'))
from sdk_installation import DEFAULT_STATE, InstallationError, Keychain, TwilioHTTP, cleanup, ensure_installed


async def run_command(args, *, keychain=None, request=None):
    keychain = keychain or Keychain()
    directory = Path(args.state_dir)
    try:
        config = json.loads((directory.parent / 'config.json').read_text())
        prefix = config.get('keychain_service_prefix', 'executive-assistant-calls')
        account = keychain.get(prefix + '.twilio-account-sid', config['keychain_account'])
        operation = ensure_installed if args.command == 'install' else cleanup
        options = dict(account_sid=account, state_dir=directory, keychain=keychain)
        if request is not None:
            return await operation(config, request=request, **options)
        token = keychain.get(prefix + '.twilio-auth-token', config['keychain_account'])
        if not token:
            raise InstallationError('twilio_credentials_unavailable')
        import aiohttp
        async with aiohttp.ClientSession() as session:
            provider = TwilioHTTP(session, account, token)
            return await operation(config, request=provider.request, **options)
    except InstallationError:
        raise
    except Exception:
        raise InstallationError('sdk_setup_failed') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('install', 'cleanup'))
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE,
                        help='ROOT/.state/sdk-transport (defaults to this installed runtime)')
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run_command(args))
    except InstallationError as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

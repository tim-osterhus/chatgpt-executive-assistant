"""Executive Assistant's local entry point to the tested, single-call voice runtime."""
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from call_profiles import OUTCOMES, validate_profiles
from voicemail import call_settings

RUNTIME = Path(__file__).resolve().parent
STATE = RUNTIME.parent / ".state"
RUNS = STATE / "runs"


def request_from_stdin():
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise ValueError("Call request exceeds 16384 bytes")
    return validate_request(json.loads(raw))


def validate_request(request):
    if len(json.dumps(request).encode()) > 16384:
        raise ValueError("Call request exceeds 16384 bytes")
    required = {"request_id", "focus"}
    optional = {"briefing", "outcome", "recipient_number", "recipient_name"}
    if not isinstance(request, dict) or not required <= request.keys() or request.keys() - required - optional:
        raise ValueError("Supply request_id, focus, and optionally briefing, outcome, and recipient fields")
    request_id = request["request_id"]
    focus = request["focus"]
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", request_id):
        raise ValueError("Invalid request_id")
    if not isinstance(focus, str) or not 1 <= len(focus) <= 240 or not focus.isprintable():
        raise ValueError("Focus must be 1 to 240 printable characters")
    request["focus"] = focus.strip()
    if not request["focus"]:
        raise ValueError("Focus must contain text")
    if "briefing" in request:
        briefing = request["briefing"]
        if not isinstance(briefing, str) or not briefing.strip() or len(briefing) > 8000:
            raise ValueError("Briefing must contain 1 to 8000 characters")
        if any(not c.isprintable() and c not in "\n\t" for c in briefing):
            raise ValueError("Briefing contains unsupported control characters")
        request["briefing"] = briefing.strip()
    if "outcome" in request and (not isinstance(request["outcome"], str) or request["outcome"] not in OUTCOMES):
        raise ValueError("Invalid call outcome")
    # An absent recipient keeps the configured default and the legacy request identity.
    if "recipient_name" in request and "recipient_number" not in request:
        raise ValueError("recipient_name requires an explicit recipient_number")
    if "recipient_number" in request:
        if not isinstance(request["recipient_number"], str) or not re.fullmatch(r"\+1[2-9]\d{9}", request["recipient_number"]):
            raise ValueError("recipient_number must be a US or Canadian E.164 number")
        if "briefing" not in request:
            raise ValueError("An explicit recipient requires a briefing")
    if "recipient_name" in request:
        name = request["recipient_name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or not name.isprintable():
            raise ValueError("recipient_name must be 1 to 80 printable characters")
        request["recipient_name"] = name.strip()
    return request


def resolve_destination(request, config):
    """The one destination for this request; explicit fields never fall back to the default."""
    explicit = "recipient_number" in request
    number = request["recipient_number"] if explicit else config["to_number"]
    if number == config["from_number"]:
        raise ValueError("Caller ID and destination must be different")
    return {"request_id": request["request_id"], "number": number,
            "name": request.get("recipient_name"), "source": "request" if explicit else "configured_default"}


def recorded_destination(run, request, config):
    """Destination saved before dialing; only legacy runs without a record use today's default."""
    path = run / "destination.json"
    if path.is_file():
        destination = json.loads(path.read_text())
        if (not isinstance(destination, dict) or destination.get("request_id") != request["request_id"]
                or not isinstance(destination.get("number"), str)
                or not re.fullmatch(r"\+1[2-9]\d{9}", destination["number"])
                or destination["number"] != request.get("recipient_number", destination["number"])):
            raise ValueError("Recorded destination does not match this request")
        return destination
    if "recipient_number" in request:
        return {"request_id": request["request_id"], "number": request["recipient_number"],
                "name": request.get("recipient_name"), "source": "request"}
    return {"request_id": request["request_id"], "number": config["to_number"], "name": None,
            "source": "legacy_configured_default"}


def receipt(run, request):
    output = run / "evidence"
    result_path = output / "result.json"
    recovery_path=output/'phone-summary.recovery.json'
    recovery=json.loads(recovery_path.read_text()) if recovery_path.is_file() else {}
    recovered=(recovery.get('transport')=='sdk' and recovery.get('request_id')==request['request_id']
               and recovery.get('recovered') is True)
    destination_path = run / "destination.json"
    destination = json.loads(destination_path.read_text()) if destination_path.is_file() else {}
    last4 = {"destination_last4": destination["number"][-4:]} if isinstance(destination.get("number"), str) else {}
    if not result_path.is_file() and not recovered:
        return {
            **request, **last4, "status": "result_unavailable", "dial_attempt_recorded": (run / "dial.slot").exists()
        }
    result = json.loads(result_path.read_text()) if result_path.is_file() else {
        'checkin_status':'partial_or_failed','transcripts':[],'phone_transport':'sdk'}
    carrier_path = output / "phone-summary.json"
    carrier = json.loads(carrier_path.read_text()) if carrier_path.is_file() else {}
    if recovered:
        carrier=recovery
        # Recovery proves safe termination only, never retroactive conversation/delivery.
        result={**result,'checkin_status':'partial_or_failed','phone_transport':'sdk'}
    exact_call = bool(result.get("twilio_call_sid") and result["twilio_call_sid"] == carrier.get("call_sid"))
    sdk_summary = (result.get('phone_transport')=='sdk' and carrier.get('transport')=='sdk'
                   and carrier.get('request_id')==request['request_id'])
    call_id = carrier.get('call_sid') if sdk_summary else result.get('twilio_call_sid')
    if sdk_summary:
        exact_call=bool(re.fullmatch(r'CA[0-9a-fA-F]{32}',call_id or '')
                        and call_id==carrier.get('sdk_child_sid'))
    return {
        **request, **last4,
        "status": result["checkin_status"] if exact_call else "partial_or_failed",
        "call_id": call_id if exact_call else None,
        "carrier_status": (carrier.get('twilio_status') if sdk_summary else result.get("twilio_status")) if exact_call else None,
        "duration_seconds": carrier.get("duration_seconds") if exact_call else None,
        "voice_authentication": result.get("account_type"),
        "ended_by": result.get("stop_reason"),
        "failure": result.get("failure_type") or result.get("provider_error_category"),
        "turns": result["transcripts"] if exact_call else [],
        "backend_profile": result.get("backend_profile"),
        "backend_turns_completed": result.get("backend_turns_completed", 0),
        "answered_by": carrier.get("answered_by") if exact_call else None,
        "delivery": carrier.get("delivery") if exact_call else None,
        'transport':carrier.get('transport','media_streams'),
        'parent_call_id':carrier.get('sdk_parent_sid') if sdk_summary else None,
        'child_call_id':carrier.get('sdk_child_sid') if sdk_summary else None,
        'physical_calls_terminal':carrier.get('physical_calls_terminal') if sdk_summary else None,
        'local_resources_stopped':carrier.get('local_resources_stopped') if sdk_summary else None,
        'admission_restored':carrier.get('admission_restored') if sdk_summary else None,
        'sdk_leg_states':carrier.get('sdk_leg_states') if sdk_summary else None,
        'phone_dial_returned':carrier.get('phone_dial_returned') if sdk_summary else None,
        'sdk_safe_before_phone_leg':carrier.get('sdk_safe_before_phone_leg') if sdk_summary else None,
        "evidence_path": str(result_path),
    }


def load_config():
    try:
        config = json.loads((STATE / "config.json").read_text())
    except FileNotFoundError as exc:
        raise ValueError("Copy config.example.json to .state/config.json and set both phone numbers") from exc
    required = {"from_number", "to_number", "keychain_account"}
    optional_text = {"keychain_service_prefix", "assistant_name", "participant_name", "checkin_purpose"}
    optional = optional_text | {"spoken_disclosure", "max_call_seconds", "call_profiles", "voicemail_enabled", "ring_timeout_seconds", "phone_transport", "chrome_executable"}
    if not isinstance(config, dict) or not required <= config.keys() or config.keys() - required - optional:
        raise ValueError("Check the fields in .state/config.json against config.example.json")
    for key in ("from_number", "to_number"):
        value = config[key]
        if not isinstance(value, str) or not re.fullmatch(r"\+1[2-9]\d{9}", value):
            raise ValueError(f"Set {key} to a US or Canadian E.164 number")
    if config["from_number"] == config["to_number"]:
        raise ValueError("Caller ID and destination must be different")
    if not isinstance(config["keychain_account"], str) or not config["keychain_account"].strip():
        raise ValueError("Set keychain_account to the owner label of the two Twilio Keychain entries")
    for key in optional_text:
        if key in config and (not isinstance(config[key], str) or not config[key].strip()
                              or not config[key].isprintable() or len(config[key]) > 160):
            raise ValueError(f"Set {key} to 1 to 160 printable characters")
    if "spoken_disclosure" in config and not isinstance(config["spoken_disclosure"], bool):
        raise ValueError("spoken_disclosure must be true or false")
    limit = config.get("max_call_seconds", 2700)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("max_call_seconds must be a positive integer")
    validate_profiles(config.get("call_profiles"))
    if not isinstance(config.get('phone_transport','media_streams'),str) or config.get('phone_transport','media_streams') not in {'media_streams','sdk'}:
        raise ValueError('phone_transport must be media_streams or sdk')
    chrome = config.get("chrome_executable")
    if chrome is not None and (not isinstance(chrome, str) or not chrome.startswith("/")
                               or not chrome.isprintable() or len(chrome) > 1024):
        raise ValueError("chrome_executable must be an absolute path to an installed Chrome executable")
    call_settings(config)
    return config


def read_keychain(service, keychain_account, prefix="executive-assistant-calls"):
    return subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", f"{prefix}.{service}",
         "-a", keychain_account, "-w"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        timeout=8, env={"PATH": "/usr/bin:/bin"},
    ).stdout.strip()


async def place_call(run, request, config, destination):
    prefix = config.get("keychain_service_prefix", "executive-assistant-calls")
    account = read_keychain("twilio-account-sid", config["keychain_account"], prefix)
    token = read_keychain("twilio-auth-token", config["keychain_account"], prefix)
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", account) or not token:
        raise ValueError("Twilio Keychain entries are unavailable or invalid")
    transport=config.get('phone_transport','media_streams')
    if transport not in {'sdk','media_streams'}:raise ValueError('Invalid phone transport selection')
    sdk_credentials=None
    config={**config,'phone_transport':transport}
    if transport=='sdk':
        from sdk_installation import browser_executable, load_credentials
        sdk_credentials=load_credentials(config,account_sid=account)
        # Resolve before HOME is replaced below; ~/Applications belongs to the real user.
        config['chrome_executable']=browser_executable(config.get('chrome_executable'))
    path = os.environ["PATH"]
    os.environ.clear()
    os.environ.update({
        "PATH": path, "HOME": str(STATE / "home"), "TMPDIR": str(STATE / "tmp"),
        "XDG_CACHE_HOME": str(STATE / "cache"), "TWILIO_ACCOUNT_SID": account,
        "TWILIO_AUTH_TOKEN": token, "TWILIO_FROM_NUMBER": config["from_number"],
    })
    sys.path.insert(0, str(RUNTIME))
    import voice_session as runtime

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    try:
        await runtime.conduct(
            run / "evidence", run / "dial.slot", config["from_number"],
            destination["number"], request["focus"], settings=config, briefing=request.get("briefing"),
            outcome=request.get("outcome"),
            sdk_credentials=sdk_credentials,
            recipient=({"name": destination["name"]} if destination["source"] == "request" else None),
        )
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


def diagnose():
    config = load_config()
    prefix = config.get("keychain_service_prefix", "executive-assistant-calls")
    for service in ("twilio-account-sid", "twilio-auth-token"):
        if not read_keychain(service, config["keychain_account"], prefix):
            raise ValueError("Required Twilio Keychain item is empty")
    executable = shutil.which("codex")
    if not executable:
        raise ValueError("Install the tested Codex CLI")
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, check=True, timeout=15)
    if version.stdout.strip() != "codex-cli 0.160.0":
        raise ValueError("The calling runtime requires its tested Codex CLI 0.160.0")
    login = subprocess.run(
        [executable, "login", "status", "-c", 'cli_auth_credentials_store="file"'],
        env={**os.environ, "CODEX_HOME": str(STATE / "profile")},
        capture_output=True, text=True, timeout=15,
    )
    if login.returncode or "ChatGPT" not in login.stdout + login.stderr:
        raise ValueError("Complete this installation's ChatGPT login")
    sys.path.insert(0, str(RUNTIME))
    import voice_session, phone_call, phone_bridge, room_adapter
    transport = config.get("phone_transport", "media_streams")
    tools = ("cloudflared",) if transport == "sdk" else ("cloudflared", "livekit-server")
    if not all(shutil.which(tool) for tool in tools):
        raise ValueError("Install this runtime's pinned media tools with the add-on setup")
    sdk = None
    if transport == "sdk":
        import sdk_phone, sdk_recovery
        from sdk_installation import InstallationError, load_credentials, sdk_readiness
        sdk = sdk_readiness(RUNTIME.parent, config.get("chrome_executable"))
        if not sdk["ready"]:
            raise ValueError("SDK prerequisites are incomplete: Node.js 20+, npm ci in runtime/sdk, and installed Chrome")
        try:
            # Local journal and Keychain secret only; no provider request.
            load_credentials(config, account_sid=read_keychain("twilio-account-sid", config["keychain_account"], prefix))
        except InstallationError as exc:
            raise ValueError("Run scripts/sdk_setup.py install for this runtime's owned SDK resources") from exc
    return {"status": "ready_for_call_test", "codex_version": version.stdout.strip(),
            "keychain": "available", "chatgpt_login": "available", "runtime_imports": "passed",
            "phone_transport": transport, "sdk_readiness": sdk,
            "max_call_seconds": config.get("max_call_seconds", 2700),
            "spoken_disclosure": config.get("spoken_disclosure", True),
            "destination_last4": config["to_number"][-4:], "dial_attempted": False}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("validate", "call", "result", "diagnose"))
    args = parser.parse_args()
    try:
        if args.mode == "diagnose":
            print(json.dumps(diagnose()))
            return
        request = request_from_stdin()
        if args.mode == "validate":
            print(json.dumps({**request, "status": "validated"}))
            return
        run = RUNS / request["request_id"]
        if run.is_dir():
            original = json.loads((run / "request.json").read_text())
            if original != request:
                raise ValueError("Request ID already belongs to a different brief")
            print(json.dumps(receipt(run, request)))
            return
        if args.mode == "result":
            print(json.dumps({**request, "status": "request_not_found"}))
            return
        config = load_config()
        destination = resolve_destination(request, config)
        RUNS.mkdir(mode=0o700, exist_ok=True)
        with (RUNS / ".call.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            from sdk_call_state import unresolved
            if unresolved(STATE):raise ValueError('An SDK call needs exact-ID reconciliation before another call')
            run.mkdir(mode=0o700)
            (run / "request.json").write_text(json.dumps(request) + "\n")
            # Record the resolved destination before any provider work; recovery reads this, not today's default.
            (run / "destination.json").write_text(json.dumps(destination) + "\n")
            try:
                asyncio.run(place_call(run, request, config, destination))
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                result = receipt(run, request)
                result.update(status="partial_or_failed", launcher_error=type(exc).__name__)
                print(json.dumps(result))
                return
            print(json.dumps(receipt(run, request)))
    except subprocess.SubprocessError:
        print(json.dumps({"status": "rejected", "reason": "Local credential or runtime check failed"}))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}))


if __name__ == "__main__":
    main()

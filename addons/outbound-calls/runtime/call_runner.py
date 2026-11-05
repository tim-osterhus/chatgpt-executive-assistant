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

RUNTIME = Path(__file__).resolve().parent
STATE = RUNTIME.parent / ".state"
RUNS = STATE / "runs"


def request_from_stdin():
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise ValueError("Call request exceeds 16384 bytes")
    return validate_request(json.loads(raw))


def validate_request(request):
    required = {"request_id", "focus"}
    if not isinstance(request, dict) or not required <= request.keys() or request.keys() - required - {"briefing"}:
        raise ValueError("Supply request_id, focus, and optionally briefing")
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
    return request


def receipt(run, request):
    output = run / "evidence"
    result_path = output / "result.json"
    if not result_path.is_file():
        return {
            **request, "status": "result_unavailable", "dial_attempt_recorded": (run / "dial.slot").exists()
        }
    result = json.loads(result_path.read_text())
    carrier_path = output / "phone-summary.json"
    carrier = json.loads(carrier_path.read_text()) if carrier_path.is_file() else {}
    exact_call = bool(result.get("twilio_call_sid") and result["twilio_call_sid"] == carrier.get("call_sid"))
    return {
        **request,
        "status": result["checkin_status"] if exact_call else "partial_or_failed",
        "call_id": result["twilio_call_sid"] if exact_call else None,
        "carrier_status": result.get("twilio_status") if exact_call else None,
        "duration_seconds": carrier.get("duration_seconds") if exact_call else None,
        "voice_authentication": result.get("account_type"),
        "ended_by": result.get("stop_reason"),
        "failure": result.get("failure_type") or result.get("provider_error_category"),
        "turns": result["transcripts"] if exact_call else [],
        "evidence_path": str(result_path),
    }


def load_config():
    try:
        config = json.loads((STATE / "config.json").read_text())
    except FileNotFoundError as exc:
        raise ValueError("Copy config.example.json to .state/config.json and set both phone numbers") from exc
    required = {"from_number", "to_number", "keychain_account"}
    optional_text = {"keychain_service_prefix", "assistant_name", "participant_name", "checkin_purpose"}
    optional = optional_text | {"spoken_disclosure", "max_call_seconds"}
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
    return config


def read_keychain(service, keychain_account, prefix="executive-assistant-calls"):
    return subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", f"{prefix}.{service}",
         "-a", keychain_account, "-w"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        timeout=8, env={"PATH": "/usr/bin:/bin"},
    ).stdout.strip()


async def place_call(run, request, config):
    prefix = config.get("keychain_service_prefix", "executive-assistant-calls")
    account = read_keychain("twilio-account-sid", config["keychain_account"], prefix)
    token = read_keychain("twilio-auth-token", config["keychain_account"], prefix)
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", account) or not token:
        raise ValueError("Twilio Keychain entries are unavailable or invalid")
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
            config["to_number"], request["focus"], settings=config, briefing=request.get("briefing"),
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
    return {"status": "ready_for_call_test", "codex_version": version.stdout.strip(),
            "keychain": "available", "chatgpt_login": "available", "runtime_imports": "passed",
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
        RUNS.mkdir(mode=0o700, exist_ok=True)
        with (RUNS / ".call.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run.mkdir(mode=0o700)
            (run / "request.json").write_text(json.dumps(request) + "\n")
            try:
                asyncio.run(place_call(run, request, config))
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

"""Optional private stdio MCP adapter for the existing outbound-call runner."""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

RUNTIME = Path(__file__).resolve().parent
ROOT = RUNTIME.parent
STATE = ROOT / ".state"
PLUGIN_STATE = STATE / "plugin"
LEDGER = STATE / "plugin-requests"
DIAL_ENABLED = PLUGIN_STATE / "dial-enabled"
RUNNER = ROOT / "run"

# The adapter runs with Python's isolated mode, so make the sibling runner
# module importable without consulting PYTHONPATH or user site packages.
sys.path.insert(0, str(RUNTIME))
from call_runner import load_config, validate_request, receipt as runner_receipt  # noqa: E402
from call_profiles import select_profile  # noqa: E402
from voicemail import PLAYABLE_MACHINE_RESULTS, call_settings  # noqa: E402
from sdk_call_state import unresolved as sdk_unresolved  # noqa: E402

app = FastMCP(
    "executive-assistant-calling",
    instructions=(
        "Use calling_health to inspect readiness. request_call can place one call "
        "to the configured default recipient, or to an explicitly supplied recipient_number, "
        "only when the local dialing gate is enabled. "
        "A successful request submission means accepted, not completed."
    ),
)


def _normal_request(request_id: str, focus: str, briefing: str, outcome: str | None = None,
                    recipient_number: str | None = None, recipient_name: str | None = None) -> dict[str, str]:
    if not isinstance(briefing, str) or not briefing.strip():
        raise ValueError("A non-empty briefing is required")
    payload = {
        "request_id": request_id,
        "focus": focus,
        "briefing": briefing,
    }
    if outcome is not None:
        payload["outcome"] = outcome
    # Absent recipient fields keep the legacy request identity and the configured default.
    if recipient_number is not None:
        payload["recipient_number"] = recipient_number
    if recipient_name is not None:
        payload["recipient_name"] = recipient_name
    request = validate_request(payload)
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(encoded) > 16384:
        raise ValueError("Call request exceeds 16384 bytes")
    return request


def _valid_request_id(request_id: str) -> str:
    # Reuse the runner's validator so MCP IDs follow the same strict slug rule.
    validate_request({"request_id": request_id, "focus": "status", "briefing": "status"})
    return request_id


def _load_saved_request(path: Path) -> dict[str, str] | None:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            return None
        normalized = validate_request(request)
        if "briefing" not in normalized:
            return None
        return normalized
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


_RECEIPT_FIELDS = (
    "request_id", "focus", "briefing", "status", "call_id", "carrier_status",
    "duration_seconds", "voice_authentication", "ended_by", "failure", "turns",
    "dial_attempt_recorded", "launcher_error", "outcome", "backend_profile", "backend_turns_completed",
    "answered_by", "delivery", "recipient_number", "recipient_name", "destination_last4",
    'transport','parent_call_id','child_call_id','physical_calls_terminal','local_resources_stopped',
    'admission_restored','phone_dial_returned','sdk_safe_before_phone_leg','sdk_leg_states',
)


def _terminal_receipt(request_dir: Path, request: dict[str, str]) -> dict[str, Any] | None:
    """Read only a complete runner receipt bound to this exact ledger request."""
    receipt_path = request_dir / "runner.stdout.json"
    candidates = []
    try:
        candidates.append(json.loads(receipt_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    run = ROOT / ".state" / "runs" / request["request_id"]
    matching_run = _load_saved_request(run / "request.json") == request
    if matching_run:
        try:
            candidates.append(runner_receipt(run, request))
        except (OSError, ValueError, KeyError):
            pass
    for result in candidates:
        if not isinstance(result, dict) or any(result.get(key) != value for key, value in request.items()):
            continue
        if result.get("status") not in {"review_required", "partial_or_failed", "voicemail_played",'voicemail_submitted'}:
            continue
        if result.get('transport')=='sdk':
            if any(result.get(key) is not True for key in ('physical_calls_terminal','local_resources_stopped','admission_restored')):
                continue
            rows=result.get('sdk_leg_states')
            if not isinstance(rows,list) or any(not isinstance(row,dict)
                    or not re.fullmatch(r'CA[0-9a-fA-F]{32}',row.get('sid') or '')
                    or row.get('status') not in {'completed','busy','no-answer','failed','canceled'}
                    or row.get('role') not in {'sdk_parent','pstn_child'} for row in rows):
                continue
            if len({row['sid'] for row in rows})!=len(rows):continue
            parents={row['sid'] for row in rows if row['role']=='sdk_parent'}
            children={row['sid'] for row in rows if row['role']=='pstn_child'}
            if (result.get('parent_call_id') and result['parent_call_id'] not in parents
                    or children!=({result['call_id']} if result.get('call_id') else set())
                    or result.get('call_id')!=result.get('child_call_id')):continue
            if result.get('call_id') and (not result.get('parent_call_id')
                    or next(row['status'] for row in rows if row['sid']==result['call_id'])!=result.get('carrier_status')):
                continue
        if result.get('status')=='voicemail_submitted':
            delivery=result.get('delivery') or {}
            count=delivery.get('submitted_pcm_samples')
            if (result.get('transport')!='sdk' or result.get('carrier_status')!='completed'
                    or result.get('answered_by') not in PLAYABLE_MACHINE_RESULTS
                    or delivery.get('kind')!='voicemail' or delivery.get('status')!='submitted_local_drain'
                    or delivery.get('source_completion')!='inferred_turn_done_and_receiver_quiet'
                    or delivery.get('sdk_codec')!='opus'
                    or any(delivery.get(key) is not True for key in ('finite_pcm_sealed','local_queue_drained','source_receiver_healthy_at_seal'))
                    or delivery.get('provider_playback_confirmed') is not False
                    or delivery.get('playback_completed') is not False
                    or type(count) is not int or count<=0
                    or delivery.get('local_rendered_source_samples')!=count
                    or delivery.get('local_rendered_padding_samples')!=96000
                    or delivery.get('source_failure')):
                continue
        if result.get("status") == "voicemail_played":
            delivery = result.get("delivery") or {}
            if (not isinstance(delivery, dict) or delivery.get("kind") != "voicemail"
                    or delivery.get("playback_completed") is not True
                    or result.get("answered_by") not in PLAYABLE_MACHINE_RESULTS
                    or result.get("carrier_status") != "completed"):
                continue
            proof = delivery.get("playback_evidence")
            if proof == "twilio_final_mark":
                if (delivery.get("source_completion") != "inferred_turn_done_and_receiver_quiet"
                        or any(delivery.get(key) is not True for key in
                               ("finite_pcm_sealed", "sender_queue_drained", "matching_final_mark", "no_clear_during_playback"))
                        or delivery.get("source_receiver_healthy_at_seal") is not True
                        or type(delivery.get("submitted_pcm_samples")) is not int
                        or delivery["submitted_pcm_samples"] <= 0):
                    continue
            elif proof != "authenticated_post_say_redirect":  # Preserve earlier exact-ID TTS receipts.
                continue
        carrier_ended = (isinstance(result.get("call_id"), str)
                         and result["call_id"].startswith("CA") and len(result["call_id"]) == 34
                         and result.get("carrier_status") in {"completed", "busy", "no-answer", "failed", "canceled"})
        before_dial_failure = (matching_run and not (run / "dial.slot").exists()
                               and result.get("status") == "partial_or_failed"
                               and not result.get("call_id"))
        sdk_no_phone=(result.get('transport')=='sdk' and result.get('sdk_safe_before_phone_leg') is True
                      and result.get('phone_dial_returned') is False and result.get('status')=='partial_or_failed'
                      and not result.get('call_id'))
        if carrier_ended or before_dial_failure or sdk_no_phone:
            return {key: result[key] for key in _RECEIPT_FIELDS if key in result}
    return None


def _status(request_id: str, request_dir: Path, request: dict[str, str] | None) -> dict[str, Any]:
    if request is None:
        return {"request_id": request_id, "status": "submission_uncertain"}
    terminal = _terminal_receipt(request_dir, request)
    if terminal is not None:
        return terminal
    return {
        "request_id": request_id,
        "status": "pending_or_uncertain",
        "terminal_receipt_saved": False,
    }


def _is_unresolved(request_dir: Path) -> bool:
    saved = _load_saved_request(request_dir / "request.json")
    if saved is None:
        return True
    return _terminal_receipt(request_dir, saved) is None


def _private_ledger_lock():
    LEDGER.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(LEDGER / ".admission.lock", os.O_CREAT | os.O_RDWR, 0o600)
    return os.fdopen(fd, "a+")


def _atomic_write_request(request_dir: Path, request: dict[str, str]) -> Path:
    request_path = request_dir / "request.json"
    temporary = request_dir / ".request.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(request, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, request_path)
    directory_fd = os.open(request_dir, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return request_path


def _child_environment() -> dict[str, str]:
    result = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    return result


def _launch(request_dir: Path, request_path: Path) -> None:
    with request_path.open("rb") as stdin_file, \
            (request_dir / "runner.stdout.json").open("xb") as stdout_file, \
            (request_dir / "runner.stderr.log").open("xb") as stderr_file:
        subprocess.Popen(
            [str(RUNNER), "call"],
            cwd=str(ROOT),
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
            close_fds=True,
            env=_child_environment(),
        )


@app.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    description="Inspect local call configuration and the explicit dialing gate. Does not access credentials or place a call.",
)
def calling_health() -> dict[str, Any]:
    """Return configuration readiness without exposing secrets or the full phone number."""
    dialing_enabled = DIAL_ENABLED.is_file()
    try:
        config = load_config()
    except (OSError, ValueError):
        return {
            "status": "not_configured",
            "config_ready": False,
            "max_call_seconds": None,
            "spoken_disclosure": None,
            "recipient_last4": None,
            "dialing_enabled": dialing_enabled,
            "per_request_recipients": True,
        }
    profile = select_profile(overrides=config.get("call_profiles"))
    voicemail_enabled, ringing = call_settings(config)
    transport=config.get('phone_transport','media_streams')
    installation_ready=None
    if transport=='sdk':
        try:
            installation=json.loads((STATE/'sdk-transport/installation.json').read_text())
            installation_ready=(installation.get('status')=='ready' and not installation.get('pending')
                and installation.get('keychain_saved') is True
                and all(re.fullmatch(prefix+r'[0-9a-fA-F]{32}',installation.get(field) or '')
                        for field,prefix in (('app_sid','AP'),('key_sid','SK'))))
        except (OSError,ValueError,AttributeError):installation_ready=False
    return {
        "status": "configured" if installation_ready is not False else "not_configured",
        "config_ready": installation_ready is not False,
        "phone_transport":transport,
        "sdk_installation_local_ready":installation_ready,
        "max_call_seconds": config.get("max_call_seconds", 2700),
        "spoken_disclosure": config.get("spoken_disclosure", True),
        "voicemail_enabled": voicemail_enabled,
        "ring_timeout_seconds": ringing,
        "recipient_last4": config["to_number"][-4:],  # The default; requests may name another.
        "dialing_enabled": dialing_enabled,
        "per_request_recipients": True,  # Watchers must see this before sending recipient fields.
        "default_backend": {key: profile[key] for key in ("model", "effort", "service_tier")},
    }


@app.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True),
    description="Submit one authorized call. Omit recipient_number to call the configured default recipient; otherwise supply the full +1 US/Canadian E.164 recipient_number and optionally recipient_name for this request only. recipient_name requires recipient_number. A request ID stays bound to its recipient. Optional outcome (complete, still_running, failed_or_blocked, unclear) selects a reasoning profile and call framing, not permission to call. Requires a briefing and local gate. Accepted is not completion.",
)
def request_call(
    request_id: str, focus: str, briefing: str,
    outcome: Literal["complete", "still_running", "failed_or_blocked", "unclear"] | None = None,
    recipient_number: str | None = None, recipient_name: str | None = None,
) -> dict[str, Any]:
    """Record and launch a validated request once; repeated IDs never relaunch."""
    try:
        request = _normal_request(request_id, focus, briefing, outcome, recipient_number, recipient_name)
    except (TypeError, ValueError) as exc:
        return {"status": "rejected", "reason": str(exc)}

    if not DIAL_ENABLED.is_file():
        return {"request_id": request["request_id"], "status": "rejected", "reason": "Dialing is disabled"}
    try:
        config = load_config()
    except (OSError, ValueError):
        return {"request_id": request["request_id"], "status": "rejected", "reason": "Call configuration is not ready"}
    if request.get("recipient_number") == config["from_number"]:
        return {"request_id": request["request_id"], "status": "rejected", "reason": "Recipient cannot be the caller ID"}

    try:
        with _private_ledger_lock() as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"request_id": request["request_id"], "status": "busy"}

            request_dir = LEDGER / request["request_id"]
            if request_dir.exists():
                saved = _load_saved_request(request_dir / "request.json")
                if saved is None:
                    return {"request_id": request["request_id"], "status": "submission_uncertain"}
                if saved != request:
                    return {"request_id": request["request_id"], "status": "rejected", "reason": "Request ID already belongs to a different brief"}
                return _status(request["request_id"], request_dir, saved)

            if sdk_unresolved(STATE):
                return {'request_id':request['request_id'],'status':'busy','reason':'An SDK call needs exact-ID reconciliation'}

            for other_dir in LEDGER.iterdir():
                if other_dir.is_dir() and other_dir != request_dir and _is_unresolved(other_dir):
                    return {"request_id": request["request_id"], "status": "busy", "reason": "Another call request has no terminal receipt"}

            request_dir.mkdir(mode=0o700)
            request_path = _atomic_write_request(request_dir, request)
            try:
                _launch(request_dir, request_path)
            except OSError:
                # The ledger is intentionally retained: even a launch error can be
                # ambiguous at the process boundary, so this ID is never replayed.
                return {"request_id": request["request_id"], "status": "pending_or_uncertain", "terminal_receipt_saved": False}
            return {"request_id": request["request_id"], "status": "accepted", "terminal_receipt_saved": False}
    except OSError:
        return {"request_id": request["request_id"], "status": "pending_or_uncertain", "terminal_receipt_saved": False}


@app.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    description="Read status and the saved terminal receipt for a request created through this plugin. Does not launch or inspect arbitrary runner files.",
)
def get_call_status(request_id: str) -> dict[str, Any]:
    """Read the plugin ledger and exact-ID receipt only; never launch or write."""
    try:
        request_id = _valid_request_id(request_id)
    except (TypeError, ValueError):
        return {"status": "request_not_found"}
    request_dir = LEDGER / request_id
    if not request_dir.is_dir():
        return {"request_id": request_id, "status": "request_not_found"}
    return _status(request_id, request_dir, _load_saved_request(request_dir / "request.json"))


def main() -> None:
    os.umask(0o077)
    app.run(transport="stdio")


if __name__ == "__main__":
    main()

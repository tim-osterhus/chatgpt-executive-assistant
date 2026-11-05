"""Optional private stdio MCP adapter for the existing outbound-call runner."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

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

app = FastMCP(
    "executive-assistant-calling",
    instructions=(
        "Use calling_health to inspect readiness. request_call can place one call "
        "to the configured recipient only when the local dialing gate is enabled. "
        "A successful request submission means accepted, not completed."
    ),
)


def _normal_request(request_id: str, focus: str, briefing: str) -> dict[str, str]:
    if not isinstance(briefing, str) or not briefing.strip():
        raise ValueError("A non-empty briefing is required")
    request = validate_request({
        "request_id": request_id,
        "focus": focus,
        "briefing": briefing,
    })
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
    "dial_attempt_recorded", "launcher_error",
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
        if result.get("status") not in {"review_required", "partial_or_failed"}:
            continue
        carrier_ended = (isinstance(result.get("call_id"), str)
                         and result["call_id"].startswith("CA") and len(result["call_id"]) == 34
                         and result.get("carrier_status") in {"completed", "busy", "no-answer", "failed", "canceled"})
        before_dial_failure = (matching_run and not (run / "dial.slot").exists()
                               and result.get("status") == "partial_or_failed"
                               and not result.get("call_id"))
        if carrier_ended or before_dial_failure:
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
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }


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
        }
    return {
        "status": "configured",
        "config_ready": True,
        "max_call_seconds": config.get("max_call_seconds", 2700),
        "spoken_disclosure": config.get("spoken_disclosure", True),
        "recipient_last4": config["to_number"][-4:],
        "dialing_enabled": dialing_enabled,
    }


@app.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True),
    description="Submit one call request to the fixed configured recipient. Requires a briefing and the local dialing gate. Returns accepted after launching the existing runner; it does not wait for call completion.",
)
def request_call(request_id: str, focus: str, briefing: str) -> dict[str, Any]:
    """Record and launch a validated request once; repeated IDs never relaunch."""
    try:
        request = _normal_request(request_id, focus, briefing)
    except (TypeError, ValueError) as exc:
        return {"status": "rejected", "reason": str(exc)}

    if not DIAL_ENABLED.is_file():
        return {"request_id": request["request_id"], "status": "rejected", "reason": "Dialing is disabled"}
    try:
        load_config()
    except (OSError, ValueError):
        return {"request_id": request["request_id"], "status": "rejected", "reason": "Call configuration is not ready"}

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

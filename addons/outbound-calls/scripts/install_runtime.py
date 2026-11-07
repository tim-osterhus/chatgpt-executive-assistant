"""Install the optional calling runtime as a small source copy outside this checkout.

Copies an explicit file allowlist, keeps the runtime's private .state and dependencies on
re-runs, and installs only the selected transport's dependencies. It never logs in, reads
secrets, places a call, or starts a service.
"""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[1]
MARKER = ".executive-assistant-calls-install.json"
NAMESPACE = "executive-assistant-calls"
DEFAULT_RUNTIME = "~/Library/Application Support/Executive Assistant Calls"
CODEX_PACKAGE = "@openai/codex@0.160.0"
EXECUTABLES = {"run", "run-plugin"}
RUNTIME_FILES = (
    "run", "run-plugin", "config.example.json", "requirements.lock", "requirements-plugin.lock",
    "licenses/Cloudflared-LICENSE", "licenses/LiveKit-LICENSE", "licenses/LiveKit-NOTICE",
    "runtime/app_server.py", "runtime/call_profiles.py", "runtime/call_runner.py", "runtime/calling_mcp.py",
    "runtime/phone_bridge.py", "runtime/phone_call.py", "runtime/room_adapter.py", "runtime/sdk_adapter.py",
    "runtime/sdk_call_state.py", "runtime/sdk_installation.py", "runtime/sdk_phone.py", "runtime/sdk_recovery.py",
    "runtime/voice_session.py", "runtime/voicemail.py", "runtime/fixtures/disclosure.txt",
    "runtime/sdk/client.js", "runtime/sdk/driver.cjs", "runtime/sdk/media.js", "runtime/sdk/pcm-worklet.js",
    "runtime/sdk/token.cjs", "runtime/sdk/package.json", "runtime/sdk/package-lock.json",
    "scripts/install_tools.py", "scripts/private_plugin.py", "scripts/sdk_recover.py", "scripts/sdk_setup.py",
    "scripts/store_twilio_credentials.py",
    "skill/SKILL.md",
    "watcher/install.py", "watcher/integrations.py", "watcher/runtime.py", "watcher/watch_call.py",
    "watcher/skill/SKILL.md", "watcher/skill/agents/openai.yaml",
)
GENERATED_SKILL = "generated/outbound-assistant-call/SKILL.md"


class InstallError(RuntimeError):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_target(value):
    target = Path(os.path.expanduser(value))
    if not target.is_absolute():
        raise InstallError("Use an absolute runtime directory.")
    if target.is_symlink():
        raise InstallError("The runtime directory cannot be a symlink.")
    target = target.parent.resolve() / target.name
    checkout = next((path for path in (SOURCE, *SOURCE.parents) if (path / ".git").exists()), SOURCE)
    for inside, outside in ((target, checkout), (checkout, target)):
        if inside == outside or outside in inside.parents:
            raise InstallError("Keep the runtime outside this checkout; its private state must not live in Git.")
    return target


def read_marker(target):
    """None for a new or empty directory; the marker for our runtime; refusal otherwise."""
    if not target.exists():
        return None
    if not target.is_dir():
        raise InstallError("The runtime path exists and is not a directory. Nothing changed.")
    marker = target / MARKER
    if not marker.is_file():
        if any(target.iterdir()):
            raise InstallError("The runtime directory is not empty and is not an Executive Assistant Calls "
                               "runtime. Choose another --runtime-dir. Nothing changed.")
        return None
    try:
        data = json.loads(marker.read_text())
    except ValueError:
        raise InstallError("The runtime marker is unreadable. Inspect it before reinstalling.") from None
    if not isinstance(data, dict) or data.get("namespace") != NAMESPACE or not isinstance(data.get("files"), dict):
        raise InstallError("The runtime marker belongs to another installation. Nothing changed.")
    return data


@contextlib.contextmanager
def held(path, busy):
    """Create and hold one existing runtime lock without waiting; a busy lock defers the update."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), "a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError(busy + " Nothing changed.") from None
        yield


@contextlib.contextmanager
def idle_runtime(target):
    """Hold MCP admission, then the runner's call lock (the order SDK setup uses) for the whole update."""
    state = target / ".state"
    with held(state / "plugin-requests" / ".admission.lock", "A call request is being submitted. Update after it is accepted."), \
            held(state / "runs" / ".call.lock", "A call is running. Update after its receipt is saved."):
        if (state / "sdk-transport" / "active.json").exists():
            raise InstallError("An SDK call needs exact-ID reconciliation before this runtime is updated. Nothing changed.")
        try:
            # The installed calling_mcp judges its own ledger; no submissions means no MCP environment is needed.
            load_sdk(SOURCE).caller_ready(state / "sdk-transport")
        except Exception:
            raise InstallError("A submitted call request has no terminal receipt. Check it by its exact ID "
                               "before updating this runtime. Nothing changed.") from None
        yield


def write_file(path, data, mode):
    if path.is_symlink() or path.is_dir():
        raise InstallError("Refusing to replace a symlink or directory at " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = path.with_name("." + path.name + ".installing")
    pending.unlink(missing_ok=True)
    with os.fdopen(os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "wb") as stream:
        stream.write(data)
    os.chmod(pending, mode)
    os.replace(pending, path)


def save_marker(target, data):
    write_file(target / MARKER, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode(), 0o600)


def copy_source(target, previous):
    """Copy only allowlisted regular files; private state and dependencies are never touched."""
    sources = {}
    for relative in RUNTIME_FILES:
        path = SOURCE / relative
        if path.is_symlink() or not path.is_file():
            raise InstallError("Source file is missing or not a regular file: " + relative)
        sources[relative] = path.read_bytes()
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = {"namespace": NAMESPACE, "format": 1, "status": "installing",
              "files": (previous or {}).get("files", {})}
    save_marker(target, marker)
    for relative, data in sources.items():
        write_file(target / relative, data, 0o700 if relative in EXECUTABLES else 0o600)
    for relative in set(marker["files"]) - set(sources):
        stale = target / relative
        if stale.is_file() and not stale.is_symlink():
            stale.unlink()
    marker.update(status="installed", installed_at=int(time.time()),
                  files={relative: hashlib.sha256(data).hexdigest() for relative, data in sources.items()})
    save_marker(target, marker)


def prepare_state(target, transport, chrome):
    """Create private directories and a first config. An existing config is never edited."""
    state = target / ".state"
    for name in ("", "home", "profile", "tmp", "cache"):
        (state / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path = state / "config.json"
    if config_path.exists():
        current = json.loads(config_path.read_text()).get("phone_transport", "media_streams")
        return [] if current == transport else [
            f"Existing config keeps phone_transport={current}; edit .state/config.json to switch."]
    config = json.loads((target / "config.example.json").read_text())
    config["phone_transport"] = transport
    if chrome:
        config["chrome_executable"] = chrome
    write_file(config_path, (json.dumps(config, indent=2) + "\n").encode(), 0o600)
    return []


def generate_skill(target):
    template = (target / "skill" / "SKILL.md").read_text()
    runner = shlex.quote(str(target / "run"))
    write_file(target / GENERATED_SKILL, template.replace("CALLING_RUNNER", runner).encode(), 0o600)


def load_sdk(root):
    spec = importlib.util.spec_from_file_location("installer_sdk_installation", Path(root) / "runtime" / "sdk_installation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def node_version(run):
    node = shutil.which("node")
    if not node:
        raise InstallError("The SDK transport needs Node.js 20 or later with npm.")
    version = run([node, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if not version.startswith("v") or int(version[1:].split(".")[0]) < 20:
        raise InstallError("The SDK transport needs Node.js 20 or later; found " + version)
    return version


def install_dependencies(target, transport, local_mcp, chrome=None, run=subprocess.run):
    python = target / ".venv" / "bin" / "python"
    if not python.is_file():
        run(["uv", "venv", "--python", "3.12", str(target / ".venv")], check=True)
    run(["uv", "pip", "sync", "--python", str(python), str(target / "requirements.lock")], check=True)
    if not (target / ".state" / "tools" / "node_modules" / ".bin" / "codex").is_file():
        run(["npm", "install", "--prefix", str(target / ".state" / "tools"), "--no-audit", "--no-fund",
             "--save-exact", CODEX_PACKAGE], check=True)
    tools = [str(python), "-I", "-B", str(target / "scripts" / "install_tools.py")]
    run(tools + (["--only", "cloudflared"] if transport == "sdk" else []), check=True)
    fixture = target / "runtime" / "fixtures" / "disclosure.wav"
    if not fixture.is_file():
        spoken = target / ".state" / "disclosure.aiff"
        run(["/usr/bin/say", "-o", str(spoken), "-f", str(target / "runtime" / "fixtures" / "disclosure.txt")], check=True)
        run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@48000", "-c", "1", str(spoken), str(fixture)], check=True)
    if local_mcp:
        run([str(python), "-I", "-B", str(target / "scripts" / "private_plugin.py"), "install-mcp-deps"], check=True)
    if transport != "sdk":
        return None
    node_version(run)
    run(["npm", "ci", "--prefix", str(target / "runtime" / "sdk"), "--ignore-scripts", "--no-audit", "--no-fund"],
        check=True)
    readiness = load_sdk(target).sdk_readiness(target, chrome)
    directory = target / ".state" / "sdk-transport"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_file(directory / "readiness.json", (json.dumps(readiness, indent=2) + "\n").encode(), 0o600)
    return readiness


def plan(target, transport, local_mcp):
    status = read_marker(target)
    return {"runtime_dir": str(target), "runtime_exists": target.exists(), "update": status is not None,
            "transport": transport, "local_mcp": local_mcp, "files": len(RUNTIME_FILES),
            "source_bytes": sum((SOURCE / name).stat().st_size for name in RUNTIME_FILES),
            "private_state": str(target / ".state"), "generated_skill": str(target / GENERATED_SKILL),
            "places_call": False, "starts_service": False}


def install(target, transport, local_mcp, chrome=None, run=subprocess.run):
    previous = read_marker(target)
    if previous is not None:
        context = idle_runtime(target)
    else:
        context = contextlib.nullcontext()
    with context:
        copy_source(target, previous)
        notes = prepare_state(target, transport, chrome)
        generate_skill(target)
        readiness = install_dependencies(target, transport, local_mcp, chrome, run)
    if readiness is not None and not readiness["ready"]:
        raise InstallError("SDK prerequisites are incomplete; see .state/sdk-transport/readiness.json. "
                           "Install Google Chrome or pass --chrome with its executable path.")
    return {"installed": True, "updated": previous is not None, "runtime_dir": str(target),
            "transport": transport, "local_mcp": local_mcp, "runner": str(target / "run"),
            "generated_skill": str(target / GENERATED_SKILL), "notes": notes,
            "sdk_readiness": readiness, "places_call": False, "starts_service": False}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime-dir", default=os.environ.get("EXECUTIVE_ASSISTANT_CALLS_HOME", DEFAULT_RUNTIME))
    parser.add_argument("--transport", choices=("sdk", "media_streams"), default="sdk")
    parser.add_argument("--chrome", help="Absolute path to an installed Chrome executable (SDK transport)")
    parser.add_argument("--local-mcp", action="store_true",
                        help="Also install local stdio MCP dependencies (watcher or private connector)")
    parser.add_argument("--plan", action="store_true", help="Show what would be installed; change nothing")
    args = parser.parse_args(argv)
    try:
        if args.chrome and not Path(args.chrome).is_absolute():
            raise InstallError("--chrome must be an absolute executable path.")
        target = resolve_target(args.runtime_dir)
        result = plan(target, args.transport, args.local_mcp) if args.plan else install(
            target, args.transport, args.local_mcp, args.chrome)
    except (InstallError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(json.dumps({"installed": False, "error": str(exc) if isinstance(exc, InstallError) else type(exc).__name__}),
              file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

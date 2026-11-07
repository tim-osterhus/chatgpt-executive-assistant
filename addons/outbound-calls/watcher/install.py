"""Install or remove the opt-in assistant call watcher for this macOS user.

Run from the root of an installed calls runtime:
    .plugin-venv/bin/python -I -B watcher/install.py {plan|install|store-jev-key|uninstall}
Installation never arms a watch and never starts project work. Every refusal
happens before any write, so a refused command changes nothing.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys

RUNTIME = Path(__file__).resolve().parent.parent
LABEL = "local.executive-assistant-calls.watcher"
COMMAND_NAME = "assistant-watch-call"
SKILL_NAME = "assistant-call-when-done"
LAUNCHER_MARKER = "# Executive Assistant Calls watcher managed launcher"
RUNTIME_KEY = "EXECUTIVE_ASSISTANT_CALLS_RUNTIME"  # Binds the launcher and LaunchAgent to one runtime.
OWNER_FILE = ".executive-assistant-calls-watcher"
RUNTIME_MARKER = ".executive-assistant-calls-install.json"
DEFAULT_PREFIX = "executive-assistant-calls"
JEV_ACCOUNT = "completion-watcher"
WATCHER_FILES = ("runtime.py", "integrations.py", "watch_call.py")
SKILL_FILES = ("SKILL.md", "agents/openai.yaml")
LOCAL_MCP_HINT = "Install the local MCP dependencies with the calling add-on setup's --local-mcp option first."
# Tests replace this so that no real launchctl, plutil, or security process starts.
run = subprocess.run


def refuse(message):
    raise SystemExit(message + " Nothing changed.")


def abort(message):
    raise SystemExit(message)


def atomic_write(path: Path, data: bytes, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".installing")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(mode)
    os.replace(temporary, path)


def domain():
    return f"gui/{os.getuid()}"


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("plan", "install", "store-jev-key", "uninstall"))
    result.add_argument("--bin-dir", help="Directory for the assistant-watch-call launcher (default ~/.local/bin)")
    result.add_argument("--skill-dir", help="Parent directory for the skill (default ~/.codex/skills)")
    result.add_argument("--no-service", action="store_true",
                        help="Do not create, load, or remove the LaunchAgent; an existing one is left untouched")
    return result


def preflight(runtime):
    if sys.platform != "darwin":
        refuse("This installer supports macOS user LaunchAgents only.")
    required = [RUNTIME_MARKER, "run-plugin", ".state/config.json", ".plugin-venv/bin/python"]
    required += ["watcher/" + name for name in WATCHER_FILES]
    required += ["watcher/skill/" + name for name in SKILL_FILES]
    missing = [name for name in required if not (runtime / name).is_file()]
    if missing:
        refuse("Calling runtime prerequisites are missing (" + ", ".join(missing) + "). " + LOCAL_MCP_HINT)


def keychain_prefix(runtime):
    try:
        config = json.loads((runtime / ".state/config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        refuse("Calling runtime config is unreadable.")
    prefix = config.get("keychain_service_prefix", DEFAULT_PREFIX) if isinstance(config, dict) else None
    if not isinstance(prefix, str) or not prefix:
        refuse("Calling runtime config has an invalid keychain_service_prefix.")
    return prefix


def absolute_option(value, default):
    path = Path(os.path.expanduser(value)) if value else default
    if not path.is_absolute():
        refuse("Installer directory options must be absolute paths.")
    return path


def layout(runtime, args):
    state = runtime / ".state" / "watcher"
    return {
        "python": runtime / ".plugin-venv/bin/python",
        "state": state,
        "config": state / "config.json",
        "logs": state / "logs",
        "command": absolute_option(args.bin_dir, Path.home() / ".local/bin") / COMMAND_NAME,
        "skill": absolute_option(args.skill_dir, Path.home() / ".codex/skills") / SKILL_NAME,
        "service": Path.home() / "Library/LaunchAgents" / (LABEL + ".plist"),
    }


def watcher_config(runtime, prefix):
    return {"calling_root": str(runtime), "jev_keychain_service": prefix + ".jev-api",
            "jev_keychain_account": JEV_ACCOUNT, "jev_model": "jev-latest"}


def owned_skill(skill, runtime):
    owner = skill / OWNER_FILE
    return owner.is_file() and owner.read_bytes() == str(runtime).encode()


def runtime_line(runtime):
    return "# " + RUNTIME_KEY + "=" + json.dumps(str(runtime))


def owned_launcher(command, runtime):
    """The generic marker is not enough: the launcher must name this exact runtime."""
    if not command.is_file() or command.is_symlink():
        return False
    lines = command.read_text(encoding="utf-8", errors="replace").splitlines()
    return LAUNCHER_MARKER in lines and runtime_line(runtime) in lines


def owned_service(service, command, runtime):
    try:
        data = plistlib.loads(service.read_bytes())
    except Exception:
        # An unparseable plist cannot be proven to belong to this installer.
        return False
    # The label and launcher path are shared names; the recorded runtime proves ownership.
    return (isinstance(data, dict) and data.get("Label") == LABEL
            and (data.get("ProgramArguments") or [None])[0] == str(command)
            and (data.get("EnvironmentVariables") or {}).get(RUNTIME_KEY) == str(runtime))


def ownership_check(runtime, p, prefix, service_enabled):
    if (p["command"].exists() or p["command"].is_symlink()) and not owned_launcher(p["command"], runtime):
        refuse("An unrelated " + COMMAND_NAME + " command already exists at " + str(p["command"]) + ".")
    if p["skill"].exists() and not owned_skill(p["skill"], runtime):
        refuse("An unrelated " + SKILL_NAME + " skill already exists at " + str(p["skill"]) + ".")
    if service_enabled and p["service"].exists() and not owned_service(p["service"], p["command"], runtime):
        refuse("An unrelated LaunchAgent already uses " + str(p["service"]) + ".")
    if p["config"].exists():
        try:
            current = json.loads(p["config"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            refuse("Existing watcher configuration is unreadable. Inspect it before reinstalling.")
        expected = watcher_config(runtime, prefix)
        if not isinstance(current, dict) or any(current.get(key) != value for key, value in expected.items()):
            refuse("Existing watcher configuration differs. Inspect it before reinstalling.")
    for name in ("state", "logs"):
        if p[name].is_symlink():
            refuse("Watcher state directories must not be symbolic links.")


def plan_for(runtime, p, prefix, service_enabled):
    return {
        "runtime": str(runtime), "state": str(p["state"]), "command": str(p["command"]),
        "skill": str(p["skill"]), "service": service_enabled, "service_path": str(p["service"]),
        "label": LABEL, "calling_root": str(runtime), "jev_keychain_service": prefix + ".jev-api",
        "jev_keychain_account": JEV_ACCOUNT, "service_interval_seconds": 60,
        "checkpoint_hours": 24, "arms_a_watch": False,
    }


def launcher_text(p, runtime):
    return ("#!/bin/sh\nset -eu\n" + LAUNCHER_MARKER + "\n" + runtime_line(runtime) + "\numask 077\n"
            + "export WATCH_CALL_STATE_DIR=" + shlex.quote(str(p["state"])) + "\n"
            + "exec " + shlex.quote(str(p["python"])) + " -I -B "
            + shlex.quote(str(runtime / "watcher" / "watch_call.py")) + ' "$@"\n')


def service_plist(p, runtime):
    return {
        "Label": LABEL,
        "ProgramArguments": [str(p["command"]), "tick"],
        "RunAtLoad": True,
        "StartInterval": 60,
        "Umask": 0o077,
        "ProcessType": "Background",
        "EnvironmentVariables": {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                                 RUNTIME_KEY: str(runtime)},
        "StandardOutPath": str(p["logs"] / "service.stdout.log"),
        "StandardErrorPath": str(p["logs"] / "service.stderr.log"),
    }


def install_skill(runtime, p):
    skill = p["skill"]
    atomic_write(skill / OWNER_FILE, str(runtime).encode())
    quoted_command = shlex.quote(str(p["command"])).encode()
    for name in SKILL_FILES:
        data = (runtime / "watcher" / "skill" / name).read_bytes()
        atomic_write(skill / name, data.replace(b"WATCH_CALL_COMMAND", quoted_command))


def install(runtime, p, prefix, args):
    service_enabled = not args.no_service
    if service_enabled and p["service"].exists():  # Ownership was proven by ownership_check.
        run(["/bin/launchctl", "bootout", domain() + "/" + LABEL],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    for directory in (p["state"], p["logs"]):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    if not p["config"].exists():
        atomic_write(p["config"], (json.dumps(watcher_config(runtime, prefix), indent=2) + "\n").encode())
    atomic_write(p["command"], launcher_text(p, runtime).encode(), 0o700)
    install_skill(runtime, p)
    if service_enabled:
        atomic_write(p["service"], plistlib.dumps(service_plist(p, runtime)))
        try:
            run(["/usr/bin/plutil", "-lint", str(p["service"])], check=True)
            run(["/bin/launchctl", "bootstrap", domain(), str(p["service"])], check=True)
        except (OSError, subprocess.CalledProcessError):
            abort("LaunchAgent validation or bootstrap failed. Some install files were already written; "
                  "fix the cause and rerun install. Run plan to inspect.")
    manifest = {name: hashlib.sha256((runtime / "watcher" / name).read_bytes()).hexdigest()
                for name in WATCHER_FILES}
    atomic_write(p["state"] / "installed-source.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print(json.dumps({"installed": True, **plan_for(runtime, p, prefix, service_enabled)}, indent=2))
    return 0


def store_jev_key(prefix):
    service = prefix + ".jev-api"
    value = getpass.getpass("Jev API key (input hidden): ")
    if (not value or len(value) > 8192 or value != value.strip()
            or "\n" in value or "\r" in value):
        refuse("The key was empty, too long, or had surrounding whitespace or line breaks.")
    # The secret travels only on security's stdin, never in argv or diagnostics.
    command = shlex.join(["add-generic-password", "-U", "-s", service, "-a", JEV_ACCOUNT, "-w", value]) + "\n"
    try:
        stored = run(["/usr/bin/security", "-i"], input=command, text=True,
                     capture_output=True, timeout=30, check=False)
        readback = run(["/usr/bin/security", "find-generic-password", "-s", service,
                        "-a", JEV_ACCOUNT, "-w"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        abort("Keychain access failed. No key was printed; check Keychain Access and rerun store-jev-key.")
    if stored.returncode or readback.returncode or readback.stdout.strip() != value:
        abort("Keychain write or readback did not match. No key was printed; "
              "remove the item in Keychain Access and rerun store-jev-key.")
    print(json.dumps({"stored": True, "keychain_service": service, "keychain_account": JEV_ACCOUNT}))
    return 0


def uninstall(runtime, args):
    if sys.platform != "darwin":
        refuse("This installer supports macOS user LaunchAgents only.")
    p = layout(runtime, args)
    removed, kept = [], []
    if not args.no_service and p["service"].exists():
        if owned_service(p["service"], p["command"], runtime):
            run(["/bin/launchctl", "bootout", domain() + "/" + LABEL],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            p["service"].unlink()
            removed.append(str(p["service"]))
        else:
            kept.append(str(p["service"]))
    if p["command"].exists():
        if owned_launcher(p["command"], runtime):
            p["command"].unlink()
            removed.append(str(p["command"]))
        else:
            kept.append(str(p["command"]))
    if owned_skill(p["skill"], runtime):
        for name in (*SKILL_FILES, OWNER_FILE):
            path = p["skill"] / name
            if path.is_file():
                path.unlink()
                removed.append(str(path))
        for directory in (p["skill"] / "agents", p["skill"]):
            try:
                directory.rmdir()
            except OSError:
                pass
    elif p["skill"].exists():
        kept.append(str(p["skill"]))
    print(json.dumps({"uninstalled": True, "removed": removed, "kept": kept,
                      "state_preserved": str(p["state"]), "keychain": "preserved"}, indent=2))
    return 0


def main(argv=None, runtime=RUNTIME):
    args = parser().parse_args(argv)
    runtime = Path(runtime)
    previous = os.umask(0o077)
    try:
        if args.command == "uninstall":
            return uninstall(runtime, args)
        preflight(runtime)
        prefix = keychain_prefix(runtime)
        if args.command == "store-jev-key":
            return store_jev_key(prefix)
        p = layout(runtime, args)
        ownership_check(runtime, p, prefix, service_enabled=not args.no_service)
        if args.command == "plan":
            print(json.dumps(plan_for(runtime, p, prefix, not args.no_service), indent=2))
            return 0
        return install(runtime, p, prefix, args)
    finally:
        os.umask(previous)


if __name__ == "__main__":
    raise SystemExit(main())

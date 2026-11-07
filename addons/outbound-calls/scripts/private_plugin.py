"""Configure the private calling tunnel using a locally stored runtime key."""
import argparse
import getpass
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state" / "plugin"
CLIENT = ROOT / ".state" / "plugin-tools" / "tunnel-client"
SERVICE = "executive-assistant-calls.openai-tunnel-runtime"
ACCOUNT = "private-calling"
ALIAS = "private-calling"
CLIENT_URL = "https://github.com/openai/tunnel-client/releases/download/v0.0.19/tunnel-client-v0.0.19-darwin-arm64.zip"
CLIENT_SHA256 = "2243d024b77af8ee4b4ab7a1447949e5fc8d82bcd2d51b178927f2da9e47ecfd"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def install_archive(data, expected_sha256, target):
    """Write only the verified archive's selected executable; never extract paths."""
    if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Tunnel client archive is oversized or its checksum does not match")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        candidates = [item for item in archive.infolist()
                      if Path(item.filename).name == "tunnel-client" and not item.is_dir()]
        if len(candidates) != 1:
            raise ValueError("Expected exactly one tunnel-client executable")
        member = candidates[0]
        mode = member.external_attr >> 16
        if (mode & 0o170000) not in (0, 0o100000) or member.file_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Invalid tunnel-client archive member")
        binary = archive.read(member)
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tunnel-client-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(binary)
        temporary.chmod(0o700)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def check_platform():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Run this installer with the calling runtime Python 3.12 (.venv/bin/python).")
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("This pinned installer supports Apple Silicon macOS only.")


def install_mcp_dependencies():
    """Local stdio MCP packages only; the optional watcher needs these, not the tunnel client."""
    venv = ROOT / ".plugin-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(venv / "bin/python"), "-m", "pip", "install",
                    "-r", str(ROOT / "requirements-plugin.lock")], check=True)


def install():
    check_platform()
    with urllib.request.urlopen(CLIENT_URL, timeout=60) as response:
        data = response.read(MAX_ARCHIVE_BYTES + 1)
    install_archive(data, CLIENT_SHA256, CLIENT)
    install_mcp_dependencies()
    print("Installed the pinned tunnel client and isolated plugin dependencies. The dialing gate was not changed.")


def validate_connection(config):
    if not isinstance(config, dict) or set(config) != {"tunnel_id", "workspace_id"}:
        raise ValueError("Supply only tunnel_id and workspace_id")
    if not isinstance(config["tunnel_id"], str) or not re.fullmatch(r"tunnel_[A-Za-z0-9]+", config["tunnel_id"]):
        raise ValueError("Supply the actual created tunnel ID")
    if not isinstance(config["workspace_id"], str) or not re.fullmatch(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}", config["workspace_id"]):
        raise ValueError("Supply the verified ChatGPT workspace ID")
    return config


def keychain_key():
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode or not result.stdout.strip():
        raise SystemExit("Store the dedicated tunnel runtime key first.")
    return result.stdout.strip()


def store_key():
    value = getpass.getpass("Dedicated tunnel runtime API key (hidden): ").strip()
    if not value.startswith("sk-") or len(value) < 20:
        raise SystemExit("Expected a runtime API key. Nothing stored.")
    command = shlex.join(["add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", value]) + "\n"
    result = subprocess.run(["/usr/bin/security", "-i"], input=command, text=True,
                            capture_output=True, timeout=30)
    if result.returncode or keychain_key() != value:
        raise SystemExit("Keychain storage/readback failed.")
    print("Stored and verified the dedicated tunnel runtime key in Keychain.")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("install", "install-mcp-deps", "store-key", "configure", "connect", "status", "stop"))
    parser.add_argument("--tunnel-id")
    parser.add_argument("--workspace-id")
    args = parser.parse_args()
    if args.mode == "install":
        install()
        return
    if args.mode == "install-mcp-deps":
        check_platform()
        install_mcp_dependencies()
        print("Installed isolated local MCP dependencies. No tunnel client, connection, or dialing gate changed.")
        return
    if args.mode == "store-key":
        store_key()
        return
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_file = STATE / "connection.json"
    if args.mode == "configure":
        try:
            config = validate_connection({"tunnel_id": args.tunnel_id, "workspace_id": args.workspace_id})
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        config_file.write_text(json.dumps(config, indent=2) + "\n")
        print("Saved tunnel identity and workspace association. No call or connection started.")
        return
    if args.mode == "connect":
        config = validate_connection(json.loads(config_file.read_text()))
        environment = {**os.environ, "CONTROL_PLANE_API_KEY": keychain_key()}
        command = [str(CLIENT), "runtimes", "connect", "--alias", ALIAS,
                   "--tunnel-id", config["tunnel_id"], "--profile", ALIAS,
                   "--profile-dir", str(STATE / "profiles"),
                   "--runtime-api-key", "env:CONTROL_PLANE_API_KEY",
                   "--mcp-command", shlex.quote(str(ROOT / "run-plugin")), "--json"]
    else:
        environment = dict(os.environ)
        command = [str(CLIENT), "runtimes", args.mode, ALIAS, "--json"]
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=90)
    (STATE / (args.mode + "-last.json")).write_text(result.stdout)
    (STATE / (args.mode + "-last.stderr")).write_text(result.stderr)
    if result.returncode:
        raise SystemExit("Tunnel operation failed. Inspect the private operation logs.")
    print("Tunnel operation completed. Inspect private status output for actual health/readiness.")


if __name__ == "__main__":
    main()

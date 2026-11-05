"""Prompt locally and store Twilio credentials in macOS Keychain."""
import getpass
import json
from pathlib import Path
import re
import shlex
import subprocess


def store(service, account, value):
    command = shlex.join(["add-generic-password", "-U", "-s", service, "-a", account, "-w", value]) + "\n"
    result = subprocess.run(["/usr/bin/security", "-i"], input=command, text=True,
                            capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Could not store the Keychain item")
    check = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service,
                            "-a", account, "-w"], capture_output=True, text=True, timeout=15)
    if check.returncode or check.stdout.strip() != value:
        raise RuntimeError("Keychain readback did not match")


def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / ".state/config.json").read_text())
    account = config["keychain_account"]
    prefix = config.get("keychain_service_prefix", "executive-assistant-calls")
    sid = getpass.getpass("Twilio Account SID (hidden): ").strip()
    token = getpass.getpass("Twilio Auth Token (hidden): ").strip()
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", sid) or not token:
        raise SystemExit("Invalid Account SID or empty Auth Token. No values were stored.")
    store(prefix + ".twilio-account-sid", account, sid)
    store(prefix + ".twilio-auth-token", account, token)
    print("Stored and verified both Keychain items. No credential values printed.")


if __name__ == "__main__":
    main()

"""Install checksum-pinned Apple Silicon binaries without changing global tools."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LIVEKIT_SHA = "253eb6023eb466ec1cb7355be537bb493565c3517c211000ea99c916e7a1a057"
CLOUDFLARED_SHA = "68b6bc4080ac1330234db2a9002d07f98b000537a1bd531a687b660d4160fa7f"


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def install_archive(data, digest, member_name, destination):
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Binary archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = archive.getmember(member_name)
        if not member.isfile():
            raise ValueError("Expected a regular binary file")
        binary = archive.extractfile(member).read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_suffix(".pending")
    pending.write_bytes(binary)
    pending.chmod(0o700)
    pending.replace(destination)


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    # The SDK transport needs only its callback tunnel; LiveKit serves the legacy Media Streams room.
    parser.add_argument("--only", choices=("cloudflared", "livekit-server"), action="append")
    selected = parser.parse_args(argv).only
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("This calling add-on currently supports Apple Silicon macOS only.")
    if int(platform.mac_ver()[0].split(".")[0]) < 15:
        raise SystemExit("The pinned binaries require macOS 15 or later.")
    cache = ROOT / ".state" / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    tools = [
        ("livekit-server", LIVEKIT_SHA,
         "https://ghcr.io/v2/homebrew/core/livekit/blobs/sha256:" + LIVEKIT_SHA,
         "livekit/1.13.6/bin/livekit-server"),
        ("cloudflared", CLOUDFLARED_SHA,
         "https://github.com/cloudflare/cloudflared/releases/download/2026.10.4/cloudflared-darwin-arm64.tgz",
         "cloudflared"),
    ]
    for name, digest, url, member in tools:
        if selected and name not in selected:
            continue
        path = cache / (name + ".tar.gz")
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            data = path.read_bytes()
        else:
            headers = {}
            if name == "livekit-server":
                # Anonymous public-package access, not an account credential.
                token = json.loads(fetch("https://ghcr.io/token?service=ghcr.io&scope=repository:homebrew/core/livekit:pull"))["token"]
                headers["Authorization"] = "Bearer " + token
            data = fetch(url, headers)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Binary archive checksum mismatch")
            path.write_bytes(data)
        install_archive(data, digest, member, ROOT / "bin" / name)
        print("Installed pinned " + name)


if __name__ == "__main__":
    main()

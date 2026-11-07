"""Check that the calling add-on ships source only, without runtime state or personal data."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADDON = "addons/outbound-calls/"
LICENSES = ADDON + "licenses/"
PACKAGE_LOCK = "package-lock.json"
ADDON_BUDGET = 1024 * 1024
MAX_FILE = 64 * 1024
SNIFF = 8192
FORBIDDEN_PARTS = {"node_modules", ".venv", ".plugin-venv", "venv", ".state", "__pycache__",
                   ".pytest_cache", "plugin-requests", "runs"}
FORBIDDEN_NAMES = {".ds_store", ".env"}
FORBIDDEN_SUFFIXES = (".pyc", ".pem", ".key", ".p12", ".log", ".jsonl", ".wav", ".aiff", ".aif",
                      ".mp3", ".m4a", ".ogg", ".opus", ".webm", ".zip", ".tar", ".tgz", ".gz",
                      ".dmg", ".pkg", ".so", ".dylib", ".node", ".exe")
REQUIRED_IGNORES = ("node_modules/", ".state/", ".venv/", ".plugin-venv/", "__pycache__/", "disclosure.wav")
SAFE_NAMES = {"example", "you", "user", "username", "name", "me"}
PERSONAL_PATH = re.compile(r"/(?:Users|home)/(<[^>/]*>|[^/\s\"'`<>]+)/")
TEMP_PATH = re.compile(r"/(?:private/)?var/folders/")
PHONE = re.compile(r"\+1[2-9]\d{2}[2-9]\d{6}")
SID = re.compile(r"\b(?:AC|AP|SK|CA|PN|MG)[0-9a-fA-F]{32}\b")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
SECRETS = [
    ("API key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}")),
    ("GitHub token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("Slack token", re.compile(r"xox[abp]-[A-Za-z0-9-]{10,}")),
    ("AWS key", re.compile(r"AKIA[0-9A-Z]{16}")),
    # Real identifiers mix digits in; reason strings such as tunnel_registration_timeout do not.
    ("tunnel identity", re.compile(r"tunnel_(?=[A-Za-z]*[0-9])[A-Za-z0-9]{12,}")),
    ("plugin identity", re.compile(r"plugin_asdk_app_[0-9a-f]{8,}")),
]


def forbidden_path(rel):
    parts = rel.split("/")
    name = parts[-1].lower()
    return bool(
        FORBIDDEN_PARTS.intersection(parts)
        or parts[0] == "local"
        or rel == ".codex/config.toml"
        or (rel.startswith(ADDON) and "bin" in parts[2:-1])
        or name in FORBIDDEN_NAMES or name.startswith(".env.")
        or name.endswith(FORBIDDEN_SUFFIXES)
    )


def fictional_phone(number):
    area, exchange, line = number[2:5], number[5:8], number[8:]
    return area == "555" or (exchange == "555" and "0100" <= line <= "0199")


def text_findings(text, terms, skip_ids):
    """Yield (line number, category) for each violation in text."""
    for number, line in enumerate(text.splitlines(), 1):
        found = set()
        for match in PERSONAL_PATH.finditer(line):
            if not match.group(1).startswith("<") and match.group(1).lower() not in SAFE_NAMES:
                found.add("personal absolute path")
        if TEMP_PATH.search(line):
            found.add("temporary macOS path")
        if any(not fictional_phone(match.group(0)) for match in PHONE.finditer(line)):
            found.add("unapproved phone number")
        if not skip_ids:
            if any(len(set(match.group(0)[2:].lower())) > 2 for match in SID.finditer(line)):
                found.add("provider SID")
            if any(match.group(0).replace("-", "").strip("0") for match in UUID.finditer(line)):
                found.add("UUID")
        for label, pattern in SECRETS:
            for match in pattern.finditer(line):
                value = match.group(0).lower()
                if label == "API key" and ("synthetic" in value or "test" in value):
                    continue
                found.add(label)
        if any(term.search(line) for term in terms):
            found.add("deny term")
        for category in sorted(found):
            yield number, category


def check(root, paths, deny_terms=()):
    """Return counts, the largest file, and human-readable errors for repo-relative paths."""
    root = Path(root)
    terms = [re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
             for term in deny_terms if term.strip()]
    errors, largest, addon_bytes, inspected = [], ["", 0], 0, 0
    for rel in paths:
        path = root / rel
        if path.is_symlink():
            errors.append(f"{rel}: symlink")
            continue
        if not path.is_file():
            continue
        inspected += 1
        size = path.stat().st_size
        if size > MAX_FILE:
            errors.append(f"{rel}: {size} bytes exceeds {MAX_FILE} byte limit")
        if size > largest[1]:
            largest = [rel, size]
        if rel.startswith(ADDON) and not rel.startswith(LICENSES):
            addon_bytes += size
        if forbidden_path(rel):
            errors.append(f"{rel}: forbidden path")
            continue
        data = path.read_bytes()
        if b"\0" in data[:SNIFF]:
            errors.append(f"{rel}: binary content")
        elif rel != "LICENSE" and not rel.startswith(LICENSES):
            skip_ids = rel.split("/")[-1] == PACKAGE_LOCK
            errors += [f"{rel}:{number}: {category}" for number, category
                       in text_findings(data.decode("utf-8", "replace"), terms, skip_ids)]
    if addon_bytes > ADDON_BUDGET:
        errors.append(f"add-on budget exceeded: {addon_bytes} bytes > {ADDON_BUDGET}")
    ignore = root / ".gitignore"
    text = ignore.read_text(encoding="utf-8", errors="replace") if ignore.is_file() else ""
    errors += [f".gitignore: missing required entry {token}" for token in REQUIRED_IGNORES if token not in text]
    return {"files": inspected, "addon_bytes": addon_bytes, "addon_budget_bytes": ADDON_BUDGET,
            "largest": largest, "errors": errors}


def listed_files(root, include_untracked=False):
    """Return git-tracked files, plus untracked non-ignored files when requested."""
    queries = [["ls-files", "-z"]]
    if include_untracked:
        queries.append(["ls-files", "-z", "--others", "--exclude-standard"])
    names = set()
    for query in queries:
        output = subprocess.run(["git", "-C", str(root), *query], capture_output=True, check=True).stdout
        names.update(os.fsdecode(name) for name in output.split(b"\0") if name)
    return sorted(names)


def load_terms(path):
    """Return nonblank, non-comment deny terms from a local file."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--include-untracked", action="store_true")
    parser.add_argument("--deny-terms-file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    terms_file = args.deny_terms_file or os.environ.get("CALLING_SOURCE_DENY_TERMS_FILE")
    terms = load_terms(terms_file) if terms_file else []
    try:
        paths = listed_files(args.root, args.include_untracked)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Cannot list git files under {args.root}: {exc}") from exc
    result = check(args.root, paths, terms)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        largest_path, largest_size = result["largest"]
        print(f"Checked {result['files']} files. Add-on bytes: {result['addon_bytes']} of {ADDON_BUDGET}. "
              f"Largest: {largest_path} ({largest_size} bytes).")
        for error in result["errors"]:
            print("ERROR " + error)
        print("Source package check " + ("failed." if result["errors"] else "passed."))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())

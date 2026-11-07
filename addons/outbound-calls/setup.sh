#!/bin/sh
# Opt-in calling setup. Installs a source copy and its dependencies outside this checkout.
# Options: --runtime-dir DIR, --transport sdk|media_streams, --chrome PATH, --local-mcp, --plan
set -eu
umask 077
bundle_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if [ "$(uname -sm)" != "Darwin arm64" ]; then
  echo "The calling add-on currently supports Apple Silicon macOS only." >&2
  exit 1
fi
command -v uv >/dev/null || { echo "Install uv, then rerun setup." >&2; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js with npm, then rerun setup." >&2; exit 1; }
python="$(uv python find 3.12 2>/dev/null || true)"
if [ -z "$python" ]; then
  # A preview changes nothing, so it never downloads or installs Python.
  for option in "$@"; do
    if [ "$option" = "--plan" ]; then
      echo "Preview needs Python 3.12. Run setup without --plan to install it with uv, or run: uv python install 3.12" >&2
      exit 1
    fi
  done
  uv python install 3.12
  python="$(uv python find 3.12)"
fi
exec "$python" -I -B "$bundle_dir/scripts/install_runtime.py" "$@"

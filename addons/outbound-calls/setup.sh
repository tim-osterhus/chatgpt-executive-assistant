#!/bin/sh
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
mkdir -p "$bundle_dir/.state/home" "$bundle_dir/.state/profile" "$bundle_dir/.state/tmp" "$bundle_dir/.state/cache"
if [ ! -x "$bundle_dir/.venv/bin/python" ]; then
  uv venv --python 3.12 "$bundle_dir/.venv"
fi
uv pip sync --python "$bundle_dir/.venv/bin/python" "$bundle_dir/requirements.lock"
if [ ! -x "$bundle_dir/.state/tools/node_modules/.bin/codex" ]; then
  npm install --prefix "$bundle_dir/.state/tools" --no-audit --no-fund --save-exact @openai/codex@0.160.0
fi
"$bundle_dir/.venv/bin/python" -I -B "$bundle_dir/scripts/install_tools.py"
fixture="$bundle_dir/runtime/fixtures/disclosure.wav"
if [ ! -f "$fixture" ]; then
  /usr/bin/say -o "$bundle_dir/.state/disclosure.aiff" -f "$bundle_dir/runtime/fixtures/disclosure.txt"
  /usr/bin/afconvert -f WAVE -d LEI16@48000 -c 1 "$bundle_dir/.state/disclosure.aiff" "$fixture"
fi
if [ ! -e "$bundle_dir/.state/config.json" ]; then
  cp "$bundle_dir/config.example.json" "$bundle_dir/.state/config.json"
fi
echo "Dependencies installed. Configure .state/config.json and Keychain, then run ./run login and ./run diagnose."
echo "Setup has not placed a call or configured a recurring trigger."

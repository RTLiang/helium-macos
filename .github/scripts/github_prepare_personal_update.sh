#!/bin/bash
# The private key is passed only through stdin; never enable shell tracing here.
set -euo pipefail
root="$(dirname "$(greadlink -f "$0")")"
tools="$(mktemp -d)"
trap 'rm -rf "$tools"' EXIT
curl --fail --location --retry 3 \
  https://github.com/sparkle-project/Sparkle/releases/download/2.7.1/Sparkle-2.7.1.tar.xz \
  --output "$tools/sparkle.tar.xz"
printf '%s  %s\n' f7385c3e8c70c37e5928939e6246ac9070757b4b37a5cb558afa1b0d5ef189de "$tools/sparkle.tar.xz" | shasum -a 256 -c -
tar -xJf "$tools/sparkle.tar.xz" -C "$tools"
python3 -m venv "$tools/venv"
"$tools/venv/bin/pip" install --quiet cryptography==46.0.3
app="$root/build/src/out/Default/Helium.app"
if [ -n "${MACOS_CERTIFICATE_NAME:-}" ]; then
  app="$root/build/src/out/Default/signed/stable/Helium.app"
fi
codesign --verify --deep --strict "$app"
"$tools/venv/bin/python" "$root/devutils/prepare_personal_update.py" \
  --root "$root" --app "$app" --dmg "$root/release_asset/$1" \
  --sign-tool "$tools/bin/sign_update"

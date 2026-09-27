#!/bin/bash
set -euo pipefail

# Cross-run reuse may legitimately change SDK and build commands. Keep Ninja's
# dependency records, but let the regenerated graph rebuild all dirty targets.
sha256sum -c sums.txt
mkdir -p build
tar -C build -xf build_src.tar.zst
rm build_src.tar.zst
test -s build/src/out/Default/.ninja_log
test -s build/src/out/Default/.ninja_deps
old_version=$(python3 -c 'from pathlib import Path; v=dict(line.split("=",1) for line in Path("build/src/chrome/VERSION").read_text().splitlines() if "=" in line); print(".".join(v[k] for k in ("MAJOR","MINOR","BUILD","PATCH")))')
new_version=$(cat helium-chromium/chromium_version.txt)
sha256sum -c build_resources_sums.txt
if [ "$old_version" != "$new_version" ]; then
    echo "Chromium changed ($old_version -> $new_version); using fresh sources and a clean output directory"
    rm -rf build/src
    ./github_unpack_resources.sh
else
    echo "Reusing Chromium $old_version compilation outputs; comparing fresh patched sources by content"
    zstd -dc build_resources.tar.zst | python3 devutils/overlay_build_sources.py build/src
    rm build_resources.tar.zst
fi
available_kib=$(df -Pk . | awk 'END {print $4}')
if [ "$available_kib" -lt 15728640 ]; then
    echo 'Less than 15 GiB remains after restoring the build' >&2
    exit 1
fi

# Repair checkpoints that already lost the generator's undeclared TS output.
if [ ! -f build/src/components/helium_onboarding/src/lib/strings.ts ]; then
    echo 'Onboarding strings.ts missing; invalidating its cached generator header'
    rm -f build/src/out/Default/gen/components/helium_onboarding/helium_onboarding_localized_strings.h
fi

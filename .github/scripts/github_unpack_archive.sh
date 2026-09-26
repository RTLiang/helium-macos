#!/bin/bash -eux

# Unpacking script for GitHub Actions

echo "Checking sha256sum of archive:"
sha256sum -c sums.txt

_src_dir="$PWD/build/src"
ls -lrt

mkdir build
echo "Extracting build archive"
tar -C build -xf build_src.tar.zst

rm build_src.tar.zst

# Detect a broken checkpoint before spending another five hours recompiling it.
_ninja_log="$_src_dir/out/Default/.ninja_log"
test -s "$_ninja_log"
test -s "$_src_dir/out/Default/.ninja_deps"
_first_object=$(awk -F '\t' 'NR > 1 && $4 ~ /^obj\/.*\.o$/ {print $4; exit}' "$_ninja_log")
_last_object=$(awk -F '\t' 'NR > 1 && $4 ~ /^obj\/.*\.o$/ {last = $4} END {print last}' "$_ninja_log")
test -n "$_first_object"
test -n "$_last_object"
cd "$_src_dir"
_dry_run=$(python3 third_party/depot_tools/autoninja.py -C out/Default -n \
  "$_first_object" "$_last_object")
if [[ "$_dry_run" != *"ninja: no work to do."* ]]; then
  printf '%s\n' "$_dry_run"
  echo "Restored build would recompile previously completed objects" >&2
  exit 1
fi

sudo df -h
sudo du -hs "$_src_dir"

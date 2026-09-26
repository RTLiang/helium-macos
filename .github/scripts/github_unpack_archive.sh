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
bash "$(dirname "$0")/github_check_checkpoint.sh" "$_src_dir"

sudo df -h
sudo du -hs "$_src_dir"

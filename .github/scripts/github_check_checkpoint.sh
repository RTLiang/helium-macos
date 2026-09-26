#!/bin/bash
set -euo pipefail

cd "${1:?Expected Chromium source directory}"
_ninja_log=out/Default/.ninja_log
test -s "$_ninja_log"
test -s out/Default/.ninja_deps
_first_object=$(awk -F '\t' 'NR > 1 && $4 ~ /^obj\/.*\.o$/ {print $4; exit}' "$_ninja_log")
_last_object=$(awk -F '\t' 'NR > 1 && $4 ~ /^obj\/.*\.o$/ {last = $4} END {print last}' "$_ninja_log")
test -n "$_first_object"
test -n "$_last_object"

_diagnostics=out/Default/checkpoint-check.log
_ninja=(python3 third_party/depot_tools/autoninja.py -C out/Default)
if ! _dry_run=$("${_ninja[@]}" -n -d explain "$_first_object" "$_last_object" 2>"$_diagnostics"); then
  sed -n '1,80p' "$_diagnostics" >&2
  exit 1
fi
if [[ "$_dry_run" != *"ninja: no work to do."* ]]; then
  # mac_sysroot declares external SDK headers as outputs of build/noop.py.
  # On another runner this restat edge can be dirty. A dry-run cannot observe
  # unchanged outputs and conservatively schedules downstream compilation.
  # Execute only that edge, then check the objects again. Do not execute any
  # compilation or other generators here, or disable timestamp checking.
  _sysroot_plan=$("${_ninja[@]}" -n mac_sysroot)
  _sysroot_actions=$(printf '%s\n' "$_sysroot_plan" | awk '/^\[[0-9]+\/[0-9]+\]/ {n++} END {print n+0}')
  if [[ "$_sysroot_actions" = 1 ]] && \
      printf '%s\n' "$_sysroot_plan" | grep -Eq '^\[1/1\] ACTION //build/modules:mac_sysroot\('; then
    echo "Refreshing the SDK noop/restat edge before checking restored objects"
    "${_ninja[@]}" mac_sysroot
    if ! _dry_run=$("${_ninja[@]}" -n -d explain "$_first_object" "$_last_object" 2>>"$_diagnostics"); then
      sed -n '1,80p' "$_diagnostics" >&2
      exit 1
    fi
  fi
fi

if [[ "$_dry_run" != *"ninja: no work to do."* ]]; then
  printf '%s\n' "$_dry_run" | sed -n '1,40p'
  echo "Restored build would recompile previously completed objects" >&2
  echo "Ninja dependency diagnostics (first 80 lines):" >&2
  sed -n '1,80p' "$_diagnostics" >&2
  exit 1
fi
echo "Checkpoint verified: sampled objects need no recompilation"

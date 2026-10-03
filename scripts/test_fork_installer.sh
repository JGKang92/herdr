#!/usr/bin/env bash
set -euo pipefail
# Exercise replacement of an executing file and checksum rejection in an isolated directory.
script=$(cd "$(dirname "$0")" && pwd)/install_close_confirmation.sh
binary=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
root=$(mktemp -d "$RUNNER_TEMP/fork-installer.XXXXXX")
asset="herdr-linux-$(uname -m)"
mkdir -p "$root/bin" "$root/files"
cp "$binary" "$root/files/$asset"
(cd "$root/files"; sha256sum "$asset" > "$asset.sha256")
cp /bin/sleep "$root/bin/herdr"
"$root/bin/herdr" 300 &
live_pid=$!
trap 'kill "$live_pid" 2>/dev/null || true; rm -rf "$root"' EXIT
old_hash=$(sha256sum "$root/bin/herdr" | awk '{print $1}')
old_inode=$(stat -Lc '%i' "$root/bin/herdr")
for attempt in $(seq 1 20); do
    if [ "$(stat -Lc '%i' "/proc/$live_pid/exe")" = "$old_inode" ]; then break; fi
    sleep 0.05
done
test "$(stat -Lc '%i' "/proc/$live_pid/exe")" = "$old_inode"
export HERDR_CLOSE_CONFIRMATION_DOWNLOAD_BASE_URL="file://$root/files"
export HERDR_CLOSE_CONFIRMATION_INSTALL_DIR="$root/bin"
sh "$script"
kill -0 "$live_pid"
test "$(stat -Lc '%i' "/proc/$live_pid/exe")" = "$old_inode"
test "$(stat -Lc '%i' "$root/bin/herdr")" != "$old_inode"
expected=$(awk '{print $1}' "$root/files/$asset.sha256")
test "$(sha256sum "$root/bin/herdr" | awk '{print $1}')" = "$expected"
backup=$(find "$root/bin" -maxdepth 1 -name 'herdr.before-close-confirmation.*' -type f)
test "$(sha256sum "$backup" | awk '{print $1}')" = "$old_hash"
printf '%064d  %s\n' 0 "$asset" > "$root/files/$asset.sha256"
if sh "$script"; then echo 'Corrupt download accepted' >&2; exit 1; fi
test "$(sha256sum "$root/bin/herdr" | awk '{print $1}')" = "$expected"
kill -0 "$live_pid"
echo 'PASS: replacement, backup, process preservation, corrupt download rejection'

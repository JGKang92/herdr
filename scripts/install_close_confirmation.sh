#!/bin/sh
set -eu

if [ "$(uname -s)" != Linux ]; then
    echo 'This installer requires Linux.' >&2
    exit 1
fi
case "$(uname -m)" in
    x86_64) arch=x86_64 ;;
    aarch64|arm64) arch=aarch64 ;;
    *) echo 'Supported CPUs: x86_64 and aarch64.' >&2; exit 1 ;;
esac

asset="herdr-linux-$arch"
base_url=${HERDR_CLOSE_CONFIRMATION_DOWNLOAD_BASE_URL:-https://github.com/JGKang92/herdr/releases/download/close-confirmation-v0.9.1-3d2f571}
install_dir=${HERDR_CLOSE_CONFIRMATION_INSTALL_DIR:-"$HOME/.local/bin"}
mkdir -p "$install_dir"
stage=$(mktemp "$install_dir/.herdr-close-confirmation.XXXXXX")
trap 'rm -f -- "$stage"' 0
trap 'exit 130' INT
trap 'exit 143' HUP TERM

expected_hash=$(curl -fsSL "$base_url/$asset.sha256" | awk '{print $1}')
curl -fSL "$base_url/$asset" -o "$stage"
printf '%s  %s\n' "$expected_hash" "$stage" | sha256sum -c -
chmod 755 "$stage"
"$stage" --version

destination="$install_dir/herdr"
if [ -e "$destination" ]; then
    backup="$install_dir/herdr.before-close-confirmation.$(date +%Y%m%d%H%M%S).$$"
    cp -p "$destination" "$backup"
    printf 'Backup: %s\n' "$backup"
fi
mv -f "$stage" "$destination"
printf 'Installed: %s\n' "$destination"
printf 'Run: "%s"\n' "$destination"

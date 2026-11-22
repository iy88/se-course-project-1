#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 INCOMING_RELEASE_DIR RELEASES_DIR" >&2
    exit 2
fi

incoming=$(cd "$1" && pwd -P)
releases=$(cd "$2" && pwd -P)
release_id=${incoming##*/}
if [[ ! "$release_id" =~ ^[0-9a-f]{40}-[0-9]+$ ]]; then
    echo "Invalid release ID: $release_id" >&2
    exit 2
fi

archive="project1-$release_id.tar.gz"
(
    cd "$incoming"
    if command -v sha256sum >/dev/null; then
        actual=$(sha256sum "$archive")
    else
        actual=$(shasum -a 256 "$archive")
    fi
    if [[ "$actual" != "$(cat SHA256SUMS)" ]]; then
        echo "Release checksum mismatch: $release_id" >&2
        exit 1
    fi
)

destination="$releases/$release_id"
umask 022
mkdir -- "$destination"
prepared=false
cleanup() {
    if [[ "$prepared" == false ]]; then
        rm -rf -- "$destination"
    fi
}
trap cleanup EXIT
tar -xzf "$incoming/$archive" -C "$destination"
for required in backend/backend-app.jar backend/maintenance.jar user-web/index.html admin-web/index.html release.txt deploy/activate-release.py; do
    test -s "$destination/$required"
done
grep -qxF "revision=${release_id%-*}" "$destination/release.txt"
grep -qxF "build_number=${release_id##*-}" "$destination/release.txt"
grep -qxF "release_id=$release_id" "$destination/release.txt"
touch "$destination/.prepared"
prepared=true
printf 'PREPARED_RELEASE=%s\n' "$destination"

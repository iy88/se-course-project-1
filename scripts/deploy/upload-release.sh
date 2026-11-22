#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 RELEASE_ARTIFACT_DIR" >&2
    exit 2
fi

host=${PROJECT1_V2_DEPLOY_HOST:-}
user=${PROJECT1_V2_DEPLOY_USER:-}
if [[ ! "$host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
    echo "Set PROJECT1_V2_DEPLOY_HOST to the source host name or IPv4 address" >&2
    exit 2
fi
if [[ ! "$user" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    echo "Set PROJECT1_V2_DEPLOY_USER to the source host SSH account" >&2
    exit 2
fi

artifact_dir=$(cd "$1" && pwd -P)
release_id=${artifact_dir##*/}
if [[ ! "$release_id" =~ ^[0-9a-f]{40}-[0-9]+$ ]]; then
    echo "Invalid release ID: $release_id" >&2
    exit 2
fi

server="$user@$host"
root=/srv/se-course-project1-v2
incoming="$root/incoming/$release_id"
ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10)
ssh "${ssh_options[@]}" "$server" "umask 077; mkdir -- '$incoming'"
scp "${ssh_options[@]}" "$artifact_dir/project1-$release_id.tar.gz" "$artifact_dir/SHA256SUMS" "$server:$incoming/"
ssh "${ssh_options[@]}" "$server" "bash -s -- '$incoming' '$root/releases'" < "$(dirname "$0")/prepare-release.sh"

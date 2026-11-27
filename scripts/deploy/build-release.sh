#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || ! "$2" =~ ^[0-9]+$ ]]; then
    echo "Usage: $0 OUTPUT_DIR BUILD_NUMBER" >&2
    exit 2
fi

repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
revision=$(git -C "$repo" rev-parse HEAD)
build_number=$2
release_id="$revision-$build_number"
mkdir -p "$1"
output=$(cd "$1" && pwd -P)
destination="$output/$release_id"
if [[ -e "$destination" || -L "$destination" ]]; then
    echo "Release already exists: $destination" >&2
    exit 1
fi

build_dir=$(mktemp -d "$output/.build-release.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT
source_dir="$build_dir/source"
payload="$build_dir/payload"
artifacts="$build_dir/artifacts"
mkdir -p "$source_dir" "$payload/backend" "$artifacts"

# Use a separate index to export the committed release paths without fetching docs blobs.
(
    export GIT_INDEX_FILE="$build_dir/source.index"
    git -C "$repo" read-tree "$revision"
    git -C "$repo" ls-files -z -- .node-version backend frontend scripts/deploy |
        git -C "$repo" checkout-index -z --stdin --prefix="$source_dir/"
)

(
    cd "$source_dir/backend"
    mvn --batch-mode --no-transfer-progress -T 10 -Dmaven.test.skip=true -pl backend-app,maintenance -am package
) &
backend_pid=$!

(
    cd "$source_dir/frontend"
    expected_node=$(tr -d '[:space:]' < ../.node-version)
    actual_node=$(node -p 'process.versions.node')
    if [[ "$actual_node" != "$expected_node" ]]; then
        echo "Expected Node.js $expected_node, got $actual_node" >&2
        exit 1
    fi
    expected_pnpm=$(node -p "require('./package.json').packageManager.split('@')[1]")
    actual_pnpm=$(pnpm --version)
    if [[ "$actual_pnpm" != "$expected_pnpm" ]]; then
        echo "Expected pnpm $expected_pnpm, got $actual_pnpm" >&2
        exit 1
    fi
    pnpm install --frozen-lockfile
    pnpm run build
) &
frontend_pid=$!

build_failed=0
if ! wait "$backend_pid"; then
    echo "Backend build failed" >&2
    build_failed=1
fi
if ! wait "$frontend_pid"; then
    echo "Frontend build failed" >&2
    build_failed=1
fi
if (( build_failed )); then
    exit 1
fi

copy_jar() {
    local module=$1
    local jars=("$source_dir/backend/$module/target/$module-"*.jar)
    if [[ ${#jars[@]} -ne 1 || ! -s "${jars[0]}" ]]; then
        echo "Expected one executable JAR for $module" >&2
        exit 1
    fi
    cp "${jars[0]}" "$payload/backend/$module.jar"
}

copy_jar backend-app
copy_jar maintenance
for app in user-web admin-web; do
    test -s "$source_dir/frontend/$app/dist/index.html"
    cp -R "$source_dir/frontend/$app/dist" "$payload/$app"
done
cp -R "$source_dir/scripts/deploy" "$payload/deploy"

printf 'revision=%s\nbuild_number=%s\nrelease_id=%s\n' "$revision" "$build_number" "$release_id" > "$payload/release.txt"
archive="project1-$release_id.tar.gz"
COPYFILE_DISABLE=1 tar -C "$payload" -czf "$artifacts/$archive" backend user-web admin-web deploy release.txt
(
    cd "$artifacts"
    if command -v sha256sum >/dev/null; then
        sha256sum "$archive" > SHA256SUMS
        sha256sum -c SHA256SUMS
    else
        shasum -a 256 "$archive" > SHA256SUMS
        shasum -a 256 -c SHA256SUMS
    fi
)
python3 - "$artifacts" "$destination" <<'PY'
import os
import sys

os.rename(sys.argv[1], sys.argv[2])
PY
printf 'Release packaged: %s\n' "$destination"

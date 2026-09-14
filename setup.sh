#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    echo 'Run setup.sh as root (sudo bash setup.sh).' >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    aria2 bc brotli ca-certificates curl e2fsprogs erofs-utils p7zip-full \
    python3 python3-pip unzip zip
apt-get clean
rm -rf /var/lib/apt/lists/*

repo_dir=$(cd "$(dirname "$0")" && pwd)
chmod -R a+rx "$repo_dir/bin/Linux/x86_64" "$repo_dir/scripts"
echo 'Build dependencies are ready.'

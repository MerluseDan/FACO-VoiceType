#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v sha256sum >/dev/null 2>&1; then
  echo 'Missing sha256sum from coreutils.' >&2
  exit 1
fi
echo 'Checking FACO Resource Watch release file integrity...'
sha256sum --check MANIFEST.sha256
echo 'Package hashes verified.'

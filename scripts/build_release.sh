#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$ROOT/src/faco_voicetype/__init__.py")"
[[ -n "$VERSION" ]] || { echo "Unable to determine release version." >&2; exit 1; }

NAME="FACO_VoiceType_$VERSION"
DIST="$ROOT/dist"
ARCHIVE="$DIST/$NAME.tar.gz"
CHECKSUM="$ARCHIVE.sha256"

mkdir -p "$DIST"
rm -f -- "$ARCHIVE" "$CHECKSUM"

tar \
  --exclude-vcs \
  --exclude='./.venv' \
  --exclude='./.venv/*' \
  --exclude='*/__pycache__' \
  --exclude='*/__pycache__/*' \
  --exclude='./.pytest_cache' \
  --exclude='./.pytest_cache/*' \
  --exclude='./dist' \
  --exclude='./dist/*' \
  --transform "s,^,$NAME/," \
  -czf "$ARCHIVE" \
  -C "$ROOT" .

(cd "$DIST" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$CHECKSUM")")
(cd "$DIST" && sha256sum -c "$(basename "$CHECKSUM")")
tar -tzf "$ARCHIVE" >/dev/null

printf 'Created %s\nCreated %s\n' "$ARCHIVE" "$CHECKSUM"

#!/bin/bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"
export SECOND_BRAIN_PROFILE=${SECOND_BRAIN_PROFILE:-public}

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON=${PYTHON:-"$ROOT_DIR/.venv/bin/python"}
else
  PYTHON=${PYTHON:-python3}
fi

if [ "${SECOND_BRAIN_RELEASE:-0}" = "1" ]; then
  PYTHONPATH=src "$PYTHON" scripts/validate_public_release.py
fi

"$PYTHON" -m pip install -e ".[build]"
"$PYTHON" -m PyInstaller --noconfirm --clean packaging/second_brain.spec

APP_PATH="$ROOT_DIR/dist/Second Brain Archive.app"
if [ ! -d "$APP_PATH" ]; then
  echo "macOS app bundle was not created: $APP_PATH" >&2
  exit 1
fi

if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  codesign \
    --force \
    --deep \
    --options runtime \
    --timestamp \
    --sign "$APPLE_SIGNING_IDENTITY" \
    "$APP_PATH"
else
  codesign --force --deep --sign - "$APP_PATH"
fi

ARCH=$(uname -m)
STAGING_DIR="$ROOT_DIR/build/dmg"
DMG_PATH="$ROOT_DIR/dist/Second-Brain-Archive-macOS-$ARCH.dmg"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"
rm -f "$DMG_PATH"
hdiutil create \
  -volname "Second Brain Archive" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

if [ -n "${APPLE_NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$APPLE_NOTARY_PROFILE" \
    --wait
  xcrun stapler staple "$DMG_PATH"
elif [ -n "${APPLE_ID:-}" ] \
  && [ -n "${APPLE_TEAM_ID:-}" ] \
  && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
  xcrun notarytool submit "$DMG_PATH" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" \
    --wait
  xcrun stapler staple "$DMG_PATH"
fi

echo "$DMG_PATH"

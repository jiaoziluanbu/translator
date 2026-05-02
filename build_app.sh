#!/usr/bin/env bash
# Build Local Translator.app and (optionally) a .dmg installer.
# Usage:
#   bash build_app.sh           # builds .app + .dmg
#   bash build_app.sh --no-dmg  # only .app
set -euo pipefail

cd "$(dirname "$0")"

# 1. Compile Swift translator helper.
echo "==> compiling swift/translator-helper"
( cd swift && swiftc -O -parse-as-library -o translator-helper translator_helper.swift )

# 2. Compile the SwiftUI first-run language downloader (kept under swift/).
echo "==> compiling swift/TranslatorPrepare.app"
( cd swift && swiftc -O -parse-as-library -o probe-prepare probe_prepare.swift && \
    mkdir -p TranslatorPrepare.app/Contents/MacOS && \
    cp probe-prepare TranslatorPrepare.app/Contents/MacOS/TranslatorPrepare )

# 3. Clean previous py2app artifacts (move aside so the user can recover them).
TS=$(date +%Y%m%d-%H%M%S)
[ -d build ] && mv build "build.bak-$TS"
[ -d dist  ] && mv dist  "dist.bak-$TS"

# 4. Run py2app. Bumped recursion limit because modulegraph blows up on
#    deeply nested ASTs in some transitive deps.
echo "==> running py2app (this takes 2-5 minutes)"
python3 -c "
import sys
sys.setrecursionlimit(10000)
sys.argv = ['setup.py', 'py2app']
exec(open('setup.py').read())
"

# 5. Copy the language-downloader .app next to the main bundle inside Resources/
#    so a user-visible 'install language packs' helper ships with the .dmg.
cp -R swift/TranslatorPrepare.app "dist/Local Translator.app/Contents/Resources/swift/"

echo "==> build done: dist/Local Translator.app ($(du -sh "dist/Local Translator.app" | cut -f1))"

if [[ "${1:-}" == "--no-dmg" ]]; then
    exit 0
fi

# 6. Build a simple .dmg via hdiutil (no signing, no fancy layout).
echo "==> building dmg"
DMG_NAME="LocalTranslator-2.0.0.dmg"
DMG_TMP="dist/.dmg-staging"
rm -rf "$DMG_TMP" "dist/$DMG_NAME"
mkdir -p "$DMG_TMP"
cp -R "dist/Local Translator.app" "$DMG_TMP/"
ln -s /Applications "$DMG_TMP/Applications"
hdiutil create -volname "Local Translator" \
    -srcfolder "$DMG_TMP" \
    -ov -format UDZO \
    "dist/$DMG_NAME"
rm -rf "$DMG_TMP"

echo "==> dmg done: dist/$DMG_NAME ($(du -sh "dist/$DMG_NAME" | cut -f1))"

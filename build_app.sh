#!/usr/bin/env bash
# Build Local Translator.app and (optionally) a .dmg installer.
# Usage:
#   bash build_app.sh           # builds .app + .dmg
#   bash build_app.sh --no-dmg  # only .app
set -euo pipefail

cd "$(dirname "$0")"

pick_python() {
    local candidates=()
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        candidates+=("$PYTHON_BIN")
    fi
    if [[ "$(uname)" == "Darwin" && -x /usr/bin/python3 ]]; then
        candidates+=("/usr/bin/python3")
    fi
    if command -v python3 &>/dev/null; then
        candidates+=("$(command -v python3)")
    fi
    candidates+=("/opt/homebrew/bin/python3" "/usr/local/bin/python3")

    local py
    for py in "${candidates[@]}"; do
        [[ -x "$py" ]] || continue
        "$py" - <<'PYEOF' >/dev/null 2>&1 && { echo "$py"; return 0; }
import sys
raise SystemExit(not ((3, 9) <= sys.version_info[:2] < (3, 13)))
PYEOF
    done
    return 1
}

PYTHON_BIN="$(pick_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: No compatible Python found. Need Python 3.9-3.12." >&2
    exit 1
fi
echo "==> using $("$PYTHON_BIN" --version) at $PYTHON_BIN"

# 1. Compile Swift translator helper.
echo "==> compiling swift/translator-helper"
( cd swift && swiftc -O -parse-as-library -o translator-helper translator_helper.swift )

# 2. Compile the SwiftUI first-run language downloader (kept under swift/).
echo "==> compiling swift/TranslatorPrepare.app"
( cd swift && swiftc -O -parse-as-library -o probe-prepare probe_prepare.swift && \
    mkdir -p TranslatorPrepare.app/Contents/MacOS && \
    cp probe-prepare TranslatorPrepare.app/Contents/MacOS/TranslatorPrepare && \
    cat > TranslatorPrepare.app/Contents/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key><string>TranslatorPrepare</string>
	<key>CFBundleIdentifier</key><string>com.local.translator.prepare</string>
	<key>CFBundleName</key><string>TranslatorPrepare</string>
	<key>CFBundleDisplayName</key><string>TranslatorPrepare</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>1.0</string>
	<key>CFBundleVersion</key><string>1</string>
	<key>LSMinimumSystemVersion</key><string>15.0</string>
	<key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
)

# 3. Clean previous py2app artifacts (move aside so the user can recover them).
TS=$(date +%Y%m%d-%H%M%S)
[ -d build ] && mv build "build.bak-$TS"
[ -d dist  ] && mv dist  "dist.bak-$TS"

# 4. Run py2app. Bumped recursion limit because modulegraph blows up on
#    deeply nested ASTs in some transitive deps.
echo "==> running py2app (this takes 2-5 minutes)"
"$PYTHON_BIN" -c "
import sys
sys.setrecursionlimit(10000)
sys.argv = ['setup.py', 'py2app']
exec(open('setup.py').read())
"

# 5. Copy the language-downloader .app next to the main bundle inside Resources/
#    so a user-visible 'install language packs' helper ships with the .dmg.
cp -R swift/TranslatorPrepare.app "dist/Local Translator.app/Contents/Resources/swift/"
if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - "dist/Local Translator.app"
fi

echo "==> build done: dist/Local Translator.app ($(du -sh "dist/Local Translator.app" | cut -f1))"

if [[ "${1:-}" == "--no-dmg" ]]; then
    exit 0
fi

# 6. Build a simple .dmg via hdiutil (no signing, no fancy layout).
echo "==> building dmg"
DMG_NAME="LocalTranslator-2.2.1.dmg"
DMG_TMP="dist/.dmg-staging"
rm -rf "$DMG_TMP" "dist/$DMG_NAME"
mkdir -p "$DMG_TMP"
if ! cp -cR "dist/Local Translator.app" "$DMG_TMP/"; then
    cp -R "dist/Local Translator.app" "$DMG_TMP/"
fi
ln -s /Applications "$DMG_TMP/Applications"
hdiutil create -volname "Local Translator" \
    -srcfolder "$DMG_TMP" \
    -ov -format UDZO \
    "dist/$DMG_NAME"
rm -rf "$DMG_TMP"

echo "==> dmg done: dist/$DMG_NAME ($(du -sh "dist/$DMG_NAME" | cut -f1))"

# 7. Install (or refresh) the right-click "Translate" Service for the
#    current user. Lives under ~/Library/Application Support/ to dodge
#    the macOS TCC sandbox that blocks Automator from running scripts
#    in ~/Documents. The Automator workflow itself goes to
#    ~/Library/Services/ and points to a no-space symlink under
#    ~/.local/bin/ so the shell parser doesn't choke on path spaces.
echo "==> installing right-click translate service"
SCRIPT_SRC="$(pwd)/scripts/translate-service.sh"
SAFE_DIR="$HOME/Library/Application Support/LocalTranslator/bin"
ALIAS_DIR="$HOME/.local/bin"
mkdir -p "$SAFE_DIR" "$ALIAS_DIR"
cp "$SCRIPT_SRC" "$SAFE_DIR/translate-service.sh"
chmod +x "$SAFE_DIR/translate-service.sh"
ln -sf "$SAFE_DIR/translate-service.sh" "$ALIAS_DIR/lt-translate.sh"

WF="$HOME/Library/Services/Translate.workflow"
mkdir -p "$WF/Contents"
cat > "$WF/Contents/Info.plist" <<'INFOEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSMenuItem</key><dict><key>default</key><string>Translate</string></dict>
			<key>NSMessage</key><string>runWorkflowAsService</string>
			<key>NSSendTypes</key><array><string>NSStringPboardType</string><string>public.utf8-plain-text</string></array>
		</dict>
	</array>
</dict>
</plist>
INFOEOF
cat > "$WF/Contents/document.wflow" <<WFEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key><string>523</string>
	<key>AMApplicationVersion</key><string>2.10</string>
	<key>AMDocumentVersion</key><string>2</string>
	<key>actions</key><array><dict>
		<key>action</key><dict>
			<key>AMAccepts</key><dict><key>Container</key><string>List</string><key>Optional</key><true/><key>Types</key><array><string>com.apple.cocoa.string</string></array></dict>
			<key>AMActionVersion</key><string>2.0.3</string>
			<key>AMApplication</key><array><string>Automator</string></array>
			<key>AMParameterProperties</key><dict><key>COMMAND_STRING</key><dict/><key>CheckedForUserDefaultShell</key><dict/><key>inputMethod</key><dict/><key>shell</key><dict/><key>source</key><dict/></dict>
			<key>AMProvides</key><dict><key>Container</key><string>List</string><key>Types</key><array><string>com.apple.cocoa.string</string></array></dict>
			<key>ActionBundlePath</key><string>/System/Library/Automator/Run Shell Script.action</string>
			<key>ActionName</key><string>Run Shell Script</string>
			<key>ActionParameters</key><dict>
				<key>COMMAND_STRING</key><string>$ALIAS_DIR/lt-translate.sh</string>
				<key>CheckedForUserDefaultShell</key><true/>
				<key>inputMethod</key><integer>0</integer>
				<key>shell</key><string>/bin/bash</string>
				<key>source</key><string></string>
			</dict>
			<key>BundleIdentifier</key><string>com.apple.RunShellScript</string>
			<key>CFBundleVersion</key><string>2.0.3</string>
			<key>Class Name</key><string>RunShellScriptAction</string>
			<key>InputUUID</key><string>D4D049FB-6D3C-4E0C-9B6A-1F53A0B5F45D</string>
			<key>OutputUUID</key><string>E7F14A2B-8C5D-4F1A-B3E6-2A64C1D6F78E</string>
			<key>UUID</key><string>A1B2C3D4-E5F6-7890-ABCD-EF1234567890</string>
		</dict>
		<key>isViewVisible</key><true/>
	</dict></array>
	<key>connectors</key><dict/>
	<key>workflowMetaData</key><dict>
		<key>serviceInputTypeIdentifier</key><string>com.apple.Automator.text</string>
		<key>serviceOutputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key><integer>0</integer>
		<key>workflowTypeIdentifier</key><string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
WFEOF
/System/Library/CoreServices/pbs -flush 2>/dev/null || true
echo "==> service installed at $WF (cmd: $ALIAS_DIR/lt-translate.sh)"

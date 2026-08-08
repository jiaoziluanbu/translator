#!/usr/bin/env bash
# Right-click Services translator. Reads selected text from stdin, detects
# Chinese/Japanese/Korean/English by Unicode range, calls the Swift helper
# (Apple Translation framework) for high-quality translation, falls back to
# argostranslate if the helper is missing or the language pair isn't installed,
# and shows the result in a native macOS dialog with a Copy button.
set -euo pipefail

# Resolve helper + project paths. Prefer the installed .app bundle (so this
# script works on any machine after `bash build_app.sh`); fall back to a path
# relative to this script (dev tree).
APP_RES="/Applications/Local Translator.app/Contents/Resources"
APP_EXE="/Applications/Local Translator.app/Contents/MacOS/Local Translator"
APP_DAEMON="$APP_RES/daemon.py"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$APP_RES/swift/translator-helper" ]; then
    HELPER="$APP_RES/swift/translator-helper"
    PROJECT="$APP_RES"
else
    HELPER="$SCRIPT_DIR/../swift/translator-helper"
    PROJECT="$SCRIPT_DIR/.."
fi

# Locate a Python that has argostranslate installed (for fallback path).
PY=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$HOME/Library/Python/3.9/bin/python3" python3; do
    if "$p" -c "import argostranslate" 2>/dev/null; then PY="$p"; break; fi
done

# Read selected text from stdin.
text=$(cat)
text=$(printf '%s' "$text" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
if [ -z "$text" ]; then exit 0; fi

# Detect source language by real Unicode codepoints (bash globs match bytes,
# so e.g. the full-width ideographic "。" U+3002 collides with the ぁ-ゟ byte
# range and gets mis-flagged as Japanese — delegate to python3 to avoid that).
src=$(printf '%s' "$text" | /usr/bin/python3 -c "
import sys
t = sys.stdin.read()
if any('぀' <= c <= 'ゟ' or '゠' <= c <= 'ヿ' for c in t):
    print('ja')
elif any('가' <= c <= '힯' for c in t):
    print('ko')
elif any('一' <= c <= '鿿' for c in t):
    print('zh')
else:
    print('en')
")
case "$src" in
    zh) tgt="en" ;;
    *)  tgt="zh" ;;
esac

# Prefer the app's built-in service bridge.  It carries its own Python runtime
# and argostranslate package, so Automator does not need a separately installed
# "compatible Python".  It also honours the target language selected in the
# menubar app and uses the Swift helper first internally.
result=""
# The source marker keeps this updated Service compatible with an older app
# that does not understand --service-translate (calling an old executable with
# that flag would otherwise launch another menu-bar instance and never return).
if [ -x "$APP_EXE" ] && [ -f "$APP_DAEMON" ] \
    && grep -q -- '--service-translate' "$APP_DAEMON"; then
    result=$(printf '%s' "$text" | "$APP_EXE" --service-translate \
        2>>/tmp/translator-service.log || true)
fi

# Legacy/dev fallback: try the Swift helper directly when the installed app
# executable is unavailable.
if [ -z "$result" ] && [ -x "$HELPER" ]; then
    json=$(printf '%s' "$text" | python3 -c "import json,sys; print(json.dumps({'text': sys.stdin.read(), 'src':'$src', 'tgt':'$tgt'}, ensure_ascii=False))")
    out=$(printf '%s\n' "$json" | "$HELPER" 2>/dev/null | head -1) || true
    if [ -n "$out" ]; then
        result=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('text','') if d.get('ok') else '')")
    fi
fi

# Legacy/dev argos fallback.  Guard the script path explicitly because older
# app bundles did not include translate_cli.py; that missing file caused the
# misleading "Swift helper 未编译" error even when the helper existed.
if [ -z "$result" ] && [ -n "$PY" ] && [ -f "$PROJECT/translate_cli.py" ]; then
    result=$("$PY" "$PROJECT/translate_cli.py" "$text" 2>/dev/null || true)
fi

if [ -z "$result" ]; then
    result="[翻译失败：应用翻译组件不可用。请打开 Local Translator，并从菜单栏运行“① 下载/检查语言包”后重试。]"
fi

# Show in a dialog with Copy button.
printf '%s' "$result" > /tmp/translate_result.txt
osascript <<EOF
set resultText to do shell script "cat /tmp/translate_result.txt"
set dialogResult to display dialog resultText with title "Translation" buttons {"Close", "Copy"} default button "Copy"
if button returned of dialogResult is "Copy" then
    set the clipboard to resultText
end if
EOF

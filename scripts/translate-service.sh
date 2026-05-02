#!/usr/bin/env bash
# Right-click Services translator. Reads selected text from stdin, detects
# Chinese/Japanese/Korean/English by Unicode range, calls the Swift helper
# (Apple Translation framework) for high-quality translation, falls back to
# argostranslate if the helper is missing or the language pair isn't installed,
# and shows the result in a native macOS dialog with a Copy button.
set -euo pipefail

HELPER="/Users/jiaozidemacmini/Documents/自制产品/translator/swift/translator-helper"
PROJECT="/Users/jiaozidemacmini/Documents/自制产品/translator"

# Locate a Python that has argostranslate installed (for fallback path).
PY=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /Users/jiaozidemacmini/Library/Python/3.9/bin/python3 python3; do
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

# Try the Swift helper first.
result=""
if [ -x "$HELPER" ]; then
    json=$(printf '%s' "$text" | python3 -c "import json,sys; print(json.dumps({'text': sys.stdin.read(), 'src':'$src', 'tgt':'$tgt'}, ensure_ascii=False))")
    out=$(printf '%s\n' "$json" | "$HELPER" 2>/dev/null | head -1) || true
    if [ -n "$out" ]; then
        result=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('text','') if d.get('ok') else '')")
    fi
fi

# Argos fallback.
if [ -z "$result" ] && [ -n "$PY" ]; then
    result=$("$PY" "$PROJECT/translate_cli.py" "$text" 2>/dev/null || true)
fi

if [ -z "$result" ]; then
    result="[翻译失败：Swift helper 未编译且无 argos 兼容 Python]"
fi

# Show in a dialog with Copy button.
printf '%s' "$result" > /tmp/translate_result.txt
osascript <<EOF
set resultText to do shell script "cat /tmp/translate_result.txt"
set dialogResult to display dialog resultText with title "Translation ($src → $tgt)" buttons {"Close", "Copy"} default button "Copy"
if button returned of dialogResult is "Copy" then
    set the clipboard to resultText
end if
EOF

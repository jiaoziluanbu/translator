#!/usr/bin/env python3
"""Standalone CLI translator - reads text, translates, shows result dialog."""

import sys
import subprocess
import os

import argostranslate.translate
import argostranslate.package


def detect(text):
    """Simple language detection based on Unicode ranges."""
    if any("\u3040" <= c <= "\u309f" or "\u30a0" <= c <= "\u30ff" for c in text):
        return "ja", "zh"
    if any("\uac00" <= c <= "\ud7af" for c in text):
        return "ko", "zh"
    if any("\u4e00" <= c <= "\u9fff" for c in text):
        return "zh", "en"
    return "en", "zh"


def translate(text, src_code, tgt_code):
    """Translate using argostranslate with English pivot fallback."""
    try:
        installed = argostranslate.translate.get_installed_languages()
        lm = {lang.code: lang for lang in installed}
        src = lm.get(src_code)
        tgt = lm.get(tgt_code)
        if not src or not tgt:
            return f"[Language not installed: {src_code}/{tgt_code}]"

        t = src.get_translation(tgt)
        if t:
            return t.translate(text)

        en = lm.get("en")
        if en and src_code != "en" and tgt_code != "en":
            t1 = src.get_translation(en)
            t2 = en.get_translation(tgt)
            if t1 and t2:
                return t2.translate(t1.translate(text))

        return f"[No translation path: {src_code} -> {tgt_code}]"
    except Exception as e:
        return f"[Error: {e}]"


def show_dialog(result):
    """Show translation result in a native macOS dialog, with Copy button."""
    # Write to fixed path to avoid tempdir inconsistency across environments
    tmp = "/tmp/translate_result.txt"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(result)

    subprocess.run([
        "osascript", "-e",
        'set resultText to do shell script "cat /tmp/translate_result.txt"\n'
        'set dialogResult to display dialog resultText with title '
        '"Translation" buttons {"Close", "Copy"} default button "Copy"\n'
        'if button returned of dialogResult is "Copy" then\n'
        '    set the clipboard to resultText\n'
        'end if'
    ])


def main():
    show_as_dialog = "--dialog" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dialog"]

    # Read text from args or stdin
    if args:
        text = " ".join(args)
    else:
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        return

    src, tgt = detect(text)
    result = translate(text, src, tgt)

    if show_as_dialog:
        show_dialog(result)
    else:
        print(result)


if __name__ == "__main__":
    main()

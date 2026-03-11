#!/usr/bin/env python3
"""Local Translator Daemon - system-wide select-to-translate with Cmd+Shift+T."""

import os
import subprocess
import sys
import threading
import time

import rumps
from pynput import keyboard

import argostranslate.translate
import argostranslate.package

from AppKit import (
    NSPanel, NSMakeRect, NSBackingStoreBuffered,
    NSScreen, NSEvent, NSTextField, NSFont, NSColor, NSView,
)
from PyObjCTools.AppHelper import callAfter

try:
    from ApplicationServices import AXIsProcessTrusted
except ImportError:
    AXIsProcessTrusted = None

DIR = os.path.dirname(os.path.abspath(__file__))

LANG_NAMES = {
    "en": "EN", "zh": "中文", "ja": "日本語", "ko": "한국어",
    "fr": "FR", "de": "DE", "es": "ES", "pt": "PT",
    "ru": "RU", "it": "IT", "ar": "AR",
}


class TranslatorDaemon(rumps.App):
    def __init__(self):
        super().__init__("译", quit_button=None)
        self.panel = None
        self.menu = [
            rumps.MenuItem("选中翻译 ⌘⇧Y", callback=self._show_usage),
            rumps.MenuItem("打开翻译器", callback=self._open_translator),
            None,
            rumps.MenuItem("退出", callback=rumps.quit_application),
        ]
        # Check accessibility permission on launch
        if AXIsProcessTrusted and not AXIsProcessTrusted():
            rumps.notification(
                "Local Translator",
                "需要辅助功能权限",
                "请前往 系统设置 → 隐私与安全性 → 辅助功能 中启用本应用",
            )
        self._start_hotkey()

    def _start_hotkey(self):
        """Start global hotkey listener in background thread."""
        hk = keyboard.GlobalHotKeys({"<cmd>+<shift>+y": self._on_hotkey})
        hk.daemon = True
        hk.start()

    def _on_hotkey(self):
        threading.Thread(target=self._do_translate, daemon=True).start()

    def _do_translate(self):
        """Get selected text, translate, show popup."""
        # Save current clipboard
        try:
            old_clip = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=2
            ).stdout
        except Exception:
            old_clip = ""

        # Simulate Cmd+C to copy selection
        kb = keyboard.Controller()
        kb.press(keyboard.Key.cmd)
        kb.press("c")
        kb.release("c")
        kb.release(keyboard.Key.cmd)
        time.sleep(0.2)

        # Read new clipboard content
        try:
            selected = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=2
            ).stdout
        except Exception:
            return

        # Restore original clipboard
        if selected != old_clip:
            try:
                subprocess.run(["pbcopy"], input=old_clip, text=True, timeout=2)
            except Exception:
                pass

        text = selected.strip()
        if not text:
            return

        src, tgt = self._detect(text)
        result = self._translate(text, src, tgt)
        callAfter(self._show_popup, text, result, src, tgt)

    def _detect(self, text):
        """Simple language detection based on Unicode character ranges."""
        has_ja = any(
            "\u3040" <= c <= "\u309f" or "\u30a0" <= c <= "\u30ff" for c in text
        )
        if has_ja:
            return "ja", "zh"
        if any("\uac00" <= c <= "\ud7af" for c in text):
            return "ko", "zh"
        if any("\u4e00" <= c <= "\u9fff" for c in text):
            return "zh", "en"
        return "en", "zh"

    def _translate(self, text, src_code, tgt_code):
        """Translate using argostranslate with English pivot fallback."""
        try:
            installed = argostranslate.translate.get_installed_languages()
            lm = {lang.code: lang for lang in installed}
            src = lm.get(src_code)
            tgt = lm.get(tgt_code)
            if not src or not tgt:
                return f"[语言未安装: {src_code}/{tgt_code}]"

            t = src.get_translation(tgt)
            if t:
                return t.translate(text)

            # Pivot through English
            en = lm.get("en")
            if en and src_code != "en" and tgt_code != "en":
                t1 = src.get_translation(en)
                t2 = en.get_translation(tgt)
                if t1 and t2:
                    return t2.translate(t1.translate(text))

            return f"[无翻译路径: {src_code} → {tgt_code}]"
        except Exception as e:
            return f"[翻译错误: {e}]"

    def _show_popup(self, original, translated, src, tgt):
        """Show native floating panel near the mouse cursor."""
        if self.panel:
            self.panel.close()

        W, H = 420, 260
        mouse = NSEvent.mouseLocation()
        sf = NSScreen.mainScreen().visibleFrame()

        # Center below mouse, clamped to screen edges
        x = max(
            sf.origin.x + 10,
            min(mouse.x - W / 2, sf.origin.x + sf.size.width - W - 10),
        )
        y = mouse.y - H - 30
        if y < sf.origin.y:
            y = mouse.y + 30  # Show above cursor if too close to bottom

        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, H),
            1 | 2,  # NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_(
            f"{LANG_NAMES.get(src, src)} → {LANG_NAMES.get(tgt, tgt)}"
        )
        self.panel.setLevel_(3)  # NSFloatingWindowLevel
        self.panel.setHidesOnDeactivate_(True)

        cv = self.panel.contentView()

        # --- Translation result ---
        rf = NSTextField.alloc().initWithFrame_(NSMakeRect(15, 70, W - 30, H - 100))
        rf.setStringValue_(translated)
        rf.setEditable_(False)
        rf.setBezeled_(False)
        rf.setDrawsBackground_(False)
        rf.setFont_(NSFont.systemFontOfSize_(15))
        rf.setSelectable_(True)
        rf.cell().setWraps_(True)
        rf.cell().setScrollable_(False)
        cv.addSubview_(rf)

        # --- Separator ---
        sep = NSView.alloc().initWithFrame_(NSMakeRect(15, 62, W - 30, 1))
        sep.setWantsLayer_(True)
        sep.layer().setBackgroundColor_(NSColor.separatorColor().CGColor())
        cv.addSubview_(sep)

        # --- Original text ---
        of = NSTextField.alloc().initWithFrame_(NSMakeRect(15, 10, W - 30, 45))
        of.setStringValue_(original)
        of.setEditable_(False)
        of.setBezeled_(False)
        of.setDrawsBackground_(False)
        of.setFont_(NSFont.systemFontOfSize_(11))
        of.setTextColor_(NSColor.secondaryLabelColor())
        of.setSelectable_(True)
        of.cell().setWraps_(True)
        of.cell().setScrollable_(False)
        cv.addSubview_(of)

        self.panel.makeKeyAndOrderFront_(None)

    def _open_translator(self, _):
        """Launch the full translator window (app.py) as a subprocess."""
        subprocess.Popen([sys.executable, os.path.join(DIR, "app.py")])

    def _show_usage(self, _):
        rumps.notification(
            "Local Translator",
            "使用方法",
            "选中任意文本，按 ⌘⇧Y 即可翻译",
        )


if __name__ == "__main__":
    TranslatorDaemon().run()

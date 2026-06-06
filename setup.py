"""py2app build config for Local Translator.

Build:
    python3 setup.py py2app           # full standalone .app
    python3 setup.py py2app -A        # alias mode (faster, dev only)

Output: dist/Local Translator.app

Notes
-----
- argos translation models are NOT bundled (~500MB). They live in
  ~/.local/share/argos-translate/. README explains first-run setup.
- The Swift translator-helper binary IS bundled under Resources/swift/.
- Apple Translation framework's downloaded language packs are managed by
  the OS at user level; nothing for us to bundle there either.
- This is a menubar app: LSUIElement=True so it shows in the status bar
  and not in the Dock.
"""
from setuptools import setup
import os

APP = ["daemon.py"]

# Files to copy into Contents/Resources/. Each tuple is (dest_dir, [src_files]).
DATA_FILES = [
    ("", ["app.py"]),
    ("ui", [
        "ui/__init__.py",
        "ui/editor_window.py",
        "ui/editor.html",
        "ui/gallery_window.py",
        "ui/gallery.html",
        "ui/capture.py",
    ]),
    ("ui/vendor", ["ui/vendor/konva.min.js"]),
    ("core", [
        "core/__init__.py",
        "core/ocr.py",
        "core/translate.py",
        "core/layout.py",
        "core/storage.py",
        "core/pipeline.py",
    ]),
    ("swift", ["swift/translator-helper"]),
]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Local Translator",
        "CFBundleDisplayName": "Local Translator",
        "CFBundleIdentifier": "com.local.translator",
        "CFBundleVersion": "2.2.0",
        "CFBundleShortVersionString": "2.2.0",
        "LSMinimumSystemVersion": "15.0",
        # Menubar-only: hide Dock icon.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        # Permission usage descriptions (shown in macOS prompts).
        "NSAppleEventsUsageDescription": "Local Translator uses Apple Events to read selected text.",
        "NSScreenCaptureUsageDescription": "Local Translator captures regions of the screen for OCR translation.",
        "NSInputMonitoringUsageDescription": "Local Translator listens for the global ⌃⌥A hotkey to start a screen capture.",
        "NSAccessibilityUsageDescription": "Local Translator needs accessibility access to register the global ⌃⌥A hotkey.",
    },
    # Imports py2app cannot detect statically because they are loaded by
    # rumps/pywebview/argos at runtime, or imported as PyObjC bridges.
    "packages": [
        "rumps", "pynput", "argostranslate", "webview", "PIL",
    ],
    "includes": [
        "objc", "AppKit", "Foundation", "Vision", "CoreML", "Quartz",
        "WebKit", "ApplicationServices",
        "core", "core.ocr", "core.translate", "core.layout",
        "core.storage", "core.pipeline",
    ],
    # Excluding these saves ~50-150MB and avoids known py2app/Tk issues.
    # NOTE: cannot exclude `unittest` — torch (pulled in via argostranslate ->
    # stanza -> torch) imports `unittest.mock` at module init time.
    "excludes": ["tkinter", "test", "pydoc"],
    "resources": [],
}

setup(
    app=APP,
    name="Local Translator",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

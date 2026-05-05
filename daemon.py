#!/usr/bin/env python3
"""Local Translator Daemon — thin menubar shell.

Architecture (slim daemon, 2026-04-28):
  - This daemon process owns ONLY the menubar icon, the global hotkeys, and
    spawning subprocesses. It does NOT import core.pipeline, core.ocr,
    core.translate (apple-helper), or anything that touches Vision /
    Translation framework. Those modules trigger NSApp voluntary-terminate
    on macOS 26 + py2app for reasons we never fully untangled (PyObjC bridge
    + system framework + py2app bundle interaction). Keeping them out of the
    daemon = daemon stays alive.
  - ⌃⌥A → spawn `--worker` one-shot subprocess. Worker does:
        capture overlay → OCR → translate → spawn editor → os._exit(0)
    Worker dies after every screenshot. If the worker crashes, the daemon
    is unaffected.
  - ⌘⇧Y (select-to-translate) still runs in-daemon because argostranslate is
    pure Python and has never crashed the daemon.
"""

import json
import os
import subprocess
import sys
import threading
import time

# Lightweight diagnostic hooks. Keep them — they cost nothing and help us
# spot residual exits if anything ever goes wrong.
import atexit
import faulthandler
import traceback as _tb_mod

_FAULT_LOG = "/tmp/translator-fault.log"
try:
    _fault_fh = open(_FAULT_LOG, "a")
    _fault_fh.write(f"\n=== fault log opened {time.strftime('%H:%M:%S')} pid={os.getpid()} argv={sys.argv} ===\n")
    _fault_fh.flush()
    faulthandler.enable(file=_fault_fh, all_threads=True)
except Exception:
    pass


def _atexit_dump():
    try:
        with open(_FAULT_LOG, "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] ATEXIT pid={os.getpid()}\n")
    except Exception:
        pass


atexit.register(_atexit_dump)

# --- Conditional heavy imports ---
# rumps / pynput / argostranslate are only used by the daemon (the menubar
# process). Subprocess modes (--worker, --hot-worker, --from-image, etc.)
# don't need them. Importing argostranslate transitively pulls stanza + torch,
# which costs ~3-4 seconds of cold start on the editor subprocess. Stubbing
# them out for subprocess mode shaves that off.
_SUBPROCESS_FLAGS = {"--worker", "--hot-worker", "--gallery", "--capture",
                     "--from-meta", "--from-result", "--from-image"}
_IS_SUBPROCESS = (len(sys.argv) > 1 and sys.argv[1] in _SUBPROCESS_FLAGS)

if _IS_SUBPROCESS:
    # Stubs so module-level `class TranslatorDaemon(rumps.App)` parses without
    # actually loading the heavy deps. The class is never *instantiated* in
    # subprocess mode (main block dispatches to _run_worker / _run_subapp /
    # etc. before reaching the daemon path).
    import types as _types
    rumps = _types.SimpleNamespace(
        App=object,
        MenuItem=lambda *a, **kw: None,
        notification=lambda *a, **kw: None,
        quit_application=None,
    )
    keyboard = _types.SimpleNamespace(
        GlobalHotKeys=object,
        Controller=object,
        Key=_types.SimpleNamespace(cmd=None),
    )
    argostranslate = _types.SimpleNamespace(
        translate=_types.SimpleNamespace(get_installed_languages=list),
        package=None,
    )
else:
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


def _resource_dir() -> str:
    """Source root in dev; Resources/ inside a py2app bundle."""
    return os.environ.get("RESOURCEPATH") or DIR


RESOURCES = _resource_dir()
IS_BUNDLE = bool(os.environ.get("RESOURCEPATH"))


def _spawn_subapp(extra_argv, log_path: str):
    """Launch this same app in a subprocess with extra_argv (list).

    In a py2app bundle, sys.executable points at a thin `python` launcher whose
    rpath is broken when invoked outside `__boot__`. Use the main bundle
    executable instead (Contents/MacOS/<AppName>), which has correct rpath +
    inherits TCC grants from the parent. In dev, fall back to `python3 daemon.py`.
    """
    log = open(log_path, "ab", buffering=0)
    if IS_BUNDLE:
        macos_dir = os.path.join(os.path.dirname(RESOURCES), "MacOS")
        candidates = [n for n in os.listdir(macos_dir) if n != "python"]
        exe = os.path.join(macos_dir, candidates[0]) if candidates else sys.executable
        argv = [exe] + list(extra_argv)
    else:
        argv = [sys.executable, os.path.join(DIR, "daemon.py")] + list(extra_argv)
    return subprocess.Popen(argv, stdout=log, stderr=log)


LANG_NAMES = {
    "en": "EN", "zh": "中文", "ja": "日本語", "ko": "한국어",
    "fr": "FR", "de": "DE", "es": "ES", "pt": "PT",
    "ru": "RU", "it": "IT", "ar": "AR",
}

# User preferences (target language for ⌘⇧Y) — persisted across launches.
_PREFS_DIR = os.path.expanduser("~/Library/Application Support/LocalTranslator")
_PREFS_PATH = os.path.join(_PREFS_DIR, "prefs.json")
TARGET_LANG_OPTIONS = [
    ("auto", "自动 (按内容判断)"),
    ("zh", "中文"),
    ("en", "英文"),
    ("ja", "日文"),
    ("ko", "韩文"),
]


def _load_prefs() -> dict:
    try:
        with open(_PREFS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_prefs(prefs: dict) -> None:
    try:
        os.makedirs(_PREFS_DIR, exist_ok=True)
        with open(_PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class TranslatorDaemon(rumps.App):
    def __init__(self):
        super().__init__("译", quit_button=None)
        self.panel = None
        # Hot worker pool: a primed --hot-worker subprocess that has already
        # imported the heavy stack and is blocking on stdin.readline().
        # ⌃⌥A writes "GO\n" to it; daemon spawns a replacement immediately.
        self._hot_proc = None
        self._hot_ready = False
        self._hot_lock = threading.Lock()
        self._hot_respawn_inflight = False
        # Anti-spam: ignore ⌃⌥A presses that arrive too soon after the
        # previous trigger (overlay hasn't appeared yet → user thinks the
        # hotkey didn't register and mashes it, then multiple overlays
        # eventually stack on screen).
        self._last_capture_trigger_at = 0.0
        # Load persisted prefs (currently: target_lang for ⌘⇧Y).
        self.prefs = _load_prefs()
        self.prefs.setdefault("target_lang", "auto")

        # Build「目标语言」submenu — radio-style: selected item has a checkmark.
        target_submenu = rumps.MenuItem("目标语言")
        self._target_items: dict[str, rumps.MenuItem] = {}
        for code, label in TARGET_LANG_OPTIONS:
            item = rumps.MenuItem(label, callback=self._make_target_setter(code))
            item.state = 1 if code == self.prefs["target_lang"] else 0
            target_submenu.add(item)
            self._target_items[code] = item

        self.menu = [
            rumps.MenuItem("截图翻译 ⌃⌥A", callback=self._on_capture_menu),
            rumps.MenuItem("选中翻译 ⌘⇧Y", callback=self._show_usage),
            rumps.MenuItem("打开翻译器", callback=self._open_translator),
            rumps.MenuItem("打开画廊", callback=self._open_gallery),
            None,
            target_submenu,
            None,
            rumps.MenuItem("退出", callback=rumps.quit_application),
        ]
        try:
            trusted = bool(AXIsProcessTrusted()) if AXIsProcessTrusted else None
            with open("/tmp/translator-startup.log", "a") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] AXIsProcessTrusted={trusted} bundle={IS_BUNDLE}\n")
        except Exception:
            pass
        if AXIsProcessTrusted and not AXIsProcessTrusted():
            rumps.notification(
                "Local Translator",
                "需要辅助功能权限",
                "请前往 系统设置 → 隐私与安全性 → 辅助功能 中启用本应用",
            )
        self._start_hotkey()
        # Prime the first hot worker after rumps finishes bootstrapping.
        # callAfter defers it onto the main runloop; the actual subprocess
        # spawn + pipe IO are done from a background thread inside.
        callAfter(self._spawn_hot_worker)

    def _start_hotkey(self):
        """Start global hotkey listener in background thread."""
        hk = keyboard.GlobalHotKeys({
            "<cmd>+<shift>+y": self._on_hotkey,
            "<ctrl>+<alt>+a": self._on_capture_hotkey,
        })
        hk.daemon = True
        hk.start()

    def _on_hotkey(self):
        # Select-to-translate runs in-daemon (argos is pure Python, no
        # Vision/Translation, never crashed the daemon historically).
        try:
            with open("/tmp/translator-select.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] hotkey ⌘⇧Y fired\n")
        except Exception:
            pass
        threading.Thread(target=self._do_translate, daemon=True).start()

    def _on_capture_hotkey(self):
        # Try the primed hot worker first; cold-spawn fallback if it isn't
        # ready yet. Either path is safe to do from pynput's listener thread:
        # POSIX pipe writes + fork+exec do not touch NSApp.
        self._trigger_capture()

    def _on_capture_menu(self, _):
        self._trigger_capture()

    def _trigger_capture(self):
        # Anti-spam throttle. If the user mashes ⌃⌥A while a capture is
        # still spinning up (cold fallback ~3-5s), accept only the first
        # press and silently drop the rest. Otherwise multiple overlays
        # stack on screen one after another and the user has to dismiss
        # them all.
        now = time.monotonic()
        if now - self._last_capture_trigger_at < 0.8:
            self._log_hot(f"capture throttled (delta={now - self._last_capture_trigger_at:.2f}s)")
            return
        self._last_capture_trigger_at = now

        used_hot = False
        with self._hot_lock:
            proc = self._hot_proc
            ready = self._hot_ready
            if ready and proc is not None and proc.poll() is None:
                # Detach: this worker is about to do work and exit.
                self._hot_proc = None
                self._hot_ready = False
                used_hot = True

        if used_hot:
            try:
                proc.stdin.write("GO\n")
                proc.stdin.flush()
                self._log_hot(f"GO sent to pid={proc.pid}")
                # Replenish the pool so the next hotkey is also fast.
                self._spawn_hot_worker()
                return
            except Exception as e:
                # Pipe broken between READY and now (rare). Fall through.
                self._log_hot(f"GO write failed (pid={proc.pid}): {e}; falling back to cold")

        # Cold fallback. Also try to (re-)prime the pool if it's empty.
        self._spawn_cold_worker()
        with self._hot_lock:
            need_prime = self._hot_proc is None and not self._hot_respawn_inflight
        if need_prime:
            self._spawn_hot_worker()

    def _spawn_cold_worker(self):
        try:
            _spawn_subapp(["--worker"], "/tmp/translator-worker-launch.log")
        except Exception as e:
            try:
                with open("/tmp/translator-worker-launch.log", "a") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] cold spawn failed: {e}\n")
            except Exception:
                pass

    def _log_hot(self, msg):
        try:
            with open("/tmp/translator-hot-worker.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] daemon: {msg}\n")
        except Exception:
            pass

    def _spawn_hot_worker(self):
        """Spawn a --hot-worker subprocess and start a background thread that
        flips _hot_ready to True when the worker writes READY to stdout."""
        with self._hot_lock:
            if self._hot_respawn_inflight:
                return
            self._hot_respawn_inflight = True
        try:
            if IS_BUNDLE:
                macos_dir = os.path.join(os.path.dirname(RESOURCES), "MacOS")
                candidates = [n for n in os.listdir(macos_dir) if n != "python"]
                exe = os.path.join(macos_dir, candidates[0]) if candidates else sys.executable
                argv = [exe, "--hot-worker"]
            else:
                argv = [sys.executable, os.path.join(DIR, "daemon.py"), "--hot-worker"]
            err_log = open("/tmp/translator-hot-worker.log", "ab", buffering=0)
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=err_log,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._log_hot(f"spawned pid={proc.pid}")
        except Exception as e:
            self._log_hot(f"spawn failed: {e}")
            with self._hot_lock:
                self._hot_respawn_inflight = False
            return

        with self._hot_lock:
            self._hot_proc = proc
            self._hot_ready = False
            self._hot_respawn_inflight = False

        threading.Thread(
            target=self._await_hot_ready, args=(proc,), daemon=True
        ).start()

    def _await_hot_ready(self, proc):
        """Background thread: read worker stdout until READY (or EOF)."""
        try:
            line = proc.stdout.readline()
        except Exception as e:
            self._log_hot(f"readline error pid={proc.pid}: {e}")
            line = ""
        if not line:
            # Worker died before READY. Don't loop — wait, then prime once.
            self._log_hot(f"worker pid={proc.pid} died before READY")
            with self._hot_lock:
                if self._hot_proc is proc:
                    self._hot_proc = None
                    self._hot_ready = False
            time.sleep(3)
            self._spawn_hot_worker()
            return
        if line.strip() == "READY":
            with self._hot_lock:
                if self._hot_proc is proc:
                    self._hot_ready = True
                    self._log_hot(f"worker pid={proc.pid} READY")
        else:
            self._log_hot(f"worker pid={proc.pid} unexpected stdout: {line!r}")

    def _do_translate(self):
        """Get selected text, translate, show popup."""
        def _slog(msg):
            try:
                with open("/tmp/translator-select.log", "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass
        _slog("_do_translate: start")
        # py2app bundle doesn't inherit LANG; without an explicit UTF-8 locale,
        # pbpaste/pbcopy mangle non-ASCII (CJK comes back as mojibake).
        utf8_env = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
        # Save current clipboard
        try:
            old_clip = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=2,
                encoding="utf-8", errors="replace", env=utf8_env,
            ).stdout
        except Exception:
            old_clip = ""
        _slog(f"_do_translate: saved old_clip ({len(old_clip)} chars)")

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
                ["pbpaste"], capture_output=True, text=True, timeout=2,
                encoding="utf-8", errors="replace", env=utf8_env,
            ).stdout
        except Exception as e:
            _slog(f"_do_translate: pbpaste failed: {e}")
            return
        _slog(f"_do_translate: selected ({len(selected)} chars): {selected[:60]!r}")

        # Restore original clipboard
        if selected != old_clip:
            try:
                subprocess.run(
                    ["pbcopy"], input=old_clip, text=True, timeout=2,
                    encoding="utf-8", errors="replace", env=utf8_env,
                )
            except Exception:
                pass

        text = selected.strip()
        if not text:
            _slog("_do_translate: empty selection, returning")
            return

        src, tgt = self._detect(text)
        _slog(f"_do_translate: detect {src}->{tgt}")
        result = self._translate(text, src, tgt)
        _slog(f"_do_translate: translate done -> {result[:60]!r}")
        # If user set a fixed target but source already matches, mention the
        # auto-fallback in the popup header so it isn't a silent surprise.
        pref_target = self.prefs.get("target_lang", "auto")
        hint = ""
        if pref_target != "auto" and pref_target == src:
            hint = f"原文已是{LANG_NAMES.get(src, src)}，已自动改译为{LANG_NAMES.get(tgt, tgt)}"
        callAfter(self._show_popup, text, result, src, tgt, hint)

    def _make_target_setter(self, code: str):
        """Factory: returns a rumps callback that sets target_lang to `code`."""
        def _cb(_sender):
            self.prefs["target_lang"] = code
            _save_prefs(self.prefs)
            for c, item in self._target_items.items():
                item.state = 1 if c == code else 0
        return _cb

    def _detect_src(self, text) -> str:
        """Detect the source language from a sample of the text."""
        if any("぀" <= c <= "ゟ" or "゠" <= c <= "ヿ" for c in text):
            return "ja"
        if any("가" <= c <= "힯" for c in text):
            return "ko"
        if any("一" <= c <= "鿿" for c in text):
            return "zh"
        return "en"

    def _detect(self, text):
        """Pick (src, tgt). Source is detected from the text; target follows
        the user's menubar preference. In 'auto' mode we keep the legacy
        rules ('外语→中文，中文→英文'). When the chosen target equals the
        detected source (e.g. user picked 中文 but selection is already
        Chinese), we flip to a sensible secondary so the translation isn't
        a no-op."""
        src = self._detect_src(text)
        target = self.prefs.get("target_lang", "auto")
        if target == "auto":
            return (src, "en") if src == "zh" else (src, "zh")
        if target == src:
            # Avoid same→same: pick the most useful alternative.
            return (src, "en") if src != "en" else (src, "zh")
        return src, target

    def _translate(self, text, src_code, tgt_code):
        """Translate selected text. Apple translator-helper first (high
        quality, ~100-300ms one-shot subprocess), fall back to argos.

        Spawning the helper as a one-shot child each call avoids the long-
        lived helper / NSApp-terminate interactions we saw earlier — the
        helper exits after stdin EOF and the daemon stays untouched."""
        # 1) Apple Translation via swift translator-helper (best quality).
        helper = self._helper_bin()
        if helper:
            try:
                req = json.dumps(
                    {"text": text, "src": src_code, "tgt": tgt_code},
                    ensure_ascii=False,
                ) + "\n"
                proc = subprocess.run(
                    [helper], input=req,
                    capture_output=True, text=True, timeout=8,
                    encoding="utf-8", errors="replace",
                )
                line = (proc.stdout or "").strip().splitlines()
                if line:
                    d = json.loads(line[0])
                    if d.get("ok") and d.get("text"):
                        return d["text"]
            except Exception:
                pass  # fall through to argos

        # 2) argostranslate fallback with English pivot.
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

    def _helper_bin(self):
        """Resolve swift translator-helper path. Bundle first, then user
        install dir (where the right-click Service used to live)."""
        for cand in (
            os.path.join(RESOURCES, "swift", "translator-helper"),
            os.path.expanduser(
                "~/Library/Application Support/LocalTranslator/bin/translator-helper"
            ),
        ):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    def _show_popup(self, original, translated, src, tgt, hint: str = ""):
        """Show native floating panel near the mouse cursor."""
        try:
            with open("/tmp/translator-select.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] _show_popup called: translated={translated[:40]!r} hint={hint!r}\n")
        except Exception:
            pass
        if self.panel:
            self.panel.close()

        # Reserve extra height when we need to show an auto-fallback hint.
        HINT_H = 28 if hint else 0
        W, H = 420, 260 + HINT_H
        mouse = NSEvent.mouseLocation()
        sf = NSScreen.mainScreen().visibleFrame()

        x = max(
            sf.origin.x + 10,
            min(mouse.x - W / 2, sf.origin.x + sf.size.width - W - 10),
        )
        y = mouse.y - H - 30
        if y < sf.origin.y:
            y = mouse.y + 30

        # styleMask: Titled(1) | Closable(2) | NonactivatingPanel(128)
        # Nonactivating is required for LSUIElement (menubar-only) apps so the
        # panel shows without trying to activate a process that has no Dock
        # presence — otherwise NSApp can't become active and the panel never
        # paints despite ordering it front.
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, H),
            1 | 2 | 128,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_(
            f"{LANG_NAMES.get(src, src)} → {LANG_NAMES.get(tgt, tgt)}"
        )
        # Status-bar level so it floats over fullscreen apps and IDE windows.
        self.panel.setLevel_(25)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setBecomesKeyOnlyIfNeeded_(True)

        cv = self.panel.contentView()

        if hint:
            # Top hint bar (e.g. "原文已是中文，已自动改译为EN").
            hf = NSTextField.alloc().initWithFrame_(NSMakeRect(15, H - 24, W - 30, 18))
            hf.setStringValue_(hint)
            hf.setEditable_(False)
            hf.setBezeled_(False)
            hf.setDrawsBackground_(False)
            hf.setFont_(NSFont.systemFontOfSize_(11))
            hf.setTextColor_(NSColor.secondaryLabelColor())
            hf.setSelectable_(False)
            cv.addSubview_(hf)

        rf = NSTextField.alloc().initWithFrame_(NSMakeRect(15, 70, W - 30, H - 100 - HINT_H))
        rf.setStringValue_(translated)
        rf.setEditable_(False)
        rf.setBezeled_(False)
        rf.setDrawsBackground_(False)
        rf.setFont_(NSFont.systemFontOfSize_(15))
        rf.setSelectable_(True)
        rf.cell().setWraps_(True)
        rf.cell().setScrollable_(False)
        cv.addSubview_(rf)

        sep = NSView.alloc().initWithFrame_(NSMakeRect(15, 62, W - 30, 1))
        sep.setWantsLayer_(True)
        sep.layer().setBackgroundColor_(NSColor.separatorColor().CGColor())
        cv.addSubview_(sep)

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

        # orderFrontRegardless avoids the LSUIElement activation requirement;
        # combined with the nonactivating styleMask, the panel paints without
        # NSApp ever needing to become active (which it can't, no Dock icon).
        self.panel.orderFrontRegardless()
        try:
            with open("/tmp/translator-select.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] _show_popup: panel ordered front at ({x:.0f},{y:.0f}) visible={bool(self.panel.isVisible())}\n")
        except Exception:
            pass

    def _open_translator(self, _):
        subprocess.Popen([sys.executable, os.path.join(RESOURCES, "app.py")])

    def _open_gallery(self, _):
        _spawn_subapp(["--gallery"], "/tmp/translator-gallery.log")

    def _show_usage(self, _):
        rumps.notification(
            "Local Translator",
            "使用方法",
            "选中任意文本，按 ⌘⇧Y 即可翻译",
        )


def _run_subapp(script_relpath: str, forwarded_argv):
    """argv-dispatched sub-mode: runpy a sub-script in this same interpreter.
    Lets us reuse the bundle's main executable (correct rpath + inherited TCC)
    instead of the broken `python` launcher in Contents/MacOS/."""
    if RESOURCES not in sys.path:
        sys.path.insert(0, RESOURCES)
    sys.argv = [sys.argv[0]] + list(forwarded_argv)
    import runpy
    runpy.run_path(os.path.join(RESOURCES, script_relpath), run_name="__main__")


def _worker_log_factory(label: str):
    """Tag log lines so cold/hot workers are distinguishable in the same file."""
    def _log(msg):
        try:
            with open("/tmp/translator-worker.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {label} pid={os.getpid()} {msg}\n")
                f.flush()
        except Exception:
            pass
    return _log


def _run_pipeline_after_capture(cap, _log, capture_region, ocr_mod, tr_mod, layout_mod):
    """Body of the capture pipeline starting from a successful `cap`.

    Optimized layout (2026-04-29): spawn the editor *immediately* with just
    the screenshot (image-only mode, right column shows a spinner). OCR and
    translate run in this worker afterwards; we write the translated result
    to a JSON file that the editor polls via its js_api. The user sees the
    captured image roughly when the editor's webview cold-start finishes
    (~1s) instead of waiting for OCR+translate (~3-5s) before any window
    appears at all.
    """
    import json
    import tempfile
    from dataclasses import asdict

    _log(f"capture done: {cap.w}x{cap.h}")

    # --- Step 1: persist PNG + spawn editor in image-only mode ---
    # Write PNG to a stable temp path; editor reads it then unlinks.
    fd, png_path = tempfile.mkstemp(suffix=".png", prefix="translator-cap-")
    os.write(fd, cap.png_bytes)
    os.close(fd)
    result_path = png_path + ".result.json"
    image_meta_path = png_path + ".image.json"
    image_meta = {
        "png": png_path,
        "x": cap.x, "y": cap.y, "w": cap.w, "h": cap.h,
        "result_path": result_path,
    }
    with open(image_meta_path, "w", encoding="utf-8") as f:
        json.dump(image_meta, f, ensure_ascii=False)
    _spawn_subapp(["--from-image", image_meta_path], "/tmp/translator-capture.log")
    _log(f"editor spawned (image-only); will hydrate from {result_path}")

    # --- Step 2: OCR ---
    blocks = ocr_mod.ocr(cap.png_bytes, min_confidence=0.3)
    _log(f"ocr done: {len(blocks)} blocks")

    src_lang = tr_mod.detect_lang(blocks[0].text) if blocks else "en"
    _log(f"src_lang={src_lang}, backend={tr_mod.backend_for(src_lang, 'zh')}")

    _stats = {"calls": 0, "empty_in": 0, "empty_out": 0, "errors": 0}

    def _translate(text):
        _stats["calls"] += 1
        if not text.strip():
            _stats["empty_in"] += 1
            return ""
        try:
            out = tr_mod.translate(text, src_lang, "zh")
        except BaseException as e:
            _stats["errors"] += 1
            import traceback as _t
            _log(f"  translate ERR: {type(e).__name__}: {e}; src={text[:80]!r}")
            _log("  traceback: " + _t.format_exc())
            return ""
        if not out or not out.strip():
            _stats["empty_out"] += 1
            _log(f"  translate EMPTY OUT for src={text[:80]!r}")
        else:
            _log(f"  translate OK: src={text[:60]!r} -> tgt={out[:60]!r}")
        return out

    # --- Step 3: translate ---
    aligned = layout_mod.align_modules(blocks, _translate)
    clusters = layout_mod.cluster_modules(blocks)
    tgt_by_cluster = [a.tgt_text for a in aligned]
    translations = [""] * len(blocks)
    idx_of = {id(b): i for i, b in enumerate(blocks)}
    for c, tgt in zip(clusters, tgt_by_cluster):
        for b in c:
            translations[idx_of[id(b)]] = tgt
    _log(f"translate done: {len(blocks)} blocks -> {len(aligned)} paragraphs; stats={_stats}")

    # --- Step 4: write result.json — editor polls this and hydrates the right column ---
    result = {
        "src_lang": src_lang, "tgt_lang": "zh",
        "blocks": [asdict(b) for b in blocks],
        "translations": list(translations),
        "aligned": [asdict(a) for a in aligned],
    }
    # Atomic write: tmp + rename so editor never reads a half-written file.
    tmp_result = result_path + ".tmp"
    with open(tmp_result, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(tmp_result, result_path)
    _log(f"result written: {result_path}")

    # --- Debug copies (for postmortem) ---
    try:
        dbg_dir = os.path.expanduser("~/Library/Application Support/LocalTranslator/debug")
        os.makedirs(dbg_dir, exist_ok=True)
        # Combined meta (image + result) for easier inspection.
        full_meta = {**image_meta, **result}
        with open(os.path.join(dbg_dir, "last-meta.json"), "w", encoding="utf-8") as f:
            json.dump(full_meta, f, ensure_ascii=False, indent=2)
        ts = time.strftime("%Y%m%d-%H%M%S")
        with open(os.path.join(dbg_dir, f"meta-{ts}.json"), "w", encoding="utf-8") as f:
            json.dump(full_meta, f, ensure_ascii=False, indent=2)
        try:
            import shutil
            shutil.copy(png_path, os.path.join(dbg_dir, f"img-{ts}.png"))
        except Exception:
            pass
        for prefix in ("meta-", "img-"):
            hist = sorted([n for n in os.listdir(dbg_dir) if n.startswith(prefix)])
            for old in hist[:-10]:
                try:
                    os.unlink(os.path.join(dbg_dir, old))
                except Exception:
                    pass
    except Exception as _e:
        _log(f"debug meta dump failed: {_e}")

    _log("worker exiting")


def _run_worker():
    """Cold one-shot capture pipeline. Used as fallback when no hot worker
    is ready, or when the user invoked --worker directly. ~3-5s cold start
    because the heavy stack imports here. The daemon prefers --hot-worker."""
    if RESOURCES not in sys.path:
        sys.path.insert(0, RESOURCES)
    _log = _worker_log_factory("cold")
    _log("started")
    try:
        from ui.capture import capture_region
        from core import ocr as _ocr_mod
        from core import translate as _tr
        from core import layout as _layout
    except BaseException as e:
        import traceback
        _log(f"import failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        os._exit(1)

    try:
        cap = capture_region()
        if cap is None:
            _log("capture cancelled or empty")
            os._exit(0)
        if getattr(cap, "action", "edit") == "copy":
            from ui.capture import copy_png_to_pasteboard
            copy_png_to_pasteboard(cap.png_bytes)
            _log(f"copied to pasteboard: {len(cap.png_bytes)} bytes")
            os._exit(0)
        _run_pipeline_after_capture(cap, _log, capture_region, _ocr_mod, _tr, _layout)
    except BaseException as e:
        import traceback
        _log(f"worker failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        os._exit(0)


def _run_hot_worker():
    """Long-lived primed worker. Pre-imports the heavy stack and warms the
    swift translator-helper, then writes "READY\\n" to stdout and blocks on
    stdin.readline(). The daemon writes "GO\\n" when the user presses ⌃⌥A,
    at which point we run capture + OCR + translate + spawn editor and exit.

    This trades 1 idle worker process (~400MB RSS) for an almost-instant
    overlay on hotkey trigger (~50ms vs 3-5s cold). The daemon spawns a
    replacement immediately after sending GO, so subsequent hotkeys are
    also fast as long as the user pauses long enough between captures
    (typical usage)."""
    if RESOURCES not in sys.path:
        sys.path.insert(0, RESOURCES)
    _log = _worker_log_factory("hot ")
    _log("booting; importing heavy deps")

    # Phase 1: pre-import. Done up-front so READY means truly ready.
    try:
        from ui.capture import capture_region
        from core import ocr as _ocr_mod
        from core import translate as _tr
        from core import layout as _layout
        # Warm the swift translator-helper subprocess + cache installed pairs.
        try:
            _tr._apple.installed_pairs()
            if _tr._apple.available():
                _tr._apple._ensure()
        except BaseException as _e:
            _log(f"apple warmup non-fatal: {_e}")
    except BaseException as e:
        import traceback
        _log(f"warmup failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        os._exit(1)
    _log("warmup done; emitting READY")

    # Phase 2: signal ready and block.
    try:
        sys.stdout.write("READY\n")
        sys.stdout.flush()
    except Exception:
        os._exit(1)
    try:
        line = sys.stdin.readline()
    except Exception:
        os._exit(1)
    if not line or line.strip() != "GO":
        _log(f"received {line!r} instead of GO; exiting")
        os._exit(1)
    _log("GO received, running pipeline")

    # Phase 3: same as cold worker from cap onwards.
    try:
        cap = capture_region()
        if cap is None:
            _log("capture cancelled or empty")
            os._exit(0)
        if getattr(cap, "action", "edit") == "copy":
            from ui.capture import copy_png_to_pasteboard
            copy_png_to_pasteboard(cap.png_bytes)
            _log(f"copied to pasteboard: {len(cap.png_bytes)} bytes")
            os._exit(0)
        _run_pipeline_after_capture(cap, _log, capture_region, _ocr_mod, _tr, _layout)
    except BaseException as e:
        import traceback
        _log(f"hot worker pipeline failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        os._exit(0)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--worker":
        _run_worker()
    elif args and args[0] == "--hot-worker":
        _run_hot_worker()
    elif args and args[0] == "--gallery":
        _run_subapp("ui/gallery_window.py", [])
    elif args and args[0] == "--capture":
        _run_subapp("ui/editor_window.py", [])
    elif args and args[0] == "--from-meta" and len(args) >= 2:
        _run_subapp("ui/editor_window.py", ["--from-meta", args[1]])
    elif args and args[0] == "--from-result" and len(args) >= 2:
        _run_subapp("ui/editor_window.py", ["--from-result", args[1]])
    elif args and args[0] == "--from-image" and len(args) >= 2:
        _run_subapp("ui/editor_window.py", ["--from-image", args[1]])
    else:
        try:
            TranslatorDaemon().run()
        finally:
            try:
                with open(_FAULT_LOG, "a") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] rumps app.run() RETURNED pid={os.getpid()}\n")
            except Exception:
                pass

"""Translation backends.

Two-tier strategy:
  1. Apple Translation framework via long-lived Swift helper subprocess
     (``swift/translator-helper``). Higher quality, ~50ms/sentence, only
     works for language pairs the user has installed in macOS Settings →
     General → Language & Region → Translation Languages. We treat
     ``Cause.notInstalled`` and any helper crash as a soft miss and fall
     through to argos.
  2. argostranslate offline models (legacy default; covers everything we
     ship language packs for, slower/lower quality).

Language detection is Unicode-heuristic (fast, no extra dep).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import warnings
from functools import lru_cache

warnings.filterwarnings("ignore", category=DeprecationWarning)

import argostranslate.translate as _at


class TranslateError(Exception):
    pass


def _resolve_helper_bin() -> str:
    """Find the Swift helper binary in both dev and py2app-bundled layouts."""
    # py2app sets RESOURCEPATH to <App>.app/Contents/Resources
    rp = os.environ.get("RESOURCEPATH")
    if rp:
        candidate = os.path.join(rp, "swift", "translator-helper")
        if os.path.exists(candidate):
            return candidate
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "swift", "translator-helper",
    )


_HELPER_BIN = _resolve_helper_bin()


class _AppleHelper:
    """Long-lived Swift process speaking line-delimited JSON.

    One instance per Python process; thread-safe via a lock around the
    write/read pair (the protocol is strictly request/response).
    """

    def __init__(self, path: str):
        self.path = path
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._installed_pairs: set[tuple[str, str]] | None = None

    def available(self) -> bool:
        return os.path.isfile(self.path) and os.access(self.path, os.X_OK)

    def _spawn(self) -> subprocess.Popen:
        # Capture stderr to a log file — silently dropping it has been masking
        # Apple Translation framework warnings/errors that turn into empty
        # responses in the calling worker.
        try:
            err_fh = open("/tmp/translator-helper-stderr.log", "ab", buffering=0)
        except Exception:
            err_fh = subprocess.DEVNULL
        # Explicit utf-8 encoding — py2app bundles don't inherit LANG, so
        # text=True defaults to ASCII and chokes on the helper's Chinese
        # JSON responses (0xe6 = leading byte of common 汉字 like 新/查).
        return subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err_fh,
            bufsize=1, text=True, encoding="utf-8", errors="replace",
        )

    def _ensure(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = self._spawn()
        return self._proc

    def installed_pairs(self) -> set[tuple[str, str]]:
        """Return the set of (src, tgt) short codes the helper reports as installed."""
        if self._installed_pairs is not None:
            return self._installed_pairs
        if not self.available():
            self._installed_pairs = set()
            return self._installed_pairs
        try:
            out = subprocess.run(
                [self.path, "--check"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            ).stdout.strip()
            data = json.loads(out)
            pairs = data.get("pairs", {})
            self._installed_pairs = {
                tuple(k.split("->", 1))
                for k, v in pairs.items()
                if v == "installed" and "->" in k
            }
        except Exception:
            self._installed_pairs = set()
        return self._installed_pairs

    def supports(self, src: str, tgt: str) -> bool:
        return (src, tgt) in self.installed_pairs()

    def translate(self, text: str, src: str, tgt: str) -> str:
        """Send one request; raises TranslateError on helper-side failure."""
        if not self.available():
            raise TranslateError("helper binary missing")
        with self._lock:
            proc = self._ensure()
            req = json.dumps({"text": text, "src": src, "tgt": tgt}, ensure_ascii=False)
            try:
                proc.stdin.write(req + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
            except (BrokenPipeError, OSError) as e:
                self._proc = None
                raise TranslateError(f"helper pipe broken: {e}")
            if not line:
                self._proc = None
                raise TranslateError("helper closed stdout")
            try:
                resp = json.loads(line)
            except json.JSONDecodeError as e:
                raise TranslateError(f"helper bad json: {e}: {line[:200]}")
        if not resp.get("ok"):
            err = resp.get("error", "unknown")
            # `notInstalled` is the soft case — caller will retry via argos.
            if "notInstalled" in err:
                raise TranslateError("notInstalled")
            raise TranslateError(err)
        return resp["text"]


_apple = _AppleHelper(_HELPER_BIN)


@lru_cache(maxsize=1)
def _lang_map():
    return {lang.code: lang for lang in _at.get_installed_languages()}


def installed_codes() -> list[str]:
    return sorted(_lang_map().keys())


def _argos_translate(text: str, src: str, tgt: str) -> str:
    langs = _lang_map()
    src_l = langs.get(src)
    tgt_l = langs.get(tgt)
    if src_l is None:
        raise TranslateError(f"source language not installed: {src}")
    if tgt_l is None:
        raise TranslateError(f"target language not installed: {tgt}")

    direct = src_l.get_translation(tgt_l)
    if direct is not None:
        return direct.translate(text)

    en = langs.get("en")
    if en is None or src == "en" or tgt == "en":
        raise TranslateError(f"no translation path {src}->{tgt}")
    t1 = src_l.get_translation(en)
    t2 = en.get_translation(tgt_l)
    if t1 is None or t2 is None:
        raise TranslateError(f"no translation path {src}->en->{tgt}")
    return t2.translate(t1.translate(text))


def translate(text: str, src: str, tgt: str) -> str:
    """Translate text, preferring Apple Translation when the pair is installed."""
    if not text or not text.strip():
        return ""
    if src == tgt:
        return text

    if _apple.supports(src, tgt):
        try:
            return _apple.translate(text, src, tgt)
        except TranslateError:
            # Fall through to argos.
            pass

    return _argos_translate(text, src, tgt)


def backend_for(src: str, tgt: str) -> str:
    """Diagnostic: which backend will handle this pair right now."""
    if _apple.supports(src, tgt):
        return "apple"
    return "argos"


_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_HIRA = re.compile(r"[\u3040-\u309f]")
_KATA = re.compile(r"[\u30a0-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_ARABIC = re.compile(r"[\u0600-\u06ff]")


def detect_lang(text: str) -> str:
    """Coarse Unicode-based language detection.

    Returns one of the argos-supported codes or 'en' as fallback.
    Not for serious NLP use — enough to decide source-lang for OCR output.
    """
    if not text:
        return "en"
    if _HIRA.search(text) or _KATA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _CJK.search(text):
        return "zh"
    if _CYRILLIC.search(text):
        return "ru"
    if _ARABIC.search(text):
        return "ar"
    return "en"

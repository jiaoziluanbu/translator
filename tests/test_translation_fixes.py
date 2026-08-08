from __future__ import annotations

import inspect
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


# Force daemon.py into its lightweight subprocess import path.  Unit tests do
# not need rumps/pynput and should not initialize the menu bar application.
_ORIGINAL_ARGV = sys.argv[:]
sys.argv = [sys.argv[0], "--service-translate"]
import daemon  # noqa: E402
sys.argv = _ORIGINAL_ARGV

from core import pipeline  # noqa: E402
from core import translate as core_translate  # noqa: E402


class TargetLanguageRoutingTests(unittest.TestCase):
    def test_explicit_chinese_target_never_flips_to_english(self):
        self.assertEqual(daemon._pick_langs_for_text("Hello 你好", "zh"), ("en", "zh"))
        self.assertEqual(daemon._pick_langs_for_text("你好 Hello", "zh"), ("en", "zh"))

    def test_explicit_english_target_never_flips_to_chinese(self):
        self.assertEqual(daemon._pick_langs_for_text("Hello 你好", "en"), ("zh", "en"))

    def test_text_already_in_target_is_a_noop_pair(self):
        self.assertEqual(daemon._pick_langs_for_text("只有中文", "zh"), ("zh", "zh"))

    def test_auto_mode_keeps_legacy_direction(self):
        self.assertEqual(daemon._pick_langs_for_text("Hello", "auto"), ("en", "zh"))
        self.assertEqual(daemon._pick_langs_for_text("你好", "auto"), ("zh", "en"))

    def test_core_detector_ignores_target_script_in_mixed_text(self):
        self.assertEqual(core_translate.detect_lang_for_target("Hello 你好", "zh"), "en")
        self.assertEqual(core_translate.detect_lang_for_target("Hello 你好", "en"), "zh")
        self.assertEqual(core_translate.detect_lang_for_target("只有中文", "zh"), "zh")


class ScreenshotPipelineTests(unittest.TestCase):
    def test_each_visual_module_detects_its_own_source(self):
        blocks = [SimpleNamespace(text="你好"), SimpleNamespace(text="Hello")]
        translated_pairs = []

        def fake_translate(text, src, tgt):
            translated_pairs.append((text, src, tgt))
            return f"{src}->{tgt}:{text}"

        def fake_align(_blocks, translate_fn):
            return [
                SimpleNamespace(tgt_text=translate_fn("你好")),
                SimpleNamespace(tgt_text=translate_fn("Hello")),
            ]

        with (
            mock.patch.object(pipeline.ocr_mod, "ocr", return_value=blocks),
            mock.patch.object(pipeline.tr_mod, "translate", side_effect=fake_translate),
            mock.patch.object(pipeline.layout_mod, "align_modules", side_effect=fake_align),
            mock.patch.object(pipeline.layout_mod, "cluster_modules", return_value=[[blocks[0]], [blocks[1]]]),
        ):
            pipeline.run_ocr_translate(b"png", tgt_lang="zh")

        self.assertEqual(
            translated_pairs,
            [("你好", "zh", "zh"), ("Hello", "en", "zh")],
        )

    def test_cold_worker_does_not_import_translation_before_capture(self):
        source = inspect.getsource(daemon._run_worker)
        self.assertNotIn("from core import", source)
        self.assertLess(source.index("capture_region()"), source.index("_run_pipeline_after_capture"))


class ServiceTranslationTests(unittest.TestCase):
    def test_service_uses_explicit_target_with_swift_helper(self):
        with mock.patch.object(
            daemon,
            "_translate_with_swift_once",
            side_effect=lambda _text, src, tgt: f"{src}->{tgt}",
        ):
            result = daemon._translate_service_text("Hello 你好", "zh")
        self.assertEqual(result, "en->zh")

    def test_service_returns_target_language_text_without_backend(self):
        with mock.patch.object(daemon, "_translate_with_swift_once") as helper:
            result = daemon._translate_service_text("只有中文", "zh")
        self.assertEqual(result, "只有中文")
        helper.assert_not_called()

    def test_installed_service_prefers_bundled_app_bridge(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        service_path = os.path.join(project_root, "scripts", "translate-service.sh")
        with open(service_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"$APP_EXE" --service-translate', source)
        self.assertIn("grep -q -- '--service-translate'", source)


if __name__ == "__main__":
    unittest.main()

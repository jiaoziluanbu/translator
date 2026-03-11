#!/usr/bin/env python3
"""Local Translator - offline translation app using pywebview + argos-translate."""
import os
import webview
import argostranslate.translate
import argostranslate.package

DIR = os.path.dirname(os.path.abspath(__file__))


class TranslatorAPI:
    """API exposed to JavaScript via pywebview."""

    def translate(self, text, src_lang, tgt_lang):
        try:
            # For Chinese: argos uses "zh" for Chinese
            installed = argostranslate.translate.get_installed_languages()
            lang_map = {l.code: l for l in installed}

            src = lang_map.get(src_lang)
            tgt = lang_map.get(tgt_lang)

            if not src:
                return {"error": f"Source language '{src_lang}' not installed"}
            if not tgt:
                return {"error": f"Target language '{tgt_lang}' not installed"}

            translation = src.get_translation(tgt)
            if not translation:
                # Try via English as pivot
                en = lang_map.get("en")
                if en and src_lang != "en" and tgt_lang != "en":
                    t1 = src.get_translation(en)
                    t2 = en.get_translation(tgt)
                    if t1 and t2:
                        mid = t1.translate(text)
                        result = t2.translate(mid)
                        return {"text": result}
                return {"error": f"No translation path from {src_lang} to {tgt_lang}"}

            result = translation.translate(text)
            return {"text": result}
        except Exception as e:
            return {"error": str(e)}


def main():
    api = TranslatorAPI()
    window = webview.create_window(
        "Local Translator",
        url=os.path.join(DIR, "index.html"),
        js_api=api,
        width=900,
        height=560,
        min_size=(600, 400),
    )
    webview.start()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Local Translator - offline translation app using pywebview + argos-translate."""
import os
import webview

from core.translate import translate as core_translate, TranslateError

DIR = os.path.dirname(os.path.abspath(__file__))


class TranslatorAPI:
    """API exposed to JavaScript via pywebview."""

    def translate(self, text, src_lang, tgt_lang):
        try:
            return {"text": core_translate(text, src_lang, tgt_lang)}
        except TranslateError as e:
            return {"error": str(e)}
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

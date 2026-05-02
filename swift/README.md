# Swift Translation Helper

Bridges Python `core/translate.py` to Apple's Translation framework
(macOS 15+). Translation framework's `TranslationSession` is mostly tied
to SwiftUI views; we use the CLI-friendly
`TranslationSession(installedSource:target:)` initializer, which only
works for language pairs already installed on the device.

## Files

| File | Purpose |
|---|---|
| `translator_helper.swift` | Long-lived stdin/stdout JSON bridge. Built into `translator-helper`. |
| `probe_translation.swift` | One-shot availability probe (`LanguageAvailability`). |
| `probe_translate2.swift` | One-shot single-string smoke test. |
| `probe_prepare.swift` | SwiftUI bootstrap that pops the system download sheet. Wrapped as `TranslatorPrepare.app` because the system permission sheet refuses to render inside a bare CLI process. |
| `TranslatorPrepare.app/` | Minimal `.app` bundle wrapping `probe_prepare`. |

## Build

```sh
swiftc -O -parse-as-library -o translator-helper translator_helper.swift
```

## First-run language download

Translation framework requires each language pair to be downloaded.
Open `TranslatorPrepare.app`, accept the system download dialog for each
pair (the app cycles through `zh↔en`, `ja→zh`, `ko→zh`). Languages are
managed system-wide in *System Settings → General → Language & Region →
Translation Languages*.

## Helper protocol

One JSON object per line on both stdin and stdout.

Request:
```json
{"text": "你好", "src": "zh", "tgt": "en"}
```

Response:
```json
{"ok": true, "text": "Hello"}
```

Or on failure:
```json
{"ok": false, "error": "TranslationError(... notInstalled ...)"}
```

`--check` prints a one-shot availability JSON and exits.

## Why this design

- **Separate process**: Apple's Translation framework is async-Swift; PyObjC bridging async/await is awkward.
- **Long-lived helper**: each `TranslationSession` is reused across calls (avoids re-init cost).
- **`installedSource` initializer**: skips the SwiftUI lifecycle entirely so the helper runs headless.
- **Region note**: Foundation Models (Apple Intelligence on-device LLM) returns `deviceNotEligible` for users in `zh_CN` even on capable hardware (M-series, 16GB+). Translation framework has no such region gate.

// translator-helper - Apple Translation framework CLI bridge.
//
// Protocol (one JSON object per line):
//   stdin:  {"text":"你好","src":"zh","tgt":"en"}
//   stdout: {"ok":true,"text":"Hello"}     or    {"ok":false,"error":"..."}
//
// Modes:
//   --check        Print availability for a small set of common pairs and exit.
//   (default)      Read stdin lines, translate, write one JSON line per input.
//
// Build: swiftc -O -parse-as-library -o translator-helper translator_helper.swift

import Foundation
import Translation

// Map short ISO codes to the BCP-47 identifiers Translation framework expects.
let LANG_TAG: [String: String] = [
    "en": "en-Latn-US", "zh": "zh-Hans-CN", "ja": "ja-Jpan-JP", "ko": "ko-Kore-KR",
    "fr": "fr-Latn-FR", "de": "de-Latn-DE", "es": "es-Latn-ES", "pt": "pt-Latn-BR",
    "ru": "ru-Cyrl-RU", "it": "it-Latn-IT", "ar": "ar-Arab-AE", "th": "th-Thai-TH",
    "vi": "vi-Latn-VN", "id": "id-Latn-ID", "tr": "tr-Latn-TR", "nl": "nl-Latn-NL",
    "pl": "pl-Latn-PL", "uk": "uk-Cyrl-UA",
]

func tagOf(_ code: String) -> Locale.Language {
    return Locale.Language(identifier: LANG_TAG[code] ?? code)
}

struct Req: Decodable { let text: String; let src: String; let tgt: String }

func writeLine(_ obj: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: obj, options: [])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

@main
struct Main {
    static func main() async {
        let args = CommandLine.arguments
        if args.contains("--check") {
            let avail = LanguageAvailability()
            let pairs: [(String, String)] = [
                ("zh", "en"), ("en", "zh"), ("ja", "zh"), ("ko", "zh"),
                ("zh", "ja"), ("zh", "ko"),
            ]
            var out: [String: String] = [:]
            for (s, t) in pairs {
                let status = await avail.status(from: tagOf(s), to: tagOf(t))
                let str: String
                switch status {
                case .installed: str = "installed"
                case .supported: str = "supported"
                case .unsupported: str = "unsupported"
                @unknown default: str = "unknown"
                }
                out["\(s)->\(t)"] = str
            }
            writeLine(["ok": true, "pairs": out])
            return
        }

        // One TranslationSession per (src,tgt). Built lazily on first request.
        var sessions: [String: TranslationSession] = [:]

        while let line = readLine(strippingNewline: true) {
            if line.isEmpty { continue }
            guard let data = line.data(using: .utf8),
                  let req = try? JSONDecoder().decode(Req.self, from: data) else {
                writeLine(["ok": false, "error": "bad request"])
                continue
            }
            if req.src == req.tgt {
                writeLine(["ok": true, "text": req.text])
                continue
            }
            let key = "\(req.src)->\(req.tgt)"
            let session: TranslationSession
            if let s = sessions[key] {
                session = s
            } else {
                session = TranslationSession(installedSource: tagOf(req.src), target: tagOf(req.tgt))
                sessions[key] = session
            }
            do {
                let resp = try await session.translate(req.text)
                writeLine(["ok": true, "text": resp.targetText])
            } catch {
                // Session may be poisoned after a failure - drop and retry once.
                sessions[key] = nil
                writeLine(["ok": false, "error": "\(error)"])
            }
        }
    }
}

// Probe whether Translation framework is usable from a CLI on this machine.
// Tests LanguageAvailability for a few language pairs.
import Foundation
import Translation

@main
struct Main {
    static func main() async {
        let avail = LanguageAvailability()
        let pairs: [(String, String)] = [
            ("zh", "en"), ("en", "zh"), ("ja", "zh"), ("ko", "zh"),
        ]
        for (s, t) in pairs {
            let src = Locale.Language(identifier: s)
            let tgt = Locale.Language(identifier: t)
            let status = await avail.status(from: src, to: tgt)
            let str: String
            switch status {
            case .installed: str = "installed"
            case .supported: str = "supported (needs download)"
            case .unsupported: str = "unsupported"
            @unknown default: str = "unknown"
            }
            print("\(s) -> \(t): \(str)")
        }
        let langs = await avail.supportedLanguages
        print("supportedLanguages count: \(langs.count)")
        for l in langs.prefix(20) {
            print("  - \(l.maximalIdentifier)")
        }
    }
}

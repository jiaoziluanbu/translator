// Probe TranslationSession installedSource init from CLI.
import Foundation
import Translation

@main
struct Main {
    static func main() async {
        let src = Locale.Language(identifier: "zh-Hans-CN")
        let tgt = Locale.Language(identifier: "en-Latn-US")
        do {
            let session = TranslationSession(installedSource: src, target: tgt)
            let resp = try await session.translate("你好，世界。今天天气真好。")
            print("OK: \(resp.targetText)")
        } catch {
            print("ERR: \(error)")
        }
    }
}

// First-run language downloader for Translation framework.
// Pops a small window with status. Click "下载" in the system dialog when prompted.
// Window stays open until you close it (so you can see the result).
import SwiftUI
import Translation

@main
struct PrepareApp: App {
    var body: some Scene {
        WindowGroup("Translator 语言下载") {
            ContentView()
                .frame(minWidth: 380, minHeight: 220)
        }
    }
}

struct Pair: Identifiable {
    let id = UUID()
    let src: String
    let tgt: String
    var status: String = "等待..."
}

struct ContentView: View {
    @State private var pairs: [Pair] = [
        Pair(src: "zh-Hans-CN", tgt: "en-Latn-US"),
        Pair(src: "en-Latn-US", tgt: "zh-Hans-CN"),
        Pair(src: "ja-Jpan-JP", tgt: "zh-Hans-CN"),
        Pair(src: "ko-Kore-KR", tgt: "zh-Hans-CN"),
    ]
    @State private var currentIdx: Int = 0
    @State private var config: TranslationSession.Configuration?
    @State private var allDone = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("点击下方系统对话框中的「下载」按钮")
                .font(.headline)
            ForEach(Array(pairs.enumerated()), id: \.element.id) { idx, p in
                HStack {
                    Text("\(p.src) → \(p.tgt)")
                        .font(.system(.body, design: .monospaced))
                    Spacer()
                    Text(p.status)
                        .foregroundStyle(p.status.contains("完成") ? .green : .secondary)
                }
            }
            if allDone {
                Text("✅ 全部完成，可关闭窗口").foregroundStyle(.green).padding(.top, 6)
            }
            Spacer()
        }
        .padding(20)
        .onAppear { startNext() }
        .translationTask(config) { session in
            do {
                pairs[currentIdx].status = "下载中..."
                try await session.prepareTranslation()
                pairs[currentIdx].status = "✅ 完成"
            } catch {
                pairs[currentIdx].status = "❌ \(error)"
            }
            currentIdx += 1
            startNext()
        }
    }

    func startNext() {
        if currentIdx >= pairs.count {
            allDone = true
            config = nil
            return
        }
        let p = pairs[currentIdx]
        config = TranslationSession.Configuration(
            source: Locale.Language(identifier: p.src),
            target: Locale.Language(identifier: p.tgt)
        )
    }
}

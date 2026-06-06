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
    @State private var isRunning = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Apple Translation 语言包")
                .font(.headline)
            Text("按系统对话框提示下载；每一项完成后会自动进入下一项。")
                .foregroundStyle(.secondary)
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
            Button("重试未完成项") {
                retryUnfinished()
            }
            .disabled(isRunning || allDone)
            .padding(.top, 4)
            Spacer()
        }
        .padding(20)
        .onAppear { startNext() }
        .translationTask(config) { session in
            let idx = currentIdx
            guard pairs.indices.contains(idx) else { return }
            isRunning = true
            do {
                pairs[idx].status = "下载中..."
                try await session.prepareTranslation()
                pairs[idx].status = "✅ 完成"
            } catch {
                pairs[idx].status = "❌ \(error)"
            }
            isRunning = false
            advanceAfterTask(from: idx)
        }
    }

    func startNext() {
        if currentIdx >= pairs.count {
            allDone = true
            config = nil
            return
        }
        let p = pairs[currentIdx]
        pairs[currentIdx].status = "准备中..."
        config = TranslationSession.Configuration(
            source: Locale.Language(identifier: p.src),
            target: Locale.Language(identifier: p.tgt)
        )
    }

    func advanceAfterTask(from idx: Int) {
        config = nil
        currentIdx = idx + 1
        if currentIdx >= pairs.count {
            allDone = true
            return
        }
        // Give SwiftUI's translationTask modifier one runloop turn to tear
        // down the completed session before installing the next config.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            startNext()
        }
    }

    func retryUnfinished() {
        config = nil
        allDone = false
        if let idx = pairs.firstIndex(where: { !$0.status.contains("完成") }) {
            currentIdx = idx
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                startNext()
            }
        }
    }
}

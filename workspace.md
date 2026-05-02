# Local Translator — 工作状态

> 创建于 2026-04-23，最后更新于 2026-05-02（会话 10，v1.3.4：push 推送 + 多语言菜单）

## 流程 Checklist

- [x] Phase 0: 需求确认
- [x] Phase 1: 技术设计
- [x] Phase 2: 任务拆分（已落地到任务列表）
- [x] Phase 3: 开发（含 v1.3.1 翻译升级 + py2app 打包 + v1.3.2 daemon 瘦身 + v1.3.3 性能优化）
- [x] Phase 4: 测试（端到端跑通 + 性能优化达标）
- [x] Phase 5: 上线回顾（v1.3.3 .dmg 已打 + README 更新 + 部署 /Applications）

## 当前状态

- **阶段**：v1.3.3 已收尾，端到端延迟从 8-9s → 2s（4 倍提速）
- **当前任务**：（可选）⌘⇧Y 选中翻译回归测试，需要用户实际选中文本验证
- **进度**：daemon 瘦身 ✅、编码全修 ✅、6/6 段译文 ✅、Hot worker 池 ✅、Editor 早开 ✅、Konva 本地化 ✅、v1.3.3 dmg ✅、README ✅、部署 ✅
- **阻塞项**：无

## 2026-05-02 会话 10：v1.3.4（push + 多语言）

四件事：

### 1. editor 译文 push 推送（替代 500ms poll）
- `ui/editor_window.py::open_editor_pending` 把 `webview.create_window` 返回的 window 存进 closure，watcher 线程拿到 result file 后用 `win.evaluate_js("window.__onTranslationResult(...)")` 直推 JS。
- `ui/editor.html`：注册 `window.__onTranslationResult = applyResult`，去掉 `setInterval(500ms)`；保留一次 100ms binder 检查 `pywebview.api.get_translation_result()` 兜底"先到先得"竞争。
- 体感：worker 比 editor 快时少等最多 500ms。

### 2. 首装 ja→zh / ko→zh（Apple Translation）
- `swift/TranslatorPrepare.app` 跑了，ja 系统弹窗下了，ko 系统弹窗在重启 prepare 后仍未弹 → 走「系统设置 → 通用 → 语言与地区 → 翻译语言」手动加韩文搞定。
- `./swift/translator-helper --check` 6/6 全 installed。**重要**：daemon 进程缓存 installed_pairs，安装新语言对后必须重启 daemon。
- ja→zh 实测："機械学習の研究を進めています。" → "正在推进机器学习的研究。"，质量明显高于 argos。

### 3. 选中翻译 ⌘⇧Y 端到端打通（一直没回归测，这次坑很多）
按发现顺序：
- **bug A：pbpaste/pbcopy mojibake**。py2app bundle 不继承 LANG，subprocess 执行 pbpaste 时输出按系统 default locale 而非 UTF-8 → 中文出来全是乱码。修法：subprocess 显式 `env={"LANG":"en_US.UTF-8","LC_ALL":"en_US.UTF-8",**os.environ}`。
- **bug B：codesign --force 让 TCC 授权失效**。每次重签会改 cdhash，TCC 按 cdhash 索引授权 → ad-hoc 重签后辅助功能授权立即失效但 UI 仍显示已勾，pynput 全局热键完全收不到事件，前台 app 收到 ⌘⇧Y 发出 system beep。修法：① UI 重新勾选 ② 后续部署只 `cp .py` 不 codesign（除非签名文件本身变了）。已写入 [troubleshooting_codesign_tcc_invalidation.md](../../../.claude/projects/-Users-jiaozidemacmini/memory/troubleshooting_codesign_tcc_invalidation.md)。
- **bug C：LSUIElement app 创建的 NSPanel 不显示**。menubar-only app（`LSUIElement=True`）没 dock icon，`NSPanel` 默认 styleMask + `setHidesOnDeactivate_(True)` + `makeKeyAndOrderFront_` 这套组合在 accessory 应用里 panel 立刻被认为 deactivated → 隐掉。修法：styleMask 加 `NSWindowStyleMaskNonactivatingPanel`(128)、setHidesOnDeactivate False、setLevel 25 (status bar)、`orderFrontRegardless()` 替代 `makeKeyAndOrderFront_`。

### 4. 菜单栏「目标语言」设置 + 持久化 + 同语言提示
- `daemon.py` 顶层加 `TARGET_LANG_OPTIONS`（自动/中/英/日/韩）+ `_load_prefs()` / `_save_prefs()`。prefs 路径 `~/Library/Application Support/LocalTranslator/prefs.json`。
- `__init__` 用 `rumps.MenuItem("目标语言")` + `add(item)` 构 5 项子菜单，selected 项 `state=1`。`_make_target_setter(code)` 工厂返回 callback：写 prefs + 翻 ✓。
- `_detect()` 拆成 `_detect_src(text)` + 主函数读 `prefs.target_lang`：auto 走旧规则；指定 target 时 src=detected、tgt=pref；同语言（如 pref=zh 选了中文）→ fallback 到 en（en 选英文 → 回 zh）。
- `_show_popup` 加 `hint` 参数，同语言 fallback 时弹窗顶部显示「原文已是中文，已自动改译为EN」一行 11pt secondary label，panel 高度 +28。

### 待做
- [ ] 重打 .dmg（setup.py 已升 1.3.4，build_app.sh DMG_NAME 已同步，跑 `bash build_app.sh` 即可，约 8 分钟）
- [ ] 更新 README.md 提一下「目标语言」菜单 + Push 推送
- [ ] （可选）模块聚类精度（v1.2 老 TODO）

---

## 2026-04-29 会话 9：v1.3.3 收尾

- 升版本号：`setup.py` CFBundleVersion 1.3.1 → 1.3.3；`build_app.sh` DMG_NAME 同步
- 重打包：`bash build_app.sh` → `dist/Local Translator.app` 1.1G + `dist/LocalTranslator-1.3.3.dmg` 541M（UDZO）
- README 更新：主要功能加 "极速响应" 一行、dmg 文件名同步 1.3.3、新增 "v1.3.3 架构亮点" 段（Hot worker 池/Editor 早开/Subprocess 模式/Konva 本地化四件事）、"已知限制" 加首次冷启动 5s 提示
- 部署：`pkill -f "Local Translator.app"` → codesign ad-hoc → `cp -R` 到 /Applications → `lsregister -f` → `open`
- 验证：daemon pid 71606，hot worker pid 71617 在 18:40:13 启动、18:40:17 emitting READY（4s 预热，符合预期）
- 待用户实测：⌃⌥A 端到端延迟、⌘⇧Y 选中翻译（编码已修，未回归测）

## 2026-04-29 会话 8：性能优化（8-9s → 2s）

### 优化前后对比

⌃⌥A → 译文显示的端到端延迟：

| 阶段 | 优化前 | 优化后 |
|---|---|---|
| ⌃⌥A 触发 → overlay 显示 | 3-5s（worker 冷启动 import torch+argos+swift helper） | <100ms（hot worker 已就绪，pipe 写 GO 唤醒） |
| 拖框完 → editor 进程实际启动 | 4s（py2app launcher + daemon.py 顶部 import rumps/pynput/argos） | 1s（subprocess stub 跳过 daemon-only 依赖） |
| webview.start() → JS 第一行执行 | 3-4s（unpkg CDN 拉 konva.min.js 175KB） | 60ms（vendor/konva.min.js 本地加载） |
| result 写入 → editor 渲染右栏 | OCR+translate 串行后才 spawn editor，用户黑屏等所有这些 | OCR+translate 与 editor 启动并行，editor 先展示截图 + spinner，500ms 轮询拿 result |

总感知延迟：**8-9s → 2s**。

### 4 个关键修法

#### 1. Hot worker 池（daemon.py）

daemon 启动后立刻 spawn 一个 `--hot-worker` 子进程，它做完 import + warmup 后写 `READY\n` 到 stdout 然后 `sys.stdin.readline()` 沉睡。⌃⌥A 时 daemon 写 `GO\n` 唤醒它干活，同时立刻 spawn 替补。

涉及代码：
- `daemon.py::_run_hot_worker()` — worker 端：import + READY + 等 GO + 跑 pipeline + os._exit(0)
- `daemon.py::TranslatorDaemon._spawn_hot_worker()` / `_await_hot_ready()` / `_trigger_capture()` — daemon 端：维护 1 个池，cold fallback 走 `--worker`

成本：1 个常驻 ~400MB RSS 子进程（import 完 torch/argos）。可接受。

#### 2. Editor 早开 + 后台 hydrate（worker + editor）

worker 拿到 cap 后**立刻** spawn editor（image-only meta），不等 OCR/translate；editor 启动后渲染左截图 + 右栏 spinner，启动 500ms poll；worker 后台跑 OCR+translate，原子写 `<png>.result.json`；editor poll 拿到结果替换 spinner。

涉及代码：
- `daemon.py::_run_pipeline_after_capture()` — 拆成 image-only spawn → OCR/translate → atomic write result
- `ui/editor_window.py::open_editor_pending()` + 新 `--from-image` 入口 + `_EditorApi.get_translation_result()`（JS poll 用）
- `ui/editor.html` — `payload.pending=true` 显示 spinner + setInterval poll；`renderSidebar()` 提取共用渲染逻辑

#### 3. Subprocess 模式跳过 daemon-only 依赖（daemon.py）

py2app bundle 里所有子进程都通过 main bundle exec 进入 `daemon.py`，顶部 `import rumps / pynput / argostranslate` 是 ~3-4s 重负担（argos 拉 stanza+torch）。但 worker / editor / gallery 子进程根本不用这些。

修法：顶部用 sys.argv 判断模式，subprocess 模式提供 stub 让 `class TranslatorDaemon(rumps.App)` 可以解析（class 永远不会被实例化）。

```python
_SUBPROCESS_FLAGS = {"--worker", "--hot-worker", "--gallery", "--capture",
                     "--from-meta", "--from-result", "--from-image"}
_IS_SUBPROCESS = (len(sys.argv) > 1 and sys.argv[1] in _SUBPROCESS_FLAGS)

if _IS_SUBPROCESS:
    rumps = types.SimpleNamespace(App=object, MenuItem=lambda *a, **kw: None, ...)
    keyboard = types.SimpleNamespace(...)
    argostranslate = types.SimpleNamespace(...)
else:
    import rumps; from pynput import keyboard; import argostranslate.translate; ...
```

类似地：`ui/editor_window.py` 顶部 `from core.pipeline import CaptureOCRResult` 也会拉整个 torch 栈，已改成 lazy import（在用到的 `--from-result` / `--from-meta` / `--sample` 分支里 import）。

#### 4. Konva.js 本地化

之前 `editor.html` 用 `<script src="https://unpkg.com/konva@9/konva.min.js">`，每次冷启动 WebKit 走 DNS+TLS+下载 ~150KB，3-4 秒。改成 `ui/vendor/konva.min.js` 本地加载，`_write_wrapper_html()` 把相对路径替换成绝对 file:// URL（dev/bundle 双跑通）。

setup.py 加 `("ui/vendor", ["ui/vendor/konva.min.js"])` 让 py2app 打包时带上。

### 当前文件层

- `daemon.py` 533 行（顶部条件 import + Hot worker 池逻辑 + class 定义保留 top）
- `ui/editor_window.py`：`open_editor_pending()` 新增；顶部 lazy CaptureOCRResult；`_write_wrapper_html` 改 konva 路径
- `ui/editor.html`：`renderSidebar()` 提取；pending 模式 spinner + poll；vendor/konva.min.js 引用
- `ui/vendor/konva.min.js`：175KB，新增（已纳入 setup.py DATA_FILES）

### 已知小延迟

- 第一次按 ⌃⌥A 之前 hot worker 必须有 ~5s 启动时间（daemon 启动后到 hot worker READY）。如果用户在 daemon 起后立刻按 ⌃⌥A，会 fallback 到 cold worker（~3-5s）。daemon 启动后 5s 内不要操作即可。
- result poll 间隔 500ms — 如果 worker 比 editor 快，editor 启动后最多再等 500ms 才看到译文。可以减小到 100ms 或改 webview.evaluate_js 推送（未做）。

### 待做（v1.3.3 收尾）

1. 重新跑 build_app.sh 打 .dmg（包含 vendor/ + 新代码）
2. 更新 README（架构变化 + Konva 本地化说明）
3. ⌘⇧Y 选中翻译回归测试

---

## 2026-04-28 会话 7：架构重构 + 编码修复

### 决策：daemon 瘦身（方案 A）

之前 v1.3.1 续 1-3 一直在打地鼠：每次发现 daemon voluntary 退出就加补丁（OCR 主线程化 → swift helper 主线程预热 → pipe IO 主线程化 → keepalive window → 最后 swizzle NSApp.terminate 把系统卡死）。

复盘真因：**py2app + rumps + macOS 26 + Vision/Translation framework 的组合栈本身脆弱**。daemon 主进程一接触系统 framework 就被强制 voluntary terminate。补丁路线根本上错了。

新架构：
- daemon **不 import** core.pipeline / core.translate / Vision / Translation
- daemon 只负责：菜单栏图标、⌃⌥A 全局热键、spawn 子进程
- ⌃⌥A → `_spawn_subapp(["--worker"])` → 独立 worker 子进程做 capture + OCR + translate + spawn editor → worker `os._exit(0)`
- daemon 永远不接触会触发 NSApp 终止的代码路径 → daemon 长寿

代码改动：daemon.py 从 609 行瘦到 ~430 行；新增 `_run_worker()` 入口 + `--worker` argv 分派。所有"swizzle NSApp.terminate"代码已删除（之前那把把系统卡死了）。

### bug：py2app + LANG 编码坑（同一项目第 3 次踩）

症状：⌃⌥A 截图后大部分段无译文。worker stats 显示 `errors: 0`（误导）。

定位过程（走了几小时弯路）：
1. 怀疑 Apple Translation framework 怪行为 → 单独命令行测 swift helper 全部成功，否决
2. 怀疑聚类问题 → 看 last-meta.json，aligned 6 段 4 段 tgt 空，否决
3. 加 stats 计数 → empty_out=0 矛盾
4. 放宽 `except _tr.TranslateError` → `except BaseException`，traceback 打出来 → 真凶现身：`UnicodeDecodeError: 'ascii' codec can't decode byte 0xe6 in position 9` at `core/translate.py:123` (`proc.stdout.readline()`)

根因：py2app bundle 不继承 LANG，`subprocess.Popen(..., text=True)` 默认 ASCII 解码 swift helper 返回的中文 JSON，0xe6 是常见汉字 UTF-8 首字节（新/查/阅 等都是）。异常被 `align_modules` 的 `except Exception: tgt=""` 静默吞，stats 漏计。

修法：所有 IO 加 `encoding="utf-8", errors="replace"`：
- `core/translate.py::_AppleHelper._spawn` 的 `subprocess.Popen`
- `core/translate.py::installed_pairs` 的 `subprocess.run --check`
- `daemon.py::_do_translate` 的 `pbpaste` × 2 + `pbcopy`（⌘⇧Y 之前在 bundle 里早就坏了，没人发现）
- worker `_log()` 写文件（之前 `→` 字符吞日志）
- worker 写 meta JSON（之前续 3 修过）

教训已写入两份 memory：
- [troubleshooting_py2app_lang_encoding.md](../../../.claude/projects/-Users-jiaozidemacmini/memory/troubleshooting_py2app_lang_encoding.md)
- [feedback_silent_exception_swallow.md](../../../.claude/projects/-Users-jiaozidemacmini/memory/feedback_silent_exception_swallow.md)

### 现状（v1.3.2 已部署到 /Applications）

- daemon 在 ⌃⌥A + 5 次截图后仍存活
- 6/6 段译文成功（截屏正常显示左图 + 右栏 6 段中文译文）
- ⌘⇧Y 选中翻译已修编码（待用户测）
- 画廊功能正常

### 待做（按优先级）

1. **慢的问题**：worker 每次冷启动 ~3-5 秒（import torch + argos + spawn swift helper）。方案：daemon 维持一个"沉睡 worker"，⌃⌥A 时唤醒它干活、同时 daemon 再 spawn 新 sleep worker。daemon 不接触 worker import 的内容，只 IPC 信号唤醒。
2. **回归测试**：⌘⇧Y 选中翻译（编码修复后），画廊（已确认能开）
3. **清理**：删 daemon.py 顶部的 atexit 诊断（生产期不需要）
4. （可选）首装 ja→zh / ko→zh 翻译模型

## 下次回来直接干这步

```bash
# daemon 应该还活着
pgrep -af "Local Translator"

# 跑 ⌃⌥A 验证还在工作
# 之后看
cat /tmp/translator-worker.log
cat ~/Library/Application\ Support/LocalTranslator/debug/last-meta.json | python3 -m json.tool | head -40
```

如果要进入"慢的问题"优化（沉睡 worker 池方案），先看下面"任务列表"v1.3.3 一项的设计。

## 下次回来直接干这步

```bash
# daemon 还在 /Applications，pid 40888（如果还活着）
pgrep -af "Local Translator.app"
# 如果挂了：
pkill -f "Local Translator.app"; sleep 1
rm -f /tmp/translator-{worker,fault,capture,startup}.log
open "/Applications/Local Translator.app"
# 然后按 ⌃⌥A 截图
/bin/cat /tmp/translator-worker.log
/bin/cat /tmp/translator-fault.log
/bin/cat /tmp/translator-capture.log    # 编辑器子进程的日志
```

预期 worker.log：`ocr start → ocr done → src_lang=X, backend=Y → translate done → meta written → editor subprocess spawned`，编辑器窗口弹出。

## 打包再战记录（2026-04-26 晚）

之前判定"必须 $99 Apple Developer 证书才能解决 TCC"是错的。重新拆解后真因如下：

### 真正修复的几个 bug（按发现顺序）

1. **plist 缺 UsageDescription** —— `setup.py` 只有 `NSAppleEventsUsageDescription` + `NSScreenCaptureUsageDescription`，缺 **`NSInputMonitoringUsageDescription`** 和 **`NSAccessibilityUsageDescription`**。macOS 26 没有这两个 key 时即使勾选授权也不下发，pynput 永远 not trusted。**这是上次结论错的根因**。
2. **daemon.py 缺 ⌃⌥A 截图热键注册** —— 之前只注册了 `<cmd>+<shift>+y`，截图功能从未接入 daemon。源码模式跑也没用。
3. **subprocess `sys.executable` rpath 错** —— bundle 内 `Contents/MacOS/python` 这个 launcher 的 rpath 是 `@executable_path/../../../../Python3`，会去 bundle **外面** 4 层找 framework 必然 dyld fail。任何 `subprocess.Popen([sys.executable, ...])` 都会立刻死。修法：用主 bundle exec `Contents/MacOS/Local Translator` + argv 分派子模式（`--gallery` / `--capture` / `--from-result`）。
4. **截图弹编辑器太慢（5-10s）** —— 子进程要重新 import 整个 argostranslate/torch 栈。改架构：**daemon 已 warm，由 daemon 跑 OCR+translate**，把结果序列化成 JSON，子进程仅渲染（pywebview + 已加载的 pyobjc），不再 import 重依赖。
5. **rumps.notification 在 worker 后台线程死锁** —— NSUserNotificationCenter 不能从非主线程调；要么用 `callAfter` 派发到主循环，要么干脆删掉。
6. **PyObjC Vision 桥接首次绑定必须在主线程** —— `from core import pipeline` 在 worker 后台线程触发 → daemon 进程 SIGSEGV 整个挂掉（不是 worker 死，是父进程死）。修法：daemon 启动时（`__main__` 之外的模块顶层，主线程）eager import pipeline；worker 重用已初始化的模块。subapp 模式跳过 eager import 以保留瘦身效果。

### 续 2 排查记录（2026-04-26 21:30-23:35）

之前以为是"PyObjC 后台线程首次绑定 SIGSEGV"，加了 eager import 也没用。这一轮加了完整诊断（`faulthandler` + `atexit dump frames` + `sys.excepthook` + `threading.excepthook` + rumps app.run() 退出 hook + main-thread-vs-worker 拆步骤日志），写到 `/tmp/translator-fault.log`，一刀切掉所有猜测。

#### 关键发现：daemon 不是崩溃，是 voluntary 退出

`log show --predicate 'process == "Local Translator"'` 显示：
- `ANE0: ANE_PowerOff_gated: Client requesting power off` （ANE 用过了说明 OCR 跑了）
- `Process exited: <RBSProcessExitContext| voluntary>` （干净退出，不是 SIGSEGV）

`fault log` 显示 `rumps app.run() RETURNED` 干净 return，**没有任何异常**。

#### 真因（一层层剥）

1. **第一层（capture overlay）**：`ui/capture.py` 的 `app.run()` + `mouseUp_` 里 `NSApp.stop_(None)` 共用 rumps 的 NSApp shared instance，stop flag 是**进程级**的，会把 rumps 外层主循环也停掉。**已修**：改成 `app.nextEventMatchingMask_untilDate_inMode_dequeue_` 手动事件泵 + sentinel `view.done`，不再调 `app.run()` 嵌套也不调 `stop_()`。

2. **第二层（OCR 后台线程）**：worker 调 `core.ocr.ocr()` → Vision `performRequests_error_`，从后台线程发 Vision 请求会让 NSApp 整洁 terminate（不是 SEGV，是 NSInternalInconsistencyException 在主线程被 catch 后 Apple 选 terminate；所以无 crash report）。**已修**：OCR 调到主线程跑，`_launch_capture` 同步执行。

3. **第三层（Apple translate helper subprocess）**：worker 调 `_apple.installed_pairs()` → `subprocess.run([translator-helper, --check])` 从后台线程 spawn swift helper 也让 daemon terminate。**已修**：daemon 启动时（main thread）eager warmup `_apple.installed_pairs()` + `_apple._ensure()`，缓存住 + 预 spawn 长进程 helper。

4. **第四层（pipe IO 仍在 worker）**：即使 helper 已经主线程 spawn 好，worker 调 `proc.stdin.write/proc.stdout.readline` 时 daemon 还是死。pipe 对端的 swift helper 用 `TranslationSession.translate()` 触发 Translation framework，client 端某种 IPC 通知回 daemon 触发 NSApp terminate（猜的）。**最终修法**：放弃 worker，**全流程主线程化** —— `_capture_pipeline_main()` 同步跑 OCR + translate + spawn editor，约 1s，用户可接受。

5. **JSON 写文件 ASCII 编码**：py2app bundle 不继承 LANG，`open(path, "w")` 默认 ASCII，写中文翻译 → UnicodeEncodeError。**已修**：加 `encoding="utf-8"`。

#### 已落地的代码改动

- `daemon.py` 顶部加 faulthandler + atexit + sys.excepthook + threading.excepthook 诊断
- `daemon.py` eager warmup 块加 `_apple.installed_pairs()` + `_apple._ensure()`
- `daemon.py` `_launch_capture` → `_capture_pipeline_main`（全主线程，已删除 worker thread）
- `daemon.py` JSON dump 改 `encoding="utf-8"`
- `ui/capture.py` `app.run()` → 手动事件泵；`NSApp.stop_()` → `view.done = True` sentinel
- 同步到 `/Applications/Local Translator.app/Contents/Resources/{daemon.py, ui/capture.py}`
- `codesign --force --deep --sign -` 重签名

**当前 daemon pid**: 40888 (会话结束时仍在运行，未实测 ⌃⌥A)

### 续 3 排查记录（2026-04-27 20:17-20:35）

实测 ⌃⌥A，主线程化生效，OCR 10 blocks + translate(en→zh argos) + meta 写出 + spawn editor **全部跑通**（worker.log 一路绿到 `editor subprocess spawned`）。但暴露两个新 bug：

#### Bug 1：editor 子进程 ASCII 解码崩溃（弹"Launch error"）

`/tmp/translator-capture.log` traceback：
```
File "/Applications/Local Translator.app/Contents/Resources/ui/editor_window.py", line 215, in <module>
  meta = json.load(f)
UnicodeDecodeError: 'ascii' codec can't decode byte 0xef in position 187
```

py2app bundle 不继承 LANG，`open(meta_path)` 默认 ASCII。daemon 写文件时已经加 `encoding="utf-8"`，但 editor 这边读文件忘了加。

**修法**：`ui/editor_window.py:214` 和 `:234` 都加 `encoding="utf-8"`。已 commit + 同步到 bundle。

#### Bug 2：daemon 在 spawn 编辑器后 voluntary 退出

fault log 看 daemon pid 70064 在 `editor subprocess spawned` 同一秒 `rumps app.run() RETURNED` 干净 return + ATEXIT。猜测：`ui/capture.py` 调 `app.activateIgnoringOtherApps_(True)` 让 NSApp 短暂当成普通 app，overlay 窗口 orderOut 后 AppKit 触发 `applicationShouldTerminateAfterLastWindowClosed:` → 默认 YES → NSApp terminate。

rumps 的默认 delegate 没 override 这个方法（继承 AppKit 的 YES），所以截图后 daemon 整个退出，下次 ⌃⌥A 没响应。

**修法**：在 daemon.py 加 `_install_no_terminate_on_last_close()`，用 PyObjC 的 `objc.classAddMethods` 给 rumps' NSApp delegate 注入 `applicationShouldTerminateAfterLastWindowClosed:` → return False。在 `_launch_capture` 第一次调用时安装（idempotent，那时 rumps 已经 `setDelegate_`）。已 commit + 同步到 bundle。

#### 落地的代码改动（续 3）

- `daemon.py` 顶部加 `_install_no_terminate_on_last_close()`，用 objc.classAddMethods 注入 NO override
- `daemon.py::_launch_capture` 第一行调用上述 hook（idempotent）
- `ui/editor_window.py:214` `--from-result` 分支加 `encoding="utf-8"`
- `ui/editor_window.py:234` `--from-meta` 分支加 `encoding="utf-8"`
- 同步到 bundle + 重签名 + 重启
- **当前 daemon pid**: 70205（待饺子按 ⌃⌥A 验证）

#### 下次回来直接干这步（v2）

```bash
pgrep -af "Local Translator.app"  # 看 daemon 还在不在
# 按 ⌃⌥A 截图
/bin/cat /tmp/translator-worker.log
/bin/cat /tmp/translator-capture.log    # 编辑器 stdout/stderr
/bin/cat /tmp/translator-fault.log      # daemon 是否还活着
```

预期：
1. 编辑器窗口正常弹出（左截图 + 右栏译文，工具条）
2. daemon 仍在 pgrep 里
3. 再按一次 ⌃⌥A 仍能触发新一次截图

如还有问题，对应日志会指。

### 部署/验证流程（已固化）

```bash
cd ~/Documents/自制产品/translator
pkill -f "Local Translator.app"; sleep 1
codesign --force --deep --sign - "dist/Local Translator.app"
rm -rf "/Applications/Local Translator.app"
cp -R "dist/Local Translator.app" /Applications/
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "/Applications/Local Translator.app"
open "/Applications/Local Translator.app"
```

`lsregister -f` 这步必须 —— 不显式注册到 LaunchServices 时，新 app 在系统设置授权列表里压根不出现。

诊断日志：`/tmp/translator-startup.log`（trust state）、`/tmp/translator-worker.log`（OCR/translate 进度）、`/tmp/translator-capture.log`（编辑器子进程 stderr）、`/tmp/translator-gallery.log`（画廊子进程）。

### 已验证工作的能力（截至当前）

- ✅ menubar app 启动、菜单显示
- ✅ ⌃⌥A 全局热键监听（grant Accessibility 后）
- ✅ 截图 overlay 拖框
- ✅ 屏幕录制权限弹框（grant Screen Recording 后能看到真窗口内容）
- ✅ 「打开画廊」子进程（ad-hoc 签名 + main bundle exec 启动）
- ✅ 主线程 OCR（10 blocks 实测稳定，~8s 含 model 首次加载）
- ✅ 主线程 translate + meta 写出 + spawn editor 子进程（worker.log 一路绿）
- ⏳ 编辑器子进程渲染（utf-8 修补已部署，待实测）
- ⏳ daemon 长寿（applicationShouldTerminateAfterLastWindowClosed → NO 已注入，待实测）

### 右键翻译服务（旁路，已经跑通）

不依赖打包；走 Automator workflow + 嵌入二进制。文件位置：
- workflow：`~/Library/Services/Translate.workflow`
- helper：`~/Library/Application Support/LocalTranslator/bin/translator-helper`（绕开 ~/Documents 的 TCC 拦截）
- 绑定：`defaults write -g NSServicesStatus` → ⌘⇧Y

## 预验证结论（v1.1 开头必做，2026-04-23）

| # | 项 | 结果 | 结论 |
|---|---|---|---|
| 1 | Vision OCR 精度 | 5 张样本 OCR 94-692ms，中英日混排高准确率；少量小字/符号 conf<0.5 可过滤 | ✅ 通过 |
| 2 | PyObjC 全屏 overlay | 待用户拖框验收 | ⏳ 待验收 |
| 3 | pywebview 传图延迟 | 1.5MB 图：base64=2755ms，file://=701ms | ✅ **改方案**：默认走 file:// |
| 4 | Konva.js 兼容性 | WKWebView 下 500 动画圆 59.6 fps；shape API 全部正常 | ✅ 通过 |
| 5 | argos 并发翻译 | 10 段串行 674ms（67ms/段）；线程并发无提升（GIL）| ✅ 通过，v1.1 串行即可 |

探针脚本：`scripts/probe/probe_01_ocr.py` 等；测试图 `scripts/probe/samples/`（5 张代表性截图）。

## 需求确认清单

| 项 | 内容 |
|---|------|
| 目标 | 现有翻译工具扩展为"截图翻译 + 编辑 + 画廊管理"的小型应用 |
| 做 | ①全局热键截图 ②截图后工具条（翻译/裁剪/绘图/文字/马赛克等）③右侧并排翻译 ④无边记风格画廊 ⑤双图保存（原图+译图）|
| 不做 | ①云端同步 ②跨平台（仅 macOS）③团队协作 ④Apple 签名公证（未签名 .dmg 即可）|
| 依赖 | Vision framework (OCR), argostranslate (翻译), pywebview + Konva.js (画布), PyObjC (截图 overlay) |
| 技术偏好 | Python + pywebview 主干；UI 层与能力层解耦，为未来 Swift 重写预留 |
| 时间节点 | 无硬 deadline，按会话节奏推进 |

## 技术方案摘要

**架构**：菜单栏 daemon 启动，`⌃⌥A` 热键触发截图 overlay → Vision OCR 识别文本块 → argos 翻译 → 打开编辑窗口（pywebview + Konva）→ 左侧截图 + 右侧 320px 翻译栏（段落同高度对齐）→ 工具条编辑 → 保存到本地 SQLite → 画廊窗口查看（无边记风格可拖拽）。

**目录结构**：
```
translator/
├── app.py, daemon.py       # 已有，扩展
├── core/                   # 能力层：ocr, translate, storage, layout
├── ui/                     # UI 层：capture, editor (html+py), gallery (html+py)
├── assets/                 # 图标样式
└── data/ (运行时生成)      # 用户数据 → ~/Library/Application Support/LocalTranslator/
```

**翻译栏方案**（原图铺满屏幕的应对）：编辑窗口 = 截图宽 + 320px，超出屏幕时 pywebview 按屏幕可视区设窗口大小，内部 Canvas 支持 scroll/zoom。

**分发路线**：Python + py2app + 未签名 .dmg，预估 ~550MB，README 写清楚"右键打开"绕过 Gatekeeper。

详细设计见 [docs/design.md](docs/design.md)。

## 变更影响清单（v1.1 目标）

- [ ] `daemon.py` — 新增 `⌃⌥A` 热键注册 + 菜单项"打开画廊"
- [ ] `core/ocr.py` — 新建，封装 Vision framework
- [ ] `core/translate.py` — 新建，从 app.py 抽出翻译逻辑
- [ ] `core/storage.py` — 新建，SQLite 初始化 + CRUD
- [ ] `core/layout.py` — 新建，OCR bbox → 翻译块对齐算法
- [ ] `ui/capture.py` — 新建，PyObjC 全屏截图 overlay
- [ ] `ui/editor_window.py` + `ui/editor.html` — 新建，v1.1 只有"翻译栏"，工具条留空
- [ ] `app.py` — 重构，使用 `core/translate.py`
- [ ] `install.sh` — 新增依赖（pyobjc-framework-Vision）

## 任务列表（v1.1）

| # | 任务 | 状态 | 依赖 | 会话 | 备注 |
|---|------|------|------|------|------|
| 0 | 方案定稿 + workspace.md + design.md | ✅ 完成 | 无 | 会话1 | |
| 1 | 技术点预验证（5 项）| 🟡 4/5 完成 | #0 | 会话2 | #2 待用户验收；pywebview 传图改 file:// |
| 2 | `core/` 四个模块骨架 | ✅ 完成 | #1 | 会话2 | ocr/translate/layout/storage 端到端 smoke 通过；app.py 已重构 |
| 3 | `ui/capture.py` 截图 overlay | ✅ 完成 | #2 | 会话2 | `capture_region()` 返回 CaptureResult(png_bytes, x/y/w/h)；坑：CGDisplayCreateImageForRect 用 points 不乘 scale；orderOut 后要 spin runloop 250ms 才能消 overlay |
| 4 | OCR 集成到截图流程 | ✅ 完成 | #3 | 会话2 | `core/pipeline.py` 封装 capture→OCR→translate→align；`run_ocr_translate(png)` 可单独调用；probe_07 smoke 通过（14 blocks → 8 paragraphs）|
| 5 | 编辑窗口骨架（只有截图+右栏翻译，无工具条）| ✅ 完成 | #4 | 会话2 | `ui/editor_window.py` + `editor.html`；Konva 左图 + 右栏 320px 2D 模块聚类按 y 对齐；单一滚动条；file:// 传图；修复 argos `\n` 断句 bug（`_flatten_for_translate` 预处理）。v1.1 完成标志 |
| 6 | 工具条 v1：矩形/圆/线/箭头/画笔/文字/撤销/保存 | ✅ 完成 | #5 | 会话3 | v1.2a；`editor.html` 加工具条+annotation Layer+Transformer（仅 4 角、自由比例、strokeScaleEnabled:false）；Konva Rect/Ellipse/Line/Arrow/Line(pen)/Text；形状 hitFunc 覆盖内部、线/箭头/画笔 hitStrokeWidth；select 分支忽略 transformer 子元素避免手柄误判；文字支持双击原位编辑；撤销/清空；⌘Z/⌘S/⌘⇧S 快捷键；两个保存按钮：「保存图」→ `stage.toDataURL({pixelRatio:1/scale})`；「保存带译文」→ 前端 canvas 合成 stage+右栏译文 → `api.save_png(b64, suffix)` 写 `~/Downloads/LocalTranslator-<lang>[-<suffix>]-<ts>.png` |
| 7 | 工具条 v2：马赛克/模糊/标签/裁剪 + 样式精修 | ✅ 完成 | #6 | 会话4 | v1.2b；`editor.html` 加 4 个工具：**标签**(Konva.Group=Circle+Text，自动编号 ①②③，双击改文字，字号滑块控制直径)；**马赛克/模糊**(拖矩形区域 → 从 bg 原图 naturalWidth/Height 采样到 offscreen canvas，马赛克=downscale+imageSmoothing:false、模糊=ctx.filter='blur(8px)'，包成 Konva.Image，transformend/dragend 重新采样保证清晰)；**裁剪**(拖矩形 → 浮动确认/取消 bar，确认后 stage.width/height(cw,ch) + bg kImg.x/y(-cx,-cy) + 所有 annotation 节点 x/y 同步偏移 + 右栏 .para 过滤掉完全出裁剪区的段落、其余上移，不可撤销)。工具组面板按 tool 显隐(TOOL_PANELS map)；快捷键 N/M/B/X + ⌘Enter 确认裁剪；select() 对 label 升级到 parent Group，keepRatio:true 保圆；clearAll 重置 labelCounter；stageW/H 改 mutable ref 让 crop 能改尺寸 |
| 8 | 画廊窗口（无边记风格 + 拖拽 + 数据持久化）| ✅ 完成 | #5 | 会话5 | v1.3；`core/storage.py` 扩 `gallery_items` 表(id/name/kind/src_lang/tgt_lang/file_path/thumb_path/w/h/canvas_x/y/scale/created_at) + CRUD(`add_gallery_item`/`list_gallery_items`/`update_gallery_pos`/`rename_gallery_item`/`delete_gallery_item`) + Pillow 缩略图(400px JPEG q82)；文件落 `~/Library/Application Support/LocalTranslator/gallery/{id}.png` + `gallery/thumbs/{id}.jpg`；编辑器 `_EditorApi.save_to_gallery(b64, kind)` 替换原 `save_png`，editor.html 两个按钮改调 save_to_gallery（kind='raw'/'translated'）；`ui/gallery_window.py` + `gallery.html` 用 Konva.Stage 无限画布(stage.draggable=true 平移 + 滚轮缩放 0.2-3x + 网格 fillPattern 背景)，每张图一个 `Konva.Group`(白卡 + 缩略图 + 角标"原图/译图" + 文件名 ellipsis)；首次默认 4 列网格布局，dragend → `update_pos` 持久化；双击开 lightbox 浮层显示原图；右键 contextmenu 弹自绘菜单(查看大图/重命名/删除)；工具条「居中」(getClientRect 计算 bbox 自适应 fit) / 「100%」(重置 scale+pos)；daemon.py 菜单加「打开画廊」→ subprocess 启动 gallery_window.py |
| 8.5 | Apple Translation framework 接入（翻译质量升级）| ✅ 完成 | #2 | 会话6 | v1.3.1；`swift/translator-helper`(swiftc -O -parse-as-library) 用 `TranslationSession(installedSource:target:)` headless API；stdin/stdout JSON line 协议；`core/translate.py` 重构成两层 `_AppleHelper`(长进程，threading.Lock，--check 缓存 installed_pairs) → `_argos_translate` 兜底，`backend_for(src,tgt)` 诊断；smoke：zh→en 117ms、en→zh 61ms（argos 是 5-8s），质量明显高一档。Foundation Models 因 zh_CN 区域被锁(deviceNotEligible) 放弃。语言下载靠 `swift/TranslatorPrepare.app`(SwiftUI WindowGroup + translationTask + prepareTranslation；CLI 二进制系统对话框拒渲染，必须包成 .app bundle)；首装 zh↔en 完成，ja→zh/ko→zh 仍 supported(走 argos)。pipeline 0.78s/21 modules end-to-end 质量验证通过 |
| 9 | py2app 打包 + DMG + README | ✅ 完成 | #8 | 会话6 | v1.3.1；`setup.py`(LSUIElement=True 菜单栏 only、CFBundle 1.3.1、permission usage descriptions、includes Vision/CoreML/WebKit/Quartz/objc/AppKit、unittest 不能 exclude——torch via stanza via argostranslate sbd 加载时引 unittest.mock)；`build_app.sh`(swift helper 编译 + TranslatorPrepare.app 包装 + py2app 高 recursionlimit + hdiutil UDZO 打包 + Applications 软链)；bundle-aware：`core/translate.py::_resolve_helper_bin()`、`daemon.py::RESOURCES`、`ui/{editor,gallery}_window.py` 改用 RESOURCEPATH，dev/bundle 双跑通；产物 `dist/Local Translator.app` 1.1GB（torch 占大头）+ `dist/LocalTranslator-1.3.1.dmg` 542MB（UDZO 压缩）；smoke：alias 模式 + 完整模式都 launch 不崩，daemon 进程 ~380MB RSS 稳定；坑：modulegraph RecursionError 需 `setrecursionlimit(10000)`、py2app rm 需 mv 绕安全模式；`README.md` 写完整安装/首次右键开/辅助功能+屏幕录制授权/语言包下载/数据目录/卸载步骤 |

## 待优化项（v1.2+）

- **模块聚类精度**：当前 `core/layout.py::cluster_modules` 纯几何（x/y 重叠 + 中位字高阈值），会误拆"标题/描述/按钮"留白大的模块，也可能误并无边框相邻块。可选升级方向：① 叠加图像信号（背景色突变/分隔线/边框检测 Vision `VNDetectRectangles`）；② 字体大小跳变作为模块边界；③ 绝对像素阈值 + 相对阈值二选一更宽松的。决策：v1.1 不动，等真实使用数据回流再选方向。

## 关键决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 热键 | `⌃⌥A` (Ctrl+Alt+A) | 用户坚持，不改为 macOS 风格 |
| 翻译栏位置 | 方案 2（右侧 320px 固定，超屏幕等比缩放） | 类 Figma canvas view，所见即所得 |
| OCR 方案 | macOS Vision framework | 离线免费、中英日支持好、不引入额外依赖 |
| 编辑器技术栈 | pywebview + Konva.js Canvas | 比纯 PyObjC 省 60% 工作量，工具条样式可仿参考图 |
| 分发方案 | py2app + 未签名 .dmg | GitHub 开源小白场景够用，不上 App Store |
| 模块架构 | UI 层与能力层解耦（core/ vs ui/） | 未来可能 Swift 重写 UI，能力层复用 |
| 不做签名公证 | README 指引绕过 Gatekeeper | 省 $99/年开发者账号 |

## 上一个会话产出

**会话日期**：2026-04-25（会话 6，v1.3.1）
**完成的任务**：
- 任务 #8.5：Apple Translation framework 接入
- 探查发现 Foundation Models 在 zh_CN 区域返 `deviceNotEligible`（M4/16GB 硬件够格但被锁），改用 Translation framework
- 新建 `swift/translator_helper.swift` + `translator-helper` 二进制：长进程 stdin/stdout JSON 协议，`TranslationSession(installedSource:target:)` headless API
- 新建 `swift/TranslatorPrepare.app`（SwiftUI 引导器）：CLI swiftc 出来的二进制，系统下载对话框拒绝渲染（白板），必须包成 .app bundle 才显示；用户已首装 zh↔en，ja→zh / ko→zh 暂时走 argos
- `core/translate.py` 重构：`_AppleHelper` 长进程封装（threading.Lock 串行化、--check 缓存 installed_pairs、notInstalled 软失败 fallthrough）→ `_argos_translate` 兜底；新增 `backend_for(src,tgt)` 诊断
- 性能 + 质量验证：zh→en 117ms（argos 8s），en→zh 61ms，pipeline 端到端 0.78s/21 modules
- 文档：`swift/README.md` 说明 helper 协议 / 首装流程 / 设计决策
**已知问题/待用户验收**：
- ja/ko 语言对未装；要装：再跑一次 `TranslatorPrepare.app` 让它走完后两轮，或 `系统设置 → 通用 → 语言与地区 → 翻译语言` 手动加
- py2app 打包时 `_HELPER_BIN` 路径需改成 bundle-aware（任务 #9 处理）
**技术债/Hack**：无

---

**会话日期**：2026-04-25（会话 5，v1.3）
**完成的任务**：
- 任务 #8：画廊窗口完整落地
- `core/storage.py`：新增 `gallery_items` 表 + 5 个 CRUD + `_make_thumb`(Pillow 400px JPEG)
- `ui/editor_window.py`：`_EditorApi.save_to_gallery(b64, kind)` 写 DB + Application Support
- `ui/editor.html`：两个保存按钮从 `save_png`(写 Downloads) 改为 `save_to_gallery`(入画廊)
- `ui/gallery_window.py` + `gallery.html`：Konva 无限画布、网格背景、卡片(缩略图+角标+标题)、stage 拖拽平移、滚轮缩放、双击 lightbox、右键菜单(查看/重命名/删除)、工具条「居中/100%」
- `daemon.py`：菜单加「打开画廊」(subprocess 启 gallery_window.py)
- 决策：保存按钮"只入画廊不写 Downloads"(方案 A)；分组功能 v1.3 不做
- 已 smoke 测：storage CRUD（add/list/rename/update_pos/delete 通过）+ gallery_window 模块 import + payload 序列化（5 张种子条目）
**已知问题/待用户验收**：
- pywebview 窗口需要图形会话，UI 交互（拖拽、缩放、双击 lightbox、右键、重命名 prompt、删除 confirm、居中 fit）需用户从菜单栏「打开画廊」实测
- 用户验收前可在 db.sqlite 里看到 5 条种子记录；如要清空：`sqlite3 ~/Library/Application\ Support/LocalTranslator/db.sqlite "DELETE FROM gallery_items"` + 删除 `~/Library/Application\ Support/LocalTranslator/gallery/`
**技术债/Hack**：无

---

**会话日期**：2026-04-24（会话 4，v1.2b）
**完成的任务**：
- 任务 #7：工具条 v2（label/mosaic/blur/crop）全部落地
- `ui/editor.html` 扩容约 300 行：新增 `TOOL_PANELS` 面板映射、`addLabel/editLabelNode/relayoutLabel`、`renderPixelated/addPixelOverlay`、`makeGuideRect/beginCropConfirm/cancelCrop/applyCrop`
- 关键坑点：
  - 初始化顺序：`setTool('select')` 在 init 时调 `cancelCrop()`，`let cropState` 必须前置到 `selectedNode` 旁边避免 TDZ
  - 马赛克 pixel 采样坐标要除以 `scale`（stage 坐标 → 图片自然像素）
  - Transformer.keepRatio 对 label 开启保持圆形；对其他形状关闭（自由比例）
  - 裁剪后 stage/kImg/所有 annotation 的坐标系都要偏移（-cx,-cy），但 bg kImg 的 width/height 保持不变仅改 x/y，靠 stage 自身尺寸裁掉多余部分
- `stageW/stageH` 改为 `stageWRef.v/stageHRef.v` 让裁剪能改动

**已知问题**：
- 裁剪不可撤销（undoStack 只记录 annotation 节点，不记录 stage 尺寸/背景偏移）；v1 接受，若需要可引入 stage snapshot 方案

**技术债/Hack**：无

---

**会话日期**：2026-04-23（会话 2）
**完成的任务**：
- 技术点预验证 4/5（#1 OCR、#3 pywebview、#4 Konva、#5 argos）
- 落地 `scripts/probe/` 6 个探针脚本 + 5 张代表性测试截图
- 关键修正：pywebview 传图默认方案由 base64 改为 file://（base64 在 1.5MB 图上慢 4x）
- 安装 pyobjc-framework-Vision / pyobjc-framework-CoreML（已进 install.sh）
- 任务 #2：`core/{ocr,translate,layout,storage}.py` 四个模块全部落地，端到端 smoke 通过
- app.py 重构，翻译逻辑走 core/translate

**已知问题**：
- #2 PyObjC overlay 需用户亲跑 `probe_02_overlay.py` 验收拖框流畅度

**技术债/Hack**：无

## 下一步

- [ ] **首要**：⌃⌥A 截图实测全链路（见上方"下次回来直接干这步"）
- [ ] 如果还死：fault log 会指向新一层真凶；如果是 spawn editor 子进程死，看 `/tmp/translator-capture.log`
- [ ] 全链路通后回归测：截图翻译 + 画廊 + ⌘⇧Y 选中翻译 三个入口都跑一遍
- [ ] 全链路通后清理：删 daemon.py 顶部的诊断 hook（faulthandler 留着无害但 atexit dump 可以去掉）
- [ ] （可选）首装 ja→zh / ko→zh 翻译模型：再跑 `swift/TranslatorPrepare.app`

## 上下文提醒

- v1.1/v1.2a/v1.2b/v1.3/打包 分别独占一个会话
- 每个会话开头先读本文件同步状态
- 每个会话结束前更新"上一个会话产出"和任务状态

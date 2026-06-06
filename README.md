# Local Translator

macOS 截图翻译 + 编辑 + 画廊管理工具。全程离线，不上传任何内容。

**主要功能**
- ⌃⌥A：拉框截图，自动 OCR + 翻译，打开编辑窗
- 编辑器：左图 + 右栏译文同高对齐；矩形 / 椭圆 / 线 / 箭头 / 画笔 / 文字 / 标签 / 马赛克 / 模糊 / 裁剪
- 右栏文本可选中复制：划词→浮动条（单段显示「本段」按钮、多段显示「选中 N 段」按钮）；⌘A 全选；右键菜单含「复制本段/全部 原文/译文/原+译」
- 画廊：无边记风格无限画布，拖拽 / 缩放 / 双击大图 / 重命名 / 删除
- ⌘⇧Y：选中文本即时翻译（菜单栏小弹窗）
- 翻译双引擎：Apple Translation framework（高质量、~60ms）优先，argostranslate 兜底
- 极速响应：⌃⌥A 截图到译文显示约 2 秒（v1.3.3 起，相比 v1.3.2 提速 4 倍）

**系统要求**
- macOS 15+（Apple Translation framework 需要 15+）
- Apple Silicon 推荐（Intel 也跑得起来）

## 安装

### 用法 A — 直接装 .dmg（推荐）

下载（约 540MB，**不在源码里**，由 GitHub Releases 托管）：

- **最新版**：<https://github.com/jiaoziluanbu/translator/releases/latest>
- **历史版本**：<https://github.com/jiaoziluanbu/translator/releases>

下载完之后：

1. 双击 `LocalTranslator-2.2.0.dmg`（或当前最新版），把 **Local Translator.app** 拖到 Applications。
2. 第一次启动会被 Gatekeeper 拦：**右键点应用 → 打开 → 再点确认**。之后随便启。
3. 启动后会弹出新手引导窗口，提示你看屏幕右上角菜单栏里的 **译** 字；真正的下载和授权都从 **译** 菜单按编号完成。
4. 菜单栏点 **译 → ① 下载/检查语言包**：
   - 会打开 Apple Translation 的系统语言包下载器，按提示下载中 / 英 / 日 / 韩。
   - 同时会在后台下载 argos 兜底模型；进度日志在 `/tmp/translator-language-setup.log`。
5. 菜单栏继续点授权入口：
   - **译 → ② 授权辅助功能（全局热键）**：启用 Local Translator
   - **译 → ③ 授权输入监控（选中文字）**：启用 Local Translator
   - **译 → ④ 授权屏幕录制（截图翻译）**：启用 Local Translator
6. 开始使用：
   - **译 → ⑤ 截图翻译 ⌃⌥A**
   - **译 → ⑥ 选中文字翻译 ⌘⇧Y**

### 用法 B — 从源码跑（开发者）

前置：macOS 15+ 建议先装 Xcode Command Line Tools（`xcode-select --install`），install.sh 会自动用 `swiftc` 编译 Apple Translation 桥。没有也能跑，只是只剩 argos 兜底引擎。

```bash
cd translator
bash install.sh        # 装 Python 依赖 + argos 模型 + 编译 swift 桥 + 引导下载 Apple 语言包
/usr/bin/python3 daemon.py  # 启动菜单栏 daemon；或使用 install.sh 结尾打印的 Python 路径
```

install.sh 会依次做：

1. 装 Python 依赖（pywebview / argostranslate / rumps / pynput / pyobjc）
2. 下载 argos 兜底语言包（≥1 个，0 个会直接报错退出，避免静默失败）
3. macOS 15+：`swiftc` 编译 `swift/translator-helper` 和 `swift/TranslatorPrepare.app`
4. `osacompile` 生成 `Local Translator.app` / `Translate Daemon.app`
5. 装右键服务菜单
6. 结尾弹 Y/n 提示「现在打开 TranslatorPrepare.app 装 Apple 语言包吗？」—— 强烈选 Y

## 翻译质量升级（首次必看）

Apple Translation 语言包和 argos 模型都存在当前 macOS 用户目录里，换电脑后不会跟着 `.dmg` 自动带过去。首次安装或换电脑后，菜单栏点 **译 → ① 下载/检查语言包** 即可：

1. 弹窗依次提示下载 **中文** + **英文** + **日文** + **韩文**，每个对话框都点 **下载**。
2. 4 行全部 ✅ 后关掉 Apple 语言包下载器。
3. argos 兜底模型会继续在后台下载；如果网络不稳，可之后再点一次同一个菜单项重试。

之后再翻译，状态栏弹窗的速度会从 5-8 秒降到 60-120ms，质量肉眼可见提升。

> 备注：Apple Translation 的语言包统一在 *系统设置 → 通用 → 语言与地区 → 翻译语言* 管理，所有 App 共享。
> 源码安装时如果 install.sh 跑的时候漏点了引导，事后也可以直接 `open swift/TranslatorPrepare.app`。

## 使用

| 操作 | 快捷键 / 入口 |
|---|---|
| 截图翻译 | `⌃⌥A` |
| 截图后选区操作 | 浮层条 📋 复制 / ✏️ 编辑/翻译 / ✕ 取消 |
| 选中即译 | 选中文本，按 `⌘⇧Y` |
| 编辑器右栏复制 | 划词出浮动条；右键弹菜单；`⌘A` 全选；`⌘C` 复制选中文本 |
| 打开画廊 | 菜单栏 → 译 → 打开画廊 |
| 打开翻译器（粘贴翻译模式）| 菜单栏 → 译 → 打开翻译器 |

## 数据位置

| 内容 | 路径 |
|---|---|
| 数据库（画廊条目） | `~/Library/Application Support/LocalTranslator/db.sqlite` |
| 保存的图片 | `~/Library/Application Support/LocalTranslator/gallery/` |
| argos 翻译模型 | `~/.local/share/argos-translate/` |
| Apple Translation 语言包 | macOS 系统目录（通过系统设置管理）|
| 语言包下载日志 | `/tmp/translator-language-setup.log` |

清空所有数据：

```bash
rm -rf ~/Library/Application\ Support/LocalTranslator
```

## 已知限制

- **未做代码签名**：第一次必须右键打开。如果以后换了 macOS 大版本可能需要再来一次。
- **应用体积 ~1.1GB**：argos 把 stanza/torch 整个拖进来了；后续会瘦身。
- **画廊裁剪不可撤销**：撤销栈只记录注释节点。
- **日韩翻译质量**：`ja→zh` / `ko→zh` 需要在 TranslatorPrepare.app 里把日语和韩语包也下了，否则走 argos。
- **首次冷启动**：daemon 启动后约 5 秒内完成 hot worker 预热；这段时间按 ⌃⌥A 会回退到冷启动路径（~3-5s）。hot worker 空闲 180 秒会自动退出以释放内存，下一次截图会重新预热。

## 性能 / 内存调节

默认配置偏向热键响应速度，同时会控制长期空闲内存：

```bash
python3 daemon.py
```

省内存优先：关闭 hot worker，截图翻译每次走冷启动路径。

```bash
LT_HOT_WORKER=0 python3 daemon.py
```

调短 hot worker 空闲释放时间，例如 60 秒：

```bash
LT_HOT_WORKER_IDLE_TIMEOUT=60 python3 daemon.py
```

## v1.3.3 架构亮点（性能）

为了把 ⌃⌥A 到译文显示的端到端延迟从 8-9 秒压到 ~2 秒，做了四件事：

1. **Hot worker 池**：daemon 启动后预生一个子进程，已 import 完 torch/argos 在 stdin 上沉睡；⌃⌥A 时通过 pipe 唤醒它直接干活，省掉冷启动的 3-5 秒。worker 用完后再补位，空闲超时自动退出，避免长期占用和峰值叠加。
2. **Editor 早开 + 后台 hydrate**：截图完毕立即弹出编辑器（左截图 + 右栏 spinner），OCR 与翻译在后台并行，结果就绪后 worker 写入结果文件，editor watcher 推送到 WebView 并替换 spinner。
3. **Subprocess 模式跳过 daemon-only 依赖**：worker / editor / gallery 子进程不再 import rumps / pynput / argostranslate（顶部按 sys.argv 条件加载），单进程冷启动从 4s 降到 1s。
4. **Konva.js 本地化**：编辑器从 unpkg CDN 加载 Konva 改为打包内 `ui/vendor/konva.min.js`，省去每次 3-4 秒的 DNS+TLS+下载。

## 自己打包

```bash
bash build_app.sh             # .app + .dmg
bash build_app.sh --no-dmg    # 只 .app
```

构建依赖：Xcode 命令行工具（`swiftc`）、Python 3.9+、`pip3 install py2app`、`pip3 install -r install.sh 列表`。

## License

私人项目，未对外发布。

# Local Translator v1.x 设计文档

> 2026-04-23 定稿

## 目标

把现有的"选中翻译"小工具升级为"截图翻译 + 编辑 + 画廊管理"的小型应用，最终通过 GitHub Release + 未签名 .dmg 分发给小白用户。

## 功能需求

1. **全局热键截图**：`Ctrl+Alt+A` 触发区域截图
2. **截图后编辑**：
   - 翻译（右侧 320px 栏，按段落同高度对齐）
   - 裁剪 / 绘图（矩形、圆、直线、箭头、画笔）/ 文字 / 标签 / 马赛克 / 模糊 / 背景
   - 撤销 / 下载 / 取消 / 确认
3. **保存**：
   - 编辑后的原图
   - 带翻译的合成图
   - 入库到本地画廊
4. **画廊管理**：无边记风格，时间倒序默认布局，可自由拖拽

## 非功能需求

- 仅 macOS（14+ 优先，向下兼容到 12）
- 完全离线（argos 翻译 + Vision OCR）
- 分发体积控制在 600MB 内
- 首次启动时间 <5 秒
- 截图到编辑器打开 <1 秒

## 架构

### 总览

```
┌────────────────┐        ┌──────────────────┐
│  daemon.py     │        │  menu bar        │
│  菜单栏+热键   │◄──────►│  ⌃⌥A / 画廊 ...  │
└───┬────────────┘        └──────────────────┘
    │
    │ ⌃⌥A
    ▼
┌────────────────┐
│ ui/capture.py  │  全屏 overlay 选区
└───┬────────────┘
    │ PNG bytes + bbox
    ▼
┌────────────────┐     ┌────────────────┐
│ core/ocr.py    │────►│ core/translate │
│ Vision OCR     │     │ argos          │
└───┬────────────┘     └───────┬────────┘
    │ text_blocks              │ translated
    ▼                          ▼
┌──────────────────────────────────────┐
│ core/layout.py  段落对齐                │
└───┬──────────────────────────────────┘
    │ aligned_blocks
    ▼
┌────────────────┐       ┌────────────────┐
│ ui/editor_*    │──────►│ core/storage   │
│ Canvas 编辑器  │       │ SQLite + PNG   │
└────────────────┘       └───────┬────────┘
                                 │
                                 ▼
                         ┌────────────────┐
                         │ ui/gallery_*   │
                         │ 无边记画布     │
                         └────────────────┘
```

### 目录结构

```
translator/
├── app.py                     # 主翻译窗口（重构后用 core/translate）
├── daemon.py                  # 菜单栏 + 全局热键
├── core/
│   ├── __init__.py
│   ├── ocr.py                 # Vision framework 封装
│   ├── translate.py           # argos 翻译（从 app.py 抽出）
│   ├── storage.py             # SQLite + 文件管理
│   └── layout.py              # 文本块对齐算法
├── ui/
│   ├── __init__.py
│   ├── capture.py             # 区域截图 overlay (PyObjC)
│   ├── editor_window.py       # 编辑窗口 (pywebview)
│   ├── editor.html            # 编辑器前端
│   ├── editor.css
│   ├── editor.js
│   ├── gallery_window.py      # 画廊窗口 (pywebview)
│   ├── gallery.html           # 画廊前端
│   ├── gallery.css
│   └── gallery.js
├── assets/
│   ├── icons/                 # 工具条 SVG 图标
│   └── vendor/                # Konva.js 等第三方库
├── docs/
│   ├── design.md              # 本文件
│   └── context-log.md         # 每会话结束摘要
├── data/                      # 运行时生成（gitignore）
├── install.sh
├── app.py
├── daemon.py
├── workspace.md
└── README.md
```

### 用户数据位置

```
~/Library/Application Support/LocalTranslator/
├── shots/        # 原图 PNG（UUID.png）
├── exports/      # 带翻译合成图 PNG（UUID_export.png）
└── db.sqlite     # 元数据
```

## 数据模型

```sql
-- 截图记录
CREATE TABLE shots (
  id            TEXT PRIMARY KEY,         -- uuid4
  created_at    INTEGER NOT NULL,         -- unix ms
  orig_path     TEXT NOT NULL,            -- 截图原图（已应用编辑）
  export_path   TEXT,                     -- 带翻译合成图，可空
  src_lang      TEXT NOT NULL,
  tgt_lang      TEXT NOT NULL,
  canvas_x      REAL NOT NULL DEFAULT 0,  -- 画廊坐标
  canvas_y      REAL NOT NULL DEFAULT 0,
  width         INTEGER NOT NULL,
  height        INTEGER NOT NULL
);

-- OCR 文本块 + 翻译
CREATE TABLE text_blocks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  shot_id    TEXT NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
  bbox_x     REAL NOT NULL,    -- 左上角 x（原图坐标系，0-1 归一化）
  bbox_y     REAL NOT NULL,
  bbox_w     REAL NOT NULL,
  bbox_h     REAL NOT NULL,
  src_text   TEXT NOT NULL,
  tgt_text   TEXT NOT NULL,
  confidence REAL
);

-- 画布编辑层（可重新编辑）
CREATE TABLE edits (
  shot_id    TEXT PRIMARY KEY REFERENCES shots(id) ON DELETE CASCADE,
  ops_json   TEXT NOT NULL,    -- Konva JSON 序列化
  updated_at INTEGER NOT NULL
);

CREATE INDEX idx_shots_created ON shots(created_at DESC);
CREATE INDEX idx_blocks_shot ON text_blocks(shot_id);
```

## 关键模块接口

### core/ocr.py

```python
def ocr(image_bytes: bytes) -> list[TextBlock]:
    """
    Vision framework OCR。
    返回文本块列表，坐标为原图像素坐标系（左上角原点）。
    """

@dataclass
class TextBlock:
    text: str
    x: float; y: float; w: float; h: float
    confidence: float  # 0-1
```

### core/translate.py

```python
def translate(text: str, src: str, tgt: str) -> str:
    """argos 翻译，自动 English pivot。"""

def detect_lang(text: str) -> str:
    """Unicode 启发式语言检测。"""
```

### core/layout.py

```python
def align_blocks(blocks: list[TextBlock],
                 canvas_height: int) -> list[AlignedBlock]:
    """
    把 OCR 块按 y 坐标聚簇成段落，
    生成右侧翻译栏的对齐位置。
    """
```

### core/storage.py

```python
def save_shot(orig_png: bytes, blocks: list[TextBlock],
              src: str, tgt: str) -> str:  # returns shot_id
def update_export(shot_id: str, export_png: bytes): ...
def save_edits(shot_id: str, ops_json: str): ...
def list_shots(limit=200) -> list[Shot]: ...
def update_canvas_pos(shot_id: str, x: float, y: float): ...
def delete_shot(shot_id: str): ...
```

## 交互流程

### 截图翻译主流程

1. 用户按 `⌃⌥A`
2. `capture.py` 创建全屏透明 overlay，用户拖框选区
3. 拿到 `CGImage` → 转 PNG bytes
4. 并行：
   - `ocr()` 识别文本块
   - `layout.align_blocks()` 计算段落位置
5. 对每个段落调用 `translate()`
6. `storage.save_shot()` 入库（export_path 留空）
7. `editor_window.open(shot_id)` 打开编辑窗口

### 编辑窗口交互

- 左侧：截图 Canvas（Konva）+ 工具条浮层
- 右侧 320px：翻译栏，每个段落定位到对应 y 坐标
- 工具条从左到右：拖拽手柄 · 矩形 · 圆 · 直线 · 箭头 · 画笔 · 文字 · 标签 · 马赛克 · 模糊 · 背景 · 裁剪 · 撤销 · 下载 · 取消 · 确认
- 点击"确认"：Canvas 导出 PNG → `update_export()` + `save_edits()`
- 点击"取消"：丢弃编辑，保留原图记录

### 画廊交互

- 默认布局：按 `created_at DESC` 瀑布流/网格排开在一张无限画布上
- 拖拽缩略图 → `update_canvas_pos()`
- 双击缩略图 → 重新打开编辑窗口
- 右键 → 删除

## 技术点风险清单（v1.1 开头必验证）

| # | 风险 | 验证方式 | 回退方案 |
|---|------|----------|----------|
| 1 | Vision OCR 对中英混排小字精度 | 跑 5 张典型截图看结果 | 接入 Tesseract 兜底 |
| 2 | PyObjC 全屏 overlay 绘制性能 | 原型全屏拖框看流畅度 | 改用 `screencapture -i` 系统截图（样式不可控）|
| 3 | pywebview 传 base64 大图延迟 | 打开一张 3MB 截图测耗时 | 走文件路径而非 base64 **（已验证 2026-04-23：base64 慢 4x，默认 file://）** |
| 4 | Konva.js 在 pywebview 兼容性 | 本地引入 Konva 跑 demo | 换 Fabric.js |
| 5 | argos 多段落顺序翻译吞吐 | 10 段并发测耗时 | 批量合并翻译 |

## 分发方案

- py2app 打包，产物 ~550MB
- 打包到 `.dmg`（拖拽安装）
- GitHub Release 上传（单文件 2GB 上限内）
- README 给出：
  - Gatekeeper 绕过步骤截图
  - 辅助功能权限授权步骤截图
  - 翻译模型首次下载说明（如打包不含模型）

## 里程碑

| 版本 | 交付内容 | 对应会话 |
|------|----------|----------|
| v1.1 | 截图 + OCR + 右栏翻译主干（无工具条）| 会话 2 |
| v1.2a | 工具条一期（形状/画笔/文字/撤销/保存）| 会话 3 |
| v1.2b | 工具条二期（马赛克/模糊/裁剪）+ 样式精修 | 会话 4 |
| v1.3 | 画廊 + 持久化 | 会话 5 |
| v1.4 | py2app 打包 + DMG + README | 会话 6 |

## 关键决策留档

见 [workspace.md](../workspace.md) 的"关键决策记录"表。

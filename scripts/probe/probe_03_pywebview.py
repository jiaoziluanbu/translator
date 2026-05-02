"""
Probe #3: pywebview 传 base64 大图 vs file:// 的延迟对比。
自动跑一次、几秒后自动关闭。
"""
from __future__ import annotations

import base64
import os
import shutil
import tempfile
import time
from pathlib import Path

import webview

SAMPLES = Path(__file__).parent / "samples"
# 挑一张最大的（04-mixed.png ~437KB，接近 3MB 需要再造一张）
# 为测大图，合成一个 3MB PNG 使用 04 图放大 3 倍
BIG_SRC = SAMPLES / "04-mixed.png"


def make_big_png():
    """生成 ~3MB PNG: 复制然后 rename"""
    size = BIG_SRC.stat().st_size
    # 如果 <2MB，复制拼接做成大图：用 PIL 缩放 2x
    if size < 2_000_000:
        try:
            from PIL import Image
            img = Image.open(BIG_SRC)
            big = img.resize((img.width * 2, img.height * 2))
            out = Path(tempfile.gettempdir()) / "probe_big.png"
            big.save(out)
            return out
        except Exception:
            pass
    return BIG_SRC


def build_html(mode: str, img_uri: str, mark_t0_ms: int) -> str:
    return f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>body{{margin:0;background:#222;color:#eee;font:14px/1.4 system-ui}}#log{{padding:8px;background:#111}}img{{max-width:100%;display:block}}</style></head>
<body>
<div id="log">MODE={mode} | waiting img...</div>
<img id="pic" src="{img_uri}"/>
<script>
const t0 = {mark_t0_ms};
const log = document.getElementById('log');
const pic = document.getElementById('pic');
const tLoadEvent = performance.now();
pic.addEventListener('load', () => {{
  const tImg = performance.now();
  // 用 pywebview API 传回去
  const msg = `MODE=${{"{mode}"}} html_ready_at=${{tLoadEvent.toFixed(1)}}ms  img_loaded_at=${{tImg.toFixed(1)}}ms`;
  log.textContent = msg;
  if (window.pywebview && window.pywebview.api && window.pywebview.api.report) {{
    window.pywebview.api.report(msg);
  }} else {{
    window._reported = msg;
  }}
}});
</script>
</body></html>
"""


class Api:
    def __init__(self):
        self.reports = []

    def report(self, msg):
        print(f"  [JS→Py] {msg}")
        self.reports.append(msg)


def run_once(mode: str, big_path: Path, api: Api):
    if mode == "base64":
        b = big_path.read_bytes()
        t_enc0 = time.perf_counter()
        data_uri = "data:image/png;base64," + base64.b64encode(b).decode()
        t_enc = (time.perf_counter() - t_enc0) * 1000
        print(f"\n--- mode={mode} size={len(b)/1024:.0f}KB  b64_encode={t_enc:.1f}ms  uri_len={len(data_uri)/1024:.0f}KB ---")
        html = build_html(mode, data_uri, int(time.time() * 1000))
        uri_mode_len = len(data_uri)
    else:  # file
        # copy to temp so URL is stable
        tmp = Path(tempfile.gettempdir()) / "probe_big_file.png"
        shutil.copy(big_path, tmp)
        url = "file://" + str(tmp)
        print(f"\n--- mode={mode} size={big_path.stat().st_size/1024:.0f}KB  url={url} ---")
        html = build_html(mode, url, int(time.time() * 1000))
        uri_mode_len = 0

    t_start = time.perf_counter()
    window = webview.create_window(f"probe-{mode}", html=html, js_api=api, width=900, height=700)

    def on_loaded():
        t_loaded = (time.perf_counter() - t_start) * 1000
        print(f"  [Py] window loaded_event after {t_loaded:.1f}ms")
        # wait a moment for img onload to fire
        time.sleep(1.5)
        window.destroy()

    window.events.loaded += on_loaded
    webview.start()


def main():
    big = make_big_png()
    print(f"Using image: {big}  size={big.stat().st_size/1024:.0f}KB")

    mode = os.environ.get("MODE", "base64")
    api = Api()
    run_once(mode, big, api)


if __name__ == "__main__":
    main()

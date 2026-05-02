"""
Probe #4: Konva.js 在 pywebview (WKWebView) 中的兼容性。
自动跑：加载 Konva CDN → 绘制 500 图形 → 动画 2 秒 → 上报 FPS。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import webview

HTML = r"""
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body{margin:0;background:#1e1e1e;color:#ddd;font:13px/1.4 system-ui}
#log{padding:6px;background:#000;white-space:pre-wrap}
#container{width:900px;height:520px;border:1px solid #555}
</style>
<script src="https://unpkg.com/konva@9/konva.min.js"></script>
</head>
<body>
<div id="log">loading konva...</div>
<div id="container"></div>
<script>
(async function(){
  const log = document.getElementById('log');
  function report(m){ log.textContent += '\n'+m; if(window.pywebview?.api?.report) window.pywebview.api.report(m);}
  if (typeof Konva === 'undefined') { report('FAIL: Konva not loaded'); return; }
  report('Konva ok v='+Konva.version);

  const stage = new Konva.Stage({container:'container', width:900, height:520});
  const layer = new Konva.Layer();
  stage.add(layer);

  // 测画笔/矩形/文字 API 是否可用
  try {
    layer.add(new Konva.Rect({x:20,y:20,width:100,height:60,fill:'#f55',stroke:'#fff',strokeWidth:2}));
    layer.add(new Konva.Circle({x:200,y:60,radius:40,fill:'#5af'}));
    layer.add(new Konva.Arrow({points:[300,40,500,100],pointerLength:10,pointerWidth:10,stroke:'#fa0',fill:'#fa0',strokeWidth:3}));
    layer.add(new Konva.Line({points:[550,20,700,100,640,140],stroke:'#afa',strokeWidth:2,tension:0.3}));
    layer.add(new Konva.Text({x:20,y:120,text:'Konva 中文 + English OK',fontSize:20,fill:'#fff'}));
    // 画笔模拟
    layer.add(new Konva.Line({points:[20,200,40,180,60,210,80,190,120,220,160,200],stroke:'#fd0',strokeWidth:3,lineCap:'round',tension:0.5}));
    report('shapes ok (rect/circle/arrow/line/text/brush)');
  } catch(e){ report('shape FAIL: '+e.message); }

  // 压力测试：500 随机圆 + 动画
  const N = 500;
  const dots = [];
  for (let i=0;i<N;i++){
    const c = new Konva.Circle({x:Math.random()*900,y:280+Math.random()*230,radius:4+Math.random()*6,fill:`hsl(${Math.random()*360},70%,60%)`});
    dots.push({n:c,vx:(Math.random()-0.5)*4,vy:(Math.random()-0.5)*4});
    layer.add(c);
  }
  layer.draw();

  let frames=0, t0=performance.now();
  const anim = new Konva.Animation(function(){
    for (const d of dots){
      let x=d.n.x()+d.vx, y=d.n.y()+d.vy;
      if (x<0||x>900) d.vx*=-1;
      if (y<280||y>510) d.vy*=-1;
      d.n.x(x); d.n.y(y);
    }
    frames++;
  }, layer);
  anim.start();

  setTimeout(()=>{
    anim.stop();
    const dt = performance.now() - t0;
    const fps = frames / (dt/1000);
    report(`animation: ${frames} frames in ${dt.toFixed(0)}ms → ${fps.toFixed(1)} fps (N=${N})`);
    report('DONE');
  }, 2500);
})();
</script>
</body></html>
"""


class Api:
    def __init__(self):
        self.msgs = []
        self.done = False

    def report(self, m):
        print(f"  [JS] {m}")
        self.msgs.append(m)
        if "DONE" in m:
            self.done = True


def main():
    api = Api()
    window = webview.create_window("probe-konva", html=HTML, js_api=api, width=960, height=640)

    def watch():
        t0 = time.perf_counter()
        while not api.done and time.perf_counter() - t0 < 10:
            time.sleep(0.2)
        time.sleep(0.3)
        window.destroy()

    import threading
    threading.Thread(target=watch, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()

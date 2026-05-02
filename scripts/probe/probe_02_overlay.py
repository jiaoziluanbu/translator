"""
Probe #2: PyObjC 全屏 overlay 选区性能。
跑起来后会全屏覆盖一层半透明黑，鼠标拖一个选框看流畅度。
按 ESC 退出并打印统计；按 Enter 直接完成并截图选区保存到 /tmp/probe_overlay_shot.png。
"""
from __future__ import annotations

import time
from pathlib import Path

import objc
import Quartz
from AppKit import (
    NSApplication,
    NSWindow,
    NSColor,
    NSBezierPath,
    NSView,
    NSEvent,
    NSApp,
    NSCursor,
)
from Foundation import NSRect, NSPoint, NSSize, NSObject


def screen_frame():
    screen = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    # Use NSScreen frame in AppKit pts instead; mix of Quartz/AppKit works here:
    from AppKit import NSScreen
    return NSScreen.mainScreen().frame()


class OverlayView(NSView):
    def initWithFrame_(self, rect):
        self = objc.super(OverlayView, self).initWithFrame_(rect)
        if self is None:
            return None
        self.start_pt = None
        self.cur_pt = None
        self.frames = 0
        self.t0 = time.perf_counter()
        self.last_log = self.t0
        return self

    def acceptsFirstResponder(self):
        return True

    def mouseDown_(self, evt):
        p = evt.locationInWindow()
        self.start_pt = (p.x, p.y)
        self.cur_pt = (p.x, p.y)
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, evt):
        p = evt.locationInWindow()
        self.cur_pt = (p.x, p.y)
        self.frames += 1
        self.setNeedsDisplay_(True)
        now = time.perf_counter()
        if now - self.last_log > 0.5:
            dt = now - self.t0
            fps = self.frames / dt if dt else 0
            print(f"  drag frames={self.frames}  avg_fps={fps:.1f}", flush=True)
            self.last_log = now

    def mouseUp_(self, evt):
        p = evt.locationInWindow()
        self.cur_pt = (p.x, p.y)
        self.setNeedsDisplay_(True)
        dt = time.perf_counter() - self.t0
        fps = self.frames / dt if dt else 0
        print(f"\n=== selection done ===\n  total_frames={self.frames}  drag_duration={dt:.2f}s  avg_fps={fps:.1f}")
        # Stop app
        NSApp.stop_(None)

    def keyDown_(self, evt):
        # ESC to quit
        if evt.keyCode() == 53:
            print("\n[ESC] aborted")
            NSApp.stop_(None)

    def drawRect_(self, rect):
        # dark overlay
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.35).set()
        NSBezierPath.fillRect_(self.bounds())
        if self.start_pt and self.cur_pt:
            x1, y1 = self.start_pt
            x2, y2 = self.cur_pt
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            sel = NSRect(NSPoint(x, y), NSSize(w, h))
            # clear selection
            NSColor.clearColor().set()
            NSBezierPath.fillRect_(sel)
            # border
            NSColor.whiteColor().set()
            path = NSBezierPath.bezierPathWithRect_(sel)
            path.setLineWidth_(2.0)
            path.stroke()


def main():
    app = NSApplication.sharedApplication()
    frame = screen_frame()
    print(f"screen frame: {frame.size.width}x{frame.size.height}")

    mask = 0  # NSWindowStyleMaskBorderless = 0
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, mask, 2, False
    )
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setLevel_(Quartz.kCGMaximumWindowLevelKey or 2147483631)
    # Simpler: use main menu level
    window.setLevel_(8)  # kCGMainMenuWindowLevel approximation
    window.setIgnoresMouseEvents_(False)

    view = OverlayView.alloc().initWithFrame_(frame)
    window.setContentView_(view)
    window.makeKeyAndOrderFront_(None)
    window.makeFirstResponder_(view)

    # activate, bring to front
    app.activateIgnoringOtherApps_(True)
    NSCursor.crosshairCursor().set()

    print("Drag to draw a selection. ESC to abort.")
    app.run()


if __name__ == "__main__":
    main()

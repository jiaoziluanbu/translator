"""Full-screen screenshot overlay.

Shows a translucent overlay across the main display. User drags a selection;
the selected region is captured and returned as PNG bytes.

Usage:
    from ui.capture import capture_region
    result = capture_region()
    if result:
        Path("/tmp/shot.png").write_bytes(result.png_bytes)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import objc
import Quartz
from AppKit import (
    NSApplication,
    NSApp,
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSCursor,
    NSEventMaskAny,
    NSScreen,
    NSView,
    NSWindow,
)
from Foundation import NSPoint, NSRect, NSSize, NSRunLoop, NSDate, NSDefaultRunLoopMode


@dataclass
class CaptureResult:
    png_bytes: bytes
    x: int  # pixel, top-left origin on main display
    y: int
    w: int
    h: int


class _OverlayView(NSView):
    def initWithFrame_(self, rect):
        self = objc.super(_OverlayView, self).initWithFrame_(rect)
        if self is None:
            return None
        self.start_pt = None
        self.cur_pt = None
        self.result_rect = None  # (x, y, w, h) in AppKit points, screen coords
        self.aborted = False
        self.done = False
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
        self.setNeedsDisplay_(True)

    def mouseUp_(self, evt):
        p = evt.locationInWindow()
        self.cur_pt = (p.x, p.y)
        if self.start_pt:
            x1, y1 = self.start_pt
            x2, y2 = self.cur_pt
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            if w >= 2 and h >= 2:
                self.result_rect = (x, y, w, h)
        # Don't call NSApp.stop_() — that flag also stops the rumps outer
        # main loop. We use a sentinel + manual event pump in capture_region.
        self.done = True

    def keyDown_(self, evt):
        if evt.keyCode() == 53:  # ESC
            self.aborted = True
            self.done = True

    def drawRect_(self, rect):
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.35).set()
        NSBezierPath.fillRect_(self.bounds())
        if self.start_pt and self.cur_pt:
            x1, y1 = self.start_pt
            x2, y2 = self.cur_pt
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            sel = NSRect(NSPoint(x, y), NSSize(w, h))
            NSColor.clearColor().set()
            NSBezierPath.fillRect_(sel)
            NSColor.whiteColor().set()
            path = NSBezierPath.bezierPathWithRect_(sel)
            path.setLineWidth_(2.0)
            path.stroke()


def _capture_cgimage_region(x: float, y: float, w: float, h: float):
    """Capture a region of the main display. Coords in display points, top-left origin."""
    display_id = Quartz.CGMainDisplayID()
    region = Quartz.CGRectMake(x, y, w, h)
    return Quartz.CGDisplayCreateImageForRect(display_id, region)


def _cgimage_to_png_bytes(cg_image) -> bytes:
    """Encode CGImage to PNG, converting Display-P3 pixels to sRGB first.

    On modern Macs CGDisplayCreateImageForRect returns a P3-tagged image.
    When that PNG is later drawn to an HTML canvas (Konva), browsers do
    NOT colour-manage the canvas → P3 pixel values get displayed as if
    they were sRGB → noticeably desaturated/grey-looking.

    Fix: redraw the source CGImage into a fresh sRGB CGContext so the
    output bytes are sRGB pixel values; we drop the P3 tag entirely.
    Wide-gamut colors get mapped (slightly clipped at the gamut edge,
    fine for UI screenshots), but average rendering matches Cmd+Shift+4.
    """
    from Foundation import NSMutableData
    w = Quartz.CGImageGetWidth(cg_image)
    h = Quartz.CGImageGetHeight(cg_image)
    srgb = Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB)
    bitmap_info = Quartz.kCGImageAlphaPremultipliedLast | Quartz.kCGBitmapByteOrder32Big
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, srgb, bitmap_info)
    if ctx is None:
        # Fallback: encode original via ImageIO.
        data = NSMutableData.data()
        dest = Quartz.CGImageDestinationCreateWithData(data, "public.png", 1, None)
        Quartz.CGImageDestinationAddImage(dest, cg_image, None)
        Quartz.CGImageDestinationFinalize(dest)
        return bytes(data)
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, w, h), cg_image)
    srgb_image = Quartz.CGBitmapContextCreateImage(ctx)
    data = NSMutableData.data()
    dest = Quartz.CGImageDestinationCreateWithData(data, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, srgb_image, None)
    Quartz.CGImageDestinationFinalize(dest)
    return bytes(data)


def capture_region() -> Optional[CaptureResult]:
    """Show full-screen overlay and return captured region, or None if cancelled."""
    app = NSApplication.sharedApplication()
    screen = NSScreen.mainScreen()
    frame = screen.frame()  # AppKit points
    backing_scale = screen.backingScaleFactor()

    mask = 0  # borderless
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, mask, 2, False
    )
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    # Screen-saver level (1000) — above popup panels (status-bar level 25)
    # and editor windows. Otherwise the dim overlay can't cover those.
    window.setLevel_(1000)
    window.setIgnoresMouseEvents_(False)

    view = _OverlayView.alloc().initWithFrame_(frame)
    window.setContentView_(view)
    window.makeKeyAndOrderFront_(None)
    window.makeFirstResponder_(view)
    app.activateIgnoringOtherApps_(True)
    NSCursor.crosshairCursor().set()

    # Manual event pump — do NOT call app.run() here. The daemon's rumps
    # main loop is already running; nesting [NSApp run] and then calling
    # NSApp.stop_() to break out also kills the outer rumps loop because
    # NSApp's stopped flag is process-wide. We pump events ourselves until
    # the overlay view sets `done = True`.
    while not view.done:
        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            NSEventMaskAny,
            NSDate.dateWithTimeIntervalSinceNow_(0.05),
            NSDefaultRunLoopMode,
            True,
        )
        if event is not None:
            app.sendEvent_(event)

    # Hide overlay before capturing so it doesn't appear in the screenshot.
    window.orderOut_(None)

    if view.aborted or view.result_rect is None:
        return None

    x_pt, y_pt, w_pt, h_pt = view.result_rect
    # CGDisplayCreateImageForRect takes display-space coords in points (top-left origin).
    # AppKit view coords are bottom-left origin → flip Y.
    screen_h_pt = frame.size.height
    rect_x = x_pt
    rect_y = screen_h_pt - (y_pt + h_pt)
    rect_w = w_pt
    rect_h = h_pt
    # Returned CGImage is at device pixels (scale * points); record pixel rect for callers.
    scale = float(backing_scale)
    x_px = int(round(rect_x * scale))
    y_px = int(round(rect_y * scale))
    w_px = int(round(rect_w * scale))
    h_px = int(round(rect_h * scale))

    # Make sure the overlay is actually off-screen before capturing.
    # orderOut_ alone isn't enough — spin the runloop so the window-server
    # processes the removal, then sleep a frame or two for the compositor.
    import time as _time
    rl = NSRunLoop.currentRunLoop()
    deadline = _time.monotonic() + 0.25
    while _time.monotonic() < deadline:
        rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.02))

    cg = _capture_cgimage_region(rect_x, rect_y, rect_w, rect_h)
    if cg is None:
        return None
    png = _cgimage_to_png_bytes(cg)
    return CaptureResult(png_bytes=png, x=x_px, y=y_px, w=w_px, h=h_px)


if __name__ == "__main__":
    from pathlib import Path
    print("Opening overlay… drag a region, ESC to cancel.", flush=True)
    r = capture_region()
    if r is None:
        print("[cancelled] either ESC pressed or selection < 2px")
    else:
        out = Path.home() / "Desktop" / "capture_region_test.png"
        out.write_bytes(r.png_bytes)
        print(f"[saved] {out}")
        print(f"  rect=({r.x},{r.y},{r.w},{r.h})  bytes={len(r.png_bytes)}")

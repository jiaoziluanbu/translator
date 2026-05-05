"""Full-screen screenshot overlay.

Shows a translucent overlay across the main display. User drags a selection;
after mouseUp a small toolbar appears below (or above, if there's no room
below) the selection with three buttons:

  📋 复制     — copy PNG to pasteboard, return action="copy"
  ✏️ 编辑     — open editor (legacy default), return action="edit"
  ✕  取消     — discard, return None

ESC also discards. Clicking outside the toolbar (and outside the selection)
clears the current selection so the user can drag a new region.

Usage:
    from ui.capture import capture_region
    result = capture_region()
    if result and result.action == "edit":
        Path("/tmp/shot.png").write_bytes(result.png_bytes)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import objc
import Quartz
from AppKit import (
    NSApplication,
    NSApp,
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationClear,
    NSCursor,
    NSEventMaskAny,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSPanel,
    NSPasteboard,
    NSPasteboardTypePNG,
    NSRectFillUsingOperation,
    NSScreen,
    NSString,
    NSView,
    NSWindow,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSPoint, NSRect, NSSize, NSRunLoop, NSDate, NSDefaultRunLoopMode

# Trace logger — dumps every step to /tmp so we can see where capture dies.
def _trace(msg: str) -> None:
    try:
        import time as _t, os as _o
        with open("/tmp/translator-capture-trace.log", "a", encoding="utf-8") as _f:
            _f.write(f"[{_t.strftime('%H:%M:%S')}.{int(_t.time()*1000)%1000:03d}] pid={_o.getpid()} {msg}\n")
            _f.flush()
    except Exception:
        pass


@dataclass
class CaptureResult:
    png_bytes: bytes
    x: int  # pixel, top-left origin on main display
    y: int
    w: int
    h: int
    action: Literal["edit", "copy"] = "edit"


# Toolbar layout (AppKit points)
_TB_W = 232
_TB_H = 40
_TB_GAP = 12          # vertical gap between selection edge and toolbar
_TB_BTN_W = 64
_TB_BTN_H = 28
_TB_BTN_GAP = 6
_TB_PADDING_X = 12
_TB_PADDING_Y = 6
_TB_RADIUS = 10


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
        # Toolbar state
        self.action = None       # "edit" | "copy" | None
        self.toolbar_visible = False
        self.toolbar_rect = None      # NSRect (toolbar background)
        self.button_rects = {}        # {"copy": NSRect, "edit": NSRect, "cancel": NSRect}
        self._dragging = False
        return self

    def acceptsFirstResponder(self):
        return True

    # --- toolbar geometry ---
    def _compute_toolbar(self):
        """Compute toolbar position based on current selection.
        Returns (toolbar_rect, button_rects_dict) in view coords (bottom-left origin)."""
        if not self.result_rect:
            return None, {}
        sx, sy, sw, sh = self.result_rect
        bounds = self.bounds()
        scr_w = bounds.size.width
        scr_h = bounds.size.height

        # Default: toolbar centred horizontally on selection, placed below
        # the selection (in screen sense → AppKit y < sy).
        tb_x = sx + sw / 2 - _TB_W / 2
        tb_x = max(_TB_GAP, min(tb_x, scr_w - _TB_W - _TB_GAP))

        # AppKit y: selection occupies [sy, sy+sh].  "Below" the selection
        # in screen sense = y < sy (origin is bottom-left).  We need
        # sy - _TB_GAP - _TB_H >= _TB_GAP.  If not, flip above.
        below_y = sy - _TB_GAP - _TB_H
        if below_y >= _TB_GAP:
            tb_y = below_y
        else:
            above_y = sy + sh + _TB_GAP
            if above_y + _TB_H <= scr_h - _TB_GAP:
                tb_y = above_y
            else:
                # No room either side → overlay near top of selection inside
                tb_y = sy + sh - _TB_H - _TB_GAP

        toolbar = NSRect(NSPoint(tb_x, tb_y), NSSize(_TB_W, _TB_H))

        # Three buttons left→right: copy, edit, cancel
        btn_y = tb_y + (_TB_H - _TB_BTN_H) / 2
        x0 = tb_x + _TB_PADDING_X
        copy_rect = NSRect(NSPoint(x0, btn_y), NSSize(_TB_BTN_W, _TB_BTN_H))
        x0 += _TB_BTN_W + _TB_BTN_GAP
        edit_rect = NSRect(NSPoint(x0, btn_y), NSSize(_TB_BTN_W, _TB_BTN_H))
        x0 += _TB_BTN_W + _TB_BTN_GAP
        cancel_w = _TB_W - _TB_PADDING_X * 2 - (_TB_BTN_W * 2 + _TB_BTN_GAP * 2)
        cancel_rect = NSRect(NSPoint(x0, btn_y), NSSize(cancel_w, _TB_BTN_H))

        return toolbar, {"copy": copy_rect, "edit": edit_rect, "cancel": cancel_rect}

    @staticmethod
    def _point_in_rect(p, r):
        return (r.origin.x <= p[0] <= r.origin.x + r.size.width
                and r.origin.y <= p[1] <= r.origin.y + r.size.height)

    def _hit_button(self, p):
        if not self.toolbar_visible:
            return None
        for name, r in self.button_rects.items():
            if self._point_in_rect(p, r):
                return name
        return None

    # --- mouse handling ---
    def mouseDown_(self, evt):
        p = evt.locationInWindow()
        _trace(f"mouseDown ({p.x:.0f},{p.y:.0f}) toolbar_visible={self.toolbar_visible}")
        # If toolbar is visible, route clicks first.
        hit = self._hit_button((p.x, p.y))
        if hit is not None:
            _trace(f"  -> hit button: {hit}")
            if hit == "copy":
                self.action = "copy"
                self.done = True
            elif hit == "edit":
                self.action = "edit"
                self.done = True
            elif hit == "cancel":
                self.aborted = True
                self.done = True
            return

        # Otherwise begin a new drag (clears any prior selection / toolbar).
        self.toolbar_visible = False
        self.toolbar_rect = None
        self.button_rects = {}
        self.result_rect = None
        self.start_pt = (p.x, p.y)
        self.cur_pt = (p.x, p.y)
        self._dragging = True
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, evt):
        if not self._dragging:
            return
        p = evt.locationInWindow()
        self.cur_pt = (p.x, p.y)
        self.setNeedsDisplay_(True)

    def mouseUp_(self, evt):
        _trace(f"mouseUp dragging={self._dragging}")
        if not self._dragging:
            return
        p = evt.locationInWindow()
        self.cur_pt = (p.x, p.y)
        self._dragging = False
        if self.start_pt:
            x1, y1 = self.start_pt
            x2, y2 = self.cur_pt
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            _trace(f"  selection w={w:.0f} h={h:.0f}")
            if w >= 4 and h >= 4:
                self.result_rect = (x, y, w, h)
                try:
                    self.toolbar_rect, self.button_rects = self._compute_toolbar()
                    self.toolbar_visible = self.toolbar_rect is not None
                    _trace(f"  toolbar_rect computed visible={self.toolbar_visible}")
                except BaseException as e:
                    import traceback
                    _trace(f"  _compute_toolbar FAILED: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                    # Fall back to legacy behaviour: just finish with edit action.
                    self.action = "edit"
                    self.done = True
                    return
            else:
                # Bare click (no meaningful drag) → cancel the whole overlay.
                # Matches the legacy v2.0 behaviour where any mouseUp closed
                # the overlay (returning None when selection was tiny).
                _trace("  drag < 4px → aborting overlay")
                self.aborted = True
                self.done = True
                return
        self.setNeedsDisplay_(True)

    def keyDown_(self, evt):
        if evt.keyCode() == 53:  # ESC
            self.aborted = True
            self.done = True

    # --- drawing ---
    def drawRect_(self, rect):
        try:
            self._do_draw(rect)
        except BaseException as e:
            import traceback
            _trace(f"drawRect FAILED: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            # Best-effort: still draw the dim background so the user sees something.
            try:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.35).set()
                NSBezierPath.fillRect_(self.bounds())
            except Exception:
                pass

    def _do_draw(self, rect):
        # Dim background.
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.35).set()
        NSBezierPath.fillRect_(self.bounds())

        # Selection during drag (using start/cur) OR finalised (result_rect).
        if self._dragging and self.start_pt and self.cur_pt:
            x1, y1 = self.start_pt
            x2, y2 = self.cur_pt
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
        elif self.result_rect:
            x, y, w, h = self.result_rect
        else:
            x = y = w = h = None

        if x is not None and w >= 1 and h >= 1:
            sel = NSRect(NSPoint(x, y), NSSize(w, h))
            # Punch a hole in the dim layer so the selection shows the real
            # screen content underneath (window is opaque=False, bg=clear).
            NSRectFillUsingOperation(sel, NSCompositingOperationClear)
            NSColor.whiteColor().set()
            path = NSBezierPath.bezierPathWithRect_(sel)
            path.setLineWidth_(2.0)
            path.stroke()

            # Size label above-left of selection during drag.
            if self._dragging:
                lbl = f"{int(round(w))} × {int(round(h))}"
                self._draw_size_label(lbl, x, y + h + 6)

        # Toolbar.
        if self.toolbar_visible and self.toolbar_rect is not None:
            self._draw_toolbar()

    def _draw_size_label(self, text, x, y):
        # Small black-on-white pill above the selection
        attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(11),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
        }
        s = NSString.stringWithString_(text)
        size = s.sizeWithAttributes_(attrs)
        bg_w = size.width + 12
        bg_h = size.height + 4
        bg = NSRect(NSPoint(x, y), NSSize(bg_w, bg_h))
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.65).set()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bg, 4, 4)
        path.fill()
        s.drawAtPoint_withAttributes_(NSPoint(x + 6, y + 2), attrs)

    def _draw_toolbar(self):
        _trace("_draw_toolbar entered")
        # Background pill
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.13, 0.13, 0.13, 0.92).set()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.toolbar_rect, _TB_RADIUS, _TB_RADIUS)
        path.fill()
        NSColor.colorWithCalibratedRed_green_blue_alpha_(1, 1, 1, 0.10).set()
        path.setLineWidth_(0.5)
        path.stroke()

        # Buttons
        labels = {
            "copy":   "📋 复制",
            "edit":   "✏️ 编辑",
            "cancel": "✕",
        }
        # Cancel uses red-ish accent; others are white text on subtle hover bg.
        for name, r in self.button_rects.items():
            # Subtle button bg (rounded)
            if name == "cancel":
                btn_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.85, 0.20, 0.20, 0.18)
                txt = NSColor.colorWithCalibratedRed_green_blue_alpha_(1, 0.45, 0.45, 1.0)
                font = NSFont.systemFontOfSize_(15)
            else:
                btn_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(1, 1, 1, 0.06)
                txt = NSColor.whiteColor()
                font = NSFont.systemFontOfSize_(13)
            btn_bg.set()
            bp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 6, 6)
            bp.fill()

            attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: txt}
            s = NSString.stringWithString_(labels[name])
            size = s.sizeWithAttributes_(attrs)
            sw = size.width if hasattr(size, "width") else size[0]
            sh = size.height if hasattr(size, "height") else size[1]
            tx = r.origin.x + (r.size.width - sw) / 2
            ty = r.origin.y + (r.size.height - sh) / 2
            # Use positional 2-arg variant — keyword form is flaky under py2app.
            s.drawAtPoint_withAttributes_(NSPoint(tx, ty), attrs)
        _trace("_draw_toolbar done")


def _capture_cgimage_region(x: float, y: float, w: float, h: float):
    """Capture a region of the main display. Coords in display points, top-left origin."""
    display_id = Quartz.CGMainDisplayID()
    region = Quartz.CGRectMake(x, y, w, h)
    return Quartz.CGDisplayCreateImageForRect(display_id, region)


def _cgimage_to_png_bytes(cg_image) -> bytes:
    """Encode CGImage to PNG, preserving Display P3 colour and dropping alpha.

    Goals (v2.0+):
      1. Match macOS Cmd+Shift+4 colour fidelity — the system writes a
         displayP3-tagged PNG; matching that means saturated reds/oranges
         on the M-series internal screen render identically. WebKit
         color-manages <img>/canvas drawImage on macOS, so the same PNG
         renders correctly inside the editor (Konva) too.
      2. Reduce file size — screenshots are always opaque, so the alpha
         channel is wasted bytes (~25% of pixel data). Encode as RGB.
      3. Maximum PNG compression (compressionQuality=1.0 in ImageIO maps
         to deflate level 9 + filter heuristic).
    """
    from Foundation import NSMutableData
    from CoreFoundation import CFDictionaryCreate, kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks
    w = Quartz.CGImageGetWidth(cg_image)
    h = Quartz.CGImageGetHeight(cg_image)

    # Redraw into a displayP3 RGB (no alpha) bitmap so the output PNG is
    # opaque and tagged with a P3 ICC profile.
    p3 = Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceDisplayP3)
    # 8-bit RGB, 3 bytes/pixel, no alpha.  kCGImageAlphaNone with RGB
    # colorspace is the canonical "opaque RGB" encoding.
    bitmap_info = Quartz.kCGImageAlphaNone | Quartz.kCGBitmapByteOrderDefault
    # Some platforms reject 24bpp packed contexts.  Fall back to
    # AlphaNoneSkipLast (32bpp with the 4th byte ignored) which is widely
    # supported, and tell ImageIO to drop alpha at encode time.
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 3, p3, bitmap_info)
    used_skip_last = False
    if ctx is None:
        bitmap_info = Quartz.kCGImageAlphaNoneSkipLast | Quartz.kCGBitmapByteOrder32Big
        ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, p3, bitmap_info)
        used_skip_last = True
    if ctx is None:
        # Last-ditch: encode the original CGImage as-is.
        data = NSMutableData.data()
        dest = Quartz.CGImageDestinationCreateWithData(data, "public.png", 1, None)
        Quartz.CGImageDestinationAddImage(dest, cg_image, None)
        Quartz.CGImageDestinationFinalize(dest)
        return bytes(data)

    # Draw the source image into our P3 context. CG honours the source
    # CGImage's colour space and color-matches into P3.
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, w, h), cg_image)
    p3_image = Quartz.CGBitmapContextCreateImage(ctx)

    # ImageIO encode options: max compression + drop alpha (in case we
    # fell back to AlphaNoneSkipLast). PNG compression is controlled via
    # `kCGImageDestinationLossyCompressionQuality`; 1.0 = best ratio
    # (zlib level 9). Drop alpha via the dictionary key.
    keys = (
        Quartz.kCGImageDestinationLossyCompressionQuality,
        Quartz.kCGImagePropertyHasAlpha,
    )
    vals = (1.0, False)
    options = CFDictionaryCreate(
        None, keys, vals, len(keys),
        kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks,
    )

    data = NSMutableData.data()
    dest = Quartz.CGImageDestinationCreateWithData(data, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, p3_image, options)
    Quartz.CGImageDestinationFinalize(dest)
    return bytes(data)


def capture_region() -> Optional[CaptureResult]:
    """Show full-screen overlay and return captured region, or None if cancelled."""
    _trace("capture_region: enter")
    app = NSApplication.sharedApplication()
    screen = NSScreen.mainScreen()
    frame = screen.frame()  # AppKit points
    backing_scale = screen.backingScaleFactor()
    _trace(f"capture_region: frame={frame.size.width}x{frame.size.height} scale={backing_scale}")

    # Use a NonactivatingPanel so the overlay can receive mouse/key events
    # WITHOUT stealing focus from the foreground app. This preserves the
    # active text selection in Safari/Notes/etc — otherwise the front app
    # loses key status and turns its blue selection into grey.
    mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
    window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, mask, 2, False
    )
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setHidesOnDeactivate_(False)
    # Screen-saver level (1000) — above popup panels (status-bar level 25)
    # and editor windows. Otherwise the dim overlay can't cover those.
    window.setLevel_(1000)
    window.setIgnoresMouseEvents_(False)
    window.setBecomesKeyOnlyIfNeeded_(True)

    view = _OverlayView.alloc().initWithFrame_(frame)
    window.setContentView_(view)
    # orderFrontRegardless is the no-activate counterpart of makeKeyAndOrderFront.
    # Calling makeFirstResponder is still safe (keyDown for ESC works because
    # event handling happens via our manual NSEvent pump, not the keyWindow chain).
    window.orderFrontRegardless()
    window.makeFirstResponder_(view)
    NSCursor.crosshairCursor().set()

    # Manual event pump — do NOT call app.run() here. The daemon's rumps
    # main loop is already running; nesting [NSApp run] and then calling
    # NSApp.stop_() to break out also kills the outer rumps loop because
    # NSApp's stopped flag is process-wide. We pump events ourselves until
    # the overlay view sets `done = True`.
    _trace("capture_region: entering event pump")
    pump_iters = 0
    while not view.done:
        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            NSEventMaskAny,
            NSDate.dateWithTimeIntervalSinceNow_(0.05),
            NSDefaultRunLoopMode,
            True,
        )
        if event is not None:
            app.sendEvent_(event)
        pump_iters += 1
        if pump_iters % 200 == 0:
            _trace(f"  event pump still alive iters={pump_iters} done={view.done}")
    _trace(f"capture_region: event pump exited (iters={pump_iters}) action={view.action} aborted={view.aborted}")

    # Hide overlay before capturing so it doesn't appear in the screenshot.
    window.orderOut_(None)

    if view.aborted or view.result_rect is None:
        _trace("capture_region: returning None (aborted or no result_rect)")
        return None
    _trace(f"capture_region: action={view.action} rect={view.result_rect}")

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
    _trace(f"capture_region: cgimage={'ok' if cg else 'NULL'}")
    if cg is None:
        return None
    try:
        png = _cgimage_to_png_bytes(cg)
        _trace(f"capture_region: png ok size={len(png)}")
    except BaseException as e:
        import traceback
        _trace(f"capture_region: PNG ENCODE FAILED: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return None
    action = view.action or "edit"
    return CaptureResult(png_bytes=png, x=x_px, y=y_px, w=w_px, h=h_px, action=action)


def copy_png_to_pasteboard(png_bytes: bytes) -> None:
    """Place PNG bytes onto the general pasteboard (public.png type)."""
    from Foundation import NSData
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
    pb.setData_forType_(data, NSPasteboardTypePNG)


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

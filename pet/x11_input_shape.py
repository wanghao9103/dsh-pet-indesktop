"""Cursor-independent X11/XWayland input shapes for the transparent overlay.

An XWayland pointer query can stay at its last X11 position while the pointer is
over a native Wayland surface. Toggling an entire overlay from that query can
therefore leave it permanently transparent over the desktop. Publish the actual
sprite input region instead; the compositor routes a new press without a query.
Only ShapeInput is changed: translucent artwork and aiming effects are untouched.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import math
import sys
import weakref

from PySide6.QtCore import QRect
from PySide6.QtGui import QBitmap, QGuiApplication, QImage, QPainter, QRegion

_sprite_cache = weakref.WeakKeyDictionary()


def sprite_input_region(sprite, dpr: float) -> QRegion:
    """Current rendered alpha >= 16, in window-relative *physical* pixels.

    Keep one local mask per sprite, not a growing cache of animation frames.
    Integer translations reuse it; poses, frame, scale, DPR and squash invalidate
    it. Paint through the sprite's public renderer to share all its transforms.
    """
    rebuild = getattr(sprite, "_rebuild_pixmap", None)
    if callable(rebuild):
        rebuild()
    pixmap = getattr(sprite, "_pixmap", None)
    if pixmap is None or pixmap.isNull():
        return QRegion()
    bounds = sprite.paint_bounds()
    x = math.floor(bounds.x() * dpr)
    y = math.floor(bounds.y() * dpr)
    width = math.ceil((bounds.x() + bounds.width()) * dpr) - x
    height = math.ceil((bounds.y() + bounds.height()) * dpr) - y
    if width <= 0 or height <= 0:
        return QRegion()
    signature = (pixmap.cacheKey(), width, height, dpr,
                 sprite.pos.x() * dpr - x, sprite.pos.y() * dpr - y,
                 sprite._probe_angle, sprite._throw_angle,
                 sprite._squash_progress)
    cached = _sprite_cache.get(sprite)
    if cached is not None and cached[0] == signature:
        return cached[1].translated(x, y)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.scale(dpr, dpr)
        painter.translate(-x / dpr, -y / dpr)
        sprite.paint(painter)
    finally:
        painter.end()

    # NumPy is an existing runtime dependency. Work only on the pet-sized image,
    # never allocate a desktop-sized framebuffer or scan it in a Python loop.
    import numpy as np
    pixels = np.frombuffer(image.constBits(), dtype=np.uint32).reshape(
        height, image.bytesPerLine() // 4)[:, :width]
    bits = np.packbits((pixels >> 24) >= 16, axis=1, bitorder="big")
    stride = ((width + 31) // 32) * 4  # QBitmap requires 32-bit-aligned scanlines
    aligned = np.zeros((height, stride), dtype=np.uint8)
    aligned[:, :bits.shape[1]] = bits
    data = aligned.tobytes()
    mono = QImage(data, width, height, stride, QImage.Format.Format_Mono)
    mono.setColorTable([0xFFFFFFFF, 0xFF000000])
    region = QRegion(QBitmap.fromImage(mono))
    _sprite_cache[sprite] = (signature, region)
    return region.translated(x, y)


class _XRectangle(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]


class X11InputShape:
    """One X connection, closed with its owning widget; no pointer polling."""

    def __init__(self, window):
        self._display = None
        self._last = None
        self._x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self._fixes = ctypes.CDLL(ctypes.util.find_library("Xfixes") or "libXfixes.so.3")
        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XOpenDisplay.restype = ctypes.c_void_p
        self._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self._x11.XCloseDisplay.restype = ctypes.c_int
        self._x11.XFlush.argtypes = [ctypes.c_void_p]
        self._x11.XFlush.restype = ctypes.c_int
        self._fixes.XFixesQueryExtension.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        self._fixes.XFixesQueryExtension.restype = ctypes.c_int
        self._fixes.XFixesCreateRegion.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_XRectangle), ctypes.c_int]
        self._fixes.XFixesCreateRegion.restype = ctypes.c_ulong
        self._fixes.XFixesSetWindowShapeRegion.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_ulong]
        self._fixes.XFixesSetWindowShapeRegion.restype = None
        self._fixes.XFixesDestroyRegion.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._fixes.XFixesDestroyRegion.restype = None
        self._display = self._x11.XOpenDisplay(None)
        if not self._display:
            raise OSError("XOpenDisplay failed")
        event, error = ctypes.c_int(), ctypes.c_int()
        if not self._fixes.XFixesQueryExtension(
                self._display, ctypes.byref(event), ctypes.byref(error)):
            self.close()
            raise OSError("XFixes unavailable")
        window.destroyed.connect(self.close)

    def close(self, *args):
        if self._display:
            self._x11.XCloseDisplay(self._display)
            self._display = None

    def refresh(self, window, *, force=False):
        if not self._display:
            return
        dpr = window.devicePixelRatioF()
        region = QRegion()
        if not window.mouse_through:
            if getattr(window, "_mouse_grab", None) is not None:
                region = QRegion(QRect(0, 0, math.ceil(window.width() * dpr),
                                      math.ceil(window.height() * dpr)))
            else:
                for sprite in window.sprites:
                    if getattr(sprite, "visible", True):
                        region |= sprite_input_region(sprite, dpr)
                region &= QRegion(QRect(0, 0, math.ceil(window.width() * dpr),
                                        math.ceil(window.height() * dpr)))
        handle = window.windowHandle()
        win_id = int(handle.winId() if handle is not None else window.winId())
        if not force and self._last == (win_id, region):
            return
        rects = list(region)
        rectangles = (_XRectangle * len(rects))(
            *(_XRectangle(r.x(), r.y(), r.width(), r.height()) for r in rects))
        native_region = self._fixes.XFixesCreateRegion(
            self._display, rectangles, len(rects))
        try:
            self._fixes.XFixesSetWindowShapeRegion(
                self._display, win_id, 2, 0, 0, native_region)  # ShapeInput only
        finally:
            self._fixes.XFixesDestroyRegion(self._display, native_region)
        self._x11.XFlush(self._display)
        self._last = (win_id, QRegion(region))


def create_x11_input_shape(window):
    """Other Qt backends keep their existing input implementation."""
    if sys.platform != "linux" or QGuiApplication.platformName() != "xcb":
        return None
    return X11InputShape(window)

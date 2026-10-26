"""The X11 input region must not depend on a pointer query from XWayland."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from pet.overlay_window import OverlayWindow
from pet.pet_sprite import PetSprite
from pet import platform_passthrough as pp
from tests.test_overlay_window import FakeLibrary

app = QApplication.instance() or QApplication([])


def sprite_input_region(sprite, dpr):
    from pet.x11_input_shape import sprite_input_region as build
    return build(sprite, dpr)


def make_sprite():
    sprite = PetSprite(FakeLibrary(None), pos=QPointF(30, 40), scale=1)
    image = QImage(6, 5, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(2, 2, QColor(100, 120, 140, 255))
    image.setPixelColor(3, 2, QColor(100, 120, 140, 16))
    image.setPixelColor(4, 2, QColor(100, 120, 140, 15))
    sprite._pixmap = QPixmap.fromImage(image)
    sprite._hit_image = image
    sprite._logical_size = lambda: (6, 5)
    sprite._rebuild_pixmap = lambda: False
    return sprite


def test_native_region_preserves_alpha_threshold_and_translation():
    sprite = make_sprite()
    region = sprite_input_region(sprite, 1)
    assert region.contains(QPoint(32, 42))
    assert region.contains(QPoint(33, 42))
    assert not region.contains(QPoint(34, 42))
    assert not region.contains(QPoint(30, 40))
    sprite.set_pos(QPointF(50, 60))
    moved = sprite_input_region(sprite, 1)
    assert moved.contains(QPoint(52, 62))
    assert not moved.contains(QPoint(32, 42))


def test_native_region_scales_to_physical_pixels():
    sprite = make_sprite()
    region = sprite_input_region(sprite, 2)
    assert region.contains(QPoint(64, 84))
    assert not region.contains(QPoint(60, 80))


def test_native_region_follows_rotation():
    sprite = make_sprite()
    sprite.set_throw_rotation(90)
    region = sprite_input_region(sprite, 1)
    reference = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    reference.fill(0)
    painter = QPainter(reference)
    sprite.paint(painter)
    painter.end()
    for y in range(38, 49):
        for x in range(28, 39):
            expected = reference.pixelColor(x, y).alpha() >= 16
            assert region.contains(QPoint(x, y)) == expected


class ShapeRecorder:
    def __init__(self):
        self.regions = []

    def refresh(self, window, *, force=False):
        from PySide6.QtGui import QRegion
        if window.mouse_through:
            region = QRegion()
        elif window._mouse_grab is not None:
            region = QRegion(window.rect())
        else:
            region = QRegion()
            for sprite in window.sprites:
                if getattr(sprite, "visible", True):
                    region |= sprite_input_region(sprite, window.devicePixelRatioF())
        self.regions.append(region)

    def close(self, *args):
        pass


def test_pointer_outside_pet_cannot_disable_its_native_input(monkeypatch):
    """Reproduce a permanently stale QCursor over the native desktop background."""
    shape = ShapeRecorder()
    monkeypatch.setattr(pp, "create_x11_input_shape", lambda window: shape, raising=False)
    class StaleCursor:
        @staticmethod
        def pos():
            return window.mapToGlobal(QPoint(10, 10))
    monkeypatch.setattr(pp, "QCursor", StaleCursor)
    window = OverlayWindow()
    window.resize(200, 150)
    sprite = make_sprite()
    window.add_sprite(sprite)
    try:
        window.show()
        app.processEvents()
        controller = window._input_controller
        controller.refresh()
        assert shape.regions, "native input shape must be updated without QCursor"
        assert shape.regions[-1].contains(QPoint(32, 42))
        assert not shape.regions[-1].contains(QPoint(10, 10))
        assert not window.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        window.mouse_through = True
        controller.refresh()
        assert shape.regions[-1].isEmpty()
        window.mouse_through = False
        controller.refresh()
        assert shape.regions[-1].contains(QPoint(32, 42))
    finally:
        window.close()


def test_native_shape_handles_hidden_pets_manual_mode_and_drag(monkeypatch):
    """Exercise the region publisher; replace only its X server boundary."""
    from pet.x11_input_shape import X11InputShape
    from types import SimpleNamespace
    shape = object.__new__(X11InputShape)
    calls = []
    shape._display = 1
    shape._last = None
    shape._x11 = SimpleNamespace(XFlush=lambda display: 0)
    shape._fixes = SimpleNamespace(
        XFixesCreateRegion=lambda display, rectangles, count: 1,
        XFixesSetWindowShapeRegion=lambda *args: calls.append(args),
        XFixesDestroyRegion=lambda *args: None,
    )
    window = QWidget()
    window.resize(200, 150)
    window.mouse_through = False
    window._mouse_grab = None
    sprite = make_sprite()
    window.sprites = [sprite]
    try:
        shape.refresh(window)
        assert shape._last[1].contains(QPoint(32, 42))
        count = len(calls)
        shape.refresh(window)
        assert len(calls) == count, "unchanged masks must not write to X11"
        sprite.visible = False
        shape.refresh(window)
        assert shape._last[1].isEmpty()
        sprite.visible = True
        window.mouse_through = True
        shape.refresh(window)
        assert shape._last[1].isEmpty()
        window.mouse_through = False
        window._mouse_grab = object()
        shape.refresh(window)
        assert shape._last[1].contains(QPoint(180, 120))
        window._mouse_grab = None
        shape.refresh(window)
        assert not shape._last[1].contains(QPoint(180, 120))
        assert calls[-1][2] == 2, "only ShapeInput changes, never visual clipping"
    finally:
        window.close()


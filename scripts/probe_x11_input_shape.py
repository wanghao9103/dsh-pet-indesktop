"""Real-X11 routing probe: use Xvfb, PYTHONPATH=. and QT_QPA_PLATFORM=xcb.

Requires the optional developer-only python-xlib package. Clicks land on owned
test windows; production dependencies and user configuration are untouched.
"""
import json
import os
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from Xlib import X, display
from Xlib.ext import xtest, shape

if os.environ.get('PET_PROBE_BASELINE_PATH'):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'pet.platform_passthrough', os.environ['PET_PROBE_BASELINE_PATH'])
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)

from pet import platform_passthrough as pp
from pet.overlay_window import OverlayWindow
from pet.pet_sprite import PetSprite
from tests.test_overlay_window import FakeLibrary

app = QApplication.instance() or QApplication([])


def until(check, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if check():
            return True
        time.sleep(.005)
    return bool(check())


class Background(QWidget):
    presses = 0
    def mousePressEvent(self, event):
        self.presses += 1


class Overlay(OverlayWindow):
    presses = 0
    def mousePressEvent(self, event):
        self.presses += 1
        super().mousePressEvent(event)


class StaleCursor:
    @staticmethod
    def pos():
        return win.mapToGlobal(QPoint(10, 10))


back = Background(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
back.setGeometry(100, 100, 400, 300)
back.show()
win = Overlay()
win.setGeometry(back.geometry())
image = QImage(100, 80, QImage.Format.Format_ARGB32_Premultiplied)
image.fill(0)
painter = QPainter(image)
painter.fillRect(QRect(20, 10, 60, 50), Qt.GlobalColor.blue)
painter.end()
sprite = PetSprite(FakeLibrary(None), pos=QPointF(50, 60), scale=1)
sprite._logical_size = lambda: (100, 80)
sprite._pixmap = QPixmap.fromImage(image)
sprite._hit_image = image
sprite._rebuild_pixmap = lambda: False
win.add_sprite(sprite)
win.show()
win.raise_()
# The fake renderer bypasses rebuild; restore its hit image after DPR setup,
# which normally regenerates this image from the real clip.
sprite._hit_image = image
win.tick_driver._timer.stop()
pp.QCursor = StaleCursor  # Native routing must survive a stale XWayland query.
until(lambda: win._input_controller is not None)
win._input_controller.refresh()
app.processEvents()
d = display.Display()
root = d.screen().root
original = root.query_pointer()


def pointer(local):
    native = d.create_resource_object('window', int(win.winId()))
    origin = root.translate_coords(native, 0, 0)
    dpr = win.devicePixelRatioF()
    xtest.fake_input(d, X.MotionNotify, x=origin.x + int(local[0]*dpr),
                     y=origin.y + int(local[1]*dpr))
    d.sync()
    app.processEvents()
    if os.environ.get('PET_NATIVE_DEBUG'):
        q=root.query_pointer()
        print('pointer', local, origin.x, origin.y, q.root_x, q.root_y,
              'child', q.child, flush=True)


def button(on):
    xtest.fake_input(d, X.ButtonPress if on else X.ButtonRelease, 1)
    d.sync()
    app.processEvents()


def click(local):
    pointer(local)
    button(True)
    button(False)
    app.processEvents()


results = {}
try:
    native = d.create_resource_object('window', int(win.winId()))
    rects = native.shape_get_rectangles(shape.SK.Input).rectangles
    results['native_shape_rectangles'] = len(rects)
    if os.environ.get('PET_NATIVE_DEBUG'):
        print('geometry',native.get_geometry(), 'shape', rects,flush=True)
    results['qpa'] = app.platformName()
    results['dpr'] = win.devicePixelRatioF()
    click((10, 10))
    results['transparent_routes_to_background'] = until(lambda: back.presses == 1)
    click((90, 90))
    results['opaque_routes_to_pet'] = until(lambda: win.presses == 1)
    pointer((90, 90))
    button(True)
    until(lambda: win._mouse_grab is not None)
    for x,y in ((110,100),(130,115),(150,130)):
        pointer((x,y))
        until(lambda: win._drag_committed)
    until(lambda: sprite.pos.x() > 90)
    button(False)
    results['drag_moves_pet'] = until(lambda: sprite.pos.x() > 90)
    results['final_sprite_x'] = sprite.pos.x()
    win.mouse_through = True
    win._input_controller.refresh()
    old = back.presses
    click((int(sprite.pos.x()) + 40, int(sprite.pos.y()) + 30))
    results['manual_passthrough'] = until(lambda: back.presses == old + 1)
    win.mouse_through = False
    win._input_controller.refresh()
    old = win.presses
    click((int(sprite.pos.x()) + 40, int(sprite.pos.y()) + 30))
    results['manual_restore'] = until(lambda: win.presses == old + 1)
    win.hide()
    app.processEvents()
    win.show()
    app.processEvents()
    old = win.presses
    click((int(sprite.pos.x()) + 40, int(sprite.pos.y()) + 30))
    results['hide_show_restores_input'] = until(lambda: win.presses == old + 1)
    print(json.dumps(results, ensure_ascii=False))
finally:
    button(False)
    win.close()
    back.close()
    app.processEvents()
    xtest.fake_input(d, X.MotionNotify, x=original.root_x, y=original.root_y)
    d.sync()
    d.close()
sys.exit(0 if all(v for v in results.values()) else 1)

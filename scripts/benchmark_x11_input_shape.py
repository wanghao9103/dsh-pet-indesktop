import json
import time
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QImage,QPixmap,QPainter
from PySide6.QtWidgets import QApplication
from pet.pet_sprite import PetSprite
from pet.x11_input_shape import sprite_input_region
from tests.test_overlay_window import FakeLibrary

app=QApplication.instance() or QApplication([])
sprite=PetSprite(FakeLibrary(None),pos=QPointF(30,40),scale=1)
image=QImage(640,480,QImage.Format.Format_ARGB32_Premultiplied)
image.fill(0)
p=QPainter(image);p.setBrush(Qt.GlobalColor.blue);p.drawEllipse(QRect(80,20,480,440));p.end()
sprite._logical_size=lambda:(320,240)
sprite._rebuild_pixmap=lambda:False
sprite._pixmap=QPixmap.fromImage(image)
sprite._pixmap.setDevicePixelRatio(2)
sprite._hit_image=image
sprite_input_region(sprite,2)
n=1000
t=time.perf_counter()
for _ in range(n):sprite_input_region(sprite,2)
cached=(time.perf_counter()-t)*1e6/n
t=time.perf_counter()
for _ in range(n):
    sprite._pixmap=QPixmap.fromImage(image.copy())
    sprite._pixmap.setDevicePixelRatio(2)
    sprite_input_region(sprite,2)
frame=(time.perf_counter()-t)*1e6/n
print(json.dumps({'samples':n,'logical_image':[320,240],'dpr':2,
                 'cached_mask_us':cached,'new_frame_including_pixmap_us':frame}))

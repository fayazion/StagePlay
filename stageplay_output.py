"""Native Windows video surface and Qt still-media compositing for StagePlay V2.

The video is hosted in a nested *native* child HWND, clipped by a parent widget.
Geometric cropping/zoom is applied by sizing and positioning the HWND, rather
than relying on VLC's variable video_set_scale / crop support.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QWidget, QStackedWidget

from stageplay_core import crop_transform, default_settings


def canvas_rect(window_width: int, window_height: int, logical: tuple[int, int] | None) -> QRect:
    if not logical or logical[0] <= 0 or logical[1] <= 0:
        return QRect(0, 0, window_width, window_height)
    w, h = logical
    scale = min(window_width/w, window_height/h)
    cw, ch = max(1, round(w*scale)), max(1, round(h*scale))
    return QRect(round((window_width-cw)/2), round((window_height-ch)/2), cw, ch)


class StillSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image: QImage | None = None
        self.settings = default_settings()
        self.logical_canvas: tuple[int, int] | None = None
        self.setStyleSheet('background-color: black;')

    def put_image(self, img: QImage | None, settings: dict):
        self.image = img
        self.settings = settings.copy()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self.image or self.image.isNull():
            return
        region = canvas_rect(self.width(), self.height(), self.logical_canvas)
        rect = crop_transform((self.image.width(), self.image.height()),
                              (region.width(), region.height()), self.settings)
        fx, fy, fw, fh = rect['full']
        cx, cy, cw, ch = rect['clip']
        if cw < 1 or ch < 1:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setClipRect(QRectF(region.x()+cx, region.y()+cy, cw, ch))
        painter.drawImage(QRectF(region.x()+fx, region.y()+fy, fw, fh), self.image)


class OutputWindow(QWidget):
    """Separates the programme from masking overlays; BLACK never calls stop()."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('StagePlay V2 | SORTIE PROGRAM')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet('background: black;')
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.stack = QStackedWidget(self)
        self.black_page = QWidget(self)
        self.black_page.setStyleSheet('background: black;')
        self.video_page = QWidget(self)
        self.video_page.setStyleSheet('background: black;')
        self.clip_widget = QWidget(self.video_page)
        self.clip_widget.setStyleSheet('background: black;')
        self.clip_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video_target = QWidget(self.clip_widget)
        self.video_target.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video_target.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.video_target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.video_target.setStyleSheet('background: black;')
        self.still_page = StillSurface(self)
        self.logo_page = StillSurface(self)
        for page in (self.black_page, self.video_page, self.still_page, self.logo_page):
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self.black_page)
        self.program_kind = 'black'
        self.mask = None
        self.source_size = (1920, 1080)
        self.settings = default_settings()
        self.logical_canvas = None
        self._layout_video()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.stack.setGeometry(self.rect())
        self.still_page.logical_canvas = self.logical_canvas
        self.logo_page.logical_canvas = self.logical_canvas
        self._layout_video()

    def place_on(self, screen):
        self.setGeometry(screen.geometry())
        self.show()
        if self.windowHandle():
            self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self._layout_video()

    def select_canvas(self, canvas: tuple[int, int] | None):
        self.logical_canvas = canvas
        self.still_page.logical_canvas = canvas
        self.logo_page.logical_canvas = canvas
        self._layout_video()
        self.still_page.update()
        self.logo_page.update()

    def select_settings(self, settings: dict, source_size: tuple[int, int] | None = None):
        self.settings = settings.copy()
        if source_size and source_size[0] > 0 and source_size[1] > 0:
            self.source_size = source_size
        self.still_page.settings = self.settings.copy()
        self.still_page.update()
        self._layout_video()

    def _layout_video(self):
        if not hasattr(self, 'video_target'):
            return
        region = canvas_rect(max(1, self.width()), max(1, self.height()), self.logical_canvas)
        transform = crop_transform(self.source_size,
                                   (region.width(), region.height()), self.settings)
        cx, cy, cw, ch = transform['clip']
        fx, fy, fw, fh = transform['full']
        if cw < 1 or ch < 1:
            self.clip_widget.hide()
            return
        self.clip_widget.setGeometry(region.x()+round(cx), region.y()+round(cy),
                                     max(1,round(cw)), max(1,round(ch)))
        self.video_target.setGeometry(round(fx-cx), round(fy-cy),
                                      max(1,round(fw)), max(1,round(fh)))
        self.clip_widget.show()
        self.video_target.show()

    def set_program(self, kind: str, image: QImage | None = None, settings: dict | None = None):
        self.program_kind = kind
        self.mask = None
        if settings:
            self.select_settings(settings)
        if kind == 'video':
            self._switch(self.video_page)
        elif kind in ('image', 'pdf'):
            self.still_page.put_image(image, self.settings)
            self._switch(self.still_page)
        else:
            self._switch(self.black_page)

    def update_still(self, image: QImage):
        self.still_page.put_image(image, self.settings)
        if not self.mask and self.program_kind in ('image', 'pdf'):
            self._switch(self.still_page)

    def set_logo_image(self, image: QImage):
        self.logo_page.put_image(image, default_settings())

    def mask_with(self, mode: str | None):
        self.mask = mode
        if mode == 'black':
            self._switch(self.black_page)
        elif mode == 'logo':
            self._switch(self.logo_page)
        else:
            if self.program_kind == 'video':
                self._switch(self.video_page)
            elif self.program_kind in ('image', 'pdf'):
                self._switch(self.still_page)
            else:
                self._switch(self.black_page)

    def _switch(self, page):
        self.stack.setCurrentWidget(page)
        if page == self.video_page:
            self._layout_video()

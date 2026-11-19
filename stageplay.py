"""StagePlay V2 - portable video/image/PDF playback for Windows show control.

Windows build: see .github/workflows/windows-build.yml.
Not a broadcast-grade certified playout system; test on actual show hardware.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Resolve bundled LibVLC DLL before importing python-vlc.
if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    _bundle = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    _dll = _bundle / 'libvlc.dll'
    if _dll.is_file():
        os.environ['PYTHON_VLC_LIB_PATH'] = str(_dll)
        if hasattr(os, 'add_dll_directory'):
            _vlc_dll_dir = os.add_dll_directory(str(_bundle))
    if (_bundle / 'plugins').is_dir():
        os.environ['VLC_PLUGIN_PATH'] = str(_bundle / 'plugins')

import fitz  # PyMuPDF, used for page-by-page PDF output
import vlc
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame, QApplication, QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from stageplay_core import (MEDIA_EXTS, MODES, create_entry, default_settings,
                            display_time, media_kind, media_path_for_save,
                            next_index, normalized_settings, resolve_saved_path)
from stageplay_output import OutputWindow


class CueList(QListWidget):
    filesDropped = Signal(list)
    reordered = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.filesDropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            self.reordered.emit()


class StagePlay(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('StagePlay V2 | Régie multimédia')
        self.resize(1360, 830)
        self.output = OutputWindow()
        self.instance = vlc.Instance('--quiet', '--no-video-title-show',
                                     '--no-sub-autodetect-file', '--avcodec-hw=any')
        self.player = self.instance.media_player_new()
        self.media = None
        self.current_id: str | None = None
        self.current_kind: str | None = None
        self.current_path: str | None = None
        self.current_pdf = None
        self.pdf_page = 0
        self.pdf_pages = 0
        self.still_started = 0.0
        self.still_frozen_ms = 0
        self.still_paused = False
        self.video_frozen = False
        self.pending_in_seek: int | None = None
        self.finished = False
        self.logo_path = ''
        self.entries: list[dict] = []
        self._building = False
        self._build_ui()
        self._keyboard()
        self.refresh_monitors()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(100)

    def _build_ui(self):
        base_widget = QWidget()
        self.setCentralWidget(base_widget)
        base = QVBoxLayout(base_widget)
        base.setContentsMargins(12, 10, 12, 10)
        head = QHBoxLayout()
        logo = QLabel('STAGEPLAY  /  V2')
        logo.setStyleSheet('font-weight:800;font-size:22px;color:#F0F6FF;')
        head.addWidget(logo)
        head.addStretch()
        info = QLabel('PLAYLIST MULTIMÉDIA  ·  SORTIE A')
        info.setStyleSheet('color:#9eafc5;')
        head.addWidget(info)
        base.addLayout(head)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        base.addWidget(splitter, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        buttons = QHBoxLayout()
        self._button(buttons, '+ Ajouter médias', self.add_files)
        self._button(buttons, 'Supprimer', self.remove_selected)
        self._button(buttons, 'Vider', self.clear_queue)
        ll.addLayout(buttons)
        self.queue = CueList()
        self.queue.filesDropped.connect(self.add_paths)
        self.queue.reordered.connect(self.renumber)
        self.queue.currentRowChanged.connect(self.selection_changed)
        self.queue.itemDoubleClicked.connect(lambda _: self.go())
        ll.addWidget(self.queue, 6)
        items = QHBoxLayout()
        self._button(items, '↑', lambda: self.move_cue(-1))
        self._button(items, '↓', lambda: self.move_cue(1))
        self._button(items, 'Sauver show', self.save_show)
        self._button(items, 'Ouvrir show', self.load_show)
        ll.addLayout(items)

        preview = QGroupBox('PREVIEW · CUE SÉLECTIONNÉE (pas encore diffusée)')
        pv = QVBoxLayout(preview)
        self.preview_pic = QLabel('Sélectionner un média')
        self.preview_pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_pic.setMinimumHeight(115)
        self.preview_pic.setStyleSheet('background:#0b1220;border-radius:5px;color:#9aacc4;')
        pv.addWidget(self.preview_pic)
        self.preview_info = QLabel('')
        self.preview_info.setWordWrap(True)
        pv.addWidget(self.preview_info)
        ll.addWidget(preview, 2)
        splitter.addWidget(left)

        right_area = QScrollArea()
        right_area.setWidgetResizable(True)
        right_area.setFrameShape(QFrame.Shape.NoFrame)
        right = QWidget()
        rl = QVBoxLayout(right)
        right_area.setWidget(right)
        splitter.addWidget(right_area)
        splitter.setSizes([540, 800])

        # Explicit operator output and HDMI / canvas distinction.
        screen_box = QGroupBox('SORTIE A · MONITEUR ET CANVAS')
        screen_form = QFormLayout(screen_box)
        self.screen_combo = QComboBox()
        screen_form.addRow('Moniteur Windows :', self.screen_combo)
        screen_controls = QHBoxLayout()
        self._button(screen_controls, 'Actualiser', self.refresh_monitors)
        self._button(screen_controls, 'Ouvrir sortie', self.open_output)
        self._button(screen_controls, 'Fermer sortie', self.close_output)
        screen_form.addRow(screen_controls)
        self.screen_status = QLabel('Sortie fermée')
        self.screen_status.setWordWrap(True)
        screen_form.addRow('Signal :', self.screen_status)
        self.custom_canvas = QCheckBox('Activer un canvas logique personnalisé (ne change pas le HDMI)')
        self.custom_canvas.stateChanged.connect(self.change_canvas)
        screen_form.addRow(self.custom_canvas)
        canvas_fields = QHBoxLayout()
        self.canvas_w = QSpinBox(); self.canvas_w.setRange(320, 8192); self.canvas_w.setValue(2304)
        self.canvas_h = QSpinBox(); self.canvas_h.setRange(180, 4320); self.canvas_h.setValue(1152)
        self.canvas_w.valueChanged.connect(self.change_canvas)
        self.canvas_h.valueChanged.connect(self.change_canvas)
        canvas_fields.addWidget(self.canvas_w)
        canvas_fields.addWidget(QLabel('×'))
        canvas_fields.addWidget(self.canvas_h)
        screen_form.addRow('Canvas L × H :', canvas_fields)
        rl.addWidget(screen_box)

        transport = QGroupBox('PROGRAM · COMMANDES DE DIFFUSION')
        tr = QVBoxLayout(transport)
        self.on_air = QLabel('EN ATTENTE — sélectionner une cue et appuyer sur GO')
        self.on_air.setWordWrap(True)
        self.on_air.setStyleSheet('font-weight:600;font-size:13px;')
        tr.addWidget(self.on_air)
        controls = QHBoxLayout()
        self._button(controls, '▶ GO', self.go, 'go')
        self._button(controls, '⏯ PAUSE', self.pause)
        self._button(controls, '■ STOP', self.stop)
        self._button(controls, '■ BLACK', self.black_toggle, 'dark')
        self._button(controls, '▣ LOGO', self.logo_toggle, 'dark')
        tr.addLayout(controls)
        control2 = QHBoxLayout()
        self._button(control2, '◀ Cue', lambda: self.select_adjacent(-1))
        self._button(control2, 'Cue ▶', lambda: self.select_adjacent(1))
        self._button(control2, '❄ FREEZE/RESUME', self.freeze)
        self._button(control2, 'Choisir logo…', self.choose_logo)
        tr.addLayout(control2)
        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.sliderReleased.connect(self.seek)
        tr.addWidget(self.progress)
        self.clock = QLabel('00:00 / 00:00')
        tr.addWidget(self.clock)
        playback = QHBoxLayout()
        playback.addWidget(QLabel('Répétition :'))
        self.loop_mode = QComboBox()
        self.loop_mode.addItems(['OFF', 'ONE', 'ALL'])
        self.loop_mode.setToolTip('ONE répète la cue courante; ALL enchaîne et boucle toute la playlist, même si Auto-next est désactivé.')
        playback.addWidget(self.loop_mode)
        self.auto_next = QCheckBox('Auto-next (OFF par sécurité)')
        playback.addWidget(self.auto_next)
        tr.addLayout(playback)
        self.active_status = QLabel('● PRÊT')
        tr.addWidget(self.active_status)
        rl.addWidget(transport)

        media_nav = QGroupBox('VIDÉO IN / OUT   ·   PDF PAGE / IMAGE HOLD')
        nav = QFormLayout(media_nav)
        self.in_sec = QDoubleSpinBox(); self.in_sec.setRange(0, 360000); self.in_sec.setDecimals(2); self.in_sec.setSuffix(' s')
        self.out_sec = QDoubleSpinBox(); self.out_sec.setRange(0, 360000); self.out_sec.setDecimals(2); self.out_sec.setSuffix(' s (0 = fin)')
        self.in_sec.valueChanged.connect(self.settings_changed)
        self.out_sec.valueChanged.connect(self.settings_changed)
        nav.addRow('IN :', self.in_sec)
        nav.addRow('OUT :', self.out_sec)
        inout = QHBoxLayout()
        self._button(inout, 'SET IN = position', self.set_in)
        self._button(inout, 'SET OUT = position', self.set_out)
        self._button(inout, 'Aller au IN', self.go_to_in)
        nav.addRow(inout)
        pages = QHBoxLayout()
        self._button(pages, '◀ Page', lambda: self.change_pdf_page(-1))
        self.pdf_page_label = QLabel('— / —')
        pages.addWidget(self.pdf_page_label)
        self._button(pages, 'Page ▶', lambda: self.change_pdf_page(1))
        nav.addRow('PDF à l’antenne :', pages)
        self.still_seconds = QSpinBox(); self.still_seconds.setRange(0, 3600)
        self.still_seconds.setSuffix(' s (0 = hold)')
        self.still_seconds.valueChanged.connect(self.settings_changed)
        nav.addRow('Durée image/PDF :', self.still_seconds)
        rl.addWidget(media_nav)

        adjustments = QGroupBox('CADRAGE PAR CUE · APPLIQUÉ À LA SORTIE')
        af = QFormLayout(adjustments)
        self.mode = QComboBox(); self.mode.addItems(list(MODES))
        self.mode.currentTextChanged.connect(self.settings_changed)
        af.addRow('Affichage :', self.mode)
        self.zoom = QDoubleSpinBox(); self.zoom.setRange(.25,4); self.zoom.setDecimals(2)
        self.zoom.setSingleStep(.05); self.zoom.setSuffix(' ×'); self.zoom.setValue(1)
        self.zoom.valueChanged.connect(self.settings_changed)
        af.addRow('Zoom :', self.zoom)
        self.pan_x = QDoubleSpinBox(); self.pan_x.setRange(-100,100); self.pan_x.setSuffix(' %'); self.pan_x.valueChanged.connect(self.settings_changed)
        self.pan_y = QDoubleSpinBox(); self.pan_y.setRange(-100,100); self.pan_y.setSuffix(' %'); self.pan_y.valueChanged.connect(self.settings_changed)
        af.addRow('Décalage X :', self.pan_x)
        af.addRow('Décalage Y :', self.pan_y)
        self.crops = {}
        for key, label in [('crop_l','Crop gauche'),('crop_r','Crop droite'),('crop_t','Crop haut'),('crop_b','Crop bas')]:
            widget = QSpinBox(); widget.setRange(0, 45); widget.setSuffix(' %')
            widget.valueChanged.connect(self.settings_changed)
            af.addRow(label+' :', widget)
            self.crops[key] = widget
        self.volume = QSpinBox(); self.volume.setRange(0,100); self.volume.setValue(100)
        self.volume.setSuffix(' %'); self.volume.valueChanged.connect(self.settings_changed)
        af.addRow('Volume :', self.volume)
        fit_buttons = QHBoxLayout()
        self._button(fit_buttons, 'Reset cadrage', self.reset_cadrage)
        self._button(fit_buttons, 'Copier sur toutes', self.copy_cadrage)
        af.addRow(fit_buttons)
        foot = QLabel('Le crop/zoom déplace et masque la fenêtre vidéo native. Le canvas personnalisé modifie le cadrage, pas le mode HDMI de Windows.')
        foot.setWordWrap(True)
        af.addRow(foot)
        rl.addWidget(adjustments)
        rl.addStretch(1)

        self.setStyleSheet('''
          QWidget, QMainWindow {background:#111924;color:#e2e9f2;font-size:12px;}
          QGroupBox {border:1px solid #35465a;border-radius:7px;margin-top:13px;padding:9px;font-weight:bold;}
          QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 5px;}
          QListWidget, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
            background:#1d2b3b;border:1px solid #3b4f67;border-radius:4px;padding:5px;}
          QListWidget::item:selected {background:#244e73;}
          QPushButton {background:#283c52;border:1px solid #435b76;border-radius:5px;padding:8px 9px;}
          QPushButton:hover {background:#375b79;}
          QPushButton#go {background:#16734c;border-color:#2ba66d;font-weight:800;font-size:15px;}
          QPushButton#dark {background:#0c1118;}
          QSlider::groove:horizontal {height:6px;background:#405269;}
          QSlider::handle:horizontal {background:#85c4fc;width:12px;margin:-5px 0;border-radius:6px;}
        ''')
        self._settings_widgets = [self.mode, self.zoom, self.pan_x, self.pan_y,
                                  self.volume, self.in_sec, self.out_sec, self.still_seconds,
                                  *self.crops.values()]

    @staticmethod
    def _button(layout, label, callback, object_name=None):
        button = QPushButton(label)
        if object_name:
            button.setObjectName(object_name)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _keyboard(self):
        shortcuts = {
            'F5': self.go, 'F6': self.black_toggle, 'F7': self.stop,
            'F8': lambda: self.select_adjacent(1), 'F9': self.logo_toggle,
            'Space': self.pause, 'Ctrl+O': self.add_files, 'Ctrl+S': self.save_show,
            'PageDown': lambda: self.change_pdf_page(1),
            'PageUp': lambda: self.change_pdf_page(-1),
        }
        self._shortcut_refs = []
        for binding, callback in shortcuts.items():
            obj = QShortcut(QKeySequence(binding), self)
            obj.setContext(Qt.ShortcutContext.ApplicationShortcut)
            obj.activated.connect(callback)
            self._shortcut_refs.append(obj)

    def refresh_monitors(self):
        idx = self.screen_combo.currentData()
        screens = QGuiApplication.screens()
        self.screen_combo.clear()
        for i, screen in enumerate(screens):
            g = screen.geometry()
            self.screen_combo.addItem(f'#{i+1} · {screen.name()} · {g.width()}×{g.height()} · {screen.refreshRate():.0f} Hz', i)
        if screens:
            self.screen_combo.setCurrentIndex(idx if isinstance(idx, int) and 0 <= idx < len(screens)
                                              else min(1,len(screens)-1))
        self._screen_info()
        try:
            self.screen_combo.currentIndexChanged.disconnect(self._screen_info)
        except (TypeError, RuntimeError):
            pass
        self.screen_combo.currentIndexChanged.connect(self._screen_info)

    def _screen_info(self, *_):
        idx = self.screen_combo.currentData()
        screens = QGuiApplication.screens()
        if isinstance(idx,int) and 0 <= idx < len(screens):
            scr = screens[idx]
            g = scr.geometry()
            self.screen_status.setText(f'{g.width()}×{g.height()} · {scr.refreshRate():.1f} Hz · réglage physique dans Windows')

    def open_output(self):
        idx = self.screen_combo.currentData()
        screens = QGuiApplication.screens()
        if not isinstance(idx,int) or not (0 <= idx < len(screens)):
            return False
        if len(screens) == 1:
            result = QMessageBox.question(self,'Un seul écran',
                'Un seul écran détecté : la sortie recouvrira ce moniteur. Continuer ?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if result != QMessageBox.StandardButton.Yes:
                return False
        self.output.place_on(screens[idx])
        self.change_canvas()
        self.screen_status.setText('● SORTIE OUVERTE · ÉCRAN '+str(idx+1))
        return True

    def close_output(self):
        self.stop()
        self.output.hide()
        self.screen_status.setText('SORTIE FERMÉE')

    def change_canvas(self, *_):
        canvas = ((self.canvas_w.value(), self.canvas_h.value())
                  if self.custom_canvas.isChecked() else None)
        self.output.select_canvas(canvas)
        self._enforce_video_host_ratio()

    def _cue_entries(self):
        return [self.queue.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.queue.count())]

    def add_files(self):
        names, _ = QFileDialog.getOpenFileNames(
            self, 'Ajouter des vidéos, images et PDF', '',
            'Médias (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.mpeg *.wmv *.ts *.m2ts *.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.pdf);;Tous les fichiers (*)')
        if names:
            self.add_paths(names)

    def add_paths(self, paths, allow_missing=False):
        skipped = []
        accepted = 0
        for raw in paths:
            p = Path(raw)
            kind = media_kind(str(p))
            if not kind or (not allow_missing and not p.is_file()):
                skipped.append(p.name)
                continue
            entry = create_entry(str(p))
            self._insert_entry(entry)
            accepted += 1
        self.renumber()
        if accepted and self.queue.currentRow() < 0:
            self.queue.setCurrentRow(0)
        if skipped:
            QMessageBox.information(self, 'Médias non importés',
                'Format non pris en charge ou fichier absent :\n' + '\n'.join(skipped[:12]) +
                ('\n…' if len(skipped) > 12 else '') +
                '\n\nPPT/PPTX : convertir les diapositives en PDF pour cette V2.')

    def _insert_entry(self, entry):
        row = QListWidgetItem()
        row.setData(Qt.ItemDataRole.UserRole, entry)
        self.queue.addItem(row)

    def renumber(self):
        self.entries = self._cue_entries()
        symbols = {'video':'▶', 'image':'▧', 'pdf':'▤'}
        for pos, entry in enumerate(self.entries):
            item = self.queue.item(pos)
            label = Path(entry['path']).name
            missing = not Path(entry['path']).is_file()
            onair = entry['id'] == self.current_id
            prefix = '● ON AIR' if onair else f'{pos+1:02d}'
            item.setText(f'{prefix}  {symbols.get(entry.get("kind"),"?")} {label}' + ('  [ABSENT]' if missing else ''))
            if missing:
                item.setToolTip('Fichier introuvable : '+entry['path'])

    def selected_entry(self):
        item = self.queue.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def current_entry(self):
        return next((e for e in self.entries if e['id']==self.current_id), None)

    def selection_changed(self, _row=None):
        entry = self.selected_entry()
        if not entry:
            self.preview_pic.clear()
            self.preview_pic.setText('Sélectionner un média')
            self.preview_info.setText('')
            return
        s = normalized_settings(entry.get('settings'))
        entry['settings'] = s
        self._building = True
        try:
            self.mode.setCurrentText(s['mode'])
            self.zoom.setValue(s['zoom'])
            self.pan_x.setValue(s['pan_x']); self.pan_y.setValue(s['pan_y'])
            self.in_sec.setValue(s['in_ms']/1000); self.out_sec.setValue(s['out_ms']/1000)
            self.volume.setValue(s['volume'])
            self.still_seconds.setValue(s['still_seconds'])
            for key, widget in self.crops.items():
                widget.setValue(s[key])
        finally:
            self._building = False
        kind = entry['kind']
        self.preview_info.setText(f'{kind.upper()} · {Path(entry["path"]).name}\n'
                                  f'FIT/FILL/Zoom configurables, GO pour diffuser')
        self._update_thumbnail(entry)

    def _update_thumbnail(self, entry):
        path = entry['path']
        kind = entry['kind']
        pixmap = None
        try:
            if Path(path).is_file() and kind == 'image':
                pixmap = QPixmap(path)
            elif Path(path).is_file() and kind == 'pdf':
                doc = fitz.open(path)
                try:
                    p = doc.load_page(0)
                    scale = min(1.2, 450/max(1,p.rect.width))
                    pixels = p.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False)
                    thumb = QImage(pixels.samples, pixels.width, pixels.height,
                                   pixels.stride, QImage.Format.Format_RGB888).copy()
                    pixmap = QPixmap.fromImage(thumb)
                finally:
                    doc.close()
        except Exception:
            pixmap = None
        if pixmap is not None and not pixmap.isNull():
            self.preview_pic.setPixmap(pixmap.scaled(440, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview_pic.setPixmap(QPixmap())
            self.preview_pic.setText('VIDÉO · prête à charger' if kind == 'video' else 'APERÇU INDISPONIBLE')

    def settings_changed(self, *_):
        if self._building:
            return
        entry = self.selected_entry()
        if not entry:
            return
        s = entry['settings']
        s.update(mode=self.mode.currentText(), zoom=self.zoom.value(),
                 pan_x=self.pan_x.value(), pan_y=self.pan_y.value(),
                 volume=self.volume.value(), in_ms=int(round(self.in_sec.value()*1000)),
                 out_ms=int(round(self.out_sec.value()*1000)),
                 still_seconds=self.still_seconds.value())
        for key, widget in self.crops.items():
            s[key] = widget.value()
        if entry['id'] == self.current_id:
            self.output.select_settings(s)
            if self.current_kind == 'video':
                self.player.audio_set_volume(s['volume'])
                self._enforce_video_host_ratio()

    def reset_cadrage(self):
        entry = self.selected_entry()
        if not entry:
            return
        defaults = default_settings()
        for key in ('mode','zoom','pan_x','pan_y','crop_l','crop_r','crop_t','crop_b'):
            entry['settings'][key] = defaults[key]
        self.selection_changed()
        if entry['id'] == self.current_id:
            self.output.select_settings(entry['settings'])
            self._enforce_video_host_ratio()

    def copy_cadrage(self):
        entry = self.selected_entry()
        if not entry:
            return
        keys = ('mode','zoom','pan_x','pan_y','crop_l','crop_r','crop_t','crop_b')
        for each in self.entries:
            if each['id'] != entry['id']:
                for key in keys:
                    each['settings'][key] = entry['settings'][key]

    def remove_selected(self):
        row = self.queue.currentRow()
        if row < 0:
            return
        entry = self.selected_entry()
        if entry and entry['id'] == self.current_id:
            self.stop()
        self.queue.takeItem(row)
        self.renumber()

    def clear_queue(self):
        if not self.entries:
            return
        result = QMessageBox.question(self, 'Vider le show ?', 'Supprimer toutes les cues de la liste ?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if result != QMessageBox.StandardButton.Yes:
            return
        self.stop()
        self.queue.clear()
        self.entries=[]

    def move_cue(self, delta):
        row = self.queue.currentRow()
        dest = row+delta
        if row < 0 or not (0 <= dest < self.queue.count()):
            return
        item = self.queue.takeItem(row)
        self.queue.insertItem(dest, item)
        self.queue.setCurrentRow(dest)
        self.renumber()

    def select_adjacent(self, delta):
        if not self.entries:
            return
        row = self.queue.currentRow()
        if row < 0:
            row = 0
        self.queue.setCurrentRow(max(0,min(self.queue.count()-1,row+delta)))
        # SELECT does NOT change programme: the user explicitly presses GO.

    def _start_image(self, path, kind):
        if kind == 'image':
            img = QImage(path)
            if img.isNull():
                raise ValueError('Image invalide ou non décodable')
            self.pdf_pages = 0
            self.pdf_page_label.setText('— / —')
        else:
            self.current_pdf = fitz.open(path)
            self.pdf_pages = self.current_pdf.page_count
            if self.pdf_pages < 1:
                raise ValueError('PDF vide')
            self.pdf_page = 0
            img = self._pdf_image(0)
            self.pdf_page_label.setText(f'1 / {self.pdf_pages}')
        self.output.set_program(kind, img, self.current_entry()['settings'])
        self.still_started = time.monotonic()
        self.still_frozen_ms = 0
        self.still_paused = False

    def _pdf_image(self, page_num):
        page = self.current_pdf.load_page(page_num)
        target = min(2600, max(1600, self.output.width()))
        # PDF pages are rendered near output size, not at an enormous fixed DPI.
        scale = min(3., target/max(1.,page.rect.width))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False)
        return QImage(pix.samples, pix.width, pix.height, pix.stride,
                      QImage.Format.Format_RGB888).copy()

    def go(self):
        entry = self.selected_entry()
        if not entry:
            return
        path = entry['path']
        if not Path(path).is_file():
            QMessageBox.warning(self,'Média absent',path)
            return
        if not self.output.isVisible() and not self.open_output():
            return
        self._release_program()
        self.finished = False
        self.current_id = entry['id']; self.current_kind = entry['kind']; self.current_path = path
        self.video_frozen = False; self.pending_in_seek = None
        self.output.select_settings(entry['settings'], (1920,1080))
        try:
            if self.current_kind == 'video':
                # Make native child visible before passing HWND to VLC.
                self.output.set_program('video', settings=entry['settings'])
                self.output.video_target.winId()
                self.player.set_hwnd(int(self.output.video_target.winId()))
                self.media = self.instance.media_new_path(path)
                self.player.set_media(self.media)
                if self.player.play() == -1:
                    raise RuntimeError('VLC ne parvient pas à lancer ce média')
                self.player.audio_set_volume(entry['settings']['volume'])
                self.pending_in_seek = entry['settings']['in_ms'] or None
                cue_id = self.current_id
                QTimer.singleShot(300, lambda: self._refresh_video_geometry(cue_id))
                QTimer.singleShot(850, lambda: self._refresh_video_geometry(cue_id))
            else:
                self._start_image(path, self.current_kind)
        except Exception as exc:
            self.stop()
            QMessageBox.warning(self,'Erreur de lecture',str(exc))
            return
        self.on_air.setText('● ON AIR : '+Path(path).name)
        self.active_status.setText('● PLAY · '+self.current_kind.upper())
        self.renumber()

    def _refresh_video_geometry(self, cue_id):
        if self.current_id != cue_id or self.current_kind != 'video':
            return
        try:
            size = self.player.video_get_size(0)
            if size and size[0] > 0 and size[1] > 0:
                self.output.select_settings(self.current_entry()['settings'], size)
                self._enforce_video_host_ratio()
        except Exception:
            pass

    def _enforce_video_host_ratio(self):
        # Prevent double letterboxing in the native target, including STRETCH.
        if self.current_kind == 'video':
            try:
                v=self.output.video_target
                if v.width() > 0 and v.height() > 0:
                    self.player.video_set_aspect_ratio(f'{v.width()}:{v.height()}')
            except Exception:
                pass

    def _release_program(self):
        try:
            self.player.stop()
        except Exception:
            pass
        if self.current_pdf is not None:
            try:
                self.current_pdf.close()
            except Exception:
                pass
            self.current_pdf = None
        self.media = None

    def pause(self):
        if not self.current_kind:
            return
        if self.current_kind == 'video':
            self.player.pause()
            self.active_status.setText('⏯ PAUSE / REPRISE')
        elif self.current_kind in ('image','pdf'):
            if self.still_paused:
                self.still_started = time.monotonic()-self.still_frozen_ms/1000
                self.still_paused=False
            else:
                self.still_frozen_ms = self._still_elapsed()
                self.still_paused=True
            self.active_status.setText('⏯ PAUSE / REPRISE')

    def freeze(self):
        if self.current_kind == 'video':
            # Video PAUSE holds the currently decoded frame; not a guaranteed
            # genlocked or sample-perfect freeze capture.
            self.pause()
            self.video_frozen = not self.video_frozen
        elif self.current_kind in ('image','pdf'):
            self.pause()

    def stop(self):
        self._release_program()
        self.current_id=None;self.current_kind=None;self.current_path=None
        self.finished=False
        self.pending_in_seek=None
        self.video_frozen=False
        self.output.set_program('black')
        self.active_status.setText('■ STOP · SORTIE NOIRE')
        self.on_air.setText('STOP — en attente de la prochaine cue')
        self.pdf_page_label.setText('— / —')
        self.progress.setValue(0)
        self.clock.setText('00:00 / 00:00')
        self.renumber()

    def black_toggle(self):
        # Crucial: does not stop, rewind or pause underlying VLC playback.
        if not self.output.isVisible() and not self.open_output():
            return
        on = self.output.mask == 'black'
        self.output.mask_with(None if on else 'black')
        self.active_status.setText('● PROGRAM RESTAURÉ' if on else '■ BLACK · LECTURE CONSERVÉE')

    def choose_logo(self):
        selected, _ = QFileDialog.getOpenFileName(self,'Charger un logo / holding slide', '',
                                                   'Images (*.png *.jpg *.jpeg *.bmp *.webp)')
        if not selected:
            return
        image=QImage(selected)
        if image.isNull():
            QMessageBox.warning(self,'Image invalide','Impossible de lire ce fichier.')
            return
        self.logo_path = selected
        self.output.set_logo_image(image)
        self.active_status.setText('LOGO CHARGÉ : '+Path(selected).name)

    def logo_toggle(self):
        if not self.logo_path:
            self.choose_logo()
            if not self.logo_path:
                return
        if not self.output.isVisible() and not self.open_output():
            return
        on = self.output.mask == 'logo'
        self.output.mask_with(None if on else 'logo')
        self.active_status.setText('● PROGRAM RESTAURÉ' if on else '▣ LOGO / HOLD')

    def change_pdf_page(self, delta):
        if self.current_kind != 'pdf' or not self.current_pdf:
            return
        target = min(self.pdf_pages-1, max(0, self.pdf_page+delta))
        if target == self.pdf_page:
            return
        try:
            img = self._pdf_image(target)
        except Exception as exc:
            self.active_status.setText('Erreur PDF : '+str(exc))
            return
        self.pdf_page = target
        self.output.update_still(img)
        self.pdf_page_label.setText(f'{target+1} / {self.pdf_pages}')
        # Each page is a fresh duration if a timed PDF was requested.
        self.still_started=time.monotonic();self.still_frozen_ms=0

    def set_in(self):
        if self.current_kind == 'video' and self.current_id == (self.selected_entry() or {}).get('id'):
            self.in_sec.setValue(max(0,self.player.get_time())/1000)

    def set_out(self):
        if self.current_kind == 'video' and self.current_id == (self.selected_entry() or {}).get('id'):
            self.out_sec.setValue(max(0,self.player.get_time())/1000)

    def go_to_in(self):
        entry=self.current_entry()
        if entry and entry.get('kind')=='video':
            self.player.set_time(int(entry['settings'].get('in_ms',0)))

    def seek(self):
        if self.current_kind != 'video':
            return
        duration=max(0,self.player.get_length())
        if duration:
            self.player.set_time(round(duration*self.progress.value()/1000))

    def _still_elapsed(self):
        if self.still_paused:
            return self.still_frozen_ms
        return int(max(0.,time.monotonic()-self.still_started)*1000)

    def poll(self):
        if not self.current_kind or self.finished:
            return
        entry=self.current_entry()
        if not entry:
            return
        settings=entry['settings']
        if self.current_kind == 'video':
            try:
                state=self.player.get_state()
                if state == vlc.State.Error:
                    self.active_status.setText('ERREUR VLC · VÉRIFIER LE MÉDIA')
                    self.finished=True
                    return
                duration=max(0,self.player.get_length())
                current=max(0,self.player.get_time())
                if self.pending_in_seek is not None and state in (vlc.State.Playing,vlc.State.Paused):
                    if duration and self.pending_in_seek < duration:
                        self.player.set_time(self.pending_in_seek)
                        self.pending_in_seek=None
                    elif duration:
                        self.pending_in_seek=None
                if duration and not self.progress.isSliderDown():
                    self.progress.setValue(min(1000, int(1000*current/duration)))
                stop_at = int(settings.get('out_ms',0)) or duration
                in_ms = int(settings.get('in_ms',0))
                self.clock.setText(f'{display_time(current)} / {display_time(duration)} · IN {display_time(in_ms)} · OUT {display_time(stop_at)}')
                # OUT uses polling tolerance, so it is not guaranteed frame-accurate.
                if (settings.get('out_ms',0) and current >= stop_at-50 and
                        state in (vlc.State.Playing,vlc.State.Paused) and not self.pending_in_seek):
                    self._on_media_end(out_reached=True)
                elif state == vlc.State.Ended:
                    self._on_media_end(out_reached=False)
            except Exception as exc:
                self.active_status.setText('Erreur : '+str(exc))
        else:
            elapsed=self._still_elapsed()
            duration=int(settings.get('still_seconds',0))*1000
            self.clock.setText(display_time(elapsed) + (' / HOLD' if duration == 0 else ' / '+display_time(duration)))
            if duration and elapsed >= duration:
                self._on_media_end(out_reached=True)

    def _on_media_end(self, out_reached: bool):
        if self.finished:
            return
        self.finished=True
        current = next((i for i,e in enumerate(self.entries) if e['id']==self.current_id), -1)
        destination=next_index(current,len(self.entries),self.loop_mode.currentText(),self.auto_next.isChecked())
        if destination is not None:
            self.queue.setCurrentRow(destination)
            # QTimer avoids re-entrant VLC callbacks / GUI changes during polling.
            QTimer.singleShot(0,self.go)
            return
        if self.current_kind == 'video':
            if out_reached:
                try:
                    self.player.set_pause(1)  # Approximate last frame at the OUT point.
                except Exception:
                    pass
                self.active_status.setText('■ OUT · IMAGE EN PAUSE (HOLD APPROXIMATIF)')
            else:
                # VLC may clear the final frame on natural EOF, do not promise HOLD.
                self.active_status.setText('■ FIN VIDÉO · PRÊT POUR PROCHAIN GO')
        else:
            self.active_status.setText('■ FIN DURÉE · IMAGE CONSERVÉE')
        self.on_air.setText('CUE TERMINÉE · prochaine cue sur GO')

    def save_show(self):
        target, _ = QFileDialog.getSaveFileName(self, 'Sauver un show', 'show.stageplay.json',
                                                 'Shows StagePlay (*.json)')
        if not target:
            return
        payload = {
            'version': 2,
            'entries': [{**e,'path':media_path_for_save(e['path'], target)} for e in self._cue_entries()],
            'settings': {
                'loop':self.loop_mode.currentText(),
                'auto_next':self.auto_next.isChecked(),
                'canvas_on':self.custom_canvas.isChecked(),
                'canvas_w':self.canvas_w.value(),
                'canvas_h':self.canvas_h.value(),
                'logo':media_path_for_save(self.logo_path, target) if self.logo_path else '',
            },
        }
        try:
            Path(target).write_text(json.dumps(payload,ensure_ascii=False,indent=2), encoding='utf-8')
            self.active_status.setText('SHOW SAUVÉ : '+Path(target).name)
        except OSError as exc:
            QMessageBox.warning(self,'Sauvegarde impossible',str(exc))

    def load_show(self):
        target, _ = QFileDialog.getOpenFileName(self, 'Ouvrir un show', '', 'Shows StagePlay (*.json)')
        if not target:
            return
        try:
            data=json.loads(Path(target).read_text(encoding='utf-8'))
            entries=data['entries']
            if not isinstance(entries,list):
                raise ValueError('La liste des cues est invalide')
            validated=[]
            for entry in entries:
                if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):
                    continue
                absolute=resolve_saved_path(entry['path'],target)
                kind=media_kind(absolute)
                if kind is None:
                    continue
                validated.append({'id':str(entry.get('id') or os.urandom(8).hex()),
                                  'path':absolute,'kind':kind,
                                  'settings':normalized_settings(entry.get('settings'))})
        except (OSError,ValueError,TypeError,KeyError) as exc:
            QMessageBox.warning(self,'Show invalide',str(exc))
            return
        self.stop()
        self.queue.clear()
        for entry in validated:
            self._insert_entry(entry)
        self.renumber()
        if validated:
            self.queue.setCurrentRow(0)
        state=data.get('settings',{}) if isinstance(data.get('settings'),dict) else {}
        self.loop_mode.setCurrentText(state.get('loop','OFF'))
        self.auto_next.setChecked(bool(state.get('auto_next',False)))
        self.canvas_w.setValue(int(state.get('canvas_w',2304)))
        self.canvas_h.setValue(int(state.get('canvas_h',1152)))
        self.custom_canvas.setChecked(bool(state.get('canvas_on',False)))
        self.change_canvas()
        logo=state.get('logo','')
        if logo:
            logo=resolve_saved_path(logo,target)
            if Path(logo).is_file():
                img=QImage(logo)
                if not img.isNull():
                    self.logo_path=logo
                    self.output.set_logo_image(img)
        missing=sum(not Path(e['path']).exists() for e in validated)
        self.active_status.setText(f'SHOW CHARGÉ · {len(validated)} cues · {missing} absente(s)')

    def closeEvent(self,event):
        self.poll_timer.stop()
        self._release_program()
        self.output.close()
        super().closeEvent(event)


def main():
    app=QApplication(sys.argv)
    app.setApplicationName('StagePlay V2')
    gui=StagePlay()
    gui.show()
    return app.exec()


if __name__=='__main__':
    sys.exit(main())

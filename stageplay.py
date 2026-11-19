"""StagePlay Lite - dual-screen show video playback. Windows / libVLC 3.x."""
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog, QComboBox,
    QSpinBox, QDoubleSpinBox, QMessageBox, QCheckBox, QGroupBox, QFormLayout,
    QSlider, QSplitter, QAbstractItemView, QLineEdit, QInputDialog)

# Make bundled LibVLC available from PyInstaller's _internal folder on Windows.
if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    bundle_dir = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    library = bundle_dir / 'libvlc.dll'
    plugins = bundle_dir / 'plugins'
    if library.exists():
        os.environ['PYTHON_VLC_LIB_PATH'] = str(library)
        if hasattr(os, 'add_dll_directory'):
            _vlc_dll_directory = os.add_dll_directory(str(bundle_dir))
    if plugins.is_dir():
        os.environ['VLC_PLUGIN_PATH'] = str(plugins)

try:
    import vlc
except ImportError:
    print('Missing python-vlc. Install requirements.txt', file=sys.stderr)
    raise

VIDEO_EXTS = {'.mp4','.mov','.mkv','.avi','.webm','.m4v','.mpg','.mpeg','.wmv','.ts','.m2ts'}
RATIOS = ['Original', '16:9', '16:10', '4:3', '21:9', '1:1', '9:16', 'Personnalisé']
CROPS = ['Aucun', '16:9', '16:10', '4:3', '21:9', '1:1', '9:16']


def default_settings():
    return dict(ratio='Original', crop='Aucun', zoom=1.0, volume=100)


class DropList(QListWidget):
    filesDropped = Signal(list)
    orderChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

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
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            self.orderChanged.emit()


class OutputWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('StagePlay - SORTIE VIDEO')
        self.setStyleSheet('background: black;')
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(320, 180)

    def place_on(self, screen):
        # Screen geometry uses the Windows extended desktop layout.
        self.setGeometry(screen.geometry())
        self.show()
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('StagePlay Lite | Régie vidéo')
        self.resize(1120, 720)
        self.items = []
        self.current_id = None
        self.current_path = None
        self.is_black = False
        self.output = OutputWindow()
        self._media = None
        self.instance = vlc.Instance('--quiet', '--no-video-title-show', '--no-sub-autodetect-file', '--avcodec-hw=any')
        self.player = self.instance.media_player_new()
        self._build_ui()
        self._shortcuts()
        self.refresh_monitors()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(200)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        base = QVBoxLayout(root)
        base.setContentsMargins(16, 14, 16, 14)
        heading = QLabel('STAGEPLAY  /  LITE')
        heading.setStyleSheet('font-size:23px;font-weight:800;color:#e8efff;')
        base.addWidget(heading)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        base.addWidget(splitter, 1)
        left = QWidget(); ll = QVBoxLayout(left)
        top = QHBoxLayout()
        for title, action in [('＋ Ajouter vidéos', self.add_files), ('− Retirer', self.remove_item), ('Vider', self.clear_all)]:
            btn = QPushButton(title); btn.clicked.connect(action); top.addWidget(btn)
        ll.addLayout(top)
        self.queue = DropList()
        self.queue.filesDropped.connect(self.add_paths)
        self.queue.orderChanged.connect(self.sync_order)
        self.queue.currentRowChanged.connect(self.selection_changed)
        self.queue.itemDoubleClicked.connect(lambda _item: self.go_selected())
        ll.addWidget(self.queue)
        qbar = QHBoxLayout()
        for title, action in [('↑', lambda: self.move_item(-1)), ('↓', lambda: self.move_item(1)), ('Sauver playlist', self.save_playlist), ('Ouvrir playlist', self.load_playlist)]:
            btn=QPushButton(title); btn.clicked.connect(action); qbar.addWidget(btn)
        ll.addLayout(qbar)
        splitter.addWidget(left)

        right = QWidget(); rl = QVBoxLayout(right)
        screen_box = QGroupBox('SORTIE VIDÉO'); form=QFormLayout(screen_box)
        self.screen_combo=QComboBox(); form.addRow('Écran :',self.screen_combo)
        screen_buttons=QHBoxLayout()
        for title, action in [('Actualiser',self.refresh_monitors),('Ouvrir sortie',self.open_output),('Fermer sortie',self.close_output)]:
            b=QPushButton(title); b.clicked.connect(action);screen_buttons.addWidget(b)
        form.addRow(screen_buttons)
        self.res_label=QLabel('La résolution matérielle se règle dans Windows.')
        self.res_label.setWordWrap(True); form.addRow('Résolution :',self.res_label)
        rl.addWidget(screen_box)

        controls=QGroupBox('TRANSPORT / CUE');cl=QVBoxLayout(controls)
        self.now=QLabel('EN ATTENTE — choisir un clip et appuyer sur GO')
        self.now.setWordWrap(True);cl.addWidget(self.now)
        buttons=QHBoxLayout()
        self.go_btn=QPushButton('▶ GO');self.go_btn.setObjectName('go')
        self.go_btn.clicked.connect(self.go_selected);buttons.addWidget(self.go_btn)
        for title, action in [('⏯ Pause',self.pause),('■ STOP',self.stop),('⏭ Suivant',self.next_item),('⬛ BLACK',self.toggle_black)]:
            b=QPushButton(title);b.clicked.connect(action);buttons.addWidget(b)
        cl.addLayout(buttons)
        self.progress=QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0,1000)
        self.progress.sliderReleased.connect(self.seek)
        cl.addWidget(self.progress)
        self.clock=QLabel('00:00 / 00:00');cl.addWidget(self.clock)
        self.autonext=QCheckBox('Enchaîner automatiquement le clip suivant (désactivé par sécurité)')
        cl.addWidget(self.autonext)
        self.autonext.setChecked(False)
        self.status=QLabel('SORTIE FERMÉE');cl.addWidget(self.status)
        rl.addWidget(controls)

        video=QGroupBox('FORMAT / CADRAGE — réglages de la vidéo sélectionnée')
        vf=QFormLayout(video)
        self.ratio=QComboBox();self.ratio.addItems(RATIOS);self.ratio.currentTextChanged.connect(self.settings_changed)
        vf.addRow('Ratio image :',self.ratio)
        self.custom_ratio=QLineEdit('2.39:1');self.custom_ratio.setPlaceholderText('ex. 2.39:1')
        self.custom_ratio.editingFinished.connect(self.settings_changed)
        vf.addRow('Ratio personnalisé :',self.custom_ratio)
        self.crop=QComboBox();self.crop.addItems(CROPS);self.crop.currentTextChanged.connect(self.settings_changed)
        vf.addRow('Crop (recadrage) :',self.crop)
        self.zoom=QDoubleSpinBox();self.zoom.setDecimals(2);self.zoom.setRange(0.25,4);self.zoom.setSingleStep(.05)
        self.zoom.setValue(1);self.zoom.setSuffix(' ×');self.zoom.valueChanged.connect(self.settings_changed)
        vf.addRow('Zoom :',self.zoom)
        self.volume=QSpinBox();self.volume.setRange(0,100);self.volume.setSuffix(' %');self.volume.setValue(100)
        self.volume.valueChanged.connect(self.settings_changed)
        vf.addRow('Volume :',self.volume)
        self.apply_all=QPushButton('Copier ces réglages sur tous les clips')
        self.apply_all.clicked.connect(self.copy_settings);vf.addRow(self.apply_all)
        note=QLabel('Original + aucun crop + zoom 1× = proportions naturelles, sans déformation.\n'
                    'Le ratio force une forme ; le crop retire les bords ; le zoom agrandit ou réduit.\n'
                    'Les résultats exacts de zoom dépendent du moteur de sortie VLC.')
        note.setWordWrap(True);vf.addRow(note)
        rl.addWidget(video)
        rl.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([530, 590])
        self.setStyleSheet('''QMainWindow,QWidget {background:#121923;color:#e2e8f0;font-size:12px;}
            QGroupBox{border:1px solid #344256;border-radius:7px;margin-top:13px;padding:10px;font-weight:700;}
            QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;}
            QListWidget,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit{background:#1c2939;border:1px solid #38495e;border-radius:4px;padding:6px;}
            QPushButton{background:#293b50;border:1px solid #415773;border-radius:5px;padding:9px 10px;}
            QPushButton:hover{background:#385875;} QPushButton#go{background:#19764d;font-weight:800;font-size:16px;}
            QPushButton#go:hover{background:#259a64;} QSlider::groove:horizontal{height:6px;background:#415773;}
            QSlider::handle:horizontal{background:#7dbdff;width:12px;margin:-5px 0;border-radius:6px;}''')

    def _shortcuts(self):
        for key, fun in [('Space',self.pause),('Ctrl+O',self.add_files),('Ctrl+S',self.save_playlist),
                         ('F5',self.go_selected),('F6',self.toggle_black),('F7',self.stop),
                         ('F8',self.next_item)]:
            shortcut=QShortcut(QKeySequence(key),self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(fun)

    def refresh_monitors(self):
        idx=self.screen_combo.currentIndex()
        screens=QGuiApplication.screens()
        self.screen_combo.clear()
        for i,screen in enumerate(screens):
            g=screen.geometry()
            self.screen_combo.addItem(f'Écran {i+1} · {screen.name()} · {g.width()}×{g.height()} ({g.x()}, {g.y()})',i)
        self.screen_combo.setCurrentIndex(min(max(1,idx),len(screens)-1) if screens else -1)
        self.monitor_info()
        try: self.screen_combo.currentIndexChanged.disconnect(self.monitor_info)
        except (TypeError,RuntimeError): pass
        self.screen_combo.currentIndexChanged.connect(self.monitor_info)

    def monitor_info(self, *_):
        screens=QGuiApplication.screens()
        idx=self.screen_combo.currentData()
        if isinstance(idx,int) and 0<=idx<len(screens):
            s=screens[idx];g=s.geometry()
            self.res_label.setText(f'{g.width()} × {g.height()} px, à {s.refreshRate():.1f} Hz. '
                'Changer la résolution / fréquence dans Paramètres Windows > Affichage.')

    def open_output(self):
        screens=QGuiApplication.screens();idx=self.screen_combo.currentData()
        if not isinstance(idx,int) or idx>=len(screens): return
        if len(screens)==1:
            ok=QMessageBox.question(self,'Un seul écran',
                'Un seul écran détecté. La sortie va le recouvrir en plein écran. Continuer ?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ok!=QMessageBox.StandardButton.Yes:return
        self.output.place_on(screens[idx])
        self.status.setText(f'SORTIE OUVERTE · écran {idx+1}')
        # Pass the Windows native HWND to libVLC.
        self.player.set_hwnd(int(self.output.winId()))
        if self.current_path and self.player.is_playing():self.apply_settings()

    def close_output(self):
        self.player.stop()
        self.current_path=None
        self.current_id=None
        self.output.hide()
        self.status.setText('SORTIE FERMÉE')

    def _items_from_queue(self):
        return [self.queue.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.queue.count())]

    def sync_order(self):
        self.items=self._items_from_queue()

    def add_paths(self, paths):
        count=0
        for raw in paths:
            p=Path(raw)
            if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:continue
            entry={'id':os.urandom(8).hex(),'path':str(p.resolve()),'settings':default_settings()}
            self.items.append(entry)
            row=QListWidgetItem(f'{self.queue.count()+1:02d}  {p.name}')
            row.setData(Qt.ItemDataRole.UserRole,entry)
            self.queue.addItem(row);count+=1
        self.renumber()
        if count and self.queue.currentRow()<0:self.queue.setCurrentRow(0)

    def add_files(self):
        files,_=QFileDialog.getOpenFileNames(self,'Ajouter des clips','','Vidéos (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mpg *.mpeg *.wmv *.ts *.m2ts);;Tous fichiers (*)')
        self.add_paths(files)

    def renumber(self):
        for i in range(self.queue.count()):
            item=self.queue.item(i);entry=item.data(Qt.ItemDataRole.UserRole)
            marker='▶' if entry['id']==self.current_id else f'{i+1:02d}'
            item.setText(f'{marker}  {Path(entry["path"]).name}')
        self.sync_order()

    def remove_item(self):
        row=self.queue.currentRow()
        if row<0:return
        entry=self.queue.item(row).data(Qt.ItemDataRole.UserRole)
        if entry['id']==self.current_id:self.stop()
        self.queue.takeItem(row)
        self.renumber()

    def clear_all(self):
        self.stop();self.queue.clear();self.items=[]

    def move_item(self, delta):
        row=self.queue.currentRow(); dest=row+delta
        if row<0 or dest<0 or dest>=self.queue.count():return
        item=self.queue.takeItem(row);self.queue.insertItem(dest,item)
        self.queue.setCurrentRow(dest);self.renumber()

    def selection_changed(self, _row):
        entry=self.selected()
        if not entry:return
        s=entry['settings']
        for w in (self.ratio,self.crop,self.zoom,self.volume,self.custom_ratio):w.blockSignals(True)
        self.ratio.setCurrentText(s.get('ratio','Original'))
        self.crop.setCurrentText(s.get('crop','Aucun'))
        self.zoom.setValue(float(s.get('zoom',1)))
        self.volume.setValue(int(s.get('volume',100)))
        self.custom_ratio.setText(s.get('custom_ratio','2.39:1'))
        for w in (self.ratio,self.crop,self.zoom,self.volume,self.custom_ratio):w.blockSignals(False)

    def selected(self):
        item=self.queue.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def settings_changed(self, *_):
        entry=self.selected()
        if entry is None:return
        entry['settings']=dict(ratio=self.ratio.currentText(),crop=self.crop.currentText(),
                               zoom=self.zoom.value(),volume=self.volume.value(),
                               custom_ratio=self.custom_ratio.text().strip())
        if entry['id']==self.current_id:self.apply_settings()

    def copy_settings(self):
        source=self.selected()
        if source is None:return
        for item in self.items:item['settings']=source['settings'].copy()

    def go_selected(self):
        entry=self.selected()
        if not entry:return
        if not Path(entry['path']).is_file():
            QMessageBox.warning(self,'Fichier absent',entry['path']);return
        if not self.output.isVisible():self.open_output()
        if not self.output.isVisible():return
        self.player.stop()
        self.current_id=entry['id'];self.current_path=entry['path'];self.is_black=False
        self._media=self.instance.media_new_path(entry['path'])
        self.player.set_media(self._media)
        self.player.set_hwnd(int(self.output.winId()))
        result=self.player.play()
        if result==-1:
            QMessageBox.warning(self,'Erreur VLC','Lecture impossible. Vérifie VLC et le fichier vidéo.')
            return
        self.now.setText('EN LECTURE : '+Path(entry['path']).name)
        self.status.setText('● PLAY')
        self.renumber()
        QTimer.singleShot(150,self.apply_settings)
        QTimer.singleShot(550,self.apply_settings)

    def apply_settings(self):
        if not self.current_path:return
        entry=next((x for x in self.items if x['id']==self.current_id),None)
        if entry is None:return
        s=entry['settings']
        ratio=s.get('ratio','Original')
        if ratio=='Original':ratio=None
        elif ratio=='Personnalisé':
            ratio=s.get('custom_ratio','2.39:1')
            try:
                a,b=ratio.split(':');assert float(a)>0 and float(b)>0
            except (ValueError,AssertionError):ratio=None
        crop=s.get('crop','Aucun');crop=None if crop=='Aucun' else crop
        try:
            self.player.video_set_aspect_ratio(ratio)
            self.player.video_set_crop_geometry(crop)
            self.player.video_set_scale(0.0 if float(s.get('zoom',1))==1.0 else float(s['zoom']))
            self.player.audio_set_volume(int(s.get('volume',100)))
        except Exception as err:
            self.status.setText('Réglage VLC : '+str(err))

    def pause(self):
        if not self.current_path:return
        self.player.pause()
        self.status.setText('⏯ PAUSE / REPRISE')

    def stop(self):
        self.player.stop()
        self.current_id=None;self.current_path=None
        self.is_black=False
        self.now.setText('STOP — sortie noire en attente')
        self.status.setText('■ STOP')
        self.progress.setValue(0);self.clock.setText('00:00 / 00:00')
        self.renumber()

    def toggle_black(self):
        # Stop ensures an actual black frame without relying on an overlay obscuring video output.
        if not self.is_black:
            self.stop();self.is_black=True
            self.status.setText('⬛ BLACK (lecture arrêtée)')
        else:
            self.is_black=False
            self.status.setText('PRÊT')

    def next_item(self):
        if not self.items:return
        index=next((i for i,e in enumerate(self.items) if e['id']==self.current_id),-1)
        nxt=index+1
        if nxt>=len(self.items):self.stop();return
        self.queue.setCurrentRow(nxt)
        self.go_selected()

    def poll(self):
        if not self.current_path:return
        try:
            state=self.player.get_state()
            if state==vlc.State.Ended:
                if self.autonext.isChecked():self.next_item()
                else:self.stop()
                return
            if state==vlc.State.Error:
                self.status.setText('ERREUR LECTURE')
                return
            duration=max(0,self.player.get_length());current=max(0,self.player.get_time())
            if duration and not self.progress.isSliderDown():
                self.progress.setValue(int(1000*current/duration))
            self.clock.setText(f'{self.format_ms(current)} / {self.format_ms(duration)}')
        except Exception:pass

    @staticmethod
    def format_ms(ms):
        sec=ms//1000
        return f'{sec//3600:02d}:{(sec//60)%60:02d}:{sec%60:02d}' if sec>=3600 else f'{sec//60:02d}:{sec%60:02d}'

    def seek(self):
        if self.current_path:self.player.set_position(self.progress.value()/1000.0)

    def save_playlist(self):
        name,_=QFileDialog.getSaveFileName(self,'Sauver playlist','show.stageplay.json','Playlist StagePlay (*.json)')
        if not name:return
        data={'version':1,'entries':self._items_from_queue()}
        Path(name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

    def load_playlist(self):
        name,_=QFileDialog.getOpenFileName(self,'Charger playlist','','Playlist StagePlay (*.json)')
        if not name:return
        try:
            data=json.loads(Path(name).read_text(encoding='utf-8'))
            entries=data['entries'];assert isinstance(entries,list)
            self.clear_all()
            for entry in entries:
                if not isinstance(entry,dict) or 'path' not in entry:continue
                path=str(entry['path'])
                if not Path(path).exists():continue
                self.add_paths([path])
                item=self.queue.item(self.queue.count()-1)
                actual=item.data(Qt.ItemDataRole.UserRole)
                if isinstance(entry.get('settings'),dict):actual['settings'].update(entry['settings'])
            self.renumber();self.selection_changed(self.queue.currentRow())
        except (KeyError,TypeError,ValueError,OSError,AssertionError) as err:
            QMessageBox.warning(self,'Playlist invalide',str(err))

    def closeEvent(self,event):
        self.timer.stop();self.player.stop();self.output.close()
        super().closeEvent(event)


def main():
    app=QApplication(sys.argv)
    app.setApplicationName('StagePlay Lite')
    win=MainWindow();win.show()
    sys.exit(app.exec())

if __name__=='__main__':main()

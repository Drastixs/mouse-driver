"""Native Qt desktop interface. All device operations run off the GUI thread."""
import copy
import json
import os
from pathlib import Path
import time

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QLinearGradient, QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QDialog, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QToolBox, QRadioButton, QButtonGroup, QFileDialog,
    QColorDialog, QMessageBox, QInputDialog, QDialogButtonBox, QSlider,
    QScrollArea,
)

from .controller import save_json, import_profile, decode_native_profile
from .protocol import (
    DPI_VALUES, POLLING, ACTIONS, DEFAULT_BUTTONS, EFFECTS, KEYS,
    button_label, button_code, macro_button, parse_macro,
)

STYLE = """
QWidget { background: #101214; color: #bfc5c9; font-size: 12px; }
QDialog, QMainWindow { background: #101214; }
QMainWindow { border: 2px solid #009dc3; }
QLabel#brand { color: #00acd4; font-size: 30px; font-weight: bold; }
QLabel#status { color: #76c8da; }
QGroupBox { border: 1px solid #363d42; margin-top: 14px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #00afd5; }
QPushButton, QComboBox, QSpinBox, QLineEdit { background: #191d20;
 border: 1px solid #3b454c; padding: 5px; min-height: 19px; }
QPushButton:hover { border-color: #00b3de; color: white; }
QPushButton:disabled { color: #606b72; }
QPushButton#apply { border: 1px solid #00b7df; background: #003747; color: white; }
QToolBox::tab { background: #20262a; border: 1px solid #394147;
 padding: 6px; text-align: left; }
QToolBox::tab:selected { color: #00badd; }
QTableWidget, QPlainTextEdit { background: #14191d; border: 1px solid #364149; }
QHeaderView::section { background: #232b30; border: 0; padding: 4px; }
QSlider::groove:horizontal { background: #303b43; height: 4px; }
QSlider::handle:horizontal { background: #00a8cd; width: 12px; margin: -5px 0; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked { background: #00b4d5; }
QRadioButton::indicator { border: 1px solid #56636b; border-radius: 6px; width: 12px; height: 12px; }
"""


def combo(values):
    widget = QComboBox()
    for value in values:
        widget.addItem(str(value), value)
    return widget


def select_value(widget, value):
    index = widget.findData(value)
    if index < 0:
        widget.addItem(f'Unrecognized ({value})', value)
        index = widget.count() - 1
    widget.setCurrentIndex(index)


class Task(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation())
        except Exception as exc:
            self.failed.emit(str(exc))


class Canvas(QWidget):
    def __init__(self, skin_dir=None):
        super().__init__()
        self.skin_dir = skin_dir

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#101214'))
        if self.skin_dir:
            from PySide6.QtGui import QPixmap
            image = QPixmap(str(self.skin_dir / 'main_nr.png'))
            if not image.isNull():
                painter.drawPixmap(self.rect(), image)
                return
        painter.setPen(QPen(QColor('#182025'), 1))
        # Native geometric texture and cyan frame, inspired by the original skin.
        for y in range(30, self.height()-25, 14):
            for x in range(20 + (7 if y//14 % 2 else 0), self.width()-20, 14):
                painter.drawEllipse(x, y, 5, 5)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.moveTo(8, 28)
        path.lineTo(28, 8)
        path.lineTo(self.width()-28, 8)
        path.lineTo(self.width()-8, 28)
        path.lineTo(self.width()-8, self.height()-28)
        path.lineTo(self.width()-28, self.height()-8)
        path.lineTo(28, self.height()-8)
        path.lineTo(8, self.height()-28)
        path.closeSubpath()
        painter.setPen(QPen(QColor('#0089aa'), 2))
        painter.drawPath(path)


class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, color='#00aacc', compact=False):
        super().__init__()
        self.compact = compact
        self.set_color(color)
        self.clicked.connect(self.choose)

    def set_color(self, color):
        self.color = color
        self.setText('' if self.compact else color.upper())
        self.setToolTip(color.upper())
        self.setStyleSheet(f'border-left: 10px solid {color};')

    def choose(self):
        color = QColorDialog.getColor(QColor(self.color), self, 'Select color')
        if color.isValid():
            self.set_color(color.name())
            self.changed.emit()


class MouseDiagram(QWidget):
    selected = Signal(int)
    # Labels follow the vendor screen. Label 10 maps to matrix entry 11.
    positions = ((95, 135), (193, 135), (145, 159), (48, 225), (53, 279),
                 (161, 220), (161, 249), (51, 136), (161, 282), (41, 192))
    matrix_slots = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10)

    def __init__(self, skin_dir=None):
        super().__init__()
        self.setMinimumSize(290, 440)
        self.current = -1
        self.skin_dir = skin_dir
        self.setToolTip('Click a numbered button to edit its assignment')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate((self.width() - 280) / 2, (self.height() - 440) / 2)
        if self.skin_dir:
            from PySide6.QtGui import QPixmap
            image = QPixmap(str(self.skin_dir / 'mouse' / 'mouse_nr.png'))
            if not image.isNull():
                painter.drawPixmap(0, 0, 280, 440, image)
            else:
                self.draw_mouse(painter)
        else:
            self.draw_mouse(painter)
        for i, (x, y) in enumerate(self.positions):
            painter.setPen(QPen(QColor('#00b6db' if i == self.current else '#cad1d6'), 1.5))
            painter.setBrush(QColor('#00546a' if i == self.current else '#33393dcc'))
            painter.drawEllipse(QRectF(x-11, y-11, 22, 22))
            painter.drawText(QRectF(x-11, y-11, 22, 22), Qt.AlignmentFlag.AlignCenter, str(i+1))

    @staticmethod
    def draw_mouse(p):
        body = QPainterPath()
        body.moveTo(141, 73)
        body.cubicTo(63, 72, 35, 119, 34, 202)
        body.cubicTo(25, 300, 42, 403, 139, 421)
        body.cubicTo(241, 422, 264, 299, 240, 185)
        body.cubicTo(229, 110, 211, 78, 141, 73)
        gradient = QLinearGradient(30, 0, 260, 0)
        gradient.setColorAt(0, QColor('#20282e'))
        gradient.setColorAt(.45, QColor('#59626a'))
        gradient.setColorAt(1, QColor('#1c2329'))
        p.setBrush(gradient)
        p.setPen(QPen(QColor('#04adc9'), 1.4))
        p.drawPath(body)
        p.setPen(QPen(QColor('#090d10'), 3))
        p.drawLine(133, 77, 129, 266)
        p.drawLine(158, 79, 169, 281)
        p.drawLine(141, 30, 141, 72)
        p.setBrush(QColor('#003e53'))
        p.drawRoundedRect(QRectF(133, 121, 26, 63), 8, 8)
        for y in (129, 141, 153, 165, 177):
            p.setPen(QPen(QColor('#00b7d8'), 2))
            p.drawLine(138, y, 153, y)
        p.setPen(QPen(QColor('#0a0e10'), 2))
        p.setBrush(QColor('#252d32'))
        for y in (213, 244, 275):
            p.drawRoundedRect(QRectF(145, y, 34, 21), 5, 5)
        for y in (208, 261):
            p.drawRoundedRect(QRectF(36, y, 17, 41), 5, 5)
        p.setPen(QColor('#00b6d8'))
        p.setFont(QFont('Sans', 11, QFont.Weight.Bold))
        p.drawText(QRectF(55, 356, 180, 35), Qt.AlignmentFlag.AlignCenter, 'TECKNET')

    def mousePressEvent(self, event):
        point = event.position()
        x = point.x() - (self.width() - 280) / 2
        y = point.y() - (self.height() - 440) / 2
        for i, (px, py) in enumerate(self.positions):
            if (x-px)**2 + (y-py)**2 < 22**2:
                self.current = i
                self.update()
                self.selected.emit(self.matrix_slots[i])
                break


class BindingDialog(QDialog):
    def __init__(self, code, macros, parent):
        super().__init__(parent)
        self.setWindowTitle('Button assignment')
        form = QFormLayout(self)
        self.action = combo(list(ACTIONS) + ['Keystroke', 'DPI lock', 'Macro', 'Preserve current'])
        self.shortcut = QLineEdit('CTRL+C')
        self.dpi = combo(DPI_VALUES)
        self.macro = combo(macros)
        self.mode = QComboBox()
        for label, value in [('Repeat count', 'repeat'), ('Until button released', 'hold'),
                             ('Until a button is pressed', 'toggle')]:
            self.mode.addItem(label, value)
        self.repeats = QSpinBox()
        self.repeats.setRange(1, 255)
        self.repeats.setValue(1)
        self.code = code
        self.macros = macros
        label = button_label(code)
        if label in ACTIONS:
            select_value(self.action, label)
        elif label.startswith('key:'):
            select_value(self.action, 'Keystroke')
            self.shortcut.setText(label[4:])
        elif code & 255 == 0x42 and 1 <= (code >> 8) <= len(DPI_VALUES):
            select_value(self.action, 'DPI lock')
            select_value(self.dpi, DPI_VALUES[(code >> 8)-1])
        else:
            select_value(self.action, 'Preserve current')
        for label, widget in [('Function', self.action), ('Keys (e.g. CTRL+C)', self.shortcut),
                              ('Lock DPI', self.dpi), ('Macro', self.macro),
                              ('Playback', self.mode), ('Repeat count', self.repeats)]:
            form.addRow(label, widget)
        self.error = QLabel()
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.action.currentIndexChanged.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        action = self.action.currentData()
        self.shortcut.setEnabled(action == 'Keystroke')
        self.dpi.setEnabled(action == 'DPI lock')
        for widget in (self.macro, self.mode, self.repeats):
            widget.setEnabled(action == 'Macro')

    def validate(self):
        try:
            self.result_code()
        except (ValueError, KeyError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def result_code(self):
        action = self.action.currentData()
        if action == 'Preserve current':
            return self.code, None
        if action == 'Keystroke':
            return button_code('key:' + self.shortcut.text()), None
        if action == 'DPI lock':
            return 0x42 | ((DPI_VALUES.index(self.dpi.currentData()) + 1) << 8), None
        if action == 'Macro':
            name = self.macro.currentData()
            if name is None:
                raise ValueError('Create a macro in Macro Editor first')
            parse_macro(self.macros[name])
            return macro_button(1, self.mode.currentData(), self.repeats.value()) & 0xffff00ff, name
        return button_code(action), None


class Recorder(QPlainTextEdit):
    """Focused recording works on both Wayland and X11; no global input hook."""
    recorded = Signal(str)
    timing = Signal(int)

    def __init__(self):
        super().__init__('Click here, then type to record. F12 stops recording.')
        self.setReadOnly(True)
        self.recording = False
        self.last = 0
        self.held = set()

    def begin(self):
        self.recording = True
        self.held.clear()
        self.last = time.monotonic()
        self.setFocus()

    def end(self):
        for key in sorted(self.held):
            self.recorded.emit(f'up {key} 1')
        self.held.clear()
        self.recording = False

    def keyPressEvent(self, event):
        if self.recording and event.key() == Qt.Key.Key_F12:
            self.end()
            return
        self.record(event, 'down')

    def keyReleaseEvent(self, event):
        self.record(event, 'up')

    def record(self, event, kind):
        if not self.recording or event.isAutoRepeat():
            return
        special = {Qt.Key.Key_Return: 'ENTER', Qt.Key.Key_Enter: 'ENTER',
                   Qt.Key.Key_Escape: 'ESC', Qt.Key.Key_Backspace: 'BACKSPACE',
                   Qt.Key.Key_Tab: 'TAB', Qt.Key.Key_Space: 'SPACE',
                   Qt.Key.Key_Control: 'CTRL', Qt.Key.Key_Shift: 'SHIFT',
                   Qt.Key.Key_Alt: 'ALT', Qt.Key.Key_Meta: 'SUPER'}
        key = special.get(event.key())
        if key is None:
            from PySide6.QtGui import QKeySequence
            key = QKeySequence(event.key()).toString().upper()
        if key not in KEYS and key not in ('CTRL', 'SHIFT', 'ALT', 'SUPER'):
            return
        if kind == 'up' and key not in self.held:
            return
        if kind == 'down':
            self.held.add(key)
        else:
            self.held.discard(key)
        now = time.monotonic()
        self.timing.emit(min(4095, max(1, round((now-self.last)*1000))))
        self.recorded.emit(f'{kind} {key} 1')
        self.last = now

    def focusOutEvent(self, event):
        if self.recording:
            self.end()
        super().focusOutEvent(event)


class MacroDialog(QDialog):
    def __init__(self, macros, parent):
        super().__init__(parent)
        self.setWindowTitle('Macro Editor')
        self.resize(770, 570)
        self.macros = dict(macros)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.names = combo(self.macros)
        row.addWidget(self.names, 1)
        for label, action in [('New', self.new), ('Delete', self.delete),
                              ('Import', self.import_file), ('Export', self.export_file)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText('down CTRL 20\ndown C 20\nup C 20\nup CTRL 20')
        layout.addWidget(self.editor, 1)
        help_text = QLabel('One event per line: EVENT KEY_OR_VALUE DELAY_MS\n'
                           'down / up · mouse-down / mouse-up · move-x / move-y · wheel\n'
                           'Keys: A–Z, 0–9, F1–F12, CTRL, SHIFT, ALT, SUPER; delays: 1–4095 ms.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.recorder = Recorder()
        self.recorder.setMaximumHeight(64)
        layout.addWidget(self.recorder)
        recording = QHBoxLayout()
        start = QPushButton('Start record')
        stop = QPushButton('Stop record')
        start.clicked.connect(self.recorder.begin)
        stop.clicked.connect(self.recorder.end)
        self.recorder.recorded.connect(self.append_event)
        self.recorder.timing.connect(self.record_delay)
        recording.addWidget(start)
        recording.addWidget(stop)
        layout.addLayout(recording)
        self.message = QLabel()
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.last_name = None
        self.names.currentIndexChanged.connect(self.load_name)
        self.load_name()

    def load_name(self):
        if self.last_name:
            self.macros[self.last_name] = self.editor.toPlainText()
        self.last_name = self.names.currentData()
        self.editor.setPlainText(self.macros.get(self.last_name, ''))

    def new(self):
        name, ok = QInputDialog.getText(self, 'New macro', 'Macro name')
        if ok and name.strip():
            name = name.strip()
            if name in self.macros:
                self.message.setText('That macro name already exists')
                return
            self.macros[name] = 'down A 20\nup A 20'
            self.names.addItem(name, name)
            self.names.setCurrentIndex(self.names.count()-1)

    def delete(self):
        name = self.names.currentData()
        if name:
            self.last_name = None
            del self.macros[name]
            self.names.removeItem(self.names.currentIndex())
            self.load_name()

    def append_event(self, line):
        lines = self.editor.toPlainText().splitlines()
        if len(lines) >= 168:
            self.recorder.recording = False
            self.message.setText('Maximum 168 events reached; finish key releases before saving')
            return
        self.editor.appendPlainText(line)

    def record_delay(self, delay):
        lines = self.editor.toPlainText().splitlines()
        if lines:
            words = lines[-1].split()
            if len(words) == 3:
                lines[-1] = ' '.join(words[:2] + [str(delay)])
                self.editor.setPlainText('\n'.join(lines))

    def save(self):
        self.recorder.end()
        if self.last_name:
            self.macros[self.last_name] = self.editor.toPlainText()
        try:
            for text in self.macros.values():
                parse_macro(text)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self.accept()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import macro', filter='Macro text (*.txt);;All files (*)')
        if not path:
            return
        try:
            text = Path(path).read_text()
            parse_macro(text)
            name = Path(path).stem
            if name in self.macros:
                raise ValueError('A macro with that name already exists')
            self.macros[name] = text
            self.names.addItem(name, name)
            self.names.setCurrentIndex(self.names.count()-1)
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc))

    def export_file(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export macro', filter='Macro text (*.txt)')
        if path:
            try:
                parse_macro(self.editor.toPlainText())
                Path(path).write_text(self.editor.toPlainText() + '\n')
            except (OSError, ValueError) as exc:
                self.message.setText(str(exc))

    def reject(self):
        self.recorder.recording = False
        super().reject()


class Window(QMainWindow):
    def __init__(self, controller, skin_dir=None, config_dir=None):
        super().__init__()
        self.controller = controller
        self.setWindowTitle('TECKNET GM2793-1 — Native Linux' + (' — Demo' if controller.demo else ''))
        self.resize(1060, 720)
        self.task = None
        self.needs_reconnect = False
        self.originals, self.edits, self.matrices, self.original_matrices = {}, {}, {}, {}
        self.macros, self.assignments, self.dirty_matrices = {}, {n: {} for n in (1, 2, 3)}, set()
        self.number = controller.active
        self.loading = False
        self.dpi_error = None
        self.config_dir = config_dir or Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config')) / 'tecknet-gm2793'
        self.library_path = self.config_dir / ('demo-library.json' if controller.demo else 'library.json')
        self.presets = {}
        self.applied_bindings = {}
        self.load_library()
        root = Canvas(skin_dir)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(26, 20, 26, 20)
        top = QHBoxLayout()
        self.mode = combo(['Mode 1', 'Mode 2', 'Mode 3'])
        self.mode.setCurrentIndex(self.number-1)
        self.mode.currentIndexChanged.connect(self.change_mode)
        top.addWidget(self.mode)
        top.addStretch()
        self.status = QLabel('Loading mouse settings…')
        self.status.setObjectName('status')
        top.addWidget(self.status)
        layout.addLayout(top)
        body = QHBoxLayout()
        left = QVBoxLayout()
        buttons = QGroupBox('Button assignment')
        button_layout = QVBoxLayout(buttons)
        self.binding_buttons = []
        labels = ('Left Button', 'Right Button', 'Middle Button', 'Forward', 'Back',
                  'DPI +', 'DPI −', 'Three Click', 'Switch Effect', 'DPI Lock')
        for i, label in enumerate(labels):
            row = QHBoxLayout()
            number = QLabel(str(i+1))
            number.setStyleSheet('color: #00b6da; border: 1px solid #009ac0; border-radius: 10px;')
            number.setFixedSize(23, 23)
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            button = QPushButton(label)
            slot = MouseDiagram.matrix_slots[i]
            button.clicked.connect(lambda checked=False, slot=slot: self.edit_binding(slot))
            self.binding_buttons.append((slot, button))
            row.addWidget(number)
            row.addWidget(button, 1)
            button_layout.addLayout(row)
        advanced = QPushButton('All 20 matrix entries…')
        advanced.clicked.connect(self.advanced_bindings)
        button_layout.addWidget(advanced)
        left.addWidget(buttons)
        macro = QPushButton('Macro Editor')
        macro.clicked.connect(self.edit_macros)
        left.addWidget(macro)
        left.addStretch()
        body.addLayout(left, 3)
        middle = QVBoxLayout()
        self.diagram = MouseDiagram(skin_dir)
        self.diagram.selected.connect(self.edit_binding)
        middle.addWidget(self.diagram, 1)
        brand = QLabel('TECKNET')
        brand.setObjectName('brand')
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        middle.addWidget(brand)
        body.addLayout(middle, 4)
        self.panels = QToolBox()
        self.panels.setMinimumWidth(350)
        self.panels.addItem(self.dpi_panel(), 'DPI Setting')
        self.panels.addItem(self.lighting_panel(), 'Lighting')
        self.panels.addItem(self.desktop_panel(), 'Mouse Parameter')
        self.panels.addItem(self.polling_panel(), 'Polling Rate')
        body.addWidget(self.panels, 4)
        layout.addLayout(body, 1)
        bottom = QHBoxLayout()
        self.preset = combo(self.presets)
        self.preset.setMinimumWidth(130)
        bottom.addWidget(QLabel('Profile'))
        bottom.addWidget(self.preset)
        for label, action in [('Save', self.save_preset), ('Load', self.load_preset),
                              ('Delete', self.delete_preset), ('Import', self.import_file),
                              ('Export', self.export_file)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            bottom.addWidget(button)
        layout.addLayout(bottom)
        footer = QHBoxLayout()
        footer.addWidget(QLabel('Native Linux · GM2793-1 · 258a:1007'))
        footer.addStretch()
        for label, action in [('Reload', self.reload), ('Restore', self.restore), ('Apply', self.apply)]:
            button = QPushButton(label)
            if label == 'Apply':
                button.setObjectName('apply')
            button.clicked.connect(action)
            footer.addWidget(button)
        layout.addLayout(footer)
        root.setEnabled(False)
        self.reload()

    def dpi_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.xy = QCheckBox('XY Independent')
        self.xy.toggled.connect(self.dpi_changed)
        layout.addWidget(self.xy)
        self.dpi_table = QTableWidget(8, 5)
        self.dpi_table.setHorizontalHeaderLabels(['On', 'X', 'Y', 'Color', 'Use'])
        self.dpi_table.verticalHeader().setVisible(False)
        self.dpi_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.dpi_table.setMinimumHeight(300)
        self.dpi_rows = []
        self.active_group = QButtonGroup(self)
        for i in range(8):
            enabled = QCheckBox()
            x, y = combo(DPI_VALUES), combo(DPI_VALUES)
            color = ColorButton(compact=True)
            active = QRadioButton(str(i+1))
            self.active_group.addButton(active, i)
            for j, widget in enumerate((enabled, x, y, color, active)):
                self.dpi_table.setCellWidget(i, j, widget)
            enabled.toggled.connect(self.dpi_changed)
            x.currentIndexChanged.connect(self.dpi_changed)
            y.currentIndexChanged.connect(self.dpi_changed)
            color.changed.connect(self.dpi_changed)
            active.toggled.connect(self.dpi_changed)
            self.dpi_rows.append((enabled, x, y, color, active))
        layout.addWidget(self.dpi_table)
        layout.addStretch()
        return panel

    def lighting_panel(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.effect = combo(EFFECTS)
        self.speed = combo([1, 2, 3])
        self.brightness = combo([1, 2, 3, 4])
        self.light_colors = [ColorButton('#00aacc') for _ in range(8)]
        self.direction = combo(['Left', 'Right'])
        form.addRow('Effect', self.effect)
        form.addRow('Speed', self.speed)
        form.addRow('Brightness', self.brightness)
        form.addRow('Direction', self.direction)
        for i, color in enumerate(self.light_colors):
            form.addRow(f'Color {i+1}', color)
            color.changed.connect(self.lighting_changed)
        for widget in (self.effect, self.speed, self.brightness, self.direction):
            widget.currentIndexChanged.connect(self.lighting_changed)
        return panel

    def polling_panel(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.polling = combo(POLLING)
        self.polling.currentIndexChanged.connect(self.polling_changed)
        form.addRow('USB Polling Rate (Hz)', self.polling)
        return panel

    def desktop_panel(self):
        from .desktop import DesktopSettings
        self.desktop = DesktopSettings(self.controller.demo)
        panel = QWidget()
        form = QFormLayout(panel)
        self.desktop_notice = QLabel('These settings apply to your Linux desktop.')
        self.desktop_notice.setWordWrap(True)
        form.addRow(self.desktop_notice)
        self.pointer_speed = QSlider(Qt.Orientation.Horizontal)
        self.pointer_speed.setRange(-100, 100)
        self.acceleration = combo(['default', 'flat', 'adaptive'])
        self.left_handed = QCheckBox('Left hand')
        self.double_click = QSpinBox()
        self.double_click.setRange(100, 1000)
        self.double_click.setSuffix(' ms')
        self.natural_scroll = QCheckBox('Natural scrolling')
        for label, widget in [('Mouse Sensitivity', self.pointer_speed),
                              ('Pointer acceleration', self.acceleration),
                              ('Button order', self.left_handed),
                              ('Double-click interval', self.double_click),
                              ('Scrolling', self.natural_scroll)]:
            form.addRow(label, widget)
        apply = QPushButton('Apply desktop settings')
        apply.clicked.connect(self.apply_desktop)
        form.addRow(apply)
        try:
            settings = self.desktop.read()
            self.pointer_speed.setValue(round(settings['speed'] * 100))
            select_value(self.acceleration, settings['accel-profile'])
            self.left_handed.setChecked(settings['left-handed'])
            self.double_click.setValue(settings['double-click'])
            self.natural_scroll.setChecked(settings['natural-scroll'])
        except (RuntimeError, OSError, ValueError) as exc:
            self.desktop_notice.setText(str(exc))
            for widget in (self.pointer_speed, self.acceleration, self.left_handed,
                           self.double_click, self.natural_scroll, apply):
                widget.setEnabled(False)
        return panel

    def apply_desktop(self):
        try:
            self.desktop.write({'speed': self.pointer_speed.value()/100,
                                'accel-profile': self.acceleration.currentData(),
                                'left-handed': self.left_handed.isChecked(),
                                'double-click': self.double_click.value(),
                                'natural-scroll': self.natural_scroll.isChecked()})
            self.status.setText('Desktop settings applied' + (' in demo' if self.controller.demo else ''))
        except (RuntimeError, OSError, ValueError) as exc:
            self.error(str(exc))

    def start_task(self, operation, callback):
        if self.task and self.task.isRunning():
            return
        self.centralWidget().setEnabled(False)
        self.task = Task(operation, self)
        self.task.result.connect(callback)
        self.task.failed.connect(self.error)
        self.task.finished.connect(lambda: self.centralWidget().setEnabled(bool(self.edits)))
        self.task.start()

    def error(self, message):
        self.needs_reconnect = True
        self.status.setText('Operation failed — reload after reconnecting')
        QMessageBox.warning(self, 'TeckNet configuration', message)

    def reload(self):
        self.status.setText('Reading mouse settings…')
        def read():
            if self.needs_reconnect:
                self.controller.reconnect()
            profiles = {n: self.controller.load(n) for n in (1, 2, 3)}
            matrices = {n: self.controller.load_buttons(n) for n in (1, 2, 3)}
            return profiles, matrices
        self.start_task(read, self.loaded)

    def loaded(self, result):
        self.needs_reconnect = False
        profiles, matrices = result
        self.originals = profiles
        self.edits = {n: p.copy() for n, p in profiles.items()}
        self.original_matrices = copy.deepcopy(matrices)
        self.matrices = matrices
        self.assignments = {n: {} for n in (1, 2, 3)}
        for n in (1, 2, 3):
            for slot, saved in self.applied_bindings.get(str(n), {}).items():
                index = int(slot)
                if 0 <= index < 20 and matrices[n][index] == saved.get('code') and saved.get('name') in self.macros:
                    self.assignments[n][index] = saved['name']
        self.dirty_matrices.clear()
        self.display()
        self.status.setText('Demo · simulated device' if self.controller.demo else 'Connected · settings loaded')

    def display(self):
        self.loading = True
        self.dpi_error = None
        profile = self.edits[self.number]
        self.xy.setChecked(profile.separate_xy)
        for row, slot in zip(self.dpi_rows, profile.dpi_slots()):
            enabled, x, y, color, active = row
            enabled.setChecked(slot['enabled'])
            select_value(x, slot['x'])
            select_value(y, slot['y'])
            y.setEnabled(profile.separate_xy)
            color.set_color(slot['color'])
        active = profile.active_slot
        if active is not None:
            self.dpi_rows[active][4].setChecked(True)
        select_value(self.polling, profile.polling)
        light = profile.lighting()
        select_value(self.effect, EFFECTS[light['effect']] if light['effect'] < len(EFFECTS) else light['effect'])
        select_value(self.speed, light['speed'])
        select_value(self.brightness, light['brightness'])
        select_value(self.direction, 'Right' if light.get('direction', 0) else 'Left')
        colors = light.get('colors', [light['color']])
        for i, button in enumerate(self.light_colors):
            button.set_color(colors[min(i, len(colors)-1)])
        self.show_bindings()
        self.loading = False
        self.update_lighting_fields()

    def show_bindings(self):
        for slot, button in self.binding_buttons:
            name = self.assignments[self.number].get(slot)
            label = f'Macro: {name}' if name else button_label(self.matrices[self.number][slot])
            button.setText(label)
            button.setToolTip(label)

    def change_mode(self, index):
        if not self.loading and self.edits:
            self.number = index + 1
            self.display()
            self.status.setText(f'Editing Mode {self.number} · Apply activates it')

    def dpi_changed(self, *args):
        if self.loading or not self.edits:
            return
        slots = []
        for enabled, x, y, color, active in self.dpi_rows:
            y.setEnabled(self.xy.isChecked())
            slots.append({'enabled': enabled.isChecked(), 'x': x.currentData(),
                          'y': y.currentData(), 'color': color.color})
        try:
            self.edits[self.number].set_dpi(slots, self.xy.isChecked(), self.active_group.checkedId())
            self.dpi_error = None
            self.status.setText('DPI changes staged · Apply to save')
        except ValueError as exc:
            self.dpi_error = str(exc)
            self.status.setText(str(exc))

    def update_lighting_fields(self):
        effect = self.effect.currentIndex()
        count = {2: 1, 3: 7, 6: 8, 7: 2}.get(effect, 0)
        self.direction.setEnabled(effect == 1)
        self.speed.setEnabled(effect not in (0, 2, 6))
        self.brightness.setEnabled(effect not in (0, 10, 11))
        for i, button in enumerate(self.light_colors):
            button.setEnabled(i < count)

    def lighting_changed(self, *args):
        if self.loading or not self.edits:
            return
        effect = self.effect.currentIndex()
        if effect >= len(EFFECTS):
            return
        try:
            self.edits[self.number].set_lighting(effect, self.speed.currentData(),
                self.brightness.currentData(), self.light_colors[0].color,
                colors=[c.color for c in self.light_colors], direction=self.direction.currentIndex())
            self.status.setText('Lighting changes staged · Apply to save')
        except ValueError as exc:
            self.status.setText(str(exc))
        self.update_lighting_fields()

    def polling_changed(self, *args):
        if not self.loading and self.edits:
            try:
                self.edits[self.number].set_polling(self.polling.currentData())
                self.status.setText('Polling changes staged · Apply to save')
            except ValueError as exc:
                self.status.setText(str(exc))

    def edit_binding(self, slot):
        if not self.edits:
            return
        dialog = BindingDialog(self.matrices[self.number][slot], self.macros, self)
        if dialog.exec():
            code, name = dialog.result_code()
            self.matrices[self.number][slot] = code
            if name:
                self.assignments[self.number][slot] = name
            else:
                self.assignments[self.number].pop(slot, None)
            self.dirty_matrices.add(self.number)
            self.show_bindings()
            self.status.setText('Button assignment staged · Apply to save')

    def advanced_bindings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Hardware button matrix')
        dialog.resize(420, 600)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        form = QFormLayout(panel)
        for slot, code in enumerate(self.matrices[self.number]):
            button = QPushButton(button_label(code))
            def edit(checked=False, slot=slot, button=button):
                self.edit_binding(slot)
                button.setText(button_label(self.matrices[self.number][slot]))
            button.clicked.connect(edit)
            form.addRow(f'Entry {slot+1}', button)
        scroll.setWidget(panel)
        layout.addWidget(scroll)
        dialog.exec()

    def edit_macros(self):
        dialog = MacroDialog(self.macros, self)
        if dialog.exec():
            removed = set(self.macros) - set(dialog.macros)
            if any(name in removed for mapping in self.assignments.values() for name in mapping.values()):
                self.error('Unassign a macro from staged buttons before deleting it')
                return
            self.macros = dialog.macros
            self.save_library()
            self.status.setText('Macro library saved · assign a macro to a button to upload it')

    def apply(self):
        if self.dpi_error:
            self.error(self.dpi_error)
            return
        n = self.number
        original, edited = self.originals[n].copy(), self.edits[n].copy()
        matrices = copy.deepcopy(self.matrices)
        mapping = dict(self.assignments[n])
        dirty = n in self.dirty_matrices or bool(mapping)
        self.status.setText('Applying settings…')
        def write():
            # Allocate against fresh hardware matrices, including other modes.
            fresh = {p: self.controller.load_buttons(p) for p in (1, 2, 3)}
            if dirty and fresh[n] != self.original_matrices[n]:
                raise ValueError('Button assignments changed since loading; reload before applying')
            buttons, macros = self.controller.allocate_macros(n, matrices[n], mapping, self.macros, fresh)
            actual = self.controller.apply(n, original, edited, buttons if dirty else None, macros,
                                           original_buttons=self.original_matrices[n] if dirty else None)
            self.controller.select(n)
            return actual, buttons
        self.start_task(write, lambda result: self.applied(n, result))

    def applied(self, number, result):
        profile, buttons = result
        self.originals[number] = profile
        self.edits[number] = profile.copy()
        self.original_matrices[number] = list(buttons)
        self.matrices[number] = list(buttons)
        self.dirty_matrices.discard(number)
        self.applied_bindings[str(number)] = {str(slot): {'name': name, 'code': buttons[slot]}
            for slot, name in self.assignments[number].items()}
        self.save_library()
        self.display()
        self.status.setText(f'Mode {number} applied · readback verified' + (' · demo' if self.controller.demo else ''))

    def restore(self):
        n = self.number
        profile = self.edits[n]
        profile.set_polling(500)
        slots = profile.dpi_slots()
        values = [500, 1000, 2000, 3000, 4000, 250, 250, 250]
        colors = ['#ff0000', '#0000ff', '#00ff00', '#ff00ff', '#ffff00', '#00ffff', '#ffffff', '#ff8000']
        for i, slot in enumerate(slots):
            slot.update(enabled=i < 5, x=values[i], y=values[i], color=colors[i])
        profile.set_dpi(slots, False, 0)
        profile.set_lighting(1, 2, 4, '#00aacc')
        self.matrices[n] = list(DEFAULT_BUTTONS)
        self.assignments[n] = {}
        self.dirty_matrices.add(n)
        self.display()
        self.status.setText('Defaults staged · Apply to save')

    def snapshot(self):
        return {'format': 'tecknet-gm2793-native', 'version': 1,
                'report': bytes(self.edits[self.number].report).hex(),
                'buttons': self.matrices[self.number],
                'assignments': {str(k): v for k, v in self.assignments[self.number].items()},
                'library': self.macros}

    def stage_snapshot(self, data):
        profile, matrix, assignments, macros = decode_native_profile(data)
        self.edits[self.number] = profile
        self.matrices[self.number] = list(matrix)
        self.assignments[self.number] = assignments
        self.macros.update(macros)
        self.dirty_matrices.add(self.number)
        self.display()

    def load_library(self):
        if self.library_path.exists():
            try:
                data = json.loads(self.library_path.read_text())
                if not isinstance(data, dict):
                    raise ValueError('Invalid library')
                self.macros = data.get('macros', {})
                self.presets = data.get('presets', {})
                self.applied_bindings = data.get('applied_bindings', {})
                if not all(isinstance(value, dict) for value in (self.macros, self.presets, self.applied_bindings)):
                    raise ValueError('Invalid library fields')
                for mapping in self.applied_bindings.values():
                    if not isinstance(mapping, dict):
                        raise ValueError('Invalid saved bindings')
                    for slot, saved in mapping.items():
                        if not isinstance(saved, dict) or not 0 <= int(slot) < 20 or not isinstance(saved.get('code'), int):
                            raise ValueError('Invalid saved binding')
                for text in self.macros.values():
                    parse_macro(text)
            except (ValueError, TypeError, AttributeError, OSError):
                self.macros, self.presets, self.applied_bindings = {}, {}, {}

    def save_library(self):
        try:
            save_json(self.library_path, {'macros': self.macros, 'presets': self.presets,
                                         'applied_bindings': self.applied_bindings})
        except OSError as exc:
            self.error(str(exc))

    def save_preset(self):
        name, ok = QInputDialog.getText(self, 'Save profile', 'Profile name')
        if ok and name.strip():
            name = name.strip()
            self.presets[name] = copy.deepcopy(self.snapshot())
            self.save_library()
            if self.preset.findData(name) < 0:
                self.preset.addItem(name, name)
            select_value(self.preset, name)

    def load_preset(self):
        name = self.preset.currentData()
        if name:
            try:
                self.stage_snapshot(copy.deepcopy(self.presets[name]))
                self.status.setText('Profile loaded · Apply to save to the mouse')
            except (ValueError, KeyError, TypeError) as exc:
                self.error(str(exc))

    def delete_preset(self):
        name = self.preset.currentData()
        if name:
            del self.presets[name]
            self.preset.removeItem(self.preset.currentIndex())
            self.save_library()

    def export_file(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export profile', filter='Native profiles (*.json)')
        if path:
            try:
                data = self.snapshot()
                data.update(format='tecknet-gm2793-native', version=1)
                save_json(path, data)
                self.status.setText('Profile exported')
            except (OSError, ValueError) as exc:
                self.error(str(exc))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import profile', filter='Native profiles (*.json);;Raw profiles (*.bin)')
        if not path:
            return
        try:
            if Path(path).suffix.lower() == '.bin':
                from .protocol import Profile
                self.edits[self.number] = Profile(Path(path).read_bytes())
                self.display()
            else:
                data = json.loads(Path(path).read_text())
                if data.get('format') == 'tecknet-gm2793-native' and data.get('version') == 1:
                    self.stage_snapshot(data)
                else:
                    _, profile, matrix, macros = import_profile(path)
                    if macros:
                        raise ValueError('Import a native profile with named macros to allocate buffers safely')
                    self.edits[self.number] = profile
                    if matrix is not None:
                        self.matrices[self.number] = matrix
                        self.dirty_matrices.add(self.number)
                    self.display()
            self.status.setText('Profile imported · Apply to save')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.error(str(exc))

    def closeEvent(self, event):
        if self.task and self.task.isRunning():
            self.status.setText('Waiting for the current mouse operation before closing')
            event.ignore()
            return
        event.accept()


def run(controller, skin_dir=None):
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = Window(controller, skin_dir)
    window.show()
    return app.exec()

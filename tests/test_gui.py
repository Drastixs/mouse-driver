"""End-to-end native desktop tests using real Qt widgets and simulated HID."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication, QDialog
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from tecknet.gui import Window, STYLE, MacroDialog, BindingDialog
except ImportError:
    QApplication = None

from tecknet.controller import Controller
from tecknet.hid import SimulatedDevice
from tecknet.protocol import Profile, macro_button, matrix_report, button_code


@unittest.skipUnless(QApplication and (os.environ.get('DISPLAY') or os.environ.get('QT_QPA_PLATFORM') == 'offscreen'),
                     'Requires PySide6 and a display or QT_QPA_PLATFORM=offscreen')
class QtDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.device = SimulatedDevice()
        self.controller = Controller(self.device, True)
        self.window = Window(self.controller, config_dir=Path(self.folder.name))
        self.window.show()
        self.wait()

    def wait(self):
        end = time.monotonic() + 5
        while self.window.task and self.window.task.isRunning() and time.monotonic() < end:
            self.app.processEvents()
            QTest.qWait(5)
        self.app.processEvents()
        self.assertFalse(self.window.task and self.window.task.isRunning(), 'HID worker did not finish')

    def tearDown(self):
        self.wait()
        self.window.close()
        self.app.processEvents()
        self.folder.cleanup()

    def test_polling_changes_through_widget_preserve_buttons(self):
        self.window.polling.setCurrentIndex(3)
        with patch.object(self.window, 'error') as error:
            self.window.apply()
            self.wait()
            error.assert_not_called()
        self.assertEqual(self.controller.load(1).polling, 1000)
        self.assertEqual(self.device.matrices, {})
        writes = [data for get, data in self.device.transfers if not get and data[0] == 4]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][10], 4)

    def test_xy_dpi_lighting_and_mode_apply(self):
        self.window.mode.setCurrentIndex(1)
        self.window.xy.setChecked(True)
        self.window.dpi_rows[0][1].setCurrentText('1200')
        self.window.dpi_rows[0][2].setCurrentText('2400')
        self.window.effect.setCurrentIndex(3)
        self.window.light_colors[0].set_color('#123456')
        self.window.light_colors[1].set_color('#abcdef')
        self.window.lighting_changed()
        with patch.object(self.window, 'error') as error:
            self.window.apply()
            self.wait()
            error.assert_not_called()
        profile = self.controller.load(2)
        self.assertEqual(profile.dpi_slots()[0]['x'], 1200)
        self.assertEqual(profile.dpi_slots()[0]['y'], 2400)
        self.assertEqual(profile.lighting()['colors'][:2], ['#123456', '#abcdef'])
        self.assertEqual(self.controller.active, 2)

    def test_invalid_disabled_active_stage_never_writes(self):
        self.window.dpi_rows[0][0].setChecked(False)
        self.device.transfers.clear()
        with patch.object(self.window, 'error') as error:
            self.window.apply()
            error.assert_called_once()
        self.assertFalse(self.device.transfers)

    def test_named_macros_allocate_around_other_modes_and_roundtrip(self):
        matrix = self.controller.load_buttons(3)
        matrix[5] = macro_button(1)
        self.device.matrices[3] = matrix_report(3, matrix)
        self.window.macros['Copy'] = 'down CTRL 10\ndown C 20\nup C 20\nup CTRL 10'
        self.window.matrices[1][5] = macro_button(1, 'hold') & 0xffff00ff
        self.window.assignments[1][5] = 'Copy'
        self.window.dirty_matrices.add(1)
        snapshot = copy.deepcopy(self.window.snapshot())
        self.window.stage_snapshot(json.loads(json.dumps(snapshot)))
        with patch.object(self.window, 'error') as error:
            self.window.apply()
            self.wait()
            error.assert_not_called()
        self.assertIn(2, self.device.macros)
        self.assertNotIn(1, self.device.macros)
        actual = self.controller.load_buttons(1)[5]
        self.assertEqual(actual, macro_button(2, 'hold'))
        self.assertEqual(self.controller.load_buttons(3), matrix)

    def test_binding_dialog_generates_independent_keyboard_code(self):
        dialog = BindingDialog(0x111, {}, self.window)
        dialog.action.setCurrentText('Keystroke')
        dialog.shortcut.setText('CTRL+C')
        dialog.validate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_code(), (0x00060121, None))

    def test_macro_editor_focused_recording(self):
        dialog = MacroDialog({'Recorded': 'down A 20\nup A 20'}, self.window)
        dialog.editor.clear()
        dialog.show()
        self.app.processEvents()
        dialog.recorder.begin()
        QTest.keyPress(dialog.recorder, Qt.Key.Key_C)
        QTest.qWait(10)
        QTest.keyRelease(dialog.recorder, Qt.Key.Key_C)
        dialog.recorder.end()
        text = dialog.editor.toPlainText()
        self.assertIn('down C ', text)
        self.assertIn('up C ', text)
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_desktop_demo_does_not_launch_processes(self):
        with patch('tecknet.desktop.subprocess.run') as run:
            self.window.pointer_speed.setValue(50)
            self.window.apply_desktop()
            self.assertEqual(self.window.desktop.read()['speed'], .5)
            run.assert_not_called()


class CorrectedWireTests(unittest.TestCase):
    def test_variant_specific_actions_and_lighting_offsets(self):
        self.assertEqual(button_code('Scroll up'), 0x112)
        self.assertEqual(button_code('Mode cycle'), 0x650)
        self.assertEqual(button_code('Lighting on/off'), 0x850)
        device = SimulatedDevice()
        profile = Profile(device.read_profile(1))
        baseline = bytes(profile.report)
        profile.set_lighting(7, 3, 4, '#123456', colors=['#123456', '#abcdef'])
        self.assertEqual(profile.report[8+0x66], 0x43)
        self.assertEqual(profile.report[8+0x67:8+0x6d], bytes.fromhex('123456abcdef'))
        self.assertEqual(profile.report[8+0x6d:8+0x7b], baseline[8+0x6d:8+0x7b])

    def test_macro_cannot_overwrite_other_mode_buffer(self):
        device = SimulatedDevice()
        controller = Controller(device, True)
        matrix = controller.load_buttons(2)
        matrix[5] = macro_button(1)
        device.matrices[2] = matrix_report(2, matrix)
        original = controller.load(1)
        device.transfers.clear()
        with self.assertRaisesRegex(ValueError, 'another mode'):
            controller.apply(1, original, original.copy(), macros={'1': 'down A 20\nup A 20'})
        self.assertFalse(any(data[0] == 4 for get, data in device.transfers if not get))


if __name__ == '__main__':
    unittest.main()

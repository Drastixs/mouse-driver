import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tecknet.__main__ import main
from tecknet.hid import SimulatedDevice


class CliTests(unittest.TestCase):
    def test_gui_native_export_imports_through_cli_with_safe_macro_allocation(self):
        from tecknet.controller import Controller, save_json
        from tecknet.protocol import macro_button, matrix_report
        device = SimulatedDevice()
        controller = Controller(device, True)
        matrix = controller.load_buttons(2)
        matrix[5] = macro_button(1)
        device.matrices[2] = matrix_report(2, matrix)
        exported = controller.load_buttons(1)
        exported[5] = macro_button(1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native.json'
            save_json(path, {'format': 'tecknet-gm2793-native', 'version': 1,
                'report': bytes(controller.load(1).report).hex(), 'buttons': exported,
                'assignments': {'5': 'Test'}, 'library': {'Test': 'down A 20\nup A 20'}})
            with patch('tecknet.__main__.SimulatedDevice', return_value=device), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--demo', 'import', '1', str(path)]), 0)
        self.assertIn(2, device.macros)
        self.assertNotIn(1, device.macros)
        self.assertEqual(controller.load_buttons(2), matrix)

    def test_native_configuration_commands_without_process_launch(self):
        # Reuse one simulated physical device so independent CLI invocations
        # exercise persistent transport state without external processes.
        device = SimulatedDevice()
        with patch('tecknet.__main__.SimulatedDevice', return_value=device), \
             patch('subprocess.Popen', side_effect=AssertionError('No external application should launch')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--demo', 'set', '1', '--polling', '1000', '--dpi', '500', '8000']), 0)
            self.assertEqual(device.read_profile(1)[10] & 15, 4)
            self.assertEqual(main(['--demo', 'select', '2']), 0)
            self.assertEqual(device.active, 2)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'profile.json'
                self.assertEqual(main(['--demo', 'export', '1', str(path)]), 0)
                self.assertEqual(main(['--demo', 'import', '2', str(path)]), 0)
                self.assertEqual(device.read_profile(2)[10] & 15, 4)

    def test_example_macro_upload_with_explicit_matrix(self):
        root = Path(__file__).resolve().parents[1]
        device = SimulatedDevice()
        with patch('tecknet.__main__.SimulatedDevice', return_value=device), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--demo', 'macro', '1', '1', str(root / 'examples/macro.txt'),
                                   '--button', '6', '--matrix', str(root / 'examples/buttons.json')]), 0)
        self.assertIn(1, device.macros)
        self.assertEqual(device.matrices[1][8 + 5*4:12 + 5*4], bytes.fromhex('70 01 01 01'))

    def test_cli_rejects_more_than_eight_dpi_values(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            main(['--demo', 'set', '1', '--dpi'] + ['500'] * 9)
        self.assertEqual(result.exception.code, 1)


if __name__ == '__main__':
    unittest.main()

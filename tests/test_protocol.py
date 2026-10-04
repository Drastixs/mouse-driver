import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tecknet.controller import Controller, import_profile
from tecknet.hid import SimulatedDevice
from tecknet.protocol import (DEFAULT_BUTTONS, DPI_VALUES, MacroEvent, Profile,
                              button_code, button_label, macro_button, macro_report,
                              matrix_report, parse_macro)

FIXTURE = Path(__file__).resolve().parents[1] / 'docs/validation/vendor-demo-transfers.json'


class NativeEncodingTests(unittest.TestCase):
    def setUp(self):
        self.device = SimulatedDevice()
        self.controller = Controller(self.device, True)

    def test_vendor_general_write_reproduced_byte_for_byte(self):
        writes = [bytes.fromhex(t['request']) for t in json.loads(FIXTURE.read_text())
                  if t['operation'] == 'SET' and t['request'].startswith('0411007b')]
        profile = Profile(writes[0])
        profile.set_polling(1000)
        self.assertEqual(profile.write_report(1), writes[1])
        self.assertEqual([i for i, (a, b) in enumerate(zip(writes[0], writes[1])) if a != b], [10])

    def test_vendor_default_button_matrix_reproduced(self):
        vendor = next(bytes.fromhex(t['request']) for t in json.loads(FIXTURE.read_text())
                      if t['operation'] == 'SET' and t['request'].startswith('04120050'))
        self.assertEqual(matrix_report(1, DEFAULT_BUTTONS), vendor)
        self.assertEqual(matrix_report(2, DEFAULT_BUTTONS)[1], 0x22)

    def test_dpi_table_sparse_stages_and_separate_xy(self):
        profile = self.controller.load(1)
        slots = profile.dpi_slots()
        for i, slot in enumerate(slots):
            slot.update(enabled=i in (1, 4), x=4000, y=8000, color='#abcdef')
        profile.set_dpi(slots, True, 4)
        self.assertEqual(profile.report[11:15], bytes((0x22, 0xed, 16, 24)))
        self.assertEqual(profile.active_slot, 4)
        self.assertEqual(profile.dpi_slots(), slots)
        self.assertTrue(profile.separate_xy)
        self.assertIn(1200, DPI_VALUES)
        self.assertIn(2400, DPI_VALUES)
        with self.assertRaises(ValueError):
            profile.set_dpi(slots, True, 0)

    def test_keyboard_and_media_encoding(self):
        self.assertEqual(button_code('key:CTRL+C'), 0x00060121)
        self.assertEqual(button_code('Volume +'), 0x4022)
        for code in (0x00060121, 0x0b0a0821, 0x142):
            self.assertEqual(button_code(button_label(code)), code)

    def test_macro_matches_recovered_encoder(self):
        # FUN_004145d0: BE record count, type/delay high nibble,
        # delay low byte, HID usage. Bit 7 means release.
        events = parse_macro('down CTRL 10\ndown A 20\nup A 30\nup CTRL 40\nwheel -1 50')
        report = macro_report(2, events)
        self.assertEqual(report[:26], bytes.fromhex(
            '04 30 02 00 00 00 00 00 02 00 05 60 0a 01 50 14 04 d0 1e 04 e0 28 01 40 32 ff'))
        self.assertEqual(len(report), 520)
        self.assertEqual(macro_button(2, 'hold', 3), 0x03040270)
        self.assertEqual(macro_button(2, 'toggle', 3), 0x03020270)
        self.assertEqual(MacroEvent('down', 'A', 256).encode(), bytes.fromhex('51 01 04'))

    def test_macro_rejects_overflow_and_invalid_events(self):
        for text in ('down A 0', 'down A 4096', 'down UNKNOWN 20', 'wheel 128 20', 'down A 20\n'*169):
            with self.assertRaises(ValueError):
                parse_macro(text)

    def test_polling_apply_preserves_unknown_bytes_and_buttons(self):
        raw = bytearray(self.device.profiles[1])
        raw[8+0x75] = 0xab
        self.device.profiles[1] = bytes(raw)
        original = self.controller.load(1)
        edited = original.copy()
        edited.set_polling(1000)
        actual = self.controller.apply(1, original, edited)
        self.assertEqual(actual.polling, 1000)
        self.assertEqual(actual.report[8+0x75], 0xab)
        self.assertEqual(self.device.matrices, {})
        self.assertEqual(self.device.macros, {})

    def test_apply_merges_unrelated_external_edits(self):
        original = self.controller.load(1)
        edited = original.copy()
        edited.set_polling(1000)
        raw = bytearray(self.device.profiles[1])
        raw[100] = 0x99
        self.device.profiles[1] = bytes(raw)
        actual = self.controller.apply(1, original, edited)
        self.assertEqual(actual.report[100], 0x99)
        self.assertEqual(actual.polling, 1000)

    def test_conflicting_edit_fails_before_any_write(self):
        original = self.controller.load(1)
        edited = original.copy()
        edited.set_polling(1000)
        raw = bytearray(self.device.profiles[1])
        raw[10] = 1
        self.device.profiles[1] = bytes(raw)
        with self.assertRaises(ValueError):
            self.controller.apply(1, original, edited, DEFAULT_BUTTONS, {'1': 'down A 10\nup A 10'})
        self.assertFalse(any(not get and report[0] == 4 for get, report in self.device.transfers))

    def test_invalid_macro_prevents_all_writes(self):
        original = self.controller.load(1)
        before = len(self.device.transfers)
        with self.assertRaises(ValueError):
            self.controller.apply(1, original, original.copy(), DEFAULT_BUTTONS, {'1': 'invalid'})
        self.assertEqual(len(self.device.transfers), before)

    def test_macro_matrix_general_order_and_profile_switch(self):
        original = self.controller.load(2)
        matrix = list(DEFAULT_BUTTONS)
        matrix[5] = macro_button(1)
        self.controller.apply(2, original, original.copy(), matrix, {'1': 'down A 20\nup A 20'})
        writes = [report for get, report in self.device.transfers if not get and report[0] == 4]
        self.assertEqual([report[1] for report in writes], [0x30, 0x22, 0x21])
        self.assertEqual(self.device.matrices[2], matrix_report(2, matrix))
        self.controller.select(2)
        self.assertEqual(self.controller.active, 2)

    def test_general_readback_failure_is_reported(self):
        original = self.controller.load(1)
        edited = original.copy()
        edited.set_polling(1000)
        transfer = self.device.transfer
        def ignore_write(get, report):
            return b'' if not get and report[0] == 4 else transfer(get, report)
        with patch.object(self.device, 'transfer', side_effect=ignore_write):
            with self.assertRaises(OSError):
                self.controller.apply(1, original, edited)

    def test_json_roundtrip_validates_before_restoring(self):
        original = self.controller.load(1)
        macros = {'1': 'down A 20\nup A 20'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            self.controller.export(path, 1, original, DEFAULT_BUTTONS, macros)
            number, restored, buttons, library = import_profile(path)
            self.assertEqual((number, restored.report, buttons, library), (1, original.report, DEFAULT_BUTTONS, macros))
            data = json.loads(path.read_text())
            data['buttons'] = [0]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                import_profile(path)

    def test_lighting_only_changes_supported_effect_fields(self):
        original = self.controller.load(1)
        edited = original.copy()
        edited.set_lighting(2, 4, 7, '#102030')
        self.assertEqual(edited.report[8+0x30] >> 4, 7)
        self.assertEqual(edited.report[8+0x31:8+0x34], bytes.fromhex('10 20 30'))
        for i, (a, b) in enumerate(zip(original.report, edited.report)):
            if i not in (8+0x2d, 8+0x30, 8+0x31, 8+0x32, 8+0x33):
                self.assertEqual(a, b)

    def test_sensor_and_firmware_mismatch_rejected(self):
        raw = bytearray(self.device.profiles[1]); raw[9] = 0
        with self.assertRaises(ValueError):
            Profile(raw)
        with patch.object(self.device, 'command', return_value=bytes(6)):
            with self.assertRaises(ValueError):
                Controller(self.device)


if __name__ == '__main__':
    unittest.main()

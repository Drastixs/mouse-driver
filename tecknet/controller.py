"""Configuration operations shared by the native desktop app and CLI."""
import json
import os
from pathlib import Path
import tempfile
import time
import struct

from .protocol import Profile, matrix_report, macro_report, parse_macro, profile_number


def save_json(path, data):
    """Write settings atomically, including when exporting over an existing file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            name = stream.name
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class Controller:
    def __init__(self, device, demo=False):
        self.device, self.demo = device, demo
        firmware = device.command(1)
        if firmware != bytes.fromhex('05 01 32 37 36 34'):
            raise ValueError('Firmware identity does not match the GM2793-1')
        self.firmware = firmware[2:].hex()
        self.active = device.command(2)[2]
        profile_number(self.active)

    def load(self, number):
        return Profile(self.device.read_profile(profile_number(number)))

    def load_buttons(self, number):
        report = self.device.read_matrix(profile_number(number))
        if len(report) != 520 or report[0] != 4:
            raise ValueError('Invalid button matrix readback')
        return list(struct.unpack('<20I', report[8:88]))

    def reconnect(self):
        if self.demo:
            return
        from .hid import HidDevice
        index = self.device.index
        self.device.close()
        device = HidDevice(index)
        try:
            replacement = Controller(device)
            replacement.load(replacement.active)
        except Exception:
            device.close()
            raise
        self.device = device
        self.firmware, self.active = replacement.firmware, replacement.active

    def allocate_macros(self, number, buttons, assignments, library, matrices=None):
        """Allocate named macros around existing opaque assignments in all modes."""
        number = profile_number(number)
        matrix_report(number, buttons)
        if matrices is None:
            matrices = {n: self.load_buttons(n) for n in (1, 2, 3)}
        reserved = set()
        for n, matrix in matrices.items():
            for slot, code in enumerate(matrix):
                if code & 255 in (0x60, 0x70) and (n != number or slot not in assignments):
                    reserved.add((code >> 8) & 127)
        # Imported opaque references also reserve their original buffer IDs.
        for slot, code in enumerate(buttons):
            if slot not in assignments and code & 255 in (0x60, 0x70):
                reserved.add((code >> 8) & 127)
        uploads, allocated = {}, {}
        result = list(buttons)
        for slot, name in assignments.items():
            if type(slot) is not int or not 0 <= slot < 20 or name not in library:
                raise ValueError('Invalid named macro assignment')
            if name not in allocated:
                buffer = next((i for i in range(1, 15) if i not in reserved), None)
                if buffer is None:
                    raise ValueError('All macro buffers are in use; free an assignment before uploading')
                reserved.add(buffer)
                text = library[name]
                macro_report(buffer, parse_macro(text))
                allocated[name] = buffer
                uploads[str(buffer)] = text
            result[slot] = (result[slot] & 0xffff00ff) | (allocated[name] << 8)
        return result, uploads

    def select(self, number):
        number = profile_number(number)
        self.device.command(2, number)
        actual = self.device.command(2)[2]
        if actual != number:
            raise OSError(f'Profile selection did not take effect (reported {actual})')
        self.active = number

    def apply(self, number, original, edited, buttons=None, macros=None, original_buttons=None):
        """Merge edited bytes into a fresh read; don't replace unedited fields.

        Validate every report before the first write. General settings never
        rewrite button matrices unless the caller explicitly supplies one.
        """
        number = profile_number(number)
        if not isinstance(original, Profile) or not isinstance(edited, Profile):
            raise ValueError('Expected original and edited profiles')
        reports = []
        for buffer_id, text in (macros or {}).items():
            reports.append(macro_report(int(buffer_id), parse_macro(text)))
        if buttons is not None:
            reports.append(matrix_report(number, buttons))
            if not any(code & 255 == 0x11 and (code >> 8) & 1 for code in buttons):
                raise ValueError('Keep at least one button assigned to left click')
            if original_buttons is not None and self.load_buttons(number) != original_buttons:
                raise ValueError('Button assignments changed since loading; reload before applying')
        if macros:
            uploading = {int(i) for i in macros}
            for other in (1, 2, 3):
                if other == number:
                    continue
                for code in self.load_buttons(other):
                    if code & 255 in (0x60, 0x70) and ((code >> 8) & 127) in uploading:
                        raise ValueError('Macro buffer is used by another mode; choose an unused buffer')
        fresh = self.load(number)
        for i in range(8, 148):
            if edited.report[i] != original.report[i]:
                if fresh.report[i] not in (original.report[i], edited.report[i]):
                    raise ValueError('Mouse settings changed since loading; reload before applying')
                fresh.report[i] = edited.report[i]
        reports.append(fresh.write_report(number))
        for report in reports:
            self.device.transfer(False, report)
            time.sleep(.022)
        # General and matrix readback are supported; macro contents are opaque.
        actual = self.load(number)
        if actual.report[8:148] != fresh.report[8:148]:
            raise OSError('General profile readback differs from the written settings')
        if buttons is not None and self.load_buttons(number) != list(buttons):
            raise OSError('Button matrix readback differs from the written assignments')
        return actual

    def export(self, path, number, profile, buttons=None, macros=None):
        save_json(path, {'format': 'tecknet-gm2793-profile', 'version': 1,
                         'profile': profile_number(number), 'report': bytes(profile.report).hex(),
                         'buttons': buttons, 'macros': macros or {}})


def import_profile(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or data.get('format') != 'tecknet-gm2793-profile' or data.get('version') != 1:
        raise ValueError('Unsupported profile file')
    try:
        number = profile_number(data['profile'])
        profile = Profile(bytes.fromhex(data['report']))
        buttons = data.get('buttons')
        if buttons is not None:
            matrix_report(number, buttons)
        macros = data.get('macros', {})
        if not isinstance(macros, dict):
            raise ValueError('Macros must be an object')
        for buffer_id, text in macros.items():
            macro_report(int(buffer_id), parse_macro(text))
    except (KeyError, TypeError) as exc:
        raise ValueError('Malformed profile file') from exc
    return number, profile, buttons, macros


def decode_native_profile(data):
    """Validate the GUI's portable profile before changing any staged state."""
    if not isinstance(data, dict) or data.get('format') != 'tecknet-gm2793-native' or data.get('version') != 1:
        raise ValueError('Unsupported native profile')
    try:
        profile = Profile(bytes.fromhex(data['report']))
        buttons = data['buttons']
        matrix_report(1, buttons)
        library = data.get('library', {})
        mapping = data.get('assignments', {})
        if not isinstance(library, dict) or not isinstance(mapping, dict):
            raise ValueError('Invalid native macro library')
        for text in library.values():
            parse_macro(text)
        assignments = {int(k): v for k, v in mapping.items()}
        if any(not 0 <= k < 20 or v not in library or buttons[k] & 255 != 0x70 for k, v in assignments.items()):
            raise ValueError('Invalid macro assignment in profile')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Malformed native profile') from exc
    return profile, list(buttons), assignments, library

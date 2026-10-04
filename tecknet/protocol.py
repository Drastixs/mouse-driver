"""Native GM2793-1 encoders, derived from the vendor's 8948 protocol.

Only documented fields are changed. Unknown profile bytes survive edits.
See docs/protocol.md for evidence and the hardware validation boundary.
"""
from dataclasses import dataclass
import re
import struct

from .hid import validate_report

DPI_VALUES = (250, 500, 750, 1000, 1200, 1500, 1750, 2000, 2250, 2400,
              2750, 3000, 3250, 3500, 3750, 4000, 4500, 5000, 5500, 6000,
              6500, 7000, 7500, 8000)
POLLING = (125, 250, 500, 1000)
BUTTON_NAMES = ('Left', 'Right', 'Middle', 'Forward', 'Back', 'DPI +', 'DPI −',
                'Fire', 'Lighting', 'DPI lock', 'Mode')
ACTIONS = {
    'Left click': 0x111, 'Right click': 0x211, 'Middle click': 0x411,
    'Forward': 0x1011, 'Back': 0x811, 'Double click': 0x02320131,
    'Triple click': 0x03320131, 'Scroll up': 0x0112, 'Scroll down': 0xFF12,
    'Tilt left': 0xFF13, 'Tilt right': 0x0113,
    'DPI +': 0x141, 'DPI −': 0x241, 'DPI cycle': 0x41,
    'Lighting on/off': 0x850, 'Lighting effect cycle': 0x750,
    'Mode cycle': 0x650, 'Polling cycle': 0x450, 'Disable': 0x150,
    'Play/pause': 0x0822, 'Stop': 0x0422, 'Previous track': 0x0222,
    'Next track': 0x0122, 'Volume +': 0x4022, 'Volume −': 0x8022,
    'Mute': 0x1022,
    'Media player': 0x010022, 'File manager': 0x020022,
    'Email': 0x100022, 'Calculator': 0x200022,
    'Browser search': 0x01000022, 'Browser home': 0x02000022,
    'Browser back': 0x04000022, 'Browser forward': 0x08000022,
    'Browser stop': 0x10000022, 'Browser refresh': 0x20000022,
    'Browser bookmarks': 0x40000022,
}
DEFAULT_BUTTONS = [0x111, 0x211, 0x411, 0x1011, 0x811, 0x141, 0x241,
                   0x03320131, 0x750, 0x650, 0x142] + [0x150] * 9
KEYS = {chr(65 + i): 4 + i for i in range(26)}
KEYS.update({str(i): 29 + i for i in range(1, 10)})
KEYS.update({'0': 39, 'ENTER': 40, 'ESC': 41, 'BACKSPACE': 42, 'TAB': 43,
             'SPACE': 44, 'MINUS': 45, 'EQUAL': 46, 'LEFTBRACKET': 47,
             'RIGHTBRACKET': 48, 'BACKSLASH': 49, 'SEMICOLON': 51,
             'APOSTROPHE': 52, 'GRAVE': 53, 'COMMA': 54, 'PERIOD': 55,
             'SLASH': 56, 'CAPSLOCK': 57, 'PRINTSCREEN': 70, 'SCROLLLOCK': 71,
             'PAUSE': 72, 'INSERT': 73, 'HOME': 74, 'PAGEUP': 75,
             'DELETE': 76, 'END': 77, 'PAGEDOWN': 78, 'RIGHT': 79,
             'LEFT': 80, 'DOWN': 81, 'UP': 82})
KEYS.update({f'F{i}': 57 + i for i in range(1, 13)})
MODIFIERS = {'CTRL': 1, 'SHIFT': 2, 'ALT': 4, 'SUPER': 8,
             'RCTRL': 16, 'RSHIFT': 32, 'RALT': 64, 'RSUPER': 128}
MOUSE_KEYS = {'LEFT': 1, 'RIGHT': 2, 'MIDDLE': 4, 'BACK': 8, 'FORWARD': 16}
EFFECTS = ('Off', 'Colorful Streaming', 'Steady', 'Breathing', 'Colorful Tail',
           'Neon', 'Reaction', 'Flicker', 'Stars twinkle', 'Wave', 'Streaming', 'Effect 11')
EFFECT_PARAMETER = {1: 0x2e, 2: 0x30, 3: 0x34, 4: 0x4b, 5: 0x4c,
                    6: 0x4d, 7: 0x66, 8: 0x6d, 9: 0x6e, 10: 0x6f, 11: 0x70}
EFFECT_COLORS = {2: (0x31, 1), 3: (0x36, 7), 6: (0x4e, 8), 7: (0x67, 2)}


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}')
    return value


def profile_number(number):
    return integer(number, 1, 3, 'Profile')


def data_report(opcode, payload, field=0, second=0):
    if len(payload) > 512:
        raise ValueError('Data payload is too large')
    return bytes((4, opcode, second, field, 0, 0, 0, 0)) + payload + bytes(512 - len(payload))


class Profile:
    def __init__(self, report):
        validate_report(report)
        if len(report) != 520 or report[9] != 0x13:
            raise ValueError('Profile does not belong to the supported 3104 sensor')
        self.report = bytearray(report)

    def copy(self):
        return Profile(self.report)

    @property
    def polling(self):
        code = self.report[10] & 15
        return POLLING[code - 1] if 1 <= code <= 4 else None

    def set_polling(self, rate):
        if rate not in POLLING:
            raise ValueError('Polling must be 125, 250, 500 or 1000 Hz')
        self.report[10] = (self.report[10] & 0xf0) | (POLLING.index(rate) + 1)

    @property
    def separate_xy(self):
        return bool(self.report[10] & 0x80)

    def dpi_slots(self):
        result = []
        for i in range(8):
            offset = 13 + i * (2 if self.separate_xy else 1)
            x = self.report[offset]
            y = self.report[offset + 1] if self.separate_xy else x
            color = self.report[8 + 0x15 + 3*i:8 + 0x18 + 3*i]
            result.append({'enabled': not bool(self.report[12] & (1 << i)),
                           'x': DPI_VALUES[x - 1] if 1 <= x <= len(DPI_VALUES) else None,
                           'y': DPI_VALUES[y - 1] if 1 <= y <= len(DPI_VALUES) else None,
                           'color': '#' + color.hex()})
        return result

    @property
    def active_slot(self):
        enabled = [i for i in range(8) if not self.report[12] & (1 << i)]
        ordinal = self.report[11] >> 4
        return enabled[ordinal - 1] if 1 <= ordinal <= len(enabled) else None

    def set_dpi(self, slots, separate_xy, active):
        if len(slots) != 8 or type(separate_xy) is not bool:
            raise ValueError('Provide eight DPI slots and a boolean separate_xy')
        enabled = [i for i, slot in enumerate(slots) if slot['enabled']]
        if not enabled or active not in enabled:
            raise ValueError('The active DPI slot must be enabled')
        encoded = bytearray(16)
        for i, slot in enumerate(slots):
            if type(slot['enabled']) is not bool:
                raise ValueError('DPI enabled must be a boolean')
            values = (slot['x'], slot['y']) if separate_xy else (slot['x'],)
            for j, value in enumerate(values):
                if value is None and not slot['enabled']:
                    encoded[i*len(values) + j] = 0
                    continue
                if value not in DPI_VALUES:
                    raise ValueError(f'DPI must be one of {DPI_VALUES}')
                encoded[i*len(values) + j] = DPI_VALUES.index(value) + 1
            parse_color(slot['color'])
        self.report[10] = (self.report[10] & 0x7f) | (0x80 if separate_xy else 0)
        self.report[11] = ((enabled.index(active) + 1) << 4) | len(enabled)
        self.report[12] = sum(1 << i for i in range(8) if i not in enabled)
        self.report[13:29] = encoded
        for i, slot in enumerate(slots):
            offset = 8 + 0x15 + 3*i
            self.report[offset:offset + 3] = parse_color(slot['color'])

    def lighting(self):
        effect = self.report[8 + 0x2d]
        packed = self.report[8 + EFFECT_PARAMETER.get(effect, 0x2e)]
        offset, count = EFFECT_COLORS.get(effect, (0x31, 1))
        if effect == 3:
            count = max(1, min(count, self.report[8 + 0x35]))
        colors = ['#' + self.report[8 + offset + 3*i:8 + offset + 3*i + 3].hex()
                  for i in range(count)]
        return {'effect': effect, 'speed': packed & 15, 'brightness': packed >> 4,
                'color': colors[0], 'colors': colors,
                'direction': self.report[8 + 0x2f]}

    def set_lighting(self, effect, speed, brightness, color, colors=None, direction=None):
        integer(effect, 0, 11, 'Effect')
        integer(speed, 0, 15, 'Speed')
        integer(brightness, 0, 15, 'Brightness')
        rgb = parse_color(color)
        parsed = [parse_color(c) for c in colors] if colors is not None else [rgb]
        if not parsed or len(parsed) > 8:
            raise ValueError('Provide between one and eight lighting colors')
        if direction is not None:
            integer(direction, 0, 1, 'Direction')
        self.report[8 + 0x2d] = effect
        if effect in EFFECT_PARAMETER:
            offset = 8 + EFFECT_PARAMETER[effect]
            high = brightness << 4 if effect < 10 else self.report[offset] & 0xf0
            self.report[offset] = high | (speed if effect not in (2, 6) else self.report[offset] & 15)
        if effect == 1 and direction is not None:
            self.report[8 + 0x2f] = direction
        if effect in EFFECT_COLORS:
            offset, maximum = EFFECT_COLORS[effect]
            if effect == 3:
                self.report[8 + 0x35] = min(len(parsed), maximum)
            for i, c in enumerate(parsed[:maximum]):
                start = 8 + offset + 3*i
                self.report[start:start+3] = c

    def write_report(self, number):
        # Match the vendor's 140-byte write and zero-filled tail.
        return data_report(profile_number(number) * 16 + 1, bytes(self.report[8:148]), 0x7b)

    def summary(self):
        return {'polling': self.polling, 'separate_xy': self.separate_xy,
                'active_slot': self.active_slot, 'dpi': self.dpi_slots(),
                'lighting': self.lighting()}


def parse_color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError('Color must be #RRGGBB')
    return bytes.fromhex(value[1:])


def shortcut(text):
    modifiers, keys = 0, []
    for word in text.upper().split('+'):
        word = word.strip()
        if word in MODIFIERS:
            modifiers |= MODIFIERS[word]
        elif word in KEYS:
            keys.append(KEYS[word])
        else:
            raise ValueError(f'Unknown key: {word}')
    if len(keys) > 2 or not (keys or modifiers):
        raise ValueError('A shortcut supports modifiers and up to two keys')
    keys += [0] * (2 - len(keys))
    return 0x21 | (modifiers << 8) | (keys[0] << 16) | (keys[1] << 24)


def button_code(action):
    if action in ACTIONS:
        return ACTIONS[action]
    if action.lower().startswith('key:'):
        return shortcut(action[4:])
    if action.lower().startswith('dpi lock:'):
        value = int(action.split(':', 1)[1])
        if value not in DPI_VALUES:
            raise ValueError('Invalid DPI lock value')
        return 0x42 | ((DPI_VALUES.index(value) + 1) << 8)
    if action.lower().startswith('raw:'):
        return integer(int(action[4:], 0), 0, 0xffffffff, 'Button code')
    raise ValueError(f'Unknown button action: {action}')


def button_label(code):
    for label, value in ACTIONS.items():
        if value == code:
            return label
    if code & 255 == 0x42 and 1 <= (code >> 8) <= len(DPI_VALUES):
        return f'DPI lock: {DPI_VALUES[(code >> 8)-1]}'
    if code & 255 == 0x21:
        words = [word for word, mask in MODIFIERS.items() if (code >> 8) & mask]
        reverse = {v: k for k, v in KEYS.items()}
        for value in ((code >> 16) & 255, code >> 24):
            if value:
                if value not in reverse:
                    return f'raw:0x{code:08x}'
                words.append(reverse[value])
        if words:
            return 'key:' + '+'.join(words)
    return f'raw:0x{code:08x}'


def matrix_report(number, buttons):
    if len(buttons) != 20:
        raise ValueError('A button matrix must contain twenty entries')
    for code in buttons:
        integer(code, 0, 0xffffffff, 'Button code')
    return data_report(profile_number(number) * 16 + 2, struct.pack('<20I', *buttons), 0x50)


@dataclass(frozen=True)
class MacroEvent:
    kind: str
    value: str
    delay: int = 20

    def encode(self):
        integer(self.delay, 1, 4095, 'Macro delay (ms)')
        value = self.value.upper()
        if self.kind in ('down', 'up'):
            if value in MODIFIERS:
                kind, code = 6, MODIFIERS[value]
            elif value in KEYS:
                kind, code = 5, KEYS[value]
            else:
                raise ValueError(f'Unknown macro key: {value}')
        elif self.kind in ('mouse-down', 'mouse-up'):
            if value not in MOUSE_KEYS:
                raise ValueError(f'Unknown mouse key: {value}')
            kind, code = 1, MOUSE_KEYS[value]
        elif self.kind in ('move-x', 'move-y', 'wheel'):
            kind = {'move-x': 2, 'move-y': 3, 'wheel': 4}[self.kind]
            code = integer(int(value), -127, 127, 'Movement') & 255
        else:
            raise ValueError(f'Unknown macro event: {self.kind}')
        release = self.kind in ('up', 'mouse-up')
        first = (kind << 4) | (self.delay >> 8) | (0x80 if release else 0)
        # FUN_004145d0 promotes a zero low delay byte to 1.
        return bytes((first, (self.delay & 255) or 1, code))


def parse_macro(text):
    if not isinstance(text, str):
        raise ValueError('Macro must be text')
    events = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        words = line.split()
        if len(words) != 3:
            raise ValueError(f'Macro line {n}: use EVENT KEY_OR_MOVEMENT DELAY_MS')
        try:
            event = MacroEvent(words[0].lower(), words[1], int(words[2]))
            event.encode()
        except ValueError as exc:
            raise ValueError(f'Macro line {n}: {exc}') from None
        events.append(event)
    if not 1 <= len(events) <= 168:
        raise ValueError('A macro must contain between 1 and 168 events')
    return events


def macro_report(buffer_id, events):
    integer(buffer_id, 1, 14, 'Macro buffer')
    if not 1 <= len(events) <= 168:
        raise ValueError('A macro must contain between 1 and 168 events')
    encoded = len(events).to_bytes(2, 'big') + b''.join(event.encode() for event in events)
    return data_report(0x30, bytes((buffer_id,)) + encoded.ljust(510, b'\0'), second=2)


def macro_button(buffer_id, mode='repeat', repeats=1):
    integer(buffer_id, 1, 14, 'Macro buffer')
    integer(repeats, 1, 255, 'Macro repeats')
    modes = {'repeat': 1, 'hold': 4, 'toggle': 2}
    if mode not in modes:
        raise ValueError('Macro mode must be repeat, hold or toggle')
    return 0x70 | (buffer_id << 8) | (modes[mode] << 16) | (repeats << 24)

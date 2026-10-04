"""Linux hidraw transport. No kernel driver replacement is required."""
import fcntl
import os
import time
from pathlib import Path

VID, PID = 0x258A, 0x1007
CMD_SIZE, DATA_SIZE = 6, 520


def feature_sizes(descriptor):
    """Read report sizes from HID short items, including global push/pop."""
    state = {"size": 0, "count": 0, "id": 0}
    stack, bits = [], {}
    pos = 0
    while pos < len(descriptor):
        prefix = descriptor[pos]
        pos += 1
        if prefix == 0xFE:
            if pos + 2 > len(descriptor):
                raise ValueError("Truncated HID long item")
            length = descriptor[pos]
            if pos + 2 + length > len(descriptor):
                raise ValueError("Truncated HID long item data")
            pos += 2 + length
            continue
        length = (0, 1, 2, 4)[prefix & 3]
        if pos + length > len(descriptor):
            raise ValueError("Truncated HID item")
        value = int.from_bytes(descriptor[pos:pos + length], "little")
        pos += length
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1:
            if tag in (7, 8, 9):
                state[{7: "size", 8: "id", 9: "count"}[tag]] = value
            elif tag == 10:
                stack.append(state.copy())
            elif tag == 11:
                if not stack:
                    raise ValueError("Unbalanced HID global pop")
                state = stack.pop()
        elif kind == 0 and tag == 11:
            report = state["id"]
            bits[report] = bits.get(report, 0) + state["size"] * state["count"]
    return {report: (size + 7) // 8 + 1 for report, size in bits.items()}


def discover(sysroot=Path('/sys/class/hidraw')):
    groups = {}
    for entry in sorted(sysroot.glob('hidraw*')):
        device = (entry / 'device').resolve()
        usb = next((p for p in device.parents if (p / 'idVendor').exists()), None)
        if usb is None:
            continue
        try:
            if (int((usb / 'idVendor').read_text(), 16),
                    int((usb / 'idProduct').read_text(), 16)) != (VID, PID):
                continue
            sizes = feature_sizes((device / 'report_descriptor').read_bytes())
        except (OSError, ValueError):
            continue
        group = groups.setdefault(str(usb), {})
        for report, size in sizes.items():
            if (report, size) in ((5, CMD_SIZE), (4, DATA_SIZE)):
                group[report] = Path('/dev') / entry.name
    return [group for group in groups.values() if 4 in group and 5 in group]


class HidDevice:
    def __init__(self, index=0):
        self.index = index
        groups = discover()
        if not groups:
            raise RuntimeError('No GM2793-1 (258a:1007) with the expected HID reports found')
        if not 0 <= index < len(groups):
            raise ValueError('Device index out of range')
        self.fds = {}
        try:
            opened = {}
            for report, path in groups[index].items():
                if path not in opened:
                    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
                    self.fds[report] = fd
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise RuntimeError('This mouse is already open in another configuration process') from None
                    opened[path] = fd
                self.fds[report] = opened[path]
        except (OSError, RuntimeError):
            self.close()
            raise

    def close(self):
        for fd in set(self.fds.values()):
            os.close(fd)
        self.fds.clear()

    def transfer(self, get, data):
        validate_report(data)
        buf = bytearray(data)
        # _IOC(_IOC_READ | _IOC_WRITE, 'H', GET=7 / SET=6, length)
        request = (3 << 30) | (len(buf) << 16) | (ord('H') << 8) | (7 if get else 6)
        size = fcntl.ioctl(self.fds[buf[0]], request, buf, True)
        if size != len(buf):
            raise OSError(f'Short HID feature {"read" if get else "write"}: {size}/{len(buf)}')
        return bytes(buf) if get else b''

    def command(self, opcode, value=0):
        self.transfer(False, bytes((5, opcode, value, 0, 0, 0)))
        time.sleep(.025)
        return self.transfer(True, bytes((5, 0, 0, 0, 0, 0)))

    def read_profile(self, number):
        return self.read_data(number, 1)

    def read_matrix(self, number):
        return self.read_data(number, 2)

    def read_data(self, number, kind):
        if number not in (1, 2, 3):
            raise ValueError('Profile must be 1, 2 or 3')
        self.transfer(False, bytes((5, number * 16 + kind, 0, 0, 0, 0)))
        time.sleep(.025)
        return self.transfer(True, bytes((4,)) + bytes(519))


def validate_report(data):
    if not data or (data[0], len(data)) not in ((5, CMD_SIZE), (4, DATA_SIZE)):
        raise ValueError('Unexpected feature report ID or length')


class SimulatedDevice(HidDevice):
    """In-memory transport for UI and bridge validation; never opens hardware."""
    def __init__(self, index=0):
        self.last = bytes(6)
        self.active = 1
        self.profiles = {}
        self.matrices = {}
        self.macros = {}
        self.transfers = []
        for n in (1, 2, 3):
            buf = bytearray(520)
            buf[:4] = bytes((4, n * 16 + 1, 0, 0x7B))
            buf[8:21] = bytes((100, 0x13, 3, 0x15, 0xE0, 2, 4, 8, 12, 16, 1, 1, 1))
            buf[8 + 0x2D:8 + 0x2F] = bytes((1, 0x42))
            colors = ((255,0,0),(0,0,255),(0,255,0),(255,0,255),(255,255,0),(0,255,255),(255,255,255),(255,128,0))
            for i, color in enumerate(colors):
                buf[8+0x15+i*3:8+0x18+i*3] = bytes(color)
            self.profiles[n] = bytes(buf)

    def close(self):
        pass

    def transfer(self, get, data):
        validate_report(data)
        self.transfers.append((get, bytes(data)))
        if not get:
            if data[0] == 5:
                self.last = data
                if data[1] == 2 and data[2] in (1, 2, 3):
                    self.active = data[2]
            elif data[1] in (0x11, 0x21, 0x31):
                self.profiles[data[1] >> 4] = bytes(data)
            elif data[1] in (0x12, 0x22, 0x32) and data[2] == 0:
                self.matrices[data[1] >> 4] = bytes(data)
            elif data[1:3] == bytes((0x30, 2)):
                self.macros[data[8]] = bytes(data)
            return b''
        if data[0] == 5:
            return bytes((5, 1, 0x32, 0x37, 0x36, 0x34)) if self.last[1] == 1 else bytes((5, self.last[1], self.active, 0, 0, 0))
        if self.last[1] in (0x11, 0x21, 0x31):
            return self.profiles[self.last[1] >> 4]
        if self.last[1] in (0x12, 0x22, 0x32):
            from .protocol import DEFAULT_BUTTONS, matrix_report
            n = self.last[1] >> 4
            return self.matrices.get(n, matrix_report(n, DEFAULT_BUTTONS))
        return bytes((4,)) + bytes(519)

import json
from pathlib import Path
import socket
import struct
import unittest
from unittest.mock import patch
from tecknet.hid import feature_sizes, HidDevice, SimulatedDevice, validate_report
from tecknet.bridge import Bridge, receive


class DescriptorTests(unittest.TestCase):
    def test_distinct_reports_and_accumulated_items(self):
        # Report 5: five bytes + ID; report 4: 519 bytes + ID.
        descriptor = bytes.fromhex('85 05 75 08 95 02 b1 02 95 03 b1 02 85 04 96 07 02 b1 02')
        self.assertEqual(feature_sizes(descriptor), {5:6, 4:520})

    def test_global_push_pop(self):
        self.assertEqual(feature_sizes(bytes.fromhex('85 05 75 08 95 05 a4 85 04 96 07 02 b1 02 b4 b1 02')), {4:520,5:6})

    def test_truncated_descriptor(self):
        with self.assertRaises(ValueError):
            feature_sizes(bytes.fromhex('96 01'))


class TransportTests(unittest.TestCase):
    def test_ioctl_and_report_id_preserved(self):
        device = object.__new__(HidDevice)
        device.fds = {5:123}
        def ioctl(fd, request, buf, mutate):
            self.assertEqual((fd,request,buf[0],mutate),(123,0xC0064807,5,True))
            buf[:] = bytes.fromhex('05 01 32 37 36 34')
            return 6
        with patch('tecknet.hid.fcntl.ioctl', side_effect=ioctl):
            self.assertEqual(device.transfer(True, bytes.fromhex('05 00 00 00 00 00')),bytes.fromhex('05 01 32 37 36 34'))

    def test_short_read_rejected(self):
        device = object.__new__(HidDevice)
        device.fds = {5:123}
        with patch('tecknet.hid.fcntl.ioctl', return_value=2):
            with self.assertRaises(OSError):
                device.transfer(True, bytes.fromhex('05 00 00 00 00 00'))

    def test_invalid_report(self):
        for data in (b'', bytes(520), bytes((5,))+bytes(519)):
            with self.assertRaises(ValueError):
                validate_report(data)

    def test_vendor_profile_sequence(self):
        device = SimulatedDevice()
        profile = bytearray(device.read_profile(2))
        # Mirror the vendor's 00413550 write: 0x7b header, payload at 8.
        profile[3] = 0x7B
        profile[10] = 4
        device.transfer(False, profile)
        self.assertEqual(device.read_profile(2)[10], 4)
        self.assertEqual(device.transfers[0], (False,bytes.fromhex('05 21 00 00 00 00')))


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.device = SimulatedDevice()
        self.token = 'a'*32
        self.bridge = Bridge(self.device, self.token)
        self.bridge.start()

    def tearDown(self):
        self.bridge.close()

    def request(self, operation, payload=b''):
        with socket.create_connection(('127.0.0.1', self.bridge.port),timeout=3) as sock:
            sock.sendall(self.token.encode()+struct.pack('<BH',operation,len(payload))+payload)
            ok, length = struct.unpack('<BH',receive(sock,3))
            return ok,receive(sock,length)

    def test_complete_vendor_exchange(self):
        self.assertEqual(self.request(0),(1,b''))
        self.assertEqual(self.request(1,bytes.fromhex('05 01 00 00 00 00')),(1,b''))
        self.assertEqual(self.request(2,bytes.fromhex('05 00 00 00 00 00')),(1,bytes.fromhex('05 01 32 37 36 34')))
        self.request(1,bytes.fromhex('05 11 00 00 00 00'))
        ok, profile = self.request(2,bytes((4,))+bytes(519))
        self.assertEqual((ok,len(profile),profile[8:10]),(1,520,bytes.fromhex('64 13')))

    def test_captured_vendor_apply_and_polling_change(self):
        fixture = Path(__file__).resolve().parents[1] / 'docs/validation/vendor-demo-transfers.json'
        for transfer in json.loads(fixture.read_text()):
            operation = 2 if transfer['operation'] == 'GET' else 1
            ok, response = self.request(operation, bytes.fromhex(transfer['request']))
            self.assertEqual(ok, 1)
            self.assertEqual(response.hex(), transfer['response'])
        self.assertEqual(self.device.read_profile(1)[10] & 15, 4)

    def test_wrong_token_never_touches_hardware(self):
        with socket.create_connection(('127.0.0.1',self.bridge.port),timeout=3) as sock:
            sock.sendall(b'b'*32)
            self.assertEqual(sock.recv(1),b'')
        self.assertEqual(self.device.transfers,[])

    def test_bad_report_returns_error_and_server_survives(self):
        self.assertEqual(self.request(1,b'bad')[0],0)
        self.assertEqual(self.request(0),(1,b''))


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import patch
from tecknet.hid import feature_sizes, HidDevice, SimulatedDevice, validate_report


class DescriptorTests(unittest.TestCase):
    def test_distinct_reports_and_accumulated_items(self):
        descriptor = bytes.fromhex('85 05 75 08 95 02 b1 02 95 03 b1 02 85 04 96 07 02 b1 02')
        self.assertEqual(feature_sizes(descriptor), {5: 6, 4: 520})

    def test_global_push_pop(self):
        self.assertEqual(feature_sizes(bytes.fromhex('85 05 75 08 95 05 a4 85 04 96 07 02 b1 02 b4 b1 02')), {4: 520, 5: 6})

    def test_truncated_descriptor(self):
        for descriptor in ('96 01', 'fe 04 00 ff'):
            with self.assertRaises(ValueError):
                feature_sizes(bytes.fromhex(descriptor))


class TransportTests(unittest.TestCase):
    def test_ioctl_and_report_id_preserved(self):
        device = object.__new__(HidDevice)
        device.fds = {5: 123}
        def ioctl(fd, request, buf, mutate):
            self.assertEqual((fd, request, buf[0], mutate), (123, 0xC0064807, 5, True))
            buf[:] = bytes.fromhex('05 01 32 37 36 34')
            return 6
        with patch('tecknet.hid.fcntl.ioctl', side_effect=ioctl):
            self.assertEqual(device.transfer(True, bytes.fromhex('05 00 00 00 00 00')), bytes.fromhex('05 01 32 37 36 34'))

    def test_short_transfer_rejected(self):
        device = object.__new__(HidDevice)
        device.fds = {5: 123}
        with patch('tecknet.hid.fcntl.ioctl', return_value=2):
            for get in (True, False):
                with self.assertRaises(OSError):
                    device.transfer(get, bytes.fromhex('05 00 00 00 00 00'))

    def test_invalid_report(self):
        for data in (b'', bytes(520), bytes((5,)) + bytes(519)):
            with self.assertRaises(ValueError):
                validate_report(data)

    def test_same_node_opened_once_and_locked(self):
        with patch('tecknet.hid.discover', return_value=[{4: '/dev/hidraw1', 5: '/dev/hidraw1'}]), \
             patch('tecknet.hid.os.open', return_value=12) as opened, \
             patch('tecknet.hid.os.close') as closed, patch('tecknet.hid.fcntl.flock') as locked:
            device = HidDevice()
            device.close()
            opened.assert_called_once()
            locked.assert_called_once()
            closed.assert_called_once_with(12)

    def test_lock_failure_closes_device(self):
        with patch('tecknet.hid.discover', return_value=[{4: '/dev/hidraw1', 5: '/dev/hidraw1'}]), \
             patch('tecknet.hid.os.open', return_value=12), \
             patch('tecknet.hid.os.close') as closed, \
             patch('tecknet.hid.fcntl.flock', side_effect=BlockingIOError):
            with self.assertRaises(RuntimeError):
                HidDevice()
            closed.assert_called_once_with(12)


if __name__ == '__main__':
    unittest.main()

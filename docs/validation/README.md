# Native Linux validation, 2026-10-04

The installed application is Python/PySide6 and Linux hidraw. No Wine, vendor
executable, Windows DLL, or vendor backend is used for these checks.

The automated suite exercises:

- Native polling and default button reports against the historical vendor
  fixture, byte for byte.
- DPI wire codes, including the INI overrides for 1200/2400 DPI, X/Y stages,
  active-stage ordinals and disabled-stage masks.
- HID feature ioctl numbers, short transfers, descriptor parsing and device locks.
- Native keyboard/media/button and ordinary macro encoders, playback flags,
  movement/delays and buffer allocation around other hardware modes.
- Real Qt widgets loading three modes, changing polling, applying X/Y DPI and
  multi-color lighting, activating a mode, validating edits, recording focused
  keyboard input, preserving existing mappings, and restoring exported state.
- Readback failures, conflicting external edits and atomic JSON import/export.

Run `make test PYTHON=.venv/bin/python` to include the offscreen Qt tests. The
screenshots `native-linux.png`, `native-buttons.png` and `native-macros.png` show
the native Qt application with its own graphics and a simulated device.

`vendor-demo-transfers.json` and `polling-1000.png` are historical evidence from
running the original vendor app through a Wine/DLL bridge against a simulated
mouse. The current native encoder tests consume the captured report bytes; they
do not launch that application or use its encoders. The old bridge was removed.

No physical GM2793-1 is attached. These checks establish native execution and
report construction in simulation. Physical configuration, persistence after
power cycling, matrix readback, macro playback and reconnects remain unverified.

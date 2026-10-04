# TeckNet GM2793-1 — native Linux application

A native PySide6/Qt desktop application and CLI that configure the mouse directly
through Linux `hidraw`. No Wine, Windows executable, DLL, vendor backend, compiler,
or vendor files are needed to build, install, or run the application. Normal
pointer input uses Linux's existing HID driver.

Target: USB `258a:1007`, sensor `0x3104`, firmware identity `32 37 36 34`.
USB IDs and HID report sizes are checked during discovery; the controller checks
firmware identity and sensor before configuration. The model label alone is not
sufficient because other mice reuse the USB ID.

## Install and run

Requires Linux and Python 3.10+. Install the application and its Qt dependency
in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/tecknet-mouse --demo gui
.venv/bin/tecknet-mouse gui
```

For development use `pip install -e .` instead. With the environment activated,
`python -m tecknet` and `tecknet-mouse` also open the GUI. CLI commands can run
from this source checkout with Python's standard library, without importing Qt.

`--demo` never opens hardware; its state is in memory and its window is labeled
Demo. Real mode fails if no matching device is present. With several matching
mice attached, put `--device-index N` before the subcommand.

To grant access to your desktop user:

```sh
sudo install -m 0644 packaging/70-tecknet-gm2793.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

Reconnect the mouse after installing the rule. Run the app as your desktop user.
A hidraw lock prevents competing instances of this application from configuring
the same mouse. No kernel driver replacement is required.

## Desktop application

The window follows the original application's arrangement: button assignments on
the left, a numbered mouse diagram in the middle, collapsible settings on the
right, and profiles plus Restore/Apply along the bottom. Its graphics are drawn
natively. You can optionally use skin images from your own vendor installation:

```sh
tecknet-mouse --demo gui --skin-dir /path/to/original/skins
```

Only `main_nr.png` and `mouse/mouse_nr.png` are read. Original executables,
libraries, and settings encoders are never loaded. Qt controls remain native;
the original MFC rendering is not used.

Features:

- Three hardware modes with independent staged settings; Apply saves and
  activates the selected mode. Reload reads hardware settings again.
- 125/250/500/1000 Hz polling, eight DPI stages, enabled stages, active stage,
  separate X/Y values, and per-stage RGB colors. The DPI choices use the vendor
  INI's sensor mapping, including 1200 and 2400 DPI.
- Lighting effects, speed, brightness, streaming direction, and multi-color
  palettes for breathing, reaction/steady, and flicker effects.
- Button assignments for mouse clicks, scrolling, DPI lock/cycling, polling,
  profile and lighting controls, media keys, and keyboard shortcuts. Clicking a
  numbered diagram button edits it; an additional dialog exposes all 20 matrix
  entries. At least one left-click assignment must remain.
- A named macro library, text import/export, focused keyboard recording,
  keyboard/modifier and mouse down/up, movement, wheel events, and event delays.
  Playback supports repeat count, until released, and until pressed again.
- Named local profiles, import/export, raw general-profile backup import, and
  Restore defaults staged for review before Apply.
- GNOME desktop pointer speed, acceleration, handedness, double-click interval,
  and natural scrolling. On other desktops, use their Mouse settings. This panel
  is optional and does not affect the firmware features. Demo changes stay local.

Apply merges changes into a fresh general-profile read and verifies readback.
Unknown general payload bytes survive edits; button matrices are only written
when changed. Button readback prevents silently resetting existing assignments.
Macros are assigned to buffers unused by other hardware modes. Existing opaque
macro assignments are preserved. Firmware macro contents cannot be read back;
exported native profiles contain macro source created in this app, not macros
previously programmed by other software.

The macro library, local presets, and known native macro associations are saved
atomically in `$XDG_CONFIG_HOME/tecknet-gm2793/library.json` (default
`~/.config/tecknet-gm2793/library.json`). Demo uses `demo-library.json` separately.
Closing the window exits the app. Unsaved staged firmware edits are discarded.

## CLI

```sh
python3 -m tecknet list
python3 -m tecknet info
python3 -m tecknet show 1
python3 -m tecknet select 2
python3 -m tecknet set 1 --polling 1000
python3 -m tecknet set 1 --dpi 500 1200 2400 4000 8000 --active-slot 2
python3 -m tecknet set 1 --effect 2 --brightness 4 --color '#00aaff'
python3 -m tecknet bind 1 6 'key:CTRL+C'
python3 -m tecknet dump 1 profile1.bin
python3 -m tecknet export 1 profile1.json
python3 -m tecknet import 2 profile1.json
python3 -m tecknet import 1 profile1.bin
python3 -m tecknet buttons 1 examples/buttons.json
python3 -m tecknet macro 1 1 examples/macro.txt --button 6 --matrix examples/buttons.json
```

`bind` changes one matrix entry and preserves the others. `buttons` takes twenty
complete action names or integer codes. `macro` takes an explicit matrix and
buffer ID; the controller rejects a buffer used by another mode. GUI native
profiles include named macros and allocate buffers on import. CLI general-profile
exports are also accepted by the GUI. A raw general backup excludes buttons and
macros. See [examples](examples/) and `python3 -m tecknet --help`.

`make install` additionally installs a source launcher and desktop entry under
`~/.local` (`PREFIX`/`DESTDIR` are supported). That source launcher uses system
Python, so PySide6 must be available there. For virtual-environment installations,
use the installed `tecknet-mouse` entry point instead. The udev rule is installed
separately.

## Validation

```sh
make test PYTHON=.venv/bin/python
make test-gui PYTHON=.venv/bin/python
```

Qt tests run headlessly using its offscreen platform. Native encoders reproduce
the captured vendor polling and default button reports byte for byte. Tests also
exercise real Qt widgets, macro recording/allocation, multi-color lighting,
DPI encodings, hidraw ioctls and locking, import/export, conflict detection,
report ordering, and readback failures. See [validation evidence](docs/validation/README.md)
and [protocol notes](docs/protocol.md).

No physical GM2793-1 is available in this environment. Hardware writes, persistent
storage, unplug/reconnect behavior, and macro playback still need device testing.
The simulator stores reports but does not play macros or emulate all firmware
behavior. Physical DPI changes require Reload; live notification reports are not
implemented. Vendor encrypted macro files and bullet/recoil macro formats are
not implemented. Research tools under `re/` are historical and are excluded from
the installed application.

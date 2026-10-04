# TeckNet GM2793-1 on Linux

This project has a working Linux HID backend and a Wine compatibility frontend
that uses the **exact original TeckNet UI**. It is not yet a fully native UI port.
The Windows `Lowerdev.dll` is replaced with a rebuilt bridge; mouse configuration
reports go through a local Python broker to Linux `hidraw`. Normal pointer input
continues to use Linux's existing HID driver.

Target: GM2793-1, vendor configuration `258a:1007`, sensor `0x3104`.
The USB ID and feature descriptors must match; the label alone is not sufficient.

## Run

Requirements: Python 3.10+, Wine with 32-bit application support, and
`i686-w64-mingw32-gcc` to compile the replacement DLL. No Python dependencies.
Place the original vendor application and assets in `vendor/original/`. Proprietary binaries and decompiled vendor sources are
not included in this repository. The supplied files remain unmodified.

```sh
make bridge
python3 -m tecknet --demo gui    # exact UI, simulated mouse
# Optional: add --trace transfers.jsonl after gui to record feature transfers
python3 -m tecknet list         # detect USB interfaces without opening them
python3 -m tecknet info         # read firmware/profile from the connected mouse
python3 -m tecknet dump 1 profile1.bin
python3 -m tecknet gui          # original UI backed by Linux HID
```

`--demo` never opens a physical mouse. The real mode fails if the mouse is absent;
it never silently falls back to demo. If multiple matching mice are attached,
select one with `--device-index N` before the subcommand.

For access without running the UI as root:

```sh
sudo install -m 0644 packaging/70-tecknet-gm2793.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

Reconnect the mouse after installing the rule. It grants access to the active
local desktop user through `uaccess`. Run the application as that user.

The Wine app and prefix live in `$XDG_CACHE_HOME/tecknet-gm2793/` (default:
`~/.cache/tecknet-gm2793/`), with separate `demo` and `device` directories.
The launcher loads the replacement DLL explicitly and starts an authenticated
broker on a randomly allocated localhost port. Exiting the vendor application stops the broker. Its window close button
minimizes to the tray; use the tray Exit action or Ctrl+C in the launching terminal.
Do not launch multiple copies against the same physical mouse.

## Current validation and limits

The DLL compiles with warnings treated as errors. Unit tests exercise the HID
report descriptor parser, Linux ioctl numbers, short-read detection, bridge
authentication and profile exchanges. The original UI was exercised against
the simulated device through the rebuilt bridge: startup, Apply, and changing
polling from 500 to 1000 Hz. The resulting profile writes differed only in
report byte 10 (3 to 4). A captured vendor exchange is replayed by the tests;
see [validation evidence](docs/validation/README.md).

No physical GM2793-1 is available in this environment. Real configuration writes,
firmware persistence and unplug/reconnect behavior remain unverified. The broker
forwards the original UI's feature reports, including button/macro reports;
it does not independently reimplement those encoders. Notification input reports
are not implemented, so physical DPI changes do not update the UI live.
The simulator preserves general profile writes but does not emulate macro
playback or the complete firmware behavior. Export important profiles before
using Apply on hardware.

A fully native Linux UI and independently implemented macro/button encoders
remain future work. The compatibility frontend preserves every vendor screen
while providing a usable path to test the Linux transport now.

```sh
make test
```

See [protocol notes](docs/protocol.md) for evidence and report layouts.

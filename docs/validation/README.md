# Sandbox validation, 2026-10-04

Built `re/emulator/lowerdev_linux.c` as a 32-bit DLL with
`i686-w64-mingw32-gcc -shared -O2 -Wall -Wextra -Werror ... -lws2_32`.
Ran the original application under Wine on an Xvfb display, using that DLL,
the Python broker, and `SimulatedDevice`. No physical USB device was involved.

Verified:

- Original English UI opens, loads its skin assets, and retrieves firmware ID,
  current profile, and both visible hardware modes through the bridge.
- Clicking Apply completes button-matrix and general-profile feature writes.
- Selecting 1000 Hz changes general-report byte 10 from 3 to 4; all other
  519 report bytes are identical to the preceding 500 Hz write.
- The vendor applies the polling selection immediately (`ApplyNow=1`), so the
  fixture contains both the automatic write and a subsequent explicit Apply.

`vendor-demo-transfers.json` contains the captured report requests and replies,
with timestamps removed. Unit tests replay the exchange through the broker.
`polling-1000.png` shows the original UI after the change.

This establishes compatibility of the Windows frontend, rebuilt DLL, and
Linux broker in simulation. It does not establish compatibility with physical
firmware, macro playback, or persistent storage.

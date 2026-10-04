# Historical research tools

These files document the reverse engineering used to recover the mouse protocol.
The native Linux application does not import, build, install or execute them.

- `emulator/lowerdev_emu.c` and its export definition are the historical Windows
  sandbox emulator used to obtain the vendor transfer fixture.
- `scripts/ExportDecomp.java` is the Ghidra function export helper.

The original vendor executables, assets and decompiled sources remain untracked.
No proprietary code is required to run or distribute the native application.

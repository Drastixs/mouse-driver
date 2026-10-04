# GM2793-1 protocol evidence

These notes are derived from the local vendor `Cfg.ini`, Ghidra output in
`re/decomp/`, and sandbox feature-report exchanges. They are not a USB capture
from a physical mouse. Function names below are Ghidra address labels.

## Device and transport

`Cfg.ini [MS]`: VID `258a`, PID `1007`, sensor `3104`, PSD bytes `32 37 36 34`.
`FUN_00412820` opens vendor usage page `ff00`, usage `1`, with feature lengths
6 and 520 (callbacks `FUN_00412700` / `FUN_00412720`). Linux may expose these on
separate hidraw nodes; discovery groups nodes under the same physical USB parent
and checks their report descriptors.

Report IDs are included in lengths: command `05` is 6 bytes; data `04` is 520.
`FUN_00413000` sends command data; `FUN_004130d0` retrieves the command reply.
`FUN_004131b0` sends a 520-byte data report. `FUN_00413270` reads a data report
and copies 500 payload bytes beginning at report offset 8.

## Commands

| Feature report sent | Reply/data |
| --- | --- |
| `05 01 00 00 00 00` | Firmware identification, expected `05 01 32 37 36 34` |
| `05 02 00 00 00 00` | Current profile in byte 2 |
| `05 02 PP 00 00 00` | Select hardware profile PP, numbered 1..3 |
| `05 11 00 00 00 00` | Read profile 1 with GET feature `04`, length 520 |
| `05 21 00 00 00 00` | Read profile 2 |
| `05 31 00 00 00 00` | Read profile 3 |

Read operations wait 25 ms between selecting data and retrieving it. The vendor
also inserts delays and retries. The bridge preserves the vendor's timing when
running the UI.

## Data writes

`FUN_00413550`: general profile write, with bytes:
`04 PP 00 7b 00 00 00 00 <payload>`, PP = `11`, `21`, or `31`.
The vendor apply routine calls it with **140 payload bytes** (`0x8c`) even though
the header field is `0x7b`. Treat that field as opaque, not a payload length.
The rest of the 520-byte report is zero-filled by the vendor.

`FUN_00413600`: button matrix write, opcode `12`, `22`, or `32`, byte 3 `50`,
80-byte matrix at report offset 8. There are 20 four-byte matrix entries.

`FUN_004136b0`: macro write starts `04 30 02 00 00 00 00 00`, then buffer ID
at offset 8 and macro content beginning at offset 9. The apply routine passes
510 macro bytes. Macro encoding is not independently implemented yet.

The Linux broker passes feature reports unmodified instead of inferring layouts
from decompiler guesses. That preserves the vendor encoders for the entire UI.

## General payload fields (offsets relative to report byte 8)

| Offset | Meaning and evidence |
| --- | --- |
| `00` | Vendor encoder writes `64` |
| `01` | Sensor code `13` maps to `3104` (`FUN_0046fec0`) |
| `02` | Low nibble polling code: 1=125, 2=250, 3=500, 4=1000 Hz; high bit separate X/Y DPI (`FUN_00415090`) |
| `03` | Low nibble enabled DPI count; high nibble current ordinal among enabled slots |
| `04` | DPI disabled-slot bitmask; bit 0 is slot 1 |
| `05..14` | DPI encoded values, one per slot or pairs in separate-X/Y mode |
| `15..2c` | Eight RGB triplets, channel order follows vendor configuration |
| `2d` | Lighting effect selector |
| `2e` | Streaming speed/brightness fields for effect 1 |
| `7a` | Lighting off state in the configured protocol branch |

DPI is **not generally `DPI / 250`**. `FUN_0046fd80` looks up the sensor's DPI
value in an initialized table. For `3104`, the default table in the initialization
routine is `[250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 2750,
3000, 3250, 3500, 3750, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500, 8000]`;
wire values are the **one-based indexes**. For example, 4000 = 16 and 8000 = 24.
The INI's `DPISET` lists 1200 and 2400 in two places; these differ from the
initialized encoder table. Keep the vendor encoder for compatibility until
those values have been checked on hardware.

## Emulator repair

The original sandbox emulator stored one command handle. The vendor also opens
a notification interface whose callback accepts the offered command caps,
replacing that stored handle. Subsequent SetFeature calls on the original handle
failed. The repaired emulator dispatches valid reports by their IDs/lengths;
the new Linux DLL forwards reports independently of that bookkeeping.

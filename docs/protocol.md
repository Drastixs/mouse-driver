# GM2793-1 native protocol evidence

Evidence comes from local vendor configuration, Ghidra function exports and the
historical sandbox feature exchanges in `validation/vendor-demo-transfers.json`.
These are not captures from a physical mouse. The native application implements
the encoders independently in `tecknet/protocol.py` and needs no vendor files.

## Transport and identity

VID `258a`, PID `1007`, sensor `3104`, identification `32 37 36 34`.
`FUN_00412820` opens vendor usage page `ff00`, usage 1, with feature lengths 6
and 520 (`FUN_00412700` / `FUN_00412720`). Linux discovery checks USB IDs and
report sizes and groups interfaces by physical USB parent; it does not currently
validate the usage page. The controller additionally checks firmware identity;
`Profile` checks the sensor code.

Report lengths include the ID: command report `05` is 6 bytes; data report `04`
is 520 bytes. Configuration uses `HIDIOCGFEATURE` / `HIDIOCSFEATURE` via hidraw.
Command reads wait 25 ms after SET, data writes wait 22 ms, matching the vendor's
20–25 ms spacing. The controller validates all planned reports before writing.

| Command SET | Meaning |
| --- | --- |
| `05 01 00 00 00 00` | GET command reply must be `05 01 32 37 36 34` |
| `05 02 00 00 00 00` | Current profile in reply byte 2 |
| `05 02 PP 00 00 00` | Select profile PP (1–3) |
| `05 11 00 00 00 00` | Read profile 1 using GET report `04`, 520 bytes |
| `05 21 00 00 00 00` | Read profile 2 |
| `05 31 00 00 00 00` | Read profile 3 |

## General settings

`FUN_00413550` writes `04 PP 00 7b 00 00 00 00 <140 payload bytes>`, with PP
`11`/`21`/`31`. `7b` is opaque, not a payload length. Remaining bytes are zero.
The native writer mirrors this framing. It preserves unknown bytes within the
140-byte general payload and merges changed bytes into a fresh hardware read.
It rejects overlapping external edits, writes, then verifies general readback.

Offsets below are relative to report byte 8. `FUN_00415090` is the source for
polling and DPI encoding; `FUN_004165d0` is the lighting branch for vendor `MsFw=3`.

| Payload offset | Meaning |
| --- | --- |
| `00` | Vendor encoder uses `64` |
| `01` | `13` identifies the `3104` sensor (`FUN_0046fec0`) |
| `02` | Low nibble: 1=125, 2=250, 3=500, 4=1000 Hz; bit 7: separate X/Y |
| `03` | Low nibble: enabled stage count; high nibble: one-based active ordinal among enabled stages |
| `04` | Disabled-stage bitmask, bit 0 = stage 1 |
| `05..14` | Eight DPI values, or eight interleaved X/Y pairs |
| `15..2c` | Eight per-stage RGB triplets; configured default channel order is R,G,B |
| `2d` | Lighting effect code 0–11; 0 selects off |
| `2e` | Effect 1: brightness high nibble, speed low nibble |
| `30`, `31..33` | Effect 2: brightness high nibble, RGB |
| `34`, `35`, `36..4a` | Effect 3: brightness/speed, color count, color palette |
| `4b`, `4c` | Effects 4/5: brightness/speed |
| `4d`, `4e..65` | Effect 6: brightness high nibble, palette |
| `66`, `67..6c` | Effect 7: brightness/speed, colors |
| `6d`, `6e` | Effects 8/9: brightness/speed |
| `6f`, `70` | Effects 10/11: speed low nibble |

Lighting labels come from the English vendor text resources and the configured
LedOpt overrides. The native editor supports one color for effect 2, up to seven
for effect 3, eight for effect 6, and two for effect 7. Effect 11 retains a numeric
label. Effect 1 also supports its direction byte at offset 2f.
The earlier notes incorrectly implied `7a` was the off flag for this target.
That offset is used in other firmware branches; it is not written here.

DPI values use **one-based table indexes**, not DPI divided by 250. The sensor
configuration loader at `OemDrv.exe.c` lines 77807–77843 replaces the initialized
table with `Cfg.ini` DPISET and generates one-based wire codes when DPIHW is
absent. For this model the values are:

`250, 500, 750, 1000, 1200, 1500, 1750, 2000, 2250, 2400, 2750, 3000,
3250, 3500, 3750, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500, 8000`.

1200 encodes as 5; 2400 as 10; 4000 as 16; 8000 as 24. The default initialized
table has 1250/2500 in two positions, but the vendor overrides them at runtime.
Disabled slots with unknown/zero codes are displayed with editable placeholders;
unchanged UI settings preserve the original bytes.

## Button matrix

`FUN_00413600` writes `04 PP 00 50 00 00 00 00 <80 matrix bytes>`, PP =
`12`/`22`/`32`. Entries are twenty little-endian 32-bit codes.
`FUN_00413e20` supplies the encodings below. The captured fixture verifies the
entire recovered default matrix, including entry ordering.

| Function | Code |
| --- | --- |
| Left / right / middle | `00000111` / `00000211` / `00000411` |
| Forward / back | `00001011` / `00000811` |
| Double / triple click | `02320131` / `03320131` |
| DPI up / down / cycle | `00000141` / `00000241` / `00000041` |
| Lighting toggle / effect cycle | `00000850` / `00000750` |
| Profile cycle / polling cycle | `00000650` / `00000450` |
| Scroll up / down | `00000112` / `0000ff12` |
| Tilt left / right | `0000ff13` / `00000113` |
| Disable | `00000150` |
| Keyboard shortcut | bytes `21 MOD KEY1 KEY2` |
| Media | low byte `22`, function bits in the following bytes (`FUN_00413c40`) |
| Macro | bytes `70 BUFFER MODE REPEATS` |

Modifier mask follows HID order: left Ctrl/Shift/Alt/Super bits 0–3, right bits
4–7. KEY1/KEY2 are HID keyboard usages. Macro mode 1 repeats a count, 4 runs until
release, 2 runs until a subsequent button press (`FUN_00413e20`). Native macros use the normal macro path, not bullet/recoil `60`.

Button matrix reads use commands 12/22/32 followed by GET feature report 04,
with twenty little-endian entries at offset 8. This read path is independently
corroborated by [libratbag’s SinoWealth implementation](https://github.com/libratbag/libratbag/blob/master/src/driver-sinowealth.c).
It is tested in simulation, not on this physical mouse. Native general Apply
never writes a matrix implicitly. Button writes verify matrix readback and
reject stale edits. Macro buffer contents lack a supported readback path.

## Native macros

The encoder vtable in the local executable pairs `FUN_00413e20` with
`FUN_004145d0`; the native implementation follows that ordinary macro encoder.
`FUN_00414980` is a separate bullet macro encoder and is not implemented.

`FUN_004136b0` wraps ordinary macro content as:
`04 30 02 00 00 00 00 00 BUFFER <510 bytes of macro content> 00`.
Buffers 1–14 are used here; firmware limits require hardware verification.
The content starts with a big-endian 16-bit event count, followed by three-byte
records: `TYPE_DELAY_HIGH DELAY_LOW VALUE`. Maximum 168 records, zero-filled tail.

High nibble types: 1 mouse button, 2 X movement, 3 Y movement, 4 wheel, 5 keyboard
usage, 6 modifier mask. Bit 7 means release for key/button/modifier records.
Movement is a signed byte. The low nibble of the first byte holds delay bits 8–11;
delay low byte follows. Native input permits 1–4095 ms and mirrors the vendor's
promotion of a zero low delay byte to 1 (e.g. 256 becomes 257 ms on the wire).

Native Apply sends macro buffers, then the button matrix, then general settings.
Macro buffers are shared across profiles. Simulation records these writes but
does not execute them. Neither real playback nor persistence is verified.

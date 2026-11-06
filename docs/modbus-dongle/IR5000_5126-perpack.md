# IR 5000-5126 — per-pack battery bank (undocumented; live on a `0x4xx` pack)

> **Dongle Modbus**, input registers (func `0x04`, read-only). **Undocumented** —
> not in the EG4 18kPV-12LV spec PDF, not in `modbus_map.h`'s 0-152 map. See the
> [index](README.md). Recovered from the factory `ceaa-07xx` image; full analysis
> in [`docs/34` §2b](../34-multi-battery-can.md), **confirmed live and decoded in
> [`docs/34` §2d](../34-multi-battery-can.md#2d-live-capture-the-5000-bank-is-populated-on-a-production-12000xp)**.

## Status up front

The factory firmware **serves** a per-pack battery bank on input registers
**5000-5126**, and a production-12000XP capture (same `ceaa`/V2.06 firmware family)
shows the dongle **polling and uploading this window to the cloud every cycle**,
alongside IR 0-380. With two packs attached it reads back two populated per-pack
records (bases 5000 and 5030) named `Battery_ID_01` / `Battery_ID_02` — **live
per-pack telemetry**, see [`docs/34` §2d](../34-multi-battery-can.md#2d-live-capture-the-5000-bank-is-populated-on-a-production-12000xp).

It is fed by CAN **`0x4xx`** per-pack frames. **The three EG4 battery images checked**
(`BATT_IN280-Z03T13`/EG4-LL, `BATT_AW280-Z02T30`/EG4-LL, `BATT_WM314-Z03T21`/EG4-314)
do **not** emit `0x4xx` (they stream `0x3xx` extended frames the ARM parses to
unserved internal scalars), so the bank reads all-zero **with those packs**. A pack
that speaks the `0x4xx` per-pack protocol — as in the §2d capture — populates it. So:

- **Live** on a `0x4xx`-per-pack (Pylontech-family) pack: per-pack V/I/SOC/SOH, cell
  min/max V and T, limits, version and an ASCII pack id, one 30-slot record per pack.
- **Dormant** with the EG4-LL `0x3xx` packs — for those, per-battery data on the
  dongle is the aggregate [`IR 81-106 BMS block`](IR081_106-BMS.md) only.

## Addressing

```
input register = 5000 + 30*pack_slot + field      field = 0..26 (27 u16 per pack)
```

- **30 register slots per pack**, 27 used; four pack slots visible per poll at bases
  **5000 / 5030 / 5060 / 5090**.
- A page index cycles for **>4 packs** (pack index is 5 bits → up to 32 packs page
  through 5000-5126). A slot reads **0** when that pack is not present.
- Served by the getter `sub_08020cc0`, gated by a pack-present bitmask
  (`0x2000a770`) and page count (`0x2000a8ae`), from a per-pack array
  (`0x2000691c`, stride `0x36`). Machine-readable map:
  [`include/inv/perpack_map.h`](../../include/inv/perpack_map.h).

## Field layout (per pack) — structure and meaning both confirmed

Each field is a **little-endian u16, unscaled** (the parser `sub_080205d4` is a
straight byte copy). Fields are sourced from CAN frames
`id = 0x400 | (subtype<<5) | pack`. The **meaning** column is from the production
capture ([`docs/34` §2d](../34-multi-battery-can.md#2d-live-capture-the-5000-bank-is-populated-on-a-production-12000xp));
**bold** meanings are cross-checked against a known-scale aggregate register in the
same capture, the rest are best-read from magnitude.

| field | reg (pack@5000) | CAN id (subtype) | source bytes | meaning (scale) |
|---|---|---|---|---|
| 0-1 | 5000-5001 | `0x400` (0) | b0:1, b2:3 | (zero in capture) |
| 2 | 5002 | `0x400` (0) | b4 (lo) ‖ b7 (hi) — split pair | status/flags (`0xc002`) |
| 3 | 5003 | `0x400` (0) | b5:6 | charge-current limit, prob. (0.1 A) |
| 4 | 5004 | `0x420` (1) | b0:1 | **charge-voltage ref (0.1 V, = IR83)** |
| 5 | 5005 | `0x420` (1) | b2:3 | discharge-current limit, prob. (0.1 A) |
| 6-7 | 5006-5007 | `0x420` (1) | b4:5, b6:7 | limits, prob. |
| 8 | 5008 | `0x440` (2) | b0:1 | **pack voltage (0.01 V; aggregate IR4=0.1 V)** |
| 9 | 5009 | `0x440` (2) | b2:3 | **pack current (signed, 0.1 A)** |
| 10 | 5010 | `0x440` (2) | b4:5 | **SOC (lo) ‖ SOH (hi), % (= IR5)** |
| 11 | 5011 | `0x440` (2) | b6:7 | cycle count, prob. |
| 12 | 5012 | `0x460` (3) | b0:1 | **max cell temp (= IR103)** |
| 13 | 5013 | `0x460` (3) | b2:3 | **min cell temp (= IR104)** |
| 14 | 5014 | `0x460` (3) | b4:5 | **max cell voltage (mV, = IR101)** |
| 15 | 5015 | `0x460` (3) | b6:7 | **min cell voltage (mV, = IR102)** |
| 16 | 5016 | `0x480` (4) | b0:1 | status/flags (differs per pack) |
| 17 | 5017 | `0x480` (4) | b2:3 | firmware/version (`0x0101`) |
| 18 | 5018 | `0x480` (4) | b4:5 | version/protocol (`0x0203`) |
| 19-25 | 5019-5025 | `0x4A0`/`0x4C0` (5,6) | b0:7 / b0:5 | **ASCII pack id** (`"Battery_ID_0N"`) |
| 26 | 5026 | `0x4C0` (6) | b6 (u8, hi 0) | (string tail / zero) |

**Field meaning is confirmed** by the §2d capture — the bolded rows against
known-scale aggregate registers, the rest by magnitude. Note the ASCII id in fields
19-25 is **not** a firmware literal (absent from `ceaa-07xx_vE_260214.bin` and the battery
image), proving these bytes are copied straight off CAN. `perpack_map.h` keeps the
**structural** names (`PP_S<subtype>_W<word>`) as the stable index and now carries
the semantic read in comments.

## Where the data comes from

CAN **`0x4xx`** → parser `sub_080205d4` → per-pack array `0x2000691c[pack]` +
presence bitmask `0x2000a770` / count `0x2000a8ae` → getter `sub_08020cc0` →
input registers 5000-5126 → dongle.

Proven end-to-end two ways: in the harness with **synthetic** `0x4xx` frames
(`tests/test_arm_sim_factory_only.py::test_per_pack_telemetry_reaches_modbus`), and
**in the wild** by a production-12000XP capture that uploads this exact window with
two real packs decoded ([`docs/34` §2d](../34-multi-battery-can.md#2d-live-capture-the-5000-bank-is-populated-on-a-production-12000xp)).
The EG4-LL packs never drive it — see [`docs/34` §2b](../34-multi-battery-can.md)
for the dormancy proof (their TX table has no `0x4xx`; the `0x311-0x321`/`0x370-0x381`
extended frames go to internal scalars via `sub_08021b68`, which the Modbus getters
do not read) — but a `0x4xx`-per-pack pack does, as §2d shows.

## Contrast with the live battery surface

| what | register(s) | live? |
|---|---|---|
| aggregate pack SOC/SOH, V/I/T, limits, faults, cell min/max | [IR 5](IR005-SOC_SOH.md), [IR 81-106](IR081_106-BMS.md) | ✔ yes, any pack (CAN `0x351/355/356/359`) |
| **per-pack** V/SOC/cell detail, one block per stacked pack | **IR 5000-5126** (this doc) | ✔ on a `0x4xx` per-pack pack (captured live, §2d); ✗ on EG4-LL `0x3xx` packs |

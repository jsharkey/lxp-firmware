# IR 5000-5126 — per-pack battery bank (undocumented; dormant on the EG4-LL pack)

> **Dongle Modbus**, input registers (func `0x04`, read-only). **Undocumented** —
> not in the EG4 18kPV-12LV spec PDF, not in `modbus_map.h`'s 0-152 map. See the
> [index](README.md). Recovered from the factory `ceaa-07xx` image; full analysis
> in [`docs/34` §2b](../34-multi-battery-can.md).

## Status up front

The factory firmware **serves** a per-pack battery bank on input registers
**5000-5126**, and it is a real, reachable part of the dongle surface (the dongle
is a transparent conduit, so a cloud poll of 5000+ is relayed like any other). But
on the **attached EG4-LL pack it is DORMANT** — it reads back all-zero — because it
is fed only by CAN **`0x4xx`** per-pack frames, which that pack does not emit (it
uses `0x3xx`, handled on a different path that lands in internal scalars no getter
reads). So:

- **Documented here** because it is a real, undocumented part of the register
  surface, and a different battery (one that streams per-pack telemetry on CAN
  `0x4xx`) would populate it.
- **Not a live source on this system.** For the attached pack, per-battery data on
  the dongle is limited to the aggregate [`IR 81-106 BMS block`](input-081_106-BMS.md).

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

## Field layout (per pack) — structure authoritative, meaning NOT confirmed

Each field is a **little-endian u16, unscaled** (the parser `sub_080205d4` is a
straight byte copy). Fields are sourced from CAN frames
`id = 0x400 | (subtype<<5) | pack`:

| field | reg (pack@5000) | CAN id (subtype) | source bytes |
|---|---|---|---|
| 0 | 5000 | `0x400` (0) | b0:1 |
| 1 | 5001 | `0x400` (0) | b2:3 |
| 2 | 5002 | `0x400` (0) | b4 (lo) ‖ b7 (hi) — split pair |
| 3 | 5003 | `0x400` (0) | b5:6 |
| 4-7 | 5004-5007 | `0x420` (1) | b0:1, b2:3, b4:5, b6:7 |
| 8-11 | 5008-5011 | `0x440` (2) | b0:1, b2:3, b4:5, b6:7 |
| 12-15 | 5012-5015 | `0x460` (3) | b0:1, b2:3, b4:5, b6:7 |
| 16-18 | 5016-5018 | `0x480` (4) | b0:1, b2:3, b4:5 |
| 19-22 | 5019-5022 | `0x4A0` (5) | b0:1, b2:3, b4:5, b6:7 |
| 23-25 | 5023-5025 | `0x4C0` (6) | b0:1, b2:3, b4:5 |
| 26 | 5026 | `0x4C0` (6) | b6 (u8, hi 0) |

**Field *meaning* is not pinned.** The parser applies no scaling or naming, so the
semantics live in the sending battery's frame definitions. The attached EG4-LL pack
does not emit these `0x4xx` frames, so its image can't name them either; confirming
them needs a battery that uses the `0x4xx` per-pack protocol, or a live CAN capture
from one. The names in `perpack_map.h` are therefore **structural**
(`PP_S<subtype>_W<word>`), not semantic.

## Where the data comes from

CAN **`0x4xx`** → parser `sub_080205d4` → per-pack array `0x2000691c[pack]` +
presence bitmask `0x2000a770` / count `0x2000a8ae` → getter `sub_08020cc0` →
input registers 5000-5126 → dongle.

Proven end-to-end in the harness with **synthetic** `0x4xx` frames
(`tests/test_arm_sim_factory_only.py::test_per_pack_telemetry_reaches_modbus`): the
serving path works. The attached pack simply never drives it — see
[`docs/34` §2b](../34-multi-battery-can.md) for the dormancy proof (the pack's TX
table has no `0x4xx`; its `0x311-0x321`/`0x370-0x381` extended frames go to internal
scalars via `sub_08021b68`, which the Modbus getters do not read).

## Contrast with the live battery surface

| what | register(s) | live on this pack? |
|---|---|---|
| aggregate pack SOC/SOH, V/I/T, limits, faults, cell min/max | [IR 5](input-005-SOC_SOH.md), [IR 81-106](input-081_106-BMS.md) | ✔ yes (CAN `0x351/355/356/359`) |
| **per-pack** V/SOC/cell detail, one block per stacked pack | **IR 5000-5126** (this doc) | ✗ no — needs a CAN-`0x4xx` per-pack battery |

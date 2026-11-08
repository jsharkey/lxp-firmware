# IR 108-112 — auxiliary temperatures (dormant on ceaa-07xx)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md). Spec-only (`idx`) group documented under T26.

| reg | name | unit | note |
|---|---|---|---|
| IR 108 | T1 | 0.1 °C | "12K BT" auxiliary temperature |
| IR 109-112 | — | — | reserved / unassigned in the published map |

The tail of the IR 81-112 **BMS block**. IR 108 is the spec's "T1 / 12K BT"
auxiliary temperature; IR 109-112 are unassigned slots.

## Classification / provenance — dormant

**These read `0` and have no observed source on ceaa-07xx** (empirically verified,
T26). Booting the RTOS harness on the factory image and reading IR 104-120 returns
`0` for IR 108-112, and feeding a USART2 safety frame does not move them (they are not
in the safety-CPU getter sweep, [`docs/33`](../../33-usart2-telemetry-bank.md) /
`SAFETY_TELEMETRY`). The BMS pack temperature the firmware *does* serve lands on IR 105
(MaxCellT) / IR 67 (T_BAT), not here — in our firmware `IR_T1` (108) is referenced
nowhere outside the register map, and the factory leaves it `0` as well. So IR 108-112
are **dormant placeholders** on this image (the "12K BT" sensor is not wired on the
12000XP build); they are not a parity gap.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Dormant parity (T26):** [`test_arm_sim.py`](../../../tests/test_arm_sim.py)
  `test_aux_temp_regs_dormant` reads IR 108-112 on both images and asserts they are all
  `0` (no phantom data) — the externally observable fact for a dormant register.
- **Whole-surface parity (T23):** also read and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) (the **match** bucket, both `0`).

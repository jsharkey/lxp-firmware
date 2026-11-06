# IR 71-75 — AutoTest (grid-protection self-test)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](registers.md).

| reg | name | unit | note |
|---|---|---|---|
| IR 71 | AutoTest status | bits | bit0-3 start, bit4-7 status, bit8-11 step |
| IR 72 | wAutoTestLimit | 0.1 V / 0.01 Hz | V or F limit by step |
| IR 73 | uwAutoTestDefaultTime | ms | |
| IR 74 | uwAutoTestTripValue | 0.1 V / 0.01 Hz | |
| IR 75 | uwAutoTestTripTime | ms | |

Step codes (IR 71 bit8-11): 1 V1L, 2 V1H, 3 F1L, 4 F1H, 5 V2L, 6 V2H, 7 F2L, 8 F2H.

## Where the data comes from / how it's driven

**ARM-local self-test engine.** The grid-protection AutoTest is run by the ARM
(`sub_0801f596`, the AutoTest/self-test path also used for the manual relay
override — [`docs/18`](../../18-power-path-relays.md)). It is **started** by writing
the holding register **`HR 98` AutoTestStart** (`0-1`); the IR 71-75 block reports
progress/results back to the dongle.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

_No automated test exercises this register yet — a focused test is welcome._

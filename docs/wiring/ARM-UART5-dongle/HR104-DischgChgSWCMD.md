# HR 104 — DischgChgSWCMD (discharge↔charge command)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](registers.md). Spec-only (`idx`) register documented under T26.

| reg | name | range | note |
|---|---|---|---|
| HR 104 | DischgChgSWCMD | 0-2 | force discharge / charge command |

A **command register** that forces the battery power direction: `0` = automatic
(normal scheduling), and the non-zero values command a forced discharge vs forced
charge switch (the "software" discharge/charge command, distinct from the
voltage/SOC schedule gates). It is a momentary control input, not a stored
measurement.

## Classification / provenance

**Command register, idle 0.** On the canonical 07 image both the factory and ours
read **0** (idle / automatic) in the seeded bare-boot state — HR 104 is in the T23
**match** bucket ([`regsweep-scoreboard.md`](regsweep-scoreboard.md) /
[`regsweep_expected.py`](../../../tests/regsweep_expected.py)), not a "no-default"
persisted setting. It is *not* in our persistence map
([`settings_map.h`](../../../include/inv/settings_map.h)) — a command, consumed by the
power-control path rather than stored. The downstream effect (how a forced
discharge/charge command overrides the schedule gates) relates to the T15
charge/discharge gate work and is a hand-off.

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **Whole-surface parity (T23):** HR 104 is read on both images and diffed in
  [`test_regsweep.py`](../../../tests/test_regsweep.py) — **match** (ours == factory ==
  0 idle). A behavioural test (command → forced power direction) needs the
  power-control consumer modelled (T15 follow-on), noted as a hand-off.

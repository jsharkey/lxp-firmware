# IR 10000–10039 — Daybreak capability & feature status (discovery block)

> **Dongle Modbus**, input registers (func `0x04`, read-only). Authoritative.
> See the [index](registers.md) and its "Address-space allocation" section.
> **Daybreak-only.** These registers exist only in our firmware built with
> `ENABLE_DAYBREAK=1`; the factory firmware doesn't have them. Design rationale:
> [`docs/45`](../../45-daybreak-feature-flags.md).
> **Status: ⬜ allocated, not implemented** (task T28 in [`docs/39`](../../39-parity-roadmap.md)).

This is Daybreak **block 0, IR side**: the only Daybreak block that answers while
every feature flag is clear, and it holds no feature behaviour. It tells a client
(1) whether it is talking to Daybreak at all, and (2) which features exist, which
are switched on, and which are actually running. The write side is
[`HR10000_10039-Daybreak-feature-control.md`](HR10000_10039-Daybreak-feature-control.md).

## Map

| IR | name | meaning |
|---|---|---|
| 10000–10001 | `DAYBREAK_MAGIC` | `0x4441`, `0x5942`: ASCII `"DA"`, `"YB"` (high byte first in each word's value; on the little-endian dongle wire the bytes appear as `41 44 42 59`). **The factory reads `0, 0`.** |
| 10002 | `DAYBREAK_SCHEMA` | Daybreak register-schema version, `major << 8 \| minor`. `major` bumps only on an incompatible change to block 0. |
| 10003 | `DAYBREAK_CTL_STATUS` | bit 0 `safe_mode`: booted with the mask forced to 0 (front-panel chord, docs/45 §7) · bit 1 `dirty`: running state ≠ saved snapshot · bit 2 `last_rejected`: the most recent `FEAT_EN`/`FEAT_CMD` write was refused · bit 3 `save_failed`: the last SAVE didn't reach flash · bit 4 `store_degraded`: the loaded snapshot had out-of-range values (defaults used) or no complete generation was found after a torn write · bits 5–15 rsvd |
| 10004–10007 | — | rsvd (reads `0`) |
| 10008–10015 | `FEAT_SUPPORTED[0..7]` | features compiled into this build **and** applicable to this variant (`variant.h`). Constant for a given image + variant. |
| 10016–10023 | `FEAT_ACTIVE[0..7]` | features enabled **and** whose `requires` and runtime preconditions currently hold, i.e. actually running. ACTIVE ⊆ `FEAT_EN` ∩ SUPPORTED. |
| 10024–10031 | `FEAT_SAVED[0..7]` | the mask in the newest complete saved snapshot (what the next boot loads) |
| 10032–10039 | — | rsvd (reads `0`) |

Every mask uses the `FEAT_EN` numbering: feature *n* = bit `n % 16` of word
`n / 16`. They are plain 16-bit registers, **not** 32-bit L/H pairs, so the
dongle's reversed-word rule doesn't apply. The block is exactly one 40-register
group, so one spec-legal read fetches it all.

## How a client uses it

1. Read IR 10000–10039 (one query).
2. If IR 10000–10001 ≠ `"DAYB"`, the unit runs factory firmware, or our firmware
   built without Daybreak (`ENABLE_DAYBREAK=0`). Stop: there are no Daybreak
   features.
3. Otherwise, offer the features in `FEAT_SUPPORTED`. After writing `FEAT_EN`,
   confirm through `FEAT_ACTIVE`. After `FEAT_CMD = SAVE`, confirm through
   `FEAT_SAVED`.

## Provenance

**Daybreak-defined, ARM-local.** SUPPORTED comes from the compiled registry
(`include/inv/daybreak_features.h`, T28) filtered by variant. ACTIVE is recomputed
each scheduler tick. SAVED mirrors the Daybreak settings ring
([`docs/45`](../../45-daybreak-feature-flags.md) §4.3, in the
[`docs/24`](../../24-oss-settings-region.md) region).

On the factory `ceaa-07xx` image (USART3 register slave, dynamic, 2026-11-08), a
read of IR 10000–10047 returns all `0`. That makes the magic a clean discriminator
(docs/45 §2.2). ⚠️ The real UART5 task is ~ inferred to behave the same (T02).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **None yet.** Not implemented (T28). Planned, per
  [`docs/45`](../../45-daybreak-feature-flags.md) §6.4:
  - sim (ours) `test_daybreak_control.py`:
    - magic and schema served with the mask at 0;
    - ACTIVE tracks EN, and drops a feature whose runtime precondition fails;
    - SAVED reflects SAVE/CLEAR across a reboot;
    - `safe_mode` is set after the UP+DOWN chord;
  - sim (factory-only): IR 10000–10039 reads all `0` (the discovery contract);
  - host `test_daybreak_features.c`: ACTIVE ⊆ EN ∩ SUPPORTED for every mask.

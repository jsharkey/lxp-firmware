# IR 10000–10039 — OSS capability & feature status (discovery block)

> **Dongle Modbus**, input registers (func `0x04`, read-only). Authoritative.
> See the [index](registers.md) and its "Address-space allocation" section.
> **OSS-only.** These registers don't exist in the factory firmware. The design
> rationale is in [`docs/45`](../../45-oss-feature-flags.md).
> **Status: ⬜ allocated, not implemented** (task T28 in [`docs/39`](../../39-parity-roadmap.md)).

This is OSS **block 0, IR side**. It is the only OSS block that answers while
every feature flag is clear, and it holds no feature behaviour. It tells a client
(1) whether it is talking to our firmware at all, and (2) which features exist,
which are switched on, and which are actually running. The write side is
[`HR10000_10039-OSS-feature-control.md`](HR10000_10039-OSS-feature-control.md).

## Map

| IR | name | meaning |
|---|---|---|
| 10000–10001 | `OSS_MAGIC` | `0x4C58`, `0x4F53` (ASCII `"LX"`,`"OS"`, high byte first in each word's value). **The factory reads `0, 0`.** |
| 10002 | `OSS_SCHEMA` | OSS register-schema version, `major << 8 \| minor`. `major` bumps only on an incompatible change to block 0. |
| 10003 | `OSS_CTL_STATUS` | bit 0 `safe_mode`: booted with the mask forced to 0 (front-panel chord) · bit 1 `dirty`: running mask ≠ saved mask · bit 2 `last_rejected`: the most recent `FEAT_EN`/`FEAT_CMD` write was refused · bit 3 `save_failed`: the last SAVE didn't reach flash · bits 4–15 rsvd |
| 10004–10007 | — | rsvd (reads `0`) |
| 10008–10015 | `FEAT_SUPPORTED[0..7]` | features compiled into this build **and** applicable to this variant (`variant.h`). Constant for a given image + variant. |
| 10016–10023 | `FEAT_ACTIVE[0..7]` | features enabled **and** whose `requires` and runtime preconditions currently hold, i.e. actually running. ACTIVE ⊆ `FEAT_EN` ∩ SUPPORTED. |
| 10024–10031 | `FEAT_SAVED[0..7]` | the mask in the OSS flash region, which the next boot will load |
| 10032–10039 | — | rsvd (reads `0`) |

All masks use the same numbering as `FEAT_EN`: feature *n* = bit `n % 16` of
word `n / 16`. Each word is a plain 16-bit register. These are **not** 32-bit
L/H pairs, so the dongle's reversed-word rule doesn't apply. The block is exactly
one 40-register group, so a single spec-legal read fetches all of it.

## How a client uses it

1. Read IR 10000–10039 (one query).
2. If IR 10000–10001 ≠ `"LXOS"`, the unit is running factory firmware (or an OSS
   build with `OSS=0`). Stop: there are no OSS features.
3. Otherwise, offer the features in `FEAT_SUPPORTED`. After writing `FEAT_EN`,
   confirm through `FEAT_ACTIVE`.

## Provenance

**OSS-defined, ARM-local.** SUPPORTED comes from the compiled registry
(`include/inv/oss_features.h`, T28) filtered by variant. ACTIVE is recomputed each
scheduler tick. SAVED mirrors the OSS-region record ([`docs/24`](../../24-oss-settings-region.md)).

On the factory `ceaa-07xx` image (USART3 register slave, dynamic, 2026-11-08), a
read of IR 10000–10047 returns all `0`. That is what makes the magic a clean
discriminator (docs/45 §2.2). ⚠️ The real UART5 task is ~ inferred to behave the
same (T02).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **None yet.** The control plane isn't implemented (T28). Planned, per
  [`docs/45`](../../45-oss-feature-flags.md) §5.4:
  - sim (ours) `test_oss_control.py`: magic + schema served with the mask at 0;
    ACTIVE tracks EN, and drops a feature whose runtime precondition fails;
    SAVED reflects SAVE/CLEAR across a reboot;
  - sim (factory-only): IR 10000–10039 reads all `0` (the discovery contract);
  - host `test_oss_features.c`: ACTIVE ⊆ EN ∩ SUPPORTED for every mask.

# HR 10000–10039 — OSS feature control (feature-enable mask + command)

> **Dongle Modbus**, holding registers (func `0x03`/`0x06`/`0x10`). Authoritative.
> See the [index](registers.md) and its "Address-space allocation" section.
> **OSS-only.** These registers don't exist in the factory firmware. The design
> rationale is in [`docs/45`](../../45-oss-feature-flags.md).
> **Status: ⬜ allocated, not implemented** (task T28 in [`docs/39`](../../39-parity-roadmap.md)).

This is OSS **block 0, HR side**: the switchboard for every open-source feature.
With every bit clear, which is the default, our firmware is the factory mirror.
The matching read-only capability view is
[`IR10000_10039-OSS-capability.md`](IR10000_10039-OSS-capability.md).

## Map

| HR | name | access | meaning |
|---|---|---|---|
| 10000–10007 | `FEAT_EN[0..7]` | RW | **running feature-enable mask**, 128 feature IDs. Feature *n* = bit `n % 16` of `FEAT_EN[n / 16]`. Default `0`. |
| 10008–10015 | — | rsvd | reserved for growth to 256 IDs (`FEAT_EN[8..15]`). Reads `0`; a write of `0` is accepted and a non-zero write raises exception 3. |
| 10016 | `FEAT_CMD` | W (reads `0`) | control-plane command, see below |
| 10017–10039 | — | rsvd | reserved for control-plane growth. Reads `0`; writes raise exception 2. |

### `FEAT_EN` write semantics

- **Atomic per request.** A `0x06` write of one word, or a `0x10` write of any
  run inside 10000–10015, is staged and **validated as a whole mask** before
  anything is applied. If the result is invalid, **nothing changes** and the reply
  is **exception 3** (illegal data value). (T28 adds an end-of-write commit hook to
  the transport-agnostic engine `src/modbus/modbus.c` for this.)
- **What makes a mask invalid** (all checked against the registry in
  `include/inv/oss_features.h`):
  - a bit for an ID that isn't in `FEAT_SUPPORTED` (compiled out, not
    applicable to this variant, or unallocated);
  - **bit 0** (ID 0 is reserved and never a feature);
  - a feature whose `requires` aren't set in the same resulting mask. Clearing a
    prerequisite while a dependent is still set is likewise refused;
  - two features that `conflict`.
- **Registry rule that makes incremental writes safe:** a feature may only
  `require` a **lower-numbered** ID, so dependencies always point "down" the mask.
- **RAM-only.** A `FEAT_EN` write changes the *running* mask, which takes effect
  from the next scheduler tick. It is **not persisted**. A power cycle restores
  the saved mask, so trying a feature is undone by a reboot. Persist it with
  `FEAT_CMD = SAVE`.
- **Read-back** returns the running mask exactly as written. Whether each feature
  is actually running is reported separately in IR 10016–10023 `FEAT_ACTIVE`.
  Tests and clients must check that, not this.
- **`0x10` is allowed here.** The EG4 spec limits write-multiple to SN and time
  (HR 2-6, 12-14). The OSS control block deliberately accepts it too, so that a
  multi-word mask lands in one atomic request. This is the one documented framing
  extension inside the OSS window. The factory-surface restriction is unchanged.

### `FEAT_CMD` (HR 10016)

| value | name | effect |
|---|---|---|
| `0x5341` (`"SA"`) | SAVE | write the running mask to the OSS flash region ([`docs/24`](../../24-oss-settings-region.md), `LXP1`/`0x5A` record); clears `OSS_CTL_STATUS.dirty`. On a flash error, sets `save_failed` and replies exception 4. |
| `0x524C` (`"RL"`) | RELOAD | running mask ← saved mask (discards un-saved changes) |
| `0x434C` (`"CL"`) | CLEAR | running mask **and** saved mask ← 0. The unit is back to the pure mirror state, durably. |
| anything else | — | exception 3 |

The ASCII-mnemonic values are deliberate. A stray small integer, or a client that
mistakes this register for a mask word, can't trigger a flash write or a wipe.

## Side-effects of writing

- **Mask change:** within one scheduler tick, newly-ACTIVE features start, and
  features that left ACTIVE release their leases and peripherals and stop
  altering any factory-surface value ([`docs/45`](../../45-oss-feature-flags.md)
  §4 rule 4).
- **No factory-surface side-effects.** Nothing here is pushed to the DSP over
  USART3 or written to the factory config slots.
- **HR 11 `AlltoDefault`** (factory reset) also performs the equivalent of
  `CLEAR` (docs/45 §4.1).

## Provenance

**OSS-defined.** There is no factory counterpart. On the factory `ceaa-07xx`
image (USART3 register slave, dynamic, 2026-11-08) a **read** of HR 10000–10047
returns `0`, and a **write-single** to HR 10000 or HR 10016 is refused with
**exception 2** and stores nothing (docs/45 §2.2). A client that writes flags to
a factory unit is therefore harmless. ⚠️ The real UART5 task is ~ inferred to
behave the same (T02).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **None yet.** The control plane isn't implemented (T28). Planned, per
  [`docs/45`](../../45-oss-feature-flags.md) §5.4:
  - host `test_oss_features.c`: mask validation (unsupported bit, bit 0,
    `requires`/`conflicts` ⇒ exception 3, all-or-nothing), SAVE/RELOAD/CLEAR,
    boot from erased/valid/corrupt OSS record;
  - sim (ours) `test_oss_control.py`: RAM-only enable lost on reboot, SAVE'd
    enable survives it, CLEAR returns to the mirror;
  - sim (factory-only): HR 10000+ reads `0` and writes get exception 2 (the
    safe-on-factory contract).
- Every feature test sets these registers as its **precondition**
  (`tests/oss_helpers.py::oss_enable`). Such tests are listed in the feature's
  own block file, not here.

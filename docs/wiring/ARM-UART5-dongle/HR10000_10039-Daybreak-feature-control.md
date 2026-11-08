# HR 10000–10039 — Daybreak feature control (feature-enable mask + command)

> **Dongle Modbus**, holding registers (func `0x03`/`0x06`/`0x10`). Authoritative.
> See the [index](registers.md) and its "Address-space allocation" section.
> **Daybreak-only.** These registers exist only in our firmware built with
> `ENABLE_DAYBREAK=1`; the factory firmware doesn't have them. Design rationale:
> [`docs/45`](../../45-daybreak-feature-flags.md).
> **Status: ⬜ allocated, not implemented** (tasks T28/T29 in [`docs/39`](../../39-parity-roadmap.md)).

This is Daybreak **block 0, HR side**: the switchboard for every Daybreak
feature. With every bit clear (the default), our firmware is the factory mirror.
The matching read-only view is
[`IR10000_10039-Daybreak-capability.md`](IR10000_10039-Daybreak-capability.md).

## Map

| HR | name | access | meaning |
|---|---|---|---|
| 10000–10007 | `FEAT_EN[0..7]` | RW | **running feature-enable mask**, 128 feature IDs. Feature *n* = bit `n % 16` of `FEAT_EN[n / 16]`. Default `0`. |
| 10008–10015 | — | rsvd | reserved for growth to 256 IDs (`FEAT_EN[8..15]`). Reads `0`; a write of `0` is accepted, non-zero gives exception 3. |
| 10016 | `FEAT_CMD` | W (reads `0`) | control-plane command, see below |
| 10017–10039 | — | rsvd | reserved for control-plane growth. Reads `0`; writes give exception 2. |

### `FEAT_EN` write semantics

- **Atomic per request.** A `0x06` write of one word, or a `0x10` write of any run
  inside 10000–10015, is staged and **validated as a whole mask** before anything
  is applied. If it's invalid, **nothing changes** and the reply is
  **exception 3** (illegal data value). T28 adds an end-of-write commit hook to
  the transport-agnostic engine `src/modbus/modbus.c` for this.
- **What makes a mask invalid** (checked against the registry
  `include/inv/daybreak_features.h`, which mirrors the docs/45 §3.2 claims table):
  - a bit for an ID that isn't in `FEAT_SUPPORTED` (compiled out, not
    applicable to this variant, unclaimed, or a 🪦 tombstone);
  - **bit 0** (ID 0 is reserved and never a feature);
  - a feature whose `requires` aren't set in the same resulting mask. Clearing a
    prerequisite while a dependent is still set is likewise refused;
  - two features that `conflict`.
- **Registry rule that keeps incremental writes simple:** a feature may only
  `require` a **lower-numbered** ID.
- **In safe mode** (docs/45 §7), every `FEAT_EN`/`FEAT_CMD` write is refused with
  **exception 4** until the next reboot.
- **RAM-only.** A write changes the *running* mask, which takes effect from the
  next scheduler tick. It is **not persisted**: a power cycle restores the saved
  snapshot. Persist it with `FEAT_CMD = SAVE`.
- **Read-back** returns the running mask exactly as written. Whether each feature
  is actually running is reported in IR 10016–10023 `FEAT_ACTIVE`, and tests and
  clients must check that instead.
- **`0x10` is allowed here.** The EG4 spec limits write-multiple to SN and time
  (HR 2-6, 12-14). The Daybreak window deliberately accepts it too, so a
  multi-word mask lands in one atomic request. The factory-surface restriction is
  unchanged.

### `FEAT_CMD` (HR 10016)

`FEAT_CMD` acts on the **whole Daybreak state**: the mask plus every Daybreak
register whose registry descriptor says `persist`.

| value | name | effect |
|---|---|---|
| `0x5341` (`"SA"`) | SAVE | write the running Daybreak state as one new **snapshot generation** to the Daybreak settings ring ([`docs/45`](../../45-daybreak-feature-flags.md) §4.3: sparse `(reg, value)` pairs, non-default only, `"DAYB"`/`0x5A` pages). Clears `DAYBREAK_CTL_STATUS.dirty`. On a flash error, sets `save_failed` and replies exception 4; the previous generation stays in force. |
| `0x524C` (`"RL"`) | RELOAD | running state ← newest complete saved generation (discards un-saved changes) |
| `0x434C` (`"CL"`) | CLEAR | running state **and** saved state ← defaults (mask 0, carried unknown entries dropped, every feature-owned ring erased). The unit is durably back to the pure mirror state. |
| anything else | — | exception 3 |

The ASCII-mnemonic values are deliberate. A stray small integer, or a client that
mistakes this register for a mask word, can't trigger a flash write or a wipe.

## Side-effects of writing

- **Mask change:** within one scheduler tick, newly-ACTIVE features start, and
  features that left ACTIVE release their leases and peripherals and stop altering
  any factory-surface value ([`docs/45`](../../45-daybreak-feature-flags.md) §5 rule 4).
- **No factory-surface side-effects.** Nothing is pushed to the DSP over USART3, and
  nothing is written to the factory config slots (docs/21/23). Daybreak data lives
  only in the docs/24 region, at `0x010000–0x03FFFF`.
- **HR 11 `AlltoDefault`** (factory reset) is proposed to also perform `CLEAR`
  (docs/45 §7, open item 5).

## Provenance

**Daybreak-defined.** There is no factory counterpart. On the factory `ceaa-07xx`
image (USART3 register slave, dynamic, 2026-11-08), a **read** of HR 10000–10047
returns `0`, and a **write-single** to HR 10000 or HR 10016 is refused with
**exception 2** and stores nothing (docs/45 §2.2). A client that writes flags to a
factory unit is therefore harmless. ⚠️ The real UART5 task is ~ inferred to behave
the same (T02).

## Test coverage

_Tests that exercise these registers. **Keep this list current when you add or change a test** (see [AGENTS.md](../../../AGENTS.md))._

- **None yet.** Not implemented (T28/T29). Planned, per
  [`docs/45`](../../45-daybreak-feature-flags.md) §6.4:
  - host `test_daybreak_features.c`: mask validation (unsupported bit, bit 0,
    `requires`/`conflicts` ⇒ exception 3, all-or-nothing) and SAVE/RELOAD/CLEAR;
  - host `test_daybreak_store.c`: sparse snapshot packing, torn-SAVE recovery,
    unknown-key carry, ring wrap;
  - sim (ours) `test_daybreak_control.py`: a RAM-only enable is lost on reboot, a
    SAVE'd enable survives it, CLEAR returns to the mirror, safe mode refuses
    writes;
  - sim (factory-only): HR 10000+ reads `0` and writes get exception 2 (the
    safe-on-factory contract).
- Every feature test sets these registers as its **precondition**
  (`tests/daybreak_helpers.py::daybreak_enable`). Such tests are listed in the
  feature's own block file, not here.

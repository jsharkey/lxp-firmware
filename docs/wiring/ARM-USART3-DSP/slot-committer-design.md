# The slot-committer design — why the factory derives, and why we mirror it

> How the factory assembles the ARM→DSP config push, why that shape is a good
> one, and how our open-source firmware now mirrors it. See the
> [index](fields.md) and [`field-provenance`](field-provenance.md).

## What the factory does

The config push does **not** serialize holding registers. Between the
register model and the wire there is a working layer:

```
holding register  --(committer: gated by an enable, marks a dirty bit)-->  slot record
                   --(builder: positional, big-endian)-->                  DSP config block
```

- **Slot records** — a working struct (factory RAM `0x2000a330…0x2000a390`) holding
  the *derived* schedule: the committed window times, per-slot active flags, etc.
- **Committer family** — ~34 small functions (the writers of the dirty mask
  `0x2000a7a8`). Each copies a specific set of settings into a slot record, **only
  when that feature's enable bit** (`0x2000a7a4`) is set, and **sets a dirty bit**
  in a mask that becomes the DSP's per-slot active mask `0xAD54`.
- **Builder** (`sub_08024dfc`) — serializes the *slot records*, big-endian, into the
  block payloads. It is a near-pure serializer; the derivation already happened in
  the committer. (It even commits-during-build, so a build reflects the latest
  settings — see the live capture below.)

So a dongle write of **HR 68** (AC-charge window-0 start) travels
`HR 68 → settings 0x2000988e → committer → slot 0x2000a370 → block 4 @0x17 → DSP`,
not as a direct register copy.

## Why it is a good design

It is the **materialized-view / projection** pattern with explicit invalidation and
an authorization gate — well matched to an MCU that bridges two protocols and feeds
a change-driven consumer:

1. **Representation decoupling.** The user model (Modbus holding registers:
   little-endian, scaled, `%` and `hour|minute`) and the DSP wire (positional,
   big-endian slot records) are independent. Either can change without touching the
   other — the committer is the one place the mapping lives.
2. **Compute once per change, not per frame.** The push streams a full snapshot
   ~6×/s forever; the builder stays a trivial serialize. Any scaling, clamping,
   cross-field derivation or window math runs in the committer, only when a setting
   actually changes. The hot path is cheap.
3. **Explicit enable gating.** Each feature has one choke point. A disabled
   feature's slot stays inert — matching what the live capture shows: the
   charge-priority / forced-discharge registers are not even writable here, so their
   slots carry nothing. Safe-by-default, and auditable in one spot.
4. **Change signalling via the dirty mask.** The committer's dirty bit becomes DSP
   `0xAD54`, which the DSP diffs to act only on slots that changed (it avoids
   re-enqueuing an unchanged AC-charge schedule, docs/07). The mask is serialized
   alongside the data, so the consumer knows *what* moved.
5. **One commit point, many writers.** HMI edits, dongle writes and internal logic
   all funnel through the committers, so the DSP always sees one consistent derived
   view regardless of who changed the setting.
6. **Deterministic, testable snapshot.** The builder's output is a pure function of
   the slot records, so "write a register, build, observe which byte moved" is
   reproducible — exactly what [`tests/test_dsp_push.py`](../../../tests/test_dsp_push.py)
   exploits to pin the field map by live capture.

The cost is one layer of indirection and the discipline of keeping committers in
sync with the register model. For a config bridge with a diffing downstream, that
cost buys all of the above — it is the right call, so we mirror it.

## How we mirror it (clean-room)

Pinned so far by live capture: the **time-window** records. We implement the design
for those and leave room for the rest, rather than hand-rolling a field table:

- [`include/inv/dsp_slots.h`](../../../include/inv/dsp_slots.h) — the slot records
  (`dsp_slot_record_t`: 6 window u16s + `enabled` + `dirty`) and the slot set
  (`dsp_slots_t`: `ac_charge`, `ac_first`).
- [`src/dsp/dsp_slots.c`](../../../src/dsp/dsp_slots.c) —
  `dsp_slots_commit()` copies the schedule holding registers into the slot records,
  gated by each feature's enable bit, setting `dirty` on change; `dsp_slot_serialize()`
  emits the slot-active mask + the six window times big-endian.
- [`src/dsp/dsp_config.c`](../../../src/dsp/dsp_config.c) — the builder commits, then
  serializes the slot record for **block 4** (AC-charge, HR 68–73) and **block 5**
  (AC-First, HR 152–157). Payload is now **big-endian** (RE-corrected from the earlier
  little-endian placeholder; the DSP readers are BE), and the rotation covers **9
  blocks** (ids 0–8) to match the factory deserialiser.

Faithful points worth noting: the enable gate drives the **slot-active mask** only,
**not** whether the window *times* are serialized — the factory serializes the
committed times regardless of enable (the live capture shows HR 68–73 reaching
block 4 with no enable set), and the mask is what tells the DSP which slots to act
on. The commit-during-build mirrors the factory filler.

What we deliberately did **not** invent: fields we have not pinned. Blocks 1–3, 6–8
still frame correctly with their recovered/empty payloads; as each is decoded it
gets its own committer + slot record rather than a direct register copy.

## Verification

[`tests/test_dsp_push.py`](../../../tests/test_dsp_push.py) (contract in
[`dsppush_contract.py`](../../../tests/dsppush_contract.py)) runs the **same** spec
against both images under Unicorn: write a holding register over the dongle, build
the snapshot with the image's own builder, and diff the config-frame bytes. It
asserts AC-charge windows → block 4 @0x17–0x21, AC-First windows → block 5
@0x17–0x21 (big-endian), AC-charge power (HR 66) not pushed, and records the
factory writability of the HR 64–89 block. `make test-sim` runs it.

# The ARM↔DSP link surface — authoritative field map

**This directory is the source of truth for the fields exchanged on the internal
ARM↔Control-DSP link** (ARM **USART3** ↔ DSP **SCI-B**). It mirrors
[`docs/wiring/ARM-UART5-dongle/`](../../wiring/ARM-UART5-dongle/registers.md), but this link is **not**
register-addressed Modbus — it is EG4's **type-1 block protocol**: the ARM pushes
the whole configuration as **nine block-tagged frames** (block ids 0–8), each a
fixed header + a positionally-packed, **big-endian** payload. So the "one file per
register" of the dongle tree becomes **one file per block** here. When a numbered
analysis doc (`docs/NN`) and a file here disagree, **the file here wins**.

Transport + endpoints: [`docs/wiring/ARM-USART3`](../../wiring/ARM-USART3-DSP/README.md). Research
trail: [`docs/05`](../../05-dsp-link.md) (link id + bootloader),
[`docs/08`](../../08-arm-dsp-config-protocol.md) (envelope + direction),
[`docs/10`](../../10-dsp-config-field-map.md) (byte-exact map),
[`docs/07`](../../07-dsp-ac-first-mode.md) (what block 0 drives).

## Scope — this is ONLY the ARM↔DSP wire

There are **four** EG4-Modbus-*family* links in this system; they share the frame
shape (`… CRC-16/0xA001`) but are **different wires with different framing**. Only
the first is in scope here:

| link | wire | framing | documented in |
|---|---|---|---|
| **ARM↔DSP** ← *this tree* | ARM **USART3**, internal TTL 19200 | **big-endian, SN-less, block-tagged** (`SOF`, `type=1`, header, **block id @ `0x14`**, BE payload @ `0x15`) + `0x21/22/23` bootloader | [`ARM-USART3`](../../wiring/ARM-USART3-DSP/README.md) |
| Dongle Modbus | ARM **UART5**, external RS-485 | little-endian, 10-byte **SN**, func `03/04/06/10`; ARM = slave | [`docs/wiring/ARM-UART5-dongle/`](../../wiring/ARM-UART5-dongle/registers.md) |
| safety CPU→ARM | ARM **USART2**, internal RS-485 | big-endian type-1 telemetry bank | [`ARM-USART2`](../../wiring/ARM-USART2-safety.md) |
| MPPT→DSP | MPPT **USART1**, internal | big-endian, `0x42` SOF | [`MPPT-USART1`](../../wiring/MPPT-USART1-DSP.md) |

This is the **internal control contract**, not something an external tool polls:
the dongle cannot read these fields. The ARM **bridges** — it ingests dongle-Modbus
holding-register writes, stores them in its settings struct, and re-emits them here
as block fields (`holding reg → ARM struct → type-1 block → DSP RAM`). So a block
field's "source" is usually a dongle holding register; its "target" is a DSP RAM
word.

## Framing & encoding

- **TTL, 19200 8N1**, not RS-485. CRC-16/MODBUS (`0xA001`, init `0xFFFF`).
- **Two SOFs, one wire** (direction-asymmetric):
  - **ARM → DSP** config push: **SOF `0x41` ('A')**, builder `FUN_080273b4`/`FUN_08026830`.
  - **DSP → ARM** telemetry: **SOF `0x49` ('I')**, DSP builder `FUN_00096EE8` — but
    the ARM's USART3 RX **rejects it** (Modbus + bootloader demux only); the ARM's
    `0x49` telemetry comes from the safety CPU on **USART2** instead. See
    [`telemetry-0x49`](telemetry-0x49.md) (T09 correction); `FUN_0801bb0e` is the
    USART2 path, not USART3.
- Plus the **firmware-update bootloader** (`0x21/0x22/0x23`, a *separate* RX state
  machine `FUN_0801bbe0`) and an unsolicited **clock** frame.
- **All payload multi-byte fields are big-endian** (`FUN_0009E7C2` = u16 BE,
  `FUN_0009E6BA` = u32 BE on the DSP; single bytes = one wire byte). The dongle
  path is little-endian — do not mix.
- **One block per frame**; the block id at `0x14` selects the layout. The ARM
  rotates the id to push the full set (~one block / 20 ms → full snapshot ~6×/s),
  continuously; the DSP diffs each field and acts only on changes.
- **Completeness mask:** each block ORs its bit into DSP `DAT_0000b300`
  (`0x001…0x100`, +`0x200` from block 3); the DSP treats the config as complete
  once all bits are set.

**Field provenance** (holding register → ARM struct → block offset) is in
[`field-provenance.md`](field-provenance.md): the real builder (`sub_080258ca` →
`sub_08024dfc`), every block field's exact ARM source address, and the finding that
the push serializes **derived working structs** (slot records, battery limits), not
raw holding registers — with the directly-mapped registers (e.g. HR 20 → block 0) and
the remaining one-layer hop called out.

**The slot-committer design** — why the factory derives slot records instead of
serializing registers, why that is a good shape, and how our firmware mirrors it —
is in [`slot-committer-design.md`](slot-committer-design.md). The
holding-reg→block mapping it rests on is verified by a live USART3 capture that runs
the **same spec against both images**: [`tests/test_dsp_push.py`](../../../tests/test_dsp_push.py).

## Index — config blocks (ARM → DSP, SOF `0x41`, block id @ `0x14`)

| block | `b300` bit | role | doc |
|---|---|---|---|
| 0 | `0x001` | **output priority / AC-First + grid-charge core** | [→](block-00-output-priority.md) |
| 1 | `0x002` | **battery charge/discharge limit set** (`0xB23x`) — *inferred* | [→](block-01.md) |
| 2 | `0x004` | **measurement calibration gains** (`0xABxx`, Q10 unity=`0x400`) — *inferred* | [→](block-02.md) |
| 3–6 | `0x008`–`0x040` | **grid-charge "slot" parameters** (change-detect triplets) | [→](block-03_06-gridcharge-slots.md) |
| 7 | `0x080` | **measurement calibration gains, cont.** (`0xABFx`/`0xACxx`) — *inferred* | [→](block-07.md) |
| 8 | `0x100` | **2 calibration gains + 2 reserved** (`0xABDx`/`0xABEx`) — *inferred* | [→](block-08.md) |

**Which fields a dongle holding register controls** (end-to-end, both factory
images, with confidence): [`hr-controlled-fields.md`](hr-controlled-fields.md).
The **live-capture map** of every writable HR → block·offset (which settings reach
the DSP vs. stay ARM-local) is [`hr-push-matrix.md`](hr-push-matrix.md) (T25).

## Index — other frames on this wire

| frame | direction | purpose | doc |
|---|---|---|---|
| 20-byte header (`0x00`–`0x13`) | both | SOF/type/len + id/serial + status, precedes every block | [→](frame-header.md) |
| clock (`0xA5 0xA5` + y/m/d h:m:s) | ARM-built | RTC stream — **the DSP does not consume it** (no parser / no time math) | [→](clock.md) |
| telemetry (`SOF 0x49`) | DSP-built | **not received by the ARM on USART3** (demux rejects it; ARM's `0x49` is on USART2) | [→](telemetry-0x49.md) |
| Modbus slave (`03/04/06/10`) | DSP → ARM | the DSP polls the ARM; register reads/writes (ARM as slave) | [→](telemetry-0x49.md) |
| bootloader `0x21/0x22/0x23` | ARM → DSP | firmware update (session/erase/program/verify) | [→](bootloader-21_23.md) |

## Confidence (from docs/10)

- **High:** field order, offsets, widths, endianness, and DSP RAM targets for all
  nine blocks (cross-validated: DSP decompiler vs an independent disassembly
  emulator; block 0 + readers checked against the raw listing).
- **Named vs opaque:** **block 0** fields are interpreted ([`docs/07`](../../07-dsp-ac-first-mode.md)).
  Blocks 1–8 targets are *located* (exact DSP RAM word) but most are **not yet
  named** as product settings — the open leg is correlating each against the
  dongle holding-register that feeds it (`holding reg → ARM struct field`).

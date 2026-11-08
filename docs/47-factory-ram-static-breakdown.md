# Factory ARM static-RAM breakdown — where the 55 KB goes

This is the **static workstream (RB-S1…S5)** of the plan in
[`docs/46`](46-factory-ram-breakdown-plan.md), answering the question
[`docs/45`](45-arm-ram-budget.md) raised: the factory ARM image uses ~55 KB of
static `.data+.bss` (`0x20000000`–`0x2000dbd8`) vs our ~4.3 KB — **what is the
55 KB, and are any of our buffers under-sized against it?**

**Bottom line:** the gap is **whole features we haven't built**, not shrunken
copies of buffers we have. The biggest consumers are a ~12 KB SPI-flash
update/decode staging area, a ~11 KB cluster of HMI/display/fault buffers, a
4 KB CAN-frame log, and ~4 KB of DSP-link buffers. Our I/O rings are **as large
or larger** than the factory's equivalents, with one thing to watch (CAN burst
buffering — see below).

All work is clean-room: facts only, from `reference/ceaa-07xx_vE_260214.bin`
(App @`0x08005000`). Tools: `tools/ramsegments.py` (new; base-pointer + offset
segmentation), `tools/ramxref.py`, `tools/disres.py`, the `reference/*.csv`
symbol/string tables.

## How the 55 KB is distributed

`tools/ramsegments.py` partitions the static block by the 774 distinct RAM base
pointers the code loads. The mass is concentrated in a few big buffers:

| object size | count | total |
|---|---|---|
| ≥ 4 KB | 3 | 23.3 KB |
| 1–4 KB | 8 | 13.3 KB |
| 256 B – 1 KB | 20 | 8.3 KB |
| 64–256 B | 38 | 4.4 KB |
| < 64 B | 705 | 5.7 KB |
| **total** | **774** | **55.0 KB** |

So **11 objects ≥ 1 KB account for ~37 KB (67 %)**; the other ~760 objects
(flags, small structs, per-field accessor targets) are ~18 KB.

## The big consumers (RB-S1 segmentation + RB-S4 sizing)

| region | size | what it is | confidence |
|---|---|---|---|
| `0x200022cc`..`0x20005020` | ~11.3 KB | **cluster of ~28 pointer-passed HMI/display/fault buffers** (not one object) — `0x200022cc` itself is a 1-byte trigger flag | size inferred; purpose a guess (RB-D target) |
| `0x20005020`..`0x20007020` | **8 KB** | **SPI-flash read/decode staging** — filled by `sub_08036d68`←`fn_NOTB` via the SPI read `sub_0801cace` (firmware-update / data-log path) | purpose proven, size from gap |
| `0x20007020`..`0x20008020` | **4096 B** | **SPI-flash decode-output / program staging** — `mov r3,#0x1000` cap into decoder `sub_08038c5c`, programmed back via `sub_0801c90e` | **proven** |
| `0x20008020`..`0x20008fc0` | **4000 B** | **CAN-frame log / RX queue — 200 frames × 20 B** (`cmp #0xc8` × `muls #0x14` in `sub_080055c8`, reading CAN1 `0x40006400`) | **proven** (two independent passes agree) |
| `0x20008fc0`..~`0x20009790` | ~2 KB | HMI/display state (the `sub_0800f4xx` family; `memset sub_08005578` fills it in ≤255 B chunks) | inferred |
| `0x2000a304` | ~1.1 KB | **USART3 (ARM↔DSP) RX frame buffer + decoded struct** (raw frame 800 B, see rings table) | proven (raw size) |
| `0x2000af60` | ~875 B | **USART2 (DSP-domain telemetry) RX buffer + decoded struct** (raw frame 64 B) | proven (raw size) |
| `0x2000b2cc` | ~804 B | **config-flash read-back scratch** ([`docs/24`](24-oss-settings-region.md), `sub_080164bc`) | proven |
| `0x2000b910` | ~600 B | DSP frame-assembly buffer (`sub_08026830`) | inferred |
| `0x20001700` | ~1.5 KB | HMI/fault display struct (`sub_0800d…`/`e…` family) | inferred |
| several 1–1.7 KB | ~4 KB | comms/upper structs (`0x20009790`, `0x20009e50`, `0x2000ab60`, …) | guess |

**Anchored small structures** (RB-S5, from prior docs): the six 256-B config
slot RAM images `0x2000c85c`–`0x2000cd5c` = 1.5 KB ([`docs/23`](23-arm-config-writer.md),
1804 refs — the hottest region); the DSP telemetry struct `0x2000ce5c` (~76 B+,
541 refs, [`docs/18`](18-power-path-relays.md)); the live settings struct near
`0x2000d850`; the super-loop state struct `0x2000d0e4` (152 B, 422 refs); the
hottest register/telemetry struct `0x2000c448` (244 B, **633 refs**); config
default/record scratches `0x2000c65c`/`0x2000c75c` (256 B each).

**Attributed:** ≈ 38 KB to the named big regions + ~several KB of anchored
structs; the residual is the long tail of < 256 B objects.

## I/O ring buffers — factory vs ours (the actionable comparison, RB-S3)

All factory RX buffers are **proven** (the wrap guard `cmp idx,#LIMIT; bge` is
the size). Peripheral bases confirm each link.

| link (peripheral) | factory RX | factory TX | **ours RX / TX** | verdict |
|---|---|---|---|---|
| USART1 `0x40013800` | — (handler is `bx lr`, **unused**) | — | — | n/a |
| USART2 `0x40004400` (DSP telemetry) | **64 B** (`0x2000af60`, `cmp #0x40`) | polled | our `uart2.c` RX **256 B** | ✅ ours larger |
| USART3 `0x40004800` (ARM↔DSP) | **800 B** (`0x2000a304`, `cmp #0x320`) | polled | our `uart3.c` RX/TX **256 B/256 B** | ⚠️ see note |
| UART4 `0x40004c00` (role TBD, SOF `0x01`) | **200 B** (`0x2000bd84`, `cmp #0xc8`) | polled | (not implemented) | — feature gap |
| UART5 `0x40005000` (dongle Modbus) | **200 B** (`0x2000bb80`, `cmp #0xc8`) | polled | our `uart5.c` RX/TX **256 B/256 B** | ✅ ours larger |
| CAN1 `0x40006400` (BMS) | **4000 B = 200 frames × 20 B** (`0x20008020`) | HW mailbox | our `can_port.c`: **drain HW FIFO immediately, no SW queue** | ⚠️ see note |

Factory serial RX are **per-frame linear accumulate** buffers (index resets on
frame complete); ours are **byte ring buffers** drained every poll — different
designs, same job. No factory interrupt-driven TX ring exists; TX is polled on
both sides.

**Notes / watch-items for our firmware:**
- **USART3 (⚠️, low risk).** The factory sizes its DSP RX frame buffer at 800 B;
  ours is a 256 B ring. The ARM↔DSP config frames we handle are ~54 B
  ([`docs/08`](08-arm-dsp-config-protocol.md)), so 256 B is comfortable **as long
  as we keep draining** — a single 800 B frame would not fit whole, but we never
  buffer a whole frame, we stream it. Keep an eye on this if we ever add a
  larger DSP message.
- **CAN1 (⚠️, worth a decision).** The factory keeps a **200-frame software
  queue / log** (4 KB); ours processes each frame immediately out of the 3-deep
  bxCAN hardware FIFO. For liveness that is fine if we poll often enough, but we
  have **no burst headroom or frame history**. If a CAN burst can outrun our
  poll, or if a diagnostic CAN log is wanted, this is where to add a software
  queue. Tracked as a possible parity item ([`docs/39`](39-parity-roadmap.md)).
- Everything else (SPI-flash staging, the HMI/display/fault cluster, the CAN
  log, UART4) is a **feature we have not built**, not an under-sized buffer. The
  HMI editors are explicitly out of scope (docs/39 T13).

## Hand-off to the dynamic workstream (RB-D)

Two things static analysis couldn't fully resolve, good targets for the
emulator-based RB-D tasks (write-PC attribution / heatmap):
- the **~11.3 KB `0x200022cc`..`0x20005020` cluster** — ~28 pointer-passed
  buffers; a write-PC map would name each and confirm the HMI/fault split.
- the **long tail of < 256 B objects** (~18 KB over ~760 bases) — a heatmap would
  show which are live telemetry vs cold/one-shot.

Authoritative link facts (RX buffer sizes) are recorded in the per-link
[`docs/wiring/`](wiring/README.md) files.

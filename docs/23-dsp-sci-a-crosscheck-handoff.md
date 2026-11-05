# Hand-off: cross-check the DSP's SCI-A transmit builder against the ARM's USART2 telemetry

**For the DSP-side agent** (you have `docs/07`/`docs/10` + the DSP image). One
physical question remains open on the ARM↔DSP interface, and only the DSP side can
close it:

> The ARM receives the **operating mode + core power telemetry** on **USART2**
> (see [`docs/22`](22-arm-dsp-core-split.md)). The *data* is unmistakably
> DSP-domain (operating mode + the DSP's own PV/grid V/F measurements, EG4-framed,
> big-endian). What firmware alone can't prove is that USART2 is *physically* the
> DSP's **second SCI (SCI-A)** rather than DSP data relayed via the third
> (redundant safety) CPU. If the DSP has an SCI-A transmit builder that emits the
> exact frame the ARM parses below, that closes it: **USART2 ⇔ DSP SCI-A**, proven
> on both ends.

Confirmed already: **USART3 ⇔ DSP SCI-B** (bootloader `0x21/0x22/0x23` + shared
CRC, docs/05) carries the ARM→DSP **config push**. This hand-off is about the
*other* direction/port: DSP→ARM **telemetry**.

## The ARM-side frame signature to match (established)

The ARM receives the frame on USART2, stages it at RAM `0x20008084`, validates and
parses it. Parsers: `sub_080259d8` (driver/validate), `sub_080241a8` (bulk
telemetry), `sub_08024d74` (mode/status). The frame is the **EG4 Modbus family**:

| property | value | note |
|---|---|---|
| byte `[0]` | address | EG4 envelope |
| byte `[1]` | **`0x01`** (type) | same type as the DSP config frames (docs/08) and the DSP uplink `[1]=1` (docs/10) |
| multi-byte fields | **big-endian** (`u16 = p[0]<<8 \| p[1]`) | via `sub_08014db8`; **the DSP family is BE** (docs/10), the dongle is LE — this is the key discriminator |
| trailer | **CRC-16/MODBUS** (`0xA001`, init `0xFFFF`) | `sub_08014bec`, table-driven (lo/hi tables `0x0803eb70`/`0x0803ec70`) — twin of the DSP's `FUN_00081034` |
| length | ≥ `0x54` bytes (gate in `sub_08024d74`) | large telemetry record |

**Payload content the ARM extracts** (these are DSP-produced quantities — grid
sync + MPPT — so they anchor the match):

| ARM input reg | quantity | ARM telemetry-bank dest (`0x20009e54+`) |
|---|---|---|
| 0 | **operating mode** byte | `+0x00` (copied from frame byte **`+4`** by `sub_08024d74`) |
| 1 / 2 | PV1 / PV2 voltage | `+0x4c` / `+0x4e` (consecutive BE u16) |
| 12 / 13 / 14 | grid voltage R / S / T | `+0x20` / `+0x28` / `+0xb6` |
| 15 | grid frequency | `+0x5e` |

The bulk parser `sub_080241a8` reads fields with a **running frame offset**
(`add r0, RXbase, fp; bl sub_08014db8; fp += 2`), so the exact frame byte offsets
are sequential from a start — recoverable by tracing `fp`, if you need them to
line up a specific field. The **operating-mode byte at frame `+4`** is the
cleanest single anchor (decoded directly from `sub_08024d74`).

## What to check on the DSP side

1. **Does the DSP transmit on SCI-A at all?** Identify the SCI-A peripheral base
   vs SCI-B (you've already placed SCI-B as the master/config link). Find the
   SCI-A TX path (DMA or ISR feeding SCI-A TXBUF).
2. **Find the SCI-A transmit *builder*** — the function that assembles the frame
   SCI-A sends. The DSP's uplink builder `FUN_00096EE8` (docs/10: `[0]=0x49`,
   `[1]=1`, `[2:3]=0x0036`, filler `FUN_00092110`) is the known config/telemetry
   TX builder — check whether it (or a sibling) targets **SCI-A** and whether its
   frame matches the ARM parse map above, specifically:
   - byte `[1] == 1`, big-endian fields, EG4 `0xA001` CRC trailer;
   - the **operating-mode / working-state byte** at the position the ARM reads
     from (frame `+4`) — and that its value is the DSP's own working state
     (`g_outputPrio`-family / the mode the DSP computes, docs/07);
   - PV voltage, 3-phase grid voltage, grid frequency present as BE u16 fields.
3. **Confirm the operating mode originates here.** The decisive point for
   `docs/22`: the mode byte the ARM classifies (`sub_0801b480`) is *produced* by
   the DSP and *sent* on this frame — i.e. the DSP writes its working-state into
   the SCI-A TX buffer.

## Outcome

- **Confirms** `USART2 ⇔ DSP SCI-A` if the DSP's SCI-A TX builder emits a
  `type=1`, big-endian, `0xA001`-CRC frame carrying the working-state byte + the
  PV/grid V/F telemetry at offsets consistent with the ARM map. Then the ARM↔DSP
  interface is fully pinned: **SCI-B/USART3 = config (ARM→DSP), SCI-A/USART2 =
  telemetry (DSP→ARM)** — append the result to `docs/10`/`docs/22`.
- **Refutes / complicates** it if the DSP has no SCI-A TX, or SCI-A carries an
  unrelated protocol. Then USART2's data is still DSP-domain but likely **relayed
  via the redundant safety CPU**; note that so the ARM side stops inferring a
  direct DSP SCI-A.

## ARM-side reference

| what | where |
|---|---|
| USART2 peripheral | `0x40004400`; RS-485 DE on PC2 (docs/16) |
| RX staging buffer | `0x20008084` |
| frame driver / validate | `sub_080259d8` (checks `[1]==1`, CRC via `sub_08014bec`) |
| bulk telemetry parser | `sub_080241a8` (running-offset, BE reads via `sub_08014db8`) |
| mode/status parser | `sub_08024d74` (mode byte = frame `+4`) |
| telemetry bank | `0x20009e54` (served as input regs by `sub_0803289c`) |
| state classifier | `sub_0801b480` → IR_STATE at `0x2000a0d8+0x90` |
| BE u16 reader / CRC | `sub_08014db8` / `sub_08014bec` |

---

## RESOLUTION (DSP side): refuted — the DSP emits mode+telemetry on **SCI-B**, not a dedicated SCI-A

Checked against the decoded DSP images (12000XP `CEAA`, where this hand-off's named
functions live, and the 18kPV `fAAB` as a cross-check).

**The frame content matches, and the mode is DSP-produced (confirms docs/22's core point).**
The DSP's telemetry builder `FUN_00096EE8` emits exactly the frame the ARM parses:
`[0]=0x49` (DSP→ARM SOF) · `[1]=0x01` (type) · `[2:3]` length · **`[4] = the operating-mode
byte`** (`DAT_0000AD64 & 0xff`, written by the DSP state machine — e.g. the `…|0x4000/
0x1000/0x8000` mode/status bits) · big-endian status fields · bulk telemetry from `[0x14]`
via `FUN_00092110` (PV / grid-V / frequency) · **CRC-16/MODBUS** trailer (`FUN_00081034`,
`0xA001`). So the mode byte at frame **`+4`** and the BE telemetry **originate in the DSP** —
the handoff's point 3 is confirmed.

**But it is transmitted on SCI-B, the config port — not a separate SCI-A.** The telemetry
path is `FUN_0009DD14 → FUN_0009D358`, and `FUN_0009D358` drives **`DAT_0000aefe` = SCI-B**
(the port binding is set in `FUN_0009E6D7`/`FUN_0009DB5F`: SCI-A→`aefc`, SCI-B→`aefe`).
SCI-B is the confirmed ARM link (bootloader `0x21/0x22/0x23`, docs/05) = **ARM USART3**. So
the DSP's mode+telemetry frame goes out the **same bidirectional SCI-B/USART3** as the
config push.

**The DSP has no second ARM-facing telemetry port.** Its other SCI ports don't match
USART2's profile (19200, RS-485 DE on PC2):
- **SCI-A** (`aefc`) *is* used for TX — `FUN_0009C3FD` feeds `SCIA_SCITXBUF` — but it sends
  **unrelated bulk `LS4_RAM` records (0x1F8-byte, strided)** at ~9600 baud, **not** the
  type-1 telemetry frame.
- On the 18kPV, **SCI-C** is the `'T'`/`'D'` sub-controller link (docs/13), SCI-A/C run
  ~9600; only SCI-B runs ~19200. Neither DSP writes a second `0x49`/type-1 telemetry frame
  on another port (the 18kPV has **no `=0x49`** builder at all).

### Verdict

This is the hand-off's **refute** branch: *the DSP has no SCI-A TX of this frame, and SCI-A
carries an unrelated protocol.* The DSP emits its working-state + PV/grid/freq telemetry on
**SCI-B → ARM USART3**. Therefore the DSP-domain telemetry the ARM parses on **USART2 is not
a direct DSP SCI-A link** — it is **relayed** (consistent with docs/22's "routed via the
redundant safety CPU" alternative), or is a re-emitted copy of the SCI-B telemetry.

**Actionable follow-up for the ARM side:** the DSP telemetry (SOF `0x49`, docs/10) is sent on
SCI-B = **USART3** — the same port as config. So the ARM's **USART3** RX (the SOF-`0x49`
parser `0x0801BA98` / ctx `0x2000AF60`, docs/10) should already carry this mode/PV/grid/freq
data. Check whether USART3's parser populates the same quantities as the USART2 bank
(`0x20009e54`); if it does, **USART3 is the direct DSP telemetry and USART2 is the relay**,
and the `docs/22` residual limit resolves to "relayed, not a second DSP SCI."

> Caveat: the hand-off's ARM shows 3-phase R/S/T (18kPV-class). The two DSP images on hand
> each expose a single ~19200 ARM port (SCI-B); neither has a dedicated SCI-A telemetry TX.
> If the MPPT/3-phase product pairs with a DSP build not analyzed here, a dedicated SCI-A
> can't be excluded outright — but it is absent from both images available.

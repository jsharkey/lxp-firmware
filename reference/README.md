# Reference images & the 05-vs-07 address convention (read this first)

Analysis in this repo has historically mixed **two** factory ARM "com" images for
the 12000XP, which confuses agents. This is the single source of truth for which
is which. For the full byte-level delta see
[`docs/11-12000xp-revisions.md`](../docs/11-12000xp-revisions.md).

## The committed, canonical image is the **07-series**

| | value |
|---|---|
| file | **`reference/ceaa-07xx_vE_260214.bin`** (converted from `…_ceaa-07xx_vE_260214_Br7k5_2.hex`) |
| md5 (flat .bin) | `fc5b44bd13f6e3494e6f6cd67d70ad38` |
| size | 522 240 bytes |
| layout | **App over a ~20 KB bootloader**; App vectors at **`0x08005000`** |
| loaded in the emulator at | base `0x08000000` (so file offset `0x5000` = App `0x08005000`) |

**Whenever a doc, test, or tool says "the factory image" / "the image we test
against" without qualification, it means this 07 image.** All `tests/` factory
oracles default to it.

## The 05-series is historical / comparison only (NOT committed)

| | value |
|---|---|
| name | `ceaa-05xx_com_vE_250325.bin` (lives in the private `lxp-factory`, not here) |
| layout | **monolithic**; App vectors at **`0x08000000`** (244 080-byte flat) |
| used by | `docs/11` (the 05↔07 delta), `docs/36`/`docs/37` (05-era energy/RTC decode), `tools/emu_acfirst.py` / `tools/emu_gpio_acfirst.py` (05 experiments) |

An address found in the 05 image does **not** transfer to the 07 image, and vice
versa — the base and RAM layout both moved.

> **Naming rule:** never write `com_flat.bin`. It was a generic flat-bin name
> reused across the 05→07 switch and is the root of most of the confusion. Name
> the actual image (`ceaa-07xx_vE_260214.bin` or `ceaa-05xx_com_vE_250325.bin`).

## Our own open firmware

Our rebuild is a **monolithic image at `0x08000000`** (`ldscripts/stm32f103ve.ld`
`ORIGIN = 0x08000000`; `SCB->VTOR = inv_variant()->vector_addr`, which is
`0x08000000` for the 12000XP variant). So the 12000XP variant descriptor's
`0x08000000` / monolithic is correct **for our build** (and matches the 05 factory
layout) — it is *not* describing the 07 factory App base.

## Key address deltas 05 → 07 (verified where tests cover them)

| thing | 05-series | 07-series (committed) |
|---|---|---|
| App vector base | `0x08000000` | `0x08005000` |
| settings / slot-config buffer | `0x20009854` (+offset) | `0x2000c85c` (+offset) — AC-First `+0x64`, AC-charge `+0x3a` |
| RTC calendar | `0x2000a718` | `0x2000d850` |
| AC-First evaluator → status bit | `0x0801ece8` → `0x2000a758` bit 24 | `0x080352d0` → `0x2000d890` bit 24 |
| AC-charge evaluator → verdict | (combined `sub_0801ed28` → bytes `0x2000aa5f/60/61`) | `0x08034590` → mask `0x2000dbb7` |
| USART2 telemetry bank | `0x20009e54` | `0x2000ce5c` (the 07 bank with 22 refs; `0x20009e54` has zero on 07) |

These are what `tests/timewindow_contract.py` (`ceaa05`/`ceaa07` profiles) and the
`tests/` factory oracles encode; the 07 rows are exercised green against the
committed image.

> ⚠️ **Known unresolved ambiguity — `0x20009854`.** Besides being the 05 settings
> base, `0x20009854` is also cited in *07-scoped* docs as a "settings store" /
> "DSP-push source struct" read by 07 handlers (`sub_0802afe2`, `sub_08024dfc` —
> see [`docs/wiring/ARM-USART3-DSP/field-provenance.md`](../docs/wiring/ARM-USART3-DSP/field-provenance.md)).
> Whether that is a genuine distinct 07 struct or a stale-05 carry-over is **not
> yet verified** — treat `0x20009854` in a 07 context with suspicion until an
> emulation pins it. The time-window/config evaluators definitively use
> `0x2000c85c` on 07.

## The committed `reference/` analysis artifacts

`symbols.csv`, `symbols_named.csv`, `callgraph.txt`, `strings_xref.csv`,
`func_string_xref.csv`, `string_catalog.txt`, `dispatch_tables.txt`,
`ghidra_rename.py` — all regenerated from the **07** image (App `0x08005000`).

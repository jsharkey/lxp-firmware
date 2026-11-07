#!/usr/bin/env python3
"""Shared ARM->DSP config-push contract -- the SAME spec, factory-vs-ours.

This is a *live USART3 capture* contract, done the definitive way docs/wiring/ARM-USART3-DSP
asks for: write a holding register over the dongle (the real Modbus write handler
stores it), then serialize the config snapshot with the image's *own* builder, and
see which config-frame byte moved. Differential (value A vs B) so it is immune to
scaling, packing and offset guesses -- a frame byte that changes is driven by that
register; one that never changes is not.

It settles the open question in docs/wiring/ARM-USART3-DSP/field-provenance.md about the
HR 64-89 charge/discharge schedule:

  * AC-charge WINDOW times HR 68-73  ARE pushed -> config block 4, @0x17..0x21 (BE16)
  * AC-First WINDOW times HR 152-157 ARE pushed -> config block 5, @0x17..0x21 (BE16)
  * AC-charge POWER   HR 66           is stored but NOT pushed (no frame byte moves)
  * HR 67 (AC-charge SOC) and HR 74-89 (charge-priority + forced-discharge) are
    NOT writable in the factory image at all -- those schedule features are inert
    here, so there is nothing to push (WRITABLE_64_89 below records the live set).

Both images are driven under Unicorn exactly the same way (dongle write + the
image's own block builder), so "the factory oracle and our firmware agree" is one
spec each satisfies -- parity by contract (cf. timewindow_contract.py).

Register semantics: include/inv/modbus_map.h. Window packing: low byte = hour
(0-23), high byte = minute (0-59).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))

# --- the shared push spec ---------------------------------------------------
# reg -> (block_id, payload_offset) of the big-endian u16 it lands in, or None if
# the register is stored but NOT serialized into any config block.
DSP_PUSH = {
    # AC-charge windows  (w0s w0e w1s w1e w2s w2e) -> block 4
    68: (4, 0x17), 69: (4, 0x19), 70: (4, 0x1b),
    71: (4, 0x1d), 72: (4, 0x1f), 73: (4, 0x21),
    # AC-First windows   (w0s w0e w1s w1e w2s w2e) -> block 5
    152: (5, 0x17), 153: (5, 0x19), 154: (5, 0x1b),
    155: (5, 0x1d), 156: (5, 0x1f), 157: (5, 0x21),
    # AC-charge power %: stored, but not part of the config push
    66: None,
}

# --- grid-charge slot fields (blocks 3 & 6), T10 -----------------------------
# Beyond the schedule WINDOWS (DSP_PUSH above), the factory per-block filler packs
# the grid-charge slot's scalar settings into blocks 3 and 6. Pinned differentially
# against the real filler (a dongle write to the register moves exactly these frame
# bytes): reg -> (block_id, payload_offset, width_bytes). Big-endian. EOD and the
# feed-in limit are single bytes; currents/voltage are u16. The DSP's current unit
# is 0.1 A (HR is A) so those are value*10 on the wire; the charge voltage HR is
# already 0.1 V. The apparent moves at payload 0x15/0x16 and in block 0 are shared
# modbus-buffer residue, not fields -- excluded by looking only at the target block
# at offset >= 0x17. See docs/wiring/ARM-USART3-DSP/block-03_06-gridcharge-slots.md.
GRID_PUSH = {
    101: (6, 0x17, 2),   # HR_CHARGE_CURR      -> charge current   (0.1 A)
    102: (6, 0x1b, 2),   # HR_DISCHG_CURR      -> discharge current (0.1 A)
    99:  (6, 0x25, 2),   # HR_CHARGE_VOLT_REF  -> charge voltage    (0.1 V)
    105: (3, 0x1b, 1),   # HR_EOD              -> end-of-discharge SOC (%)
    103: (3, 0x1c, 1),   # HR_MAX_BACKFLOW     -> feed-in grid power limit (%)
    # Generator-charge parameters (block 6 body), T25 matrix + single-write decode.
    # HR 194 start-V is a u16 at 0x1d but its high byte is pinned 0x01 across the
    # usable range (it clamps below end-V), so only 0x1e moves for in-range A/B.
    194: (6, 0x1e, 1),   # HR_GEN_CHG_START_V  -> generator charge start V (0.1 V)
    195: (6, 0x1f, 2),   # HR_GEN_CHG_END_V    -> generator charge end V   (0.1 V)
    196: (6, 0x21, 1),   # HR_GEN_CHG_START_SOC-> generator charge start SOC (%)
    197: (6, 0x22, 1),   # HR_GEN_CHG_END_SOC  -> generator charge end SOC   (%)
    198: (6, 0x23, 2),   # HR_MAX_GEN_CHG_CURR -> max generator charge (0.1 A)
}
# (A, B) write values per register: two valid, distinct in-range values that flip
# the asserted byte(s) without tripping a clamp (start-V/end-V stay ordered).
GRID_AB = {
    101: (20, 100), 102: (20, 100), 99: (510, 560), 105: (20, 80), 103: (10, 80),
    194: (400, 450), 195: (500, 560), 196: (10, 80), 197: (30, 90), 198: (20, 50),
}

# Live (writable) registers in the HR 64-89 schedule block, as the factory image
# exposes them. 67 (AC-charge SOC) and 74/76-89 (charge-priority power/windows +
# forced-discharge) are inert -- a dongle write does not store (read-back stays at
# the default). HR 75 (HR_CHGFIRST_SOC, charge-priority SOC limit) IS writable but
# is NOT pushed: an earlier "block 4 @0x26 (verified)" reading was a push_delta
# double-write artifact -- SINGLE-write fresh captures show @0x26 stays 0 for every
# value 20..90 (the byte only "moves" when one write follows another on the same
# sim, i.e. transaction residue, not serialized config). So HR 75 is stored-only,
# like HR 66.
WRITABLE_64_89 = {64, 65, 66, 68, 69, 70, 71, 72, 73, 75}
INERT_64_89    = {67, 74} | set(range(76, 90))

# window A/B: two valid, distinct times (09:10 and 21:34), hour|minute<<8.
WIN_A = (10 << 8) | 9
WIN_B = (34 << 8) | 21
# a value for non-window percent registers (valid 0-100), A/B
PCT_A, PCT_B = 40, 73

NBLOCKS = 9
_FRAME_LO, _FRAME_HI = 0x15, 0x34     # payload window compared for a delta


def ab_values(reg):
    """(A, B) write values appropriate to the register's type."""
    window_regs = set(range(68, 74)) | set(range(152, 158))
    return (WIN_A, WIN_B) if reg in window_regs else (PCT_A, PCT_B)


# --- calibration-gain blocks (2/7/8), T10 ------------------------------------
# Blocks 2/7/8 carry the DSP's per-channel measurement-calibration gains in Q10
# fixed point (unity = 0x0400). No holding register feeds them (ext-settings area,
# default-initialised to unity); they are settings/BMS-independent, so the payload
# is a constant. The spec below is the factory's default-state payload region
# (frame offsets 0x15..0x33, big-endian), which our firmware reproduces exactly.
CALIB_BLOCKS = (2, 7, 8)
_UNITY = b"\x04\x00"                      # Q10 gain 1.000


def _pad31(b):
    return (b + b"\x00" * 31)[:31]        # payload region 0x15..0x33 is 31 bytes


# block 2: unity, a reserved 0 word (0x17), then 11 unity; block 7: 12 unity;
# block 8: 2 unity + 2 received-but-unconsumed words (unity at the default).
EXPECT_CAL = {
    2: _pad31(_UNITY + b"\x00\x00" + _UNITY * 11),
    7: _pad31(_UNITY * 12),
    8: _pad31(_UNITY * 4),
}


def calib_payloads(backend):
    """{block: payload bytes 0x15..0x33} for the calibration-gain blocks. They
    depend on no register, so build after a benign dongle write (the proven build
    path -- HR 68 is writable on both images and irrelevant to blocks 2/7/8)."""
    frames = backend._blocks_after_write(68, WIN_A)
    return {blk: bytes(frames[blk][0x15:0x34]) for blk in CALIB_BLOCKS}


def _payload_delta(frames_a, frames_b):
    """Set of (block, offset) payload bytes that differ between two full snapshots.
    frames_x: {block_id: bytes}. Only payload region [0x15:0x34] is compared."""
    hits = set()
    for blk in set(frames_a) & set(frames_b):
        fa, fb = frames_a[blk], frames_b[blk]
        hi = min(len(fa), len(fb), _FRAME_HI)
        for k in range(_FRAME_LO, hi):
            if fa[k] != fb[k]:
                hits.add((blk, k))
    return hits


class _Backend:
    _USE_DSP = False   # ModbusDongle (UART5); FactoryBackend flips to ModbusDsp (USART3)
    """Common driver: boot an image ONCE, then run every probe on the same sim
    (no snapshot/restore -- the boot ends at the STOP sentinel, and probing
    different registers in sequence does not interfere: later writes overwrite or
    target unrelated registers, and each block build re-reads current state).

    Subclasses provide _new_sim() (ArmSim + symbols) and _build_block(sim, blk)
    -> captured frame bytes."""
    name = "?"
    FRAME = 0x20009414          # where the built frame is assembled (overridable)

    def __init__(self):
        self._warm = None       # (sim, dongle) for the build probes, booted once
        self._warm_w = None     # a SEPARATE sim for writability (write-only) probes

    def available(self):
        try:
            self._boot()
            return True
        except Exception:
            return False

    def _boot(self):
        if self._warm is None:
            from arm_sim_modbus import ModbusDongle, ModbusDsp
            sim = self._new_sim()
            mb = (ModbusDsp if self._USE_DSP else ModbusDongle)(sim, boot_insn=self.boot_insn)
            self._warm = (sim, mb)
        return self._warm

    def _boot_w(self):
        if self._warm_w is None:
            from arm_sim_modbus import ModbusDongle, ModbusDsp
            sim = self._new_sim()
            mb = (ModbusDsp if self._USE_DSP else ModbusDongle)(sim, boot_insn=self.boot_insn)
            self._warm_w = (sim, mb)
        return self._warm_w

    _ENGINE_VARS = ("_exc_depth", "_msp", "_pending_irqs", "_thread_on_psp",
                    "_pendsv_set", "_systick_due", "_insns", "_tick_mark")

    def writable(self, reg, value):
        """Write `value` to `reg` over the dongle; True iff it reads back. Runs on
        a SEPARATE sim from the build probes: probing the inert registers makes the
        firmware reject the write (no echo), which burns a full transaction budget
        and leaves the loop in a state the build probes should not inherit."""
        sim, mb = self._boot_w()
        mb.write_single(reg, value)
        return mb.read_holding(reg) == [value]

    def _blocks_after_write(self, reg, value):
        """Write `reg`=value over the dongle, then build all blocks. Building uses
        sim.call(), which parks the CPU at the STOP sentinel and would kill the
        dongle's next resume -- so snapshot the CPU context + RTOS-engine vars
        after the write and restore them after the builds, leaving the loop
        exactly where the dongle left it for the next transaction."""
        sim, mb = self._boot()
        mb.write_single(reg, value)
        ctx = sim.uc.context_save()
        saved = {k: getattr(sim, k) for k in self._ENGINE_VARS}
        # Quiesce the RTOS engine for the duration of the builds: the factory's live
        # RTOS leaves a SysTick/PendSV/IRQ pending after boot, and the block hook
        # would emu_stop() on the first block of each sim.call() -- running zero
        # instructions of the builder. Cleared here, restored in finally (all of
        # these are _ENGINE_VARS). Harmless for our firmware (nothing pending).
        if hasattr(sim, "_systick_due"):
            sim._systick_due = False
            sim._pendsv_set = False
            sim._pending_irqs = []
            sim._tick_mark = sim._insns + 1_000_000_000
        try:
            return {blk: self._build_block(sim, blk) for blk in range(NBLOCKS)}
        finally:
            sim.uc.context_restore(ctx)
            for k, v in saved.items():
                setattr(sim, k, (list(v) if isinstance(v, list) else v))

    def push_delta(self, reg, a, b):
        """(block, offset) payload bytes that move when `reg` goes a->b."""
        fa = self._blocks_after_write(reg, a)
        fb = self._blocks_after_write(reg, b)
        return _payload_delta(fa, fb)


class FactoryBackend(_Backend):
    _USE_DSP = True
    """Factory image: dongle write + the real per-block filler sub_08024dfc."""
    name = "factory"
    boot_insn = 1_000_000

    def __init__(self, image, symbols=None):
        super().__init__()
        self.image = image
        self.symbols = symbols or os.path.join(
            os.path.dirname(__file__), "..", "reference", "symbols.csv")

    # Per-block filler (the real builder) in 07-series ceaa-07xx_vE_260214.bin, flat base
    # 0x08000000: fn_fill_cfg_block(buf, off, block_id) -- buf[off]=block_id, then
    # the block's big-endian fields from the ARM working RAM into buf[off+1]+. This
    # is docs/10's FUN_08026830 read at the CORRECT flat base; an earlier
    # field-provenance pass mis-converted it (assuming a 0x08005000 Ghidra base) to
    # "sub_08024dfc", which is a 05-era artifact that lands mid-function here and
    # writes nothing. docs/wiring/ARM-USART3-DSP/field-provenance.md.
    _FILL_ADDR = 0x08026830

    def _new_sim(self):
        from arm_sim import ArmSim, load_symbols_csv
        if not os.path.exists(self.image):
            raise FileNotFoundError(self.image)
        syms = load_symbols_csv(self.symbols)
        self._fill = syms.get("fn_fill_cfg_block", self._FILL_ADDR)
        return ArmSim(self.image, syms)

    def _build_block(self, sim, blk):
        sim.wbytes(self.FRAME, bytes([0] * 0x40))
        sim.call(self._fill, (self.FRAME, 0x14, blk))
        return sim.rbytes(self.FRAME, 0x40)


class OursBackend(_Backend):
    """Our firmware: dongle write + our dsp_build_config_frame(&g_dsp_src, ...).
    The frame is built into a scratch page (0x30000000) the harness maps on use."""
    name = "ours"
    boot_insn = 4_000_000
    SCRATCH = 0x30000000

    def __init__(self, bin_path, elf_path):
        super().__init__()
        self.bin_path = bin_path
        self.elf_path = elf_path

    def _new_sim(self):
        from arm_sim import ArmSim, load_symbols_nm
        if not (self.bin_path and self.elf_path
                and os.path.exists(self.bin_path) and os.path.exists(self.elf_path)):
            raise FileNotFoundError(self.bin_path or "ours")
        syms = load_symbols_nm(self.elf_path)
        self._build_fn = syms["dsp_build_config_frame"]
        self._src = syms["g_dsp_src"]
        sim = ArmSim(self.bin_path, syms)
        # Map the scratch page explicitly: it is written via the direct mem API
        # (wbytes), which -- unlike emulated access -- does not trigger the
        # harness's map-on-unmapped hook.
        sim.uc.mem_map(self.SCRATCH, 0x1000)
        return sim

    def _build_block(self, sim, blk):
        sim.wbytes(self.SCRATCH, bytes([0] * 0x40))
        sim.call(self._build_fn, (self._src, blk, self.SCRATCH, 0x80))
        return sim.rbytes(self.SCRATCH, 0x40)

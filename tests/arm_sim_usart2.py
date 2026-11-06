#!/usr/bin/env python3
"""
USART2 safety-CPU wire feeder for the arm_sim harness (tools/arm_sim.py).

The factory's redundant "safety" CPU streams an EG4 type-1 telemetry frame to the
ARM over **USART2** (`0x40004400`, docs/33, docs/wiring/ARM-USART2-safety.md). The
ARM receives it **interrupt-driven on RXNE** -- NOT by DMA: at the post-boot idle
`USART2->CR1` = 0x20AC (UE|TE|RE|**RXNEIE**|TXEIE) and `USART2->CR3` = 0 (no DMAR)
(T02 harness RE, docs/19). So a harness feeds it exactly the way
tests/arm_sim_modbus.py feeds a Modbus UART: make SR show RXNE while a byte
waits, hand the next byte on the DR read, and pend the USART2 IRQ (NVIC IRQn=38 ->
exception vector 16+38=54) so the firmware's own RX ISR runs. The firmware pulls
every byte through its real interrupt path; the harness never pokes a buffer.

The full receive chain is cracked (docs/33, docs/19 §T02): the RX ISR
(`sub_0801bddc`) drains DR, the assembler (`sub_0801bb0e`) collects an EG4
"type-1" frame (SOF `0x49`, `frame[1]`=type, `frame[3]`=len so total=`len`+6,
buffer capped <0x40), validates CRC-16/MODBUS over `frame[0:total-2]` with the
checksum stored MSB-first, then the distributor (`sub_0802677a`) + tag parser
(`sub_08025ab8`) decode it into the telemetry bank at **`0x2000ce5c`** -- from
where the factory's own register getter serves it over Modbus. `build_frame()`
below assembles a valid frame; feeding one updates the bank and the served IRs
(docs/39 T02a, done). This is also the wire-feed foundation for T05 (our USART2
driver).

Requires enable_rtos() (the factory receives purely by IRQ). Needs
`pip install unicorn`.
"""
import struct

SAFETY_BANK = 0x2000ce5c     # the USART2 telemetry bank the parser fills (docs/33)
USART2   = 0x40004400
U2_SR    = USART2 + 0x00
U2_DR    = USART2 + 0x04
U2_CR1   = USART2 + 0x0C
U2_CR3   = USART2 + 0x14
SR_RXNE     = 1 << 5
CR1_RXNEIE  = 1 << 5
CR3_DMAR    = 1 << 6
USART2_VEC  = 16 + 38       # NVIC USART2_IRQn=38 -> exception vector 54


class Usart2SafetyWire:
    """Drive `sim` as the safety CPU on USART2: feed(data) delivers bytes to the
    factory's RX ISR over the wire. Boots the image into its RTOS on construction
    (config flash provisioned, enable_rtos), the same way ModbusDongle does."""

    def __init__(self, sim, systick=20_000, boot_insn=20_000_000, boot=True):
        self.sim = sim
        self._rx = []
        self._consumed = 0          # bytes the firmware has read from DR
        self._install_hooks()
        # `boot=False` attaches the wire to a sim another peer already booted
        # (e.g. a ModbusDsp on USART3): share one RTOS boot instead of two.
        if boot:
            if getattr(sim, "spi_flash", None) is None:
                sim.attach_config_flash()     # the factory needs a valid config to boot
            sim.enable_rtos(systick)          # RX is delivered via the IRQ engine
            sim.run_reset(max_insn=boot_insn)

    def _install_hooks(self):
        from unicorn import UC_HOOK_MEM_READ
        uc = self.sim.uc

        def on_sr(uc, access, addr, size, value, ud):
            if self._rx:
                cur = struct.unpack("<I", uc.mem_read(U2_SR, 4))[0]
                uc.mem_write(U2_SR, struct.pack("<I", cur | SR_RXNE))
            return True

        def on_dr(uc, access, addr, size, value, ud):
            if self._rx:
                uc.mem_write(U2_DR, struct.pack("<I", self._rx.pop(0)))
                self._consumed += 1
                # Interrupt-driven: while bytes remain and RXNEIE is armed, re-pend
                # so the ISR runs again for the next byte (back-to-back delivery).
                if self._rx and (self.sim.r32(U2_CR1) & CR1_RXNEIE):
                    self.sim.pend_irq(USART2_VEC)
            return True

        uc.hook_add(UC_HOOK_MEM_READ, on_sr, begin=U2_SR, end=U2_SR + 4)
        uc.hook_add(UC_HOOK_MEM_READ, on_dr, begin=U2_DR, end=U2_DR + 4)

    def rx_is_interrupt_driven(self):
        """True iff the factory armed RXNE interrupts and did NOT wire RX DMA."""
        return bool(self.sim.r32(U2_CR1) & CR1_RXNEIE) and not (self.sim.r32(U2_CR3) & CR3_DMAR)

    def feed(self, data, chunk=150_000, max_chunks=40, settle=600_000):
        """Feed `data` (bytes) to the firmware over USART2. Returns the number of
        bytes the firmware actually read from DR (== len(data) when every byte was
        received through the RX ISR)."""
        self._rx = list(bytes(data))
        self._consumed = 0
        want = len(self._rx)
        for _ in range(max_chunks):
            if self._rx and (self.sim.r32(U2_CR1) & CR1_RXNEIE):
                self.sim.pend_irq(USART2_VEC)
            self.sim.run(chunk)
            if not self._rx:
                break
        if settle:
            self.sim.run(settle)
        return self._consumed

    def feed_frame(self, fields, type_byte=1, total=0x3f):
        """Build a valid EG4 type-1 frame from `fields` (see build_frame) and feed
        it on the wire. Returns the bytes consumed (== len(frame) on full receipt)."""
        return self.feed(build_frame(fields, type_byte=type_byte, total=total))


def crc16_modbus(data):
    """CRC-16/MODBUS (init 0xFFFF, poly 0xA001, reflected) -- the factory's frame
    checksum (table-driven as `sub_080160bc` in the image)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def build_frame(fields, type_byte=1, total=0x3f):
    """Assemble an EG4 "type-1" USART2 safety frame the factory's RX chain accepts.

    Layout (big-endian throughout, as the parser reads it):
      frame[0]       = 0x49  (SOF)
      frame[1]       = type_byte (the consumer gates on == 1)
      frame[3]       = total - 6  (declared length; assembler caps total < 0x40)
      frame[total-2:total] = CRC-16/MODBUS over frame[0:total-2], **MSB-first**

    `fields` places payload values: {frame_offset: (value, width)} with width in
    {1,2,4}; multi-byte values are stored big-endian. Header fields live at fixed
    offsets (frame[+4]=mode, +5=fault u32, +9=warn u32, +0xd=mode2); a tag record
    starts at frame[+0x14] (frame[+0x14]=tag selector, then the tag's fields). The
    per-tag frame->bank map is in docs/33. Total defaults to 0x3f (the largest the
    assembler accepts)."""
    assert 7 <= total < 0x40, "frame total must be in [7, 0x3f) (assembler cap)"
    f = bytearray(total)
    f[0] = 0x49
    f[1] = type_byte
    f[3] = total - 6
    for off, (val, width) in fields.items():
        for i in range(width):
            f[off + i] = (val >> (8 * (width - 1 - i))) & 0xFF   # big-endian
    crc = crc16_modbus(bytes(f[:total - 2]))
    f[total - 2] = (crc >> 8) & 0xFF
    f[total - 1] = crc & 0xFF
    return bytes(f)

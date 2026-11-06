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

This is the wire-feed foundation for docs/39 T02a (feed USART2 bytes -> bank/IR)
and T05 (our USART2 driver). Frame *assembly* into the bank is still open (the
consumer's frame-completion condition, docs/19 §"T02 in progress"); this helper
proves the byte-reception half end to end, deterministically.

Requires enable_rtos() (the factory receives purely by IRQ). Needs
`pip install unicorn`.
"""
import struct

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

    def __init__(self, sim, systick=20_000, boot_insn=20_000_000):
        self.sim = sim
        self._rx = []
        self._consumed = 0          # bytes the firmware has read from DR
        self._install_hooks()
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

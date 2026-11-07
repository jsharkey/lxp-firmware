/*
 * Operating-state classifier + fault/warning composer (docs/22, docs/39 T06).
 *
 * The ARM's "mode module" is a CLASSIFIER, not a power FSM (docs/22): the DSP
 * decides the real operating mode and streams it (plus the safety CPU's
 * fault/warn cross-check) to the ARM over USART2; the ARM passes the received
 * mode byte straight through to IR 0 (State) and merges the relayed 32-bit
 * fault/warn words with a few ARM-local bits into IR 60/61 (FaultCode) and IR
 * 62/63 (WarningCode). See docs/wiring/ARM-UART5-dongle/IR000-State.md and
 * IR060_063-FaultCode_WarningCode.md for the register semantics.
 *
 * This is a pure function: (received mode byte, relayed fault/warn words, local
 * overlay flags) -> (state, fault32, warn32), no I/O and no globals, so it is
 * callable from the host unit test (tests/test_classify.c), from a sim e2e test,
 * and from main.c.
 *
 * ORACLE STATUS (docs/39 T06b): now pinned against the factory 07 image. State
 * (IR 0) is a PURE PASS-THROUGH of the relayed mode byte -- no canonicalisation,
 * no fault override (proven by feeding mode bytes on the USART2 wire and reading
 * IR_STATE 0x2000d0e4+0xa0; the classifier is sub_0801a678). The fault/warn
 * COMPOSITION is the relayed 32-bit word with ARM-set E000/E017 and ARM-computed
 * W008 (E027 is the frame's own bit); a relayed fault flows to the FaultCode
 * without changing State. (This corrected docs/22's 05-series guesses of a 0x02
 * fault-override target and a 0x08 non-canonical default -- neither exists on 07.)
 */
#ifndef INV_CLASSIFY_H
#define INV_CLASSIFY_H

#include <stdint.h>
#include <stdbool.h>

/* ARM-local overlay flags: conditions the ARM sets itself, on top of the
 * safety-CPU-relayed fault/warn words (docs/22, IR060_063). */
enum {
    INV_LOCAL_FAULT_E000  = 1u << 0,  /* E000 internal comm fault 1  -> FaultCode bit 0  */
    INV_LOCAL_FAULT_E017  = 1u << 1,  /* E017 internal comm fault 2  -> FaultCode bit 17 */
    INV_LOCAL_WARN_W008   = 1u << 2,  /* W008 FW-version mismatch    -> WarningCode bit 8 */
};

typedef struct {
    uint16_t state;   /* IR 0      operating mode (inv_state_t / states.h) */
    uint32_t fault;   /* IR 60/61  32-bit FaultCode bitfield               */
    uint32_t warn;    /* IR 62/63  32-bit WarningCode bitfield             */
} inv_class_t;

/* FaultCode bit set by the ARM locally (not relayed). */
#define INV_FAULT_BIT_E000   0u
#define INV_FAULT_BIT_E017   17u
#define INV_WARN_BIT_W008    8u

/* Classify a received DSP mode byte + relayed/safety fault&warn words into the
 * Modbus-served State / FaultCode / WarningCode. `local_flags` is a mask of
 * INV_LOCAL_*; `relayed_fault`/`relayed_warn` are the 32-bit words relayed from
 * the safety CPU (IR060_063). */
inv_class_t inv_classify(uint8_t mode_byte, uint32_t relayed_fault,
                         uint32_t relayed_warn, uint32_t local_flags);

/* True if `mode_byte` is a canonical operating-mode value (Table 9 + the two
 * LCD-only codes 0x11 Bypass and 0x19 PV-charge+Bypass). */
bool inv_state_is_canonical(uint8_t mode_byte);

#endif /* INV_CLASSIFY_H */

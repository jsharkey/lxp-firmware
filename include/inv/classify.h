/*
 * Operating-state classifier + fault/warning composer (docs/22, docs/39 T06).
 *
 * The ARM's "mode module" is a CLASSIFIER, not a power FSM (docs/22): the DSP
 * decides the real operating mode and streams it (plus the safety CPU's
 * fault/warn cross-check) to the ARM over USART2; the ARM canonicalises the
 * received mode byte into IR 0 (State) and merges the relayed 32-bit fault/warn
 * words with a few ARM-local bits into IR 60/61 (FaultCode) and IR 62/63
 * (WarningCode). See docs/wiring/ARM-UART5-dongle/IR000-State.md and
 * IR060_063-FaultCode_WarningCode.md for the register semantics.
 *
 * This is a pure function: (received mode byte, relayed fault/warn words, local
 * overlay flags) -> (state, fault32, warn32), no I/O and no globals, so it is
 * callable from the host unit test (tests/test_classify.c), from a Unicorn
 * micro-test by symbol (tests/classify_contract.py), and from main.c.
 *
 * ORACLE STATUS (docs/39 T06b): the fault/warn COMPOSITION below is pinned by
 * the Modbus spec + IR060_063 doc (relayed word, with E000/E017 ARM-set and
 * W008 ARM-computed; E027 is the frame's own bit). The STATE override target
 * and the unknown-byte default are taken from docs/22's description and are NOT
 * yet verified against the factory 07 image's classifier -- that function's
 * entry + its telemetry/STATUS RAM base are not yet re-pinned for the 07 image
 * (docs/22's addresses are 05-series; see docs/22 "07 re-pin" / docs/39 T06b).
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
    INV_LOCAL_NOT_RUNNING = 1u << 3,  /* force the not-running state override            */
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

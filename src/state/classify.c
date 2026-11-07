/*
 * Operating-state classifier + fault/warning composer -- see inv/classify.h.
 *
 * docs/22 (the ARM/DSP split) establishes the shape, refined by the 07 oracle
 * (docs/39 T06b): the ARM PASSES THROUGH the received mode byte to IR 0
 * verbatim (no canonicalisation, no fault override), and it MERGES the relayed
 * 32-bit fault/warn words with a few ARM-local bits for IR 60-63.
 */
#include "inv/classify.h"
#include "inv/states.h"

bool inv_state_is_canonical(uint8_t m)
{
    switch (m) {
    /* Table 9 (IR000-State.md) */
    case STATE_STANDBY:           /* 0x00 */
    case STATE_FAULT:             /* 0x01 */
    case STATE_PROGRAMMING:       /* 0x02 */
    case STATE_PV_ONGRID:         /* 0x04 */
    case STATE_PV_CHARGE:         /* 0x08 */
    case STATE_PV_CHARGE_ONGRID:  /* 0x0C */
    case STATE_BAT_ONGRID:        /* 0x10 */
    case STATE_PV_BAT_ONGRID:     /* 0x14 */
    case STATE_AC_CHARGE:         /* 0x20 */
    case STATE_PV_AC_CHARGE:      /* 0x28 */
    case STATE_BAT_OFFGRID:       /* 0x40 */
    case STATE_PV_OFFGRID:        /* 0x80 */
    case STATE_PV_CHARGE_OFFGRID: /* 0x88 */
    case STATE_PV_BAT_OFFGRID:    /* 0xC0 */
    /* LCD-only status codes (IR000-State.md "On the LCD"): the manual's §17.3
     * table adds these two beyond the Modbus operating-mode table. */
    case 0x11:                    /* Bypass */
    case 0x19:                    /* PV Charge + Bypass */
        return true;
    default:
        return false;
    }
}

inv_class_t inv_classify(uint8_t mode_byte, uint32_t relayed_fault,
                         uint32_t relayed_warn, uint32_t local_flags)
{
    inv_class_t out;

    /* --- FaultCode (IR 60/61): relayed word + ARM-local bits ---------------
     * Most bits pass through from the safety-CPU frame verbatim; the ARM sets
     * E000 (bit 0) and E017 (bit 17) itself. E027 (bit 27) is the frame's own
     * "sample mismatch" verdict, so it is left to pass through. (IR060_063.) */
    out.fault = relayed_fault;
    if (local_flags & INV_LOCAL_FAULT_E000)
        out.fault |= (1u << INV_FAULT_BIT_E000);
    if (local_flags & INV_LOCAL_FAULT_E017)
        out.fault |= (1u << INV_FAULT_BIT_E017);

    /* --- WarningCode (IR 62/63): relayed word + ARM-local W008 -------------
     * The grid/high warnings come from the frame; W008 (FW-version mismatch,
     * bit 8) is computed on the ARM from the per-processor version compare. */
    out.warn = relayed_warn;
    if (local_flags & INV_LOCAL_WARN_W008)
        out.warn |= (1u << INV_WARN_BIT_W008);

    /* --- State (IR 0): a PURE PASS-THROUGH of the relayed mode byte ---------
     * ORACLE-PINNED (docs/39 T06b, 07 image): the classifier writes IR_STATE
     * (0x2000d0e4+0xa0) as the received mode byte, VERBATIM -- there is no
     * canonicalisation and no fault override. Proven on the factory by feeding a
     * mode byte on the USART2 wire and reading IR_STATE back: every byte
     * 0x00-0xFF appears unchanged (canonical, LCD 0x11/0x19, and arbitrary bytes
     * like 0x55/0xFF alike), and a relayed fault flows to the FaultCode (IR 60/61,
     * below) WITHOUT changing IR_STATE. The DSP itself encodes Fault (0x01) /
     * Standby (0x00) in the mode byte it relays, so the ARM need not re-derive it.
     * (This CORRECTS docs/22's 05-series guesses of a 0x02 fault-override target
     * and a 0x08 non-canonical default -- neither exists on the 07 image.) */
    out.state = mode_byte;

    return out;
}

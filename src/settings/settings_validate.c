/*
 * Holding-register write validation. See inv/settings_validate.h and docs/39 T04/T24.
 *
 * Mirrors the factory's observed dongle write verdicts (recovered black-box by the
 * whole-HR boundary sweep, docs/39 T24 / tests/wrsem_expected.py):
 *   out-of-range value   -> MB_EXC_ILLEGAL_VALUE   (3)  (value not stored)
 *   not-writable register -> MB_EXC_ILLEGAL_ADDRESS (2)
 *   read-only register    -> MB_EXC_SLAVE_FAILURE   (4)
 * The enforced bounds below are the factory's *actual* ones, which for several
 * registers are tighter than the published spec (HR 20/59 max 6 not 7; HR 100/146
 * narrower; HR 75/99/101/105 one-sided) -- all catalogued in docs/31 Q6/Q11.
 *
 * Resolution note: bounds are pinned at the sweep's boundary probes (min-1/min/
 * max/max+1). Where the factory accepts below the documented min (HR 23/99) the low
 * bound is modelled as 0 -- no low reject was observed at that resolution.
 *
 * Not replicated (left permissive, a recorded gap in wrsem_expected.OURS_DEVIATIONS):
 * HR 24/113/144 reject *every* value in the bare-boot state -- precondition-gated
 * (docs/31 Q11), so ours keeps accepting valid writes rather than block them.
 */
#include "inv/settings_validate.h"
#include "inv/modbus_map.h"

#define NO_MAX 0xFFFFu          /* "this register enforces no upper bound" */

/* reg -> [lo, hi] inclusive. Out-of-range writes draw MB_EXC_ILLEGAL_VALUE. */
typedef struct { uint16_t reg, lo, hi; } sv_range_t;
static const sv_range_t RANGES[] = {
    { HR_COM_ADDR,         0, 150    },   /* HR 15                                   */
    { HR_PV_INPUT_MODEL,   0,   6    },   /* HR 20: factory max 6, not the spec's 7  */
    { HR_CONNECT_TIME,     0, 599    },   /* HR 23: rejects 600 (spec max); accepts <30 */
    { HR_REACTIVE_CMD_TYPE,0,   6    },   /* HR 59: factory max 6, not 7             */
    { HR_CHG_POWER_PCT,    0, 100    },   /* HR 64                                   */
    { HR_DISCHG_POWER_PCT, 0, 100    },   /* HR 65                                   */
    { HR_ACCHG_POWER_PCT,  0, 100    },   /* HR 66                                   */
    { HR_CHGFIRST_SOC,     1, NO_MAX },   /* HR 75: rejects 0, no upper bound        */
    { HR_CHARGE_VOLT_REF,  0, 590    },   /* HR 99: accepts <500 (spec min); max 590 */
    { HR_CUT_VOLT_DISCHG, 400, 499   },   /* HR 100: rejects 500 (spec max)          */
    { HR_CHARGE_CURR,      0, NO_MAX },   /* HR 101: no upper bound (docs/31 Q6)     */
    { HR_EOD,             11, NO_MAX },   /* HR 105: factory rejects 10; lower only  */
    { HR_LINE_MODE,        0,   1    },   /* HR 146: rejects 2 (GEN) in cold state   */
    { HR_BAT_NOMINAL_VOLT,400, 590   },   /* HR 148                                  */
    { HR_BAT_LOW_VOLT,    420, 560   },   /* HR 162: discharge cut-off V (T17; dongle 420-560, wider than spec) */
    { HR_BAT_LOW_SOC,      15, 100   },   /* HR 164: discharge cut-off SOC (T17; dongle 15-100) */
    { HR_GEN_CHG_START_V, 384, 519   },   /* HR 194: rejects 520 (spec max)          */
    { HR_GEN_CHG_END_V,   480, 590   },   /* HR 195                                  */
    { HR_GEN_CHG_START_SOC, 1,  90   },   /* HR 196: rejects 0                       */
    { HR_GEN_CHG_END_SOC,  20, 100   },   /* HR 197                                  */
    { HR_MAX_GEN_CHG_CURR,  1, NO_MAX },   /* HR 198: rejects 0, no upper bound       */
};

/* Registers the factory refuses to write at all (exception 2). These are the
 * charge-priority / forced-discharge power+SOC slots (inert in the DSP push too)
 * plus StartPVVolt (Q7), OutputPrioConfig, and the two discharge *recovery* points
 * (HR 163/165, "BatLowBack*") which answer ILLEGAL_ADDRESS on the dongle for every
 * value -- HMI-only there (T17; docs/11 #7). Their cut-off siblings (HR 162/164)
 * ARE dongle-writable (ranges above). */
static const uint16_t NOT_WRITABLE[] = {
    HR_START_PV_VOLT,    /* HR 22  (docs/31 Q7)   */
    HR_ACCHG_SOC_LIMIT,  /* HR 67                 */
    HR_CHGFIRST_POWER,   /* HR 74                 */
    HR_FDISCHG_POWER,    /* HR 82                 */
    HR_FDISCHG_SOC,      /* HR 83                 */
    HR_OUTPUT_PRIO_CFG,  /* HR 145                */
    HR_BAT_LOW_BACK_VOLT,/* HR 163: discharge recovery V -- dongle rejects every value (T17) */
    HR_BAT_LOW_BACK_SOC, /* HR 165: discharge recovery SOC -- dongle rejects every value (T17) */
};

/* Read-only: writes are answered with an exception (FW-version words are reported,
 * not set). */
static const uint16_t READONLY[] = { HR_SLAVE_COM_VER, HR_CNTL_FW_VER };  /* HR 9, 10 */

sv_result_t settings_validate(uint16_t reg, uint16_t val)
{
    sv_result_t r = { val, MB_OK };

    for (unsigned i = 0; i < sizeof READONLY / sizeof READONLY[0]; i++)
        if (reg == READONLY[i]) { r.exc = MB_EXC_SLAVE_FAILURE; return r; }

    for (unsigned i = 0; i < sizeof NOT_WRITABLE / sizeof NOT_WRITABLE[0]; i++)
        if (reg == NOT_WRITABLE[i]) { r.exc = MB_EXC_ILLEGAL_ADDRESS; return r; }

    /* HR 112 SetSystemType: 2 (= slave) is rejected black-box; 0/1/3 accepted
     * (docs/31 Q9). A single forbidden value, not a range. */
    if (reg == HR_SET_SYSTEM_TYPE) {
        if (val == 2) r.exc = MB_EXC_ILLEGAL_VALUE;
        return r;
    }

    for (unsigned i = 0; i < sizeof RANGES / sizeof RANGES[0]; i++) {
        if (reg == RANGES[i].reg) {
            if (val < RANGES[i].lo || val > RANGES[i].hi)
                r.exc = MB_EXC_ILLEGAL_VALUE;
            return r;
        }
    }
    return r;   /* registers without a recovered rule: accept verbatim */
}

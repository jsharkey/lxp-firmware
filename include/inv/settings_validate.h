/*
 * Holding-register write validation (dongle Modbus func 0x06/0x10).
 *
 * The factory dongle slave range-checks a write and, on an out-of-range value,
 * REJECTS it with a Modbus exception -- it does not clamp or store (oracle:
 * tests/test_settings_validate.py + settings_contract.py, docs/39 T04). Writes to
 * read-only registers draw a different exception. This is the clean-room
 * equivalent, placed in front of both the Modbus and the HMI write paths.
 *
 * Observed factory verdicts (ceaa-07xx family image):
 *   in-range value          -> accept, store (echo)
 *   out-of-range value      -> reject, MB_EXC_ILLEGAL_VALUE (3), value NOT stored
 *   write to a read-only reg -> reject, MB_EXC_SLAVE_FAILURE (4)
 * Some registers enforce only one bound (docs/31) -- replicated here for parity.
 */
#ifndef INV_SETTINGS_VALIDATE_H
#define INV_SETTINGS_VALIDATE_H

#include <stdint.h>
#include "inv/modbus.h"      /* mb_exception_t */

typedef struct {
    uint16_t       value;    /* value to store when accepted (clamp reserved; unused today) */
    mb_exception_t exc;      /* MB_OK => accept & store; otherwise reject with this code */
} sv_result_t;

/* Validate a holding-register write. Pure: register + value in, verdict out. */
sv_result_t settings_validate(uint16_t reg, uint16_t val);

#endif /* INV_SETTINGS_VALIDATE_H */

"""Shared contract for the pinned settings-persistence table (docs/23, T03).

One table drives both the cross-image oracle (`test_persist_crossimage.py`) and
mirrors the C side (`include/inv/settings_map.h`). Each row:

    (reg, slot, off, width, scale, test)

- reg    : Modbus holding register
- slot   : config-flash slot (0 = main settings, 5 = grid/protection)
- off    : byte offset into the slot's 250-byte payload (docs/23)
- width  : stored width in bytes (1 or 2) -- SETTLED against the factory oracle,
           which is why the slot-5 power-command block is width 1, not the "2B"
           docs/23 first recorded (see docs/23 "Width correction").
- scale  : wire-value * scale = stored value (factory scales ChargeCurr /
           DischgCurr / MaxBackFlow x10 before storing; everything else x1)
- test   : a distinct, in-range wire value to round-trip (docs/23 example + 1,
           so it differs from a likely default while staying in range and
           preserving High>Low ordering on the grid-limit pairs)

The C header must stay in lockstep; the cross-image test is what enforces it (a
wrong offset/width/scale makes one direction read the wrong bytes).
"""

# reg  slot  off    width scale test
SETTINGS_MAP = [
    # --- slot 0: main inverter / working settings (all width 2) ---
    (15,  0, 0x00, 1, 1,   31),    # ComAddr (1 byte; SN[0..9] occupies 0x01..0x0a, T24d)
    (21,  0, 0x13, 2, 1,  310),    # FuncEn (bitmask)
    (110, 0, 0x15, 2, 1,   22),    # FunctionEn1 (bitmask)
    (20,  0, 0x18, 2, 1,    4),    # PVInputModel (0-7)
    (112, 0, 0x1b, 2, 1,    1),    # SetSystemType (0-2; value 2=slave is gated/rejected)
    (119, 0, 0x2f, 2, 1,  101),    # wCT_PowerOffset
    (120, 0, 0x33, 2, 1,   22),    # stSysEnable (bitmask)
    (68,  0, 0x3a, 2, 1, 1542),    # ACChgStart  (hh:mm packed)
    (69,  0, 0x3c, 2, 1, 2056),    # ACChgEnd
    (70,  0, 0x3e, 2, 1, 2311),    # ACChgStart1
    (71,  0, 0x40, 2, 1, 2825),    # ACChgEnd1
    (72,  0, 0x42, 2, 1, 3339),    # ACChgStart2
    (73,  0, 0x44, 2, 1, 3853),    # ACChgEnd2
    (147, 0, 0x70, 2, 1,  101),    # Battery capacity (Ah)
    (99,  0, 0x74, 2, 1,  561),    # ChargeVoltRef (0.1 V, 500-590)
    (151, 0, 0x7c, 2, 1,    5),    # EqualizationTime
    (101, 0, 0x8c, 2, 10,  43),    # ChargeCurr  (A, stored x10)
    (102, 0, 0x8e, 2, 10,  44),    # DischgCurr  (A, stored x10)
    (103, 0, 0x9c, 2, 10,  51),    # MaxBackFlow (%, stored x10)
    (105, 0, 0x9e, 2, 1,   21),    # EOD (%, 10-90)
    (107, 0, 0xa1, 2, 1,  311),    # TemprUpperLimitDischg
    (109, 0, 0xa5, 2, 1,  331),    # TemprUpperLimitChg (docs/23 said +0xa4; real +0xa5)
    # AC-First windows (HR 152-157): pinned by T03 probe, slot 0 +0x64 stride 2
    # (not in docs/23's original table). hh:mm-packed; distinct from the ACChg set.
    (152, 0, 0x64, 2, 1, 1543),    # ACFirstStart0
    (153, 0, 0x66, 2, 1, 2057),    # ACFirstEnd0
    (154, 0, 0x68, 2, 1, 2312),    # ACFirstStart1
    (155, 0, 0x6a, 2, 1, 2826),    # ACFirstEnd1
    (156, 0, 0x6c, 2, 1, 3340),    # ACFirstStart2
    (157, 0, 0x6e, 2, 1, 3854),    # ACFirstEnd2

    # --- slot 5: packed power-command block (width 1, +0x00..+0x07) ---
    (60,  5, 0x00, 1, 1,   56),    # ActivePowerPercentCMD (%)
    (61,  5, 0x01, 1, 1,   31),    # ReactivePowerPercentCMD (%)
    (64,  5, 0x02, 1, 1,   52),    # ChargePowerPercentCMD (%)
    (65,  5, 0x03, 1, 1,   53),    # DischgPowerPercentCMD (%)
    (66,  5, 0x04, 1, 1,   54),    # ACChgPowerCMD (%)
    (23,  5, 0x05, 1, 1,  121),    # ConnectTime (s, stored as 1 byte)
    (59,  5, 0x07, 1, 1,    4),    # ReactivePowerCMDType (0-7)

    # --- slot 5: grid-code protection block (width 2, +0x0a..) ---
    (30,  5, 0x0a, 2, 1, 2701),    # GridVoltLimit1High
    (34,  5, 0x0c, 2, 1, 2801),    # GridVoltLimit2High
    (38,  5, 0x0e, 2, 1, 2901),    # GridVoltLimit3High
    (29,  5, 0x10, 2, 1, 1801),    # GridVoltLimit1Low
    (33,  5, 0x12, 2, 1, 1701),    # GridVoltLimit2Low
    (37,  5, 0x14, 2, 1, 1601),    # GridVoltLimit3Low
    (32,  5, 0x16, 2, 1,  111),    # GridVoltLimit1HighTime
    (36,  5, 0x18, 2, 1,  131),    # GridVoltLimit2HighTime
    (40,  5, 0x1a, 2, 1,  151),    # GridVoltLimit3HighTime
    (31,  5, 0x1c, 2, 1,  101),    # GridVoltLimit1LowTime
    (35,  5, 0x1e, 2, 1,  121),    # GridVoltLimit2LowTime
    (39,  5, 0x20, 2, 1,  141),    # GridVoltLimit3LowTime
    (43,  5, 0x22, 2, 1, 5301),    # GridFreqLimit1High
    (47,  5, 0x24, 2, 1, 5401),    # GridFreqLimit2High
    (51,  5, 0x26, 2, 1, 5501),    # GridFreqLimit3High
    (46,  5, 0x2a, 2, 1, 4601),    # GridFreqLimit2Low
    (45,  5, 0x2e, 2, 1,  171),    # GridFreqLimit1HighTime
    (49,  5, 0x30, 2, 1,  191),    # GridFreqLimit2HighTime
    (53,  5, 0x32, 2, 1,  211),    # GridFreqLimit3HighTime
    (44,  5, 0x34, 2, 1,  161),    # GridFreqLimit1LowTime
    (48,  5, 0x36, 2, 1,  181),    # GridFreqLimit2LowTime
    (52,  5, 0x38, 2, 1,  201),    # GridFreqLimit3LowTime
    (26,  5, 0x3a, 2, 1, 2601),    # GridVoltConnHigh
    (25,  5, 0x3c, 2, 1, 2001),    # GridVoltConnLow
    (28,  5, 0x3e, 2, 1, 5201),    # GridFreqConnHigh
    (27,  5, 0x40, 2, 1, 4801),    # GridFreqConnLow
    (75,  5, 0x7a, 2, 1,   83),    # ChgFirstSOCLimit
]


def fields():
    """Yield dicts for readability."""
    for reg, slot, off, width, scale, test in SETTINGS_MAP:
        yield {"reg": reg, "slot": slot, "off": off,
               "width": width, "scale": scale, "test": test}

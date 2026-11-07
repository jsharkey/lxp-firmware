#!/usr/bin/env python3
"""Whole-HR write-semantics sweep -- the SAME spec, factory-vs-ours (docs/39 T24).

T04 (settings_contract.py) built the verdict mechanism but covered only six
registers by hand. This extends it to every holding register with a documented
range: for each it probes the four boundary vectors -- min-1 / min / max / max+1
-- plus the read-only version registers, and records the factory's verdict
(accept / reject:<exc>) per vector. The committed expectation is wrsem_expected.py
and the per-register quirks are in docs/31 (Q6 one-sided bounds, Q9 HR112 rejects
2, ...). Our firmware (settings_validate) must give the SAME verdict for each
vector -- that parity is the test.

Verdict capture, fresh boot per value, and the ours/factory backends are reused
verbatim from settings_contract.py (T04): write_verdict() drives one write on a
clean boot and classifies the reply frame.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from settings_contract import FactoryBackend, OursBackend          # noqa: E402  (reused T04 backends)

# Curated from include/inv/modbus_map.h: holding register -> (min, max) for every
# HR with a numeric range in the spec. (Enumerated/bitfield/window/command
# registers -- 16, 21, 90, 91, 110, 120, 126-131, windows -- are not simple
# ranges and are left to T24b / their own tests; read-only 9/10 are probed below.)
RANGES = {
    15:  (0, 150),     # ComAddr
    20:  (0, 7),       # PVInputModel
    22:  (900, 5000),  # StartPVVolt (0.1 V)
    23:  (30, 600),    # ConnectTime (s)
    24:  (0, 900),     # ReconnectTime (s)
    59:  (0, 7),       # ReactiveCmdType
    64:  (0, 100),     # ChgPowerPct
    65:  (0, 100),     # DischgPowerPct
    66:  (0, 100),     # ACChgPowerPct
    67:  (0, 100),     # ACChgSocLimit
    74:  (0, 100),     # ChgFirstPower
    75:  (0, 100),     # ChgFirstSoc
    82:  (0, 100),     # FDischgPower
    83:  (0, 100),     # FDischgSoc
    99:  (500, 590),   # ChargeVoltRef (0.1 V)
    100: (400, 500),   # CutVoltDischg (0.1 V)
    101: (0, 140),     # ChargeCurr (A)
    102: (0, 140),     # DischgCurr (A)
    105: (10, 90),     # EOD (%)
    112: (0, 2),       # SetSystemType (2 = slave, gated -- Q9)
    113: (1, 3),       # SetComposedPhase
    144: (500, 560),   # FloatChargeVolt (0.1 V)
    145: (0, 2),       # OutputPrioCfg
    146: (0, 2),       # LineMode
    148: (400, 590),   # BatNominalVolt (0.1 V)
    194: (384, 520),   # GenChgStartV (0.1 V)
    195: (480, 590),   # GenChgEndV (0.1 V)
    196: (0, 90),      # GenChgStartSoc (%)
    197: (20, 100),    # GenChgEndSoc (%)
    198: (0, 60),      # MaxGenChgCurr (A)
}

# Read-only registers: any write should be rejected (SLAVE_FAILURE = exc 4).
READ_ONLY = [9, 10]


def boundary_vectors(reg):
    """(label, value) at min-1 / min / max / max+1 for one ranged register.
    min-1 is clamped at 0 (u16); if min==0 there is no 'below', so it is skipped."""
    lo, hi = RANGES[reg]
    vs = []
    if lo > 0:
        vs.append(("min-1", lo - 1))
    vs.append(("min", lo))
    vs.append(("max", hi))
    vs.append(("max+1", hi + 1))
    return vs


def all_vectors():
    """-> [(reg, label, value)] for every ranged HR boundary + read-only probes."""
    out = []
    for reg in sorted(RANGES):
        for label, val in boundary_vectors(reg):
            out.append((reg, label, val))
    for reg in READ_ONLY:
        out.append((reg, "read-only", 0x1234))
    return out


def sweep(backend):
    """Run every vector on a backend and return {(reg, value): verdict}."""
    return {(reg, val): backend.write_verdict(reg, val)
            for reg, _label, val in all_vectors()}

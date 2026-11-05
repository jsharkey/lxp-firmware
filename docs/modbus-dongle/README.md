# The dongle Modbus register surface — authoritative map

**This directory is the source of truth for the external "dongle" Modbus
registers** — the register interface the EG4 datalogger polls over RS-485. One
file per register (or merged group) that we have reverse-engineered facts for;
the full spec surface is indexed below. When a numbered analysis doc (`docs/NN`)
and a file here disagree about a dongle register, **the file here wins**.

Spec source: the **EG4 18kPV-12LV Modbus RTU Protocol** PDF (the 18kPV superset;
the 12000XP is a subset — see "Variant" below). Our committed machine-readable
map is [`include/inv/modbus_map.h`](../../include/inv/modbus_map.h).

## Scope — this is ONLY the dongle surface

There are **four** EG4-Modbus-*family* links in this system. They share the
frame shape (`addr func … CRC-16/0xA001`) but are **different wires with
different framing**, and only the first is in scope here:

| link | wire | framing | documented in |
|---|---|---|---|
| **Dongle Modbus** ← *this tree* | ARM **UART5**, external RS-485 | **little-endian**, 10-byte **SN**, func `03/04/06/10`; ARM = **slave** | [`docs/wiring/ARM-UART5`](../wiring/ARM-UART5.md), [`docs/04`](../04-modbus.md) |
| ARM↔DSP control | ARM **USART3**, internal TTL | **big-endian**, SN-less, **type-1 block** (not register-addressed) + `0x21/22/23` bootloader | [`docs/wiring/ARM-USART3`](../wiring/ARM-USART3.md) |
| safety CPU→ARM | ARM **USART2**, internal RS-485 | big-endian type-1 telemetry bank | [`docs/wiring/ARM-USART2`](../wiring/ARM-USART2.md) |
| MPPT→DSP | MPPT **USART1**, internal | big-endian, `0x42` SOF | [`docs/wiring/MPPT-USART1`](../wiring/MPPT-USART1.md) |

So when a file here says an **input** register's data is *"relayed from the
USART2 bank"* or *"from the BMS over CAN1"*, that describes where the ARM got the
number **before** it re-exports it to the dongle — it does **not** mean the
dongle reads those internal links. And when a **holding** register's side-effect
is *"pushed to the DSP over USART3"*, that is the ARM forwarding a setting on a
**different** wire after the dongle writes it here. Keep the four links distinct.

## Dongle framing & encoding (from the spec)

- **RS-485, 19200 bps (spec), 8N1.** *(Our ceaa-07xx image reads UART5 at 9600;
  dongle baud is field-configurable — see [`docs/26`](../26-dongle-firmware.md).)*
- Function codes: `0x03` read holding, `0x04` read input, `0x06` write single
  holding, `0x10` write multiple holding (**`0x10` only valid for serial number
  and time**).
- **10-byte ASCII serial number** `SN[0..9]` immediately after the function code
  in every frame.
- **16-bit value: byte order reversed** — bytes `0x01 0x02` → value `0x0201`.
- **32-bit value (reg pair): word order reversed AND bytes within each word
  reversed** — `0x01 0x02 0x03 0x04` → `0x04030201`. "L/H" pairs below form one
  32-bit value.
- **Min polling period 1 s.** A query spans **≤ 40 registers** and must not cross
  a 40-register group boundary (groups `0-39`, `40-79`, `80-119`, …).

## Register spaces — the "126 trap"

The function code selects an **independent number line**. `0x04` = **input**
(read-only telemetry); `0x03/0x06/0x10` = **holding** (read/write settings). The
same number is unrelated across spaces — e.g. **IR 126** = generator-energy high
word (and in ceaa-07xx a status word, bit 8 = AC-First active), while **HR
126-131** = the OptimalChg_DisChg time table. Always say `IR` or `HR`. Likewise
**IR 113** (parallel info) ≠ **HR 113** (SetComposedPhase).

## Variant

The spec is the **18kPV** superset. On the **12000XP** (`ceaa`, 2-MPPT,
non-hybrid): PV3 items (IR 3/9/30/44-45) are inactive, and some hybrid-only
items read 0. Register *meanings* come from the spec; where the ceaa-07xx factory
getter disagrees with the superset label, the per-register file flags it (the
clearest case is IR 90-94, see [`docs/33`](../33-usart2-telemetry-bank.md)).

## How provenance is categorized

Every documented **input** register resolves to one of:
- **USART2 bank** — the safety CPU's relayed telemetry (`0x20009e54`); the exact
  bank-offset→register map is [`docs/33`](../33-usart2-telemetry-bank.md).
- **BMS/CAN1** — battery data the ARM reads first-hand ([`docs/20`](../20-battery-bms-firmware.md)).
- **ARM-computed** — powers (float V·I), energy integrals, derived status
  ([`docs/22`](../22-arm-dsp-core-split.md)).
- **ARM-local** — runtime, self-test state the ARM owns.

Every documented **holding** register resolves to one of:
- **Config flash** — persisted in the SPI-NOR settings store ([`docs/21`](../21-arm-config-flash.md)/[`docs/23`](../23-arm-config-writer.md)).
- **Pushed to DSP** — forwarded as a config block over USART3 ([`docs/08`](../08-arm-dsp-config-protocol.md)/[`docs/10`](../10-dsp-config-field-map.md)).
- **Evaluated ARM-side** — time windows checked against the ARM clock, not pushed as a verdict ([`docs/25`](../25-modbus-register-spaces.md)).
- **Command/trigger** — a write that triggers an action (reboot, clear, switch).

(Most settings are **both** persisted to flash **and** pushed to the DSP.)

---

## Index — input registers (func `0x04`, read-only)

`→ file` links the dedicated doc; `idx` = spec-only (see modbus_map.h), not yet
RE-traced; `rsvd` = reserved/unused.

| IR | name | unit | note | doc |
|---|---|---|---|---|
| 0 | State | — | operating-mode bitmask (table in file) | [→](input-000-State.md) |
| 1-3 | Vpv1/2/3 | 0.1 V | PV string voltages (3 = 18kPV only) | [→](input-001_003-Vpv1_Vpv3.md) |
| 4 | Vbat | 0.1 V | battery voltage | [→](input-004-Vbat.md) |
| 5 | SOC / SOH | % / % | low=SOC, high=SOH | [→](input-005-SOC_SOH.md) |
| 6 | InternalFault | — | internal DTC | [→](input-006-InternalFault.md) |
| 7-9 | Ppv1/2/3 | 1 W | PV power | [→](input-007_009-Ppv1_Ppv3.md) |
| 10-11 | Pcharge / Pdischarge | 1 W | battery charge / discharge power | [→](input-010_011-Pcharge_Pdischarge.md) |
| 12-14 | VacR/S/T | 0.1 V | grid voltage R/S/T | [→](input-012_014-VacR_VacS_VacT.md) |
| 15 | Fac | 0.01 Hz | grid frequency | [→](input-015-Fac.md) |
| 16-17 | Pinv / Prec | 1 W | inverter output / AC-charge rectified power | [→](input-016_017-Pinv_Prec.md) |
| 18 | IinvRMS | 0.01 A | inverter current RMS | [→](input-018-IinvRMS.md) |
| 19 | PF | 0.001 | power factor (encoded range, see file) | [→](input-019-PF.md) |
| 20-25 | VepsR/S/T, Feps, Peps, Seps | 0.1V/0.01Hz/W/VA | off-grid (EPS) output | [→](input-020_025-EPS-output.md) |
| 26-27 | Ptogrid / Ptouser | 1 W | export / import power | [→](input-026_027-Ptogrid_Ptouser.md) |
| 28-37 | E*_day | 0.1 kWh | daily energy counters | [→](input-028_059-energy-counters.md) |
| 38-39 | Vbus1 / Vbus2 | 0.1 V | bus voltages | [→](input-038_039-Vbus1_Vbus2.md) |
| 40-59 | E*_all L/H | 0.1 kWh | cumulative energy (32-bit pairs) | [→](input-028_059-energy-counters.md) |
| 60-63 | FaultCode / WarningCode L/H | — | 32-bit fault & warn bitfields | [→](input-060_063-FaultCode_WarningCode.md) |
| 64-67 | Tinner, Tradiator1/2, Tbat | 1 °C (s16) | temperatures | [→](input-064_067-temperatures.md) |
| 68 | — | | rsvd | — |
| 69-70 | RunningTime L/H | 1 s | runtime (32-bit) | [→](input-069_070-RunningTime.md) |
| 71-75 | AutoTest (status/limit/trip) | — | grid-protection self-test | [→](input-071_075-AutoTest.md) |
| 76 | — | | rsvd | — |
| 77 | ACInputType | — | 0 grid / 1 generator | [→](input-077-ACInputType.md) |
| 78-80 | — | | rsvd | — |
| 81-106 | BMS block | various | battery data over CAN1 | [→](input-081_106-BMS.md) |
| 107 | BatVoltSample_INV | 0.1 V | inverter-side battery sample | [→](input-107-BatVoltSample_INV.md) |
| 108 | T1 | 0.1 °C | 12K BT temperature | idx |
| 109-112 | T2-T5 | 0.1 °C | reserved | idx |
| 113 | ParallelInfo | — | master/slave, phase, parallel count | [→](input-113-ParallelInfo.md) |
| 114-119 | — | | rsvd | — |
| 120 | VBusP | 0.1 V | half-bus voltage | [→](input-120-VBusP.md) |
| 121-126 | Gen volt/freq/power, Egen day/all | — | generator | [→](input-121_126-generator.md) |
| 127-138 | EPS split-phase V/P/S/E (L1N/L2N) | — | split-phase EPS detail | [→](input-127_138-EPS-split-phase.md) |
| 139 | — | | rsvd | — |
| 140-143 | AFCI_CurrCH1-4 | mA | arc-fault current | idx |
| 144 | AFCIFlag | bits | arc alarm / self-test | idx |
| 145-148 | AFCI_ArcCH1-4 | — | real-time arc | idx |
| 149-152 | AFCI_MaxArcCH1-4 | — | max arc | idx |

## Index — holding registers (func `0x03/0x06`, `0x10` SN+time only)

| HR | name | unit / range | note | doc |
|---|---|---|---|---|
| 2-6 | SN[0..9] | ASCII | device serial number | [→](holding-002_006-SN.md) |
| 7-8 | — | | rsvd | — |
| 9 | Slave Ver / Com Ver | 0-255 | redundant-CPU / comm-CPU FW ver | [→](holding-009_010-FW-versions.md) |
| 10 | Cntl Ver / FWVer | 0-255 | control-CPU (DSP) FW ver / code | [→](holding-009_010-FW-versions.md) |
| 11 | ResetSetting | bits | clear records / defaults / reboot / BMS switch | [→](holding-011-ResetSetting.md) |
| 12-14 | Time year…second | — | real-time clock | [→](holding-012_014-Time.md) |
| 15 | Com Addr | 0-150 | Modbus slave address | [→](holding-015-ComAddr.md) |
| 16 | Language | 0-1 | 0 English / 1 German | [→](holding-016-Language.md) |
| 17-19 | — | | rsvd | — |
| 20 | PVInputModel | 0-7 | PV routing / parallel | [→](holding-020-PVInputModel.md) |
| 21 | FuncEn | bits | EPS/DRMS/LVRT/AntiIsland/ACCharge/… | [→](holding-021-FuncEn.md) |
| 22 | StartPVVolt | 0.1 V (900-5000) | PV start voltage | [→](holding-022-StartPVVolt.md) |
| 23-24 | ConnectTime / ReconnectTime | s | grid connect / reconnect wait | [→](holding-023_024-ConnectTime_ReconnectTime.md) |
| 25-62 | grid-code protection + reactive (V/F levels, Q(V), PF) | per grid code | protection curves | [→](holding-025_062-grid-protection.md) |
| 63 | PowerSoftStartSlope | ‰/min | loading rate | idx |
| 64-89 | AC-charge / charge-priority / forced-discharge schedule | % / hour\|min | 3 features × (power, SOC, 3 windows) | [→](holding-064_089-charge-discharge-schedule.md) |
| 90-91 | EPSVoltageSet / EPSFreqSet | 1V / 1Hz | off-grid output V/F | [→](holding-090_091-EPS-output.md) |
| 92-97 | PF/Q(V) lock-in/out, delay | — | reactive-curve params | idx |
| 98 | AutoTestStart | 0-1 | start grid self-test (see IR 71-75) | [→](input-071_075-AutoTest.md) |
| 99-102 | ChargeVoltRef/CutVolt/ChargeCurr/DischgCurr | 0.1V / A | lead-acid charge/discharge | [→](holding-099_102-leadacid-charge.md) |
| 103 | MaxBackFlow | % | feed-in grid power limit | [→](holding-103-MaxBackFlow.md) |
| 104 | DischgChgSWCMD | 0-2 | discharge↔charge command | idx |
| 105 | EOD | % (10-90) | end-of-discharge SOC | [→](holding-105-EOD.md) |
| 106-109 | Tempr limits (lead-acid) | 0.1 °C | charge/discharge temp limits | idx |
| 110 | FunctionEn1 | bits | PVGridOff/FastZeroExport/MicroGrid/BatShared/CT ratios | [→](holding-110-FunctionEn1.md) |
| 111 | — | | rsvd | — |
| 112 | SetSystemType | 0-3 | parallel system type | [→](holding-112-SetSystemType.md) |
| 113 | SetComposedPhase | 1-3 | phase in parallel system | [→](holding-113-SetComposedPhase.md) |
| 114 | ClearFunction | 1 | clear parallel fault code | idx |
| 115-116, 118-119 | OVFDerate/PtoUser/VbatDerate/CTOffset | — | misc settings | idx |
| 120 | stSysEnable | bits | ACChargeType/DischgCtrlType/OnGridEODType/GenChargeType | [→](holding-120-SysEnable.md) |
| 121, 124-125 | Q2_QV / OVFDerateEnd / SOCLowLimitForEPS | — | misc | idx |
| 126-131 | OptimalChg_DisChg | bits | 48-slot × 2-bit charge/discharge time table | [→](holding-126_131-OptimalChg_DisChg.md) |
| 132-137 | BatCell limits, derate, SpecLoadCompensate | — | misc | idx |
| 138-143 | *PowerPercentCMD (0.1%) | 0.1 % | high-res variants of 60/64-66/74/82 | idx |
| 144 | FloatChargeVolt | 0.1 V | lead-acid float voltage | [→](holding-099_102-leadacid-charge.md) |
| 145 | OutputPrioConfig | 0-3 | 0 bat-first / 1 PV-first / 2 AC-first | [→](holding-145-OutputPrioConfig.md) |
| 146 | LineMode | 0-2 | APL / UPS / GEN | [→](holding-146-LineMode.md) |
| 147-148 | Battery capacity / nominal voltage | Ah / 0.1 V | unmatched batteries | [→](holding-147_148-battery-capacity.md) |
| 149-151 | Equalization volt/interval/time | — | lead-acid equalization | idx |
| 152-157 | AC-First load time windows | hour\|min | 3 AC-First windows | [→](holding-152_157-ACFirst-windows.md) |
| 158-169 | ACChg by V/SOC, bat-low protection, OngridEOD | — | battery/AC-charge thresholds | idx |
| 170-193 | SOCCurve, grid/gen power caps, FunctionEn2, VoltWatt/QV/QP | — | advanced curves | idx |
| 194-198 | GenChg start/end V/SOC, MaxGenChgCurr | 0.1V / % / A | generator charge | [→](holding-194_198-generator-charge.md) |

## Annex tables (in the per-register files)

- **Operating modes** (State, IR 0): [`input-000-State.md`](input-000-State.md).
- **Fault codes E000-E031 / Warning codes W000-W031**:
  [`input-060_063-FaultCode_WarningCode.md`](input-060_063-FaultCode_WarningCode.md).

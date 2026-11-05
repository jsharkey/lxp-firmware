# IR 28-59 — energy counters (daily + cumulative)

> **Dongle Modbus**, input register (func `0x04`, read-only). Authoritative. See the [index](README.md).

**Daily (16-bit, 0.1 kWh):** IR 28-37 — Epv1/2/3_day, Einv_day, Erec_day,
Echg_day, Edischg_day, Eeps_day, Etogrid_day, Etouser_day.

**Cumulative (32-bit L/H pairs, 0.1 kWh):** IR 40-59 — Epv1/2/3_all, Einv_all,
Erec_all, Echg_all, Edischg_all, Eeps_all, Etogrid_all, Etouser_all (see
[`modbus_map.h`](../../include/inv/modbus_map.h) for the exact pairing).

*(IR 38-39 Vbus1/2 sit between the two blocks — see
[`input-038_039-Vbus1_Vbus2`](input-038_039-Vbus1_Vbus2.md).)*

## Where the data comes from

**ARM-accumulated.** These are energy integrals the ARM maintains over time in its
own RAM/flash (energy totals live in a separate struct `0x20009954`, per
[`docs/33`](../33-usart2-telemetry-bank.md)); they are **not** instantaneous bank
fields and are **not** battery/CAN data. 32-bit values obey the dongle's
word+byte-swapped encoding ([index](README.md)).

> Signedness/accumulation reset: the daily counters roll at day boundary; the
> cumulative counters can be cleared via `HR 11` ResetSetting.EnergyRecordClr
> ([`holding-011-ResetSetting`](holding-011-ResetSetting.md)).

# HR 2-6 — SN (device serial number)

> **Dongle Modbus**, holding register (func `0x03`/`0x06`). Authoritative. See the [index](README.md).

| reg | name | note |
|---|---|---|
| HR 2-6 | SN[0..9] | 10 ASCII bytes (`'0'-'9'`, `'A'-'Z'`), 2 per register |

e.g. `AB12345678` → SN[0]=0x41('A') … SN[9]=0x38('8').

## Side-effects of writing

**Persisted to the config flash** (the ARM owns settings storage,
[`docs/21`](../21-arm-config-flash.md)/[`docs/23`](../23-arm-config-writer.md)).
This is one of the **only two** blocks writable with `0x10` (write-multiple) — the
other is the time (HR 12-14). The 10-byte SN is also what rides every dongle frame
(see [index](README.md)); changing it changes the SN echoed in responses.

#!/usr/bin/env python3
"""
hmi_app — an interactive on-screen HMI for the open EG4 com-MCU firmware.

Runs the firmware image in the emulator (tools/arm_sim.py), renders what it
draws to its 20x4 I2C character LCD (tools/panel.py + tools/hmi_engine.py), and
exposes the four front-panel keys as on-screen buttons that drive the real key
GPIOs — i.e. the physical device, in a browser tab.

    python3 tools/hmi_app.py                 # build/firmware.{bin,elf}, port 8080
    python3 tools/hmi_app.py --port 9000
    python3 tools/hmi_app.py --bin build/firmware.bin --elf build/firmware.elf

Then open http://localhost:<port>/. No third-party deps (Python stdlib +
unicorn, which tools/arm_sim.py already needs). Keys: on-screen buttons, or the
keyboard (Up/Down arrows, Enter, Esc/Backspace).
"""
import os, sys, json, argparse, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
from hmi_engine import HmiSim

_LOCK = threading.Lock()     # Unicorn instance is not thread-safe
_SIM = None
_META = {"image": ""}

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EG4 com-MCU HMI</title>
<style>
  :root{
    --bg:#0e1116; --panel:#171c24; --edge:#2a323d; --ink:#d7dee8; --muted:#8b97a7;
    --lcd-bezel:#10151b; --lcd-glass:#15351f; --lcd-grid:#1c4529; --lcd-text:#8effc0;
    --lcd-glow:#39ff9a; --key:#222a35; --key-hi:#2d3744; --accent:#5ad19a;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    display:flex;flex-direction:column;align-items:center;min-height:100vh;gap:18px;padding:24px 16px}
  h1{font-size:15px;font-weight:600;letter-spacing:.3px;margin:4px 0 0;color:var(--muted)}
  h1 b{color:var(--ink);font-weight:600}
  .device{background:var(--panel);border:1px solid var(--edge);border-radius:16px;
    padding:22px;width:min(560px,96vw);box-shadow:0 10px 40px rgba(0,0,0,.45)}
  .brand{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px}
  .brand .name{font-weight:700;letter-spacing:.5px}
  .brand .sub{font-size:12px;color:var(--muted)}
  /* LCD */
  .bezel{background:var(--lcd-bezel);border-radius:10px;padding:14px;border:1px solid #0a0d11}
  .lcd{background:var(--lcd-glass);border-radius:6px;padding:14px 16px;
    box-shadow:inset 0 0 24px rgba(0,0,0,.6), inset 0 0 2px var(--lcd-grid);
    font-family:"DejaVu Sans Mono",ui-monospace,Menlo,Consolas,monospace}
  .row{display:flex;gap:1px;height:30px;align-items:stretch}
  .cell{width:21px;display:flex;align-items:center;justify-content:center;
    color:var(--lcd-text);text-shadow:0 0 6px var(--lcd-glow);font-size:19px;
    background:linear-gradient(var(--lcd-grid),var(--lcd-grid)) center/100% 100% no-repeat;
    background-color:rgba(255,255,255,.015);border-radius:1px;white-space:pre}
  /* keypad */
  .keys{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:20px}
  .key{background:var(--key);border:1px solid var(--edge);border-radius:10px;color:var(--ink);
    padding:14px 8px;cursor:pointer;user-select:none;display:flex;flex-direction:column;
    align-items:center;gap:6px;transition:transform .05s,background .1s}
  .key:hover{background:var(--key-hi)}
  .key:active,.key.flash{transform:translateY(1px);background:var(--accent);color:#0b0f14}
  .key .ic{font-size:20px;line-height:1}
  .key .lb{font-size:11px;color:var(--muted);letter-spacing:.4px}
  .key:active .lb,.key.flash .lb{color:#0b0f14}
  .foot{font-size:12px;color:var(--muted);text-align:center;max-width:560px}
  .pin{font-family:ui-monospace,monospace;color:var(--accent)}
  a{color:var(--accent)}
</style></head>
<body>
  <h1>Open <b>EG4 com-MCU</b> firmware &mdash; HMI emulator</h1>
  <div class="device">
    <div class="brand"><span class="name">INVERTER</span><span class="sub" id="img">&nbsp;</span></div>
    <div class="bezel"><div class="lcd" id="lcd"></div></div>
    <div class="keys">
      <div class="key" data-k="up"><span class="ic">&#9650;</span><span class="lb">UP &middot; PA8</span></div>
      <div class="key" data-k="down"><span class="ic">&#9660;</span><span class="lb">DOWN &middot; PA11</span></div>
      <div class="key" data-k="enter"><span class="ic">&#9166;</span><span class="lb">ENTER &middot; PC8</span></div>
      <div class="key" data-k="esc"><span class="ic">&#9003;</span><span class="lb">ESC &middot; PC9</span></div>
    </div>
  </div>
  <div class="foot">The firmware runs in the emulator; each press drives the real key
    <span class="pin">GPIO</span> (active-low) and the menu engine bit-bangs the new screen
    over I&sup2;C to a modelled 20&times;4 HD44780. Use the buttons or your keyboard
    (&uarr; &darr; Enter Esc).</div>
<script>
const COLS=20, ROWS=4;
const lcd=document.getElementById('lcd');
const cells=[];
for(let r=0;r<ROWS;r++){
  const row=document.createElement('div'); row.className='row';
  const rc=[];
  for(let c=0;c<COLS;c++){const d=document.createElement('div');d.className='cell';d.textContent=' ';row.appendChild(d);rc.push(d);}
  lcd.appendChild(row); cells.push(rc);
}
function paint(rows){
  for(let r=0;r<ROWS;r++){
    const s=(rows[r]||'').padEnd(COLS,' ');
    for(let c=0;c<COLS;c++) cells[r][c].textContent = s[c]===' ' ? ' ' : s[c];
  }
}
async function refresh(){const s=await (await fetch('/api/state')).json(); document.getElementById('img').textContent=s.image; paint(s.rows);}
let chain=Promise.resolve();              // serialize presses so none are dropped
function press(k){
  const el=document.querySelector('.key[data-k="'+k+'"]'); if(el){el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),90);}
  chain=chain.then(async()=>{
    const s=await (await fetch('/api/key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})})).json();
    paint(s.rows);
  }).catch(()=>{});
  return chain;
}
document.querySelectorAll('.key').forEach(el=>el.addEventListener('click',()=>press(el.dataset.k)));
const KMAP={ArrowUp:'up',ArrowDown:'down',Enter:'enter',Escape:'esc',Backspace:'esc'};
document.addEventListener('keydown',e=>{const k=KMAP[e.key]; if(k){e.preventDefault();press(k);}});
refresh();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/api/state":
            with _LOCK:
                rows = _SIM.screen()
            return self._send(200, json.dumps({"rows": rows, "image": _META["image"]}))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/key":
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length") or 0)
        try:
            key = json.loads(self.rfile.read(n) or b"{}").get("key", "")
        except Exception:
            key = ""
        if key not in ("up", "down", "enter", "esc"):
            return self._send(400, json.dumps({"error": "bad key"}))
        with _LOCK:
            _SIM.press(key)
            rows = _SIM.screen()
        return self._send(200, json.dumps({"rows": rows, "image": _META["image"]}))


def main():
    global _SIM
    ap = argparse.ArgumentParser(description="Interactive on-screen HMI for the open firmware.")
    ap.add_argument("--bin", default="build/firmware.bin")
    ap.add_argument("--elf", default="build/firmware.elf")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    for p in (args.bin, args.elf):
        if not os.path.exists(p):
            sys.exit("missing %s (run `make` first)" % p)

    print("booting firmware in the emulator ...", flush=True)
    _SIM = HmiSim(args.bin, args.elf)
    _META["image"] = os.path.basename(args.bin)
    for r in _SIM.screen():
        print("  |%-20s|" % r)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("\nHMI app on http://localhost:%d/  (Ctrl-C to stop)" % args.port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()

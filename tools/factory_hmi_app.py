#!/usr/bin/env python3
"""
factory_hmi_app — the factory HMI on screen, driven by the real firmware.

Boots the factory ARM image in the emulator (tools/factory_hmi.py), renders what
its display task draws to the 128x160 TFT, and exposes the four front-panel keys
as on-screen buttons that press the real key GPIOs so the firmware navigates its
own menus. The browser shows exactly what the device shows.

    python3 tools/factory_hmi_app.py            # port 8090
    python3 tools/factory_hmi_app.py --port 9000

Boot takes ~90s (the firmware runs through config + its RTOS scheduler until the
display task paints); the page shows a spinner until it is ready, and again for
the ~20-30s each keypress takes to run the firmware to a settled screen. No
third-party deps beyond unicorn + numpy + pillow. Needs reference/com_flat.bin +
reference/symbols.csv.
"""
import os, sys, io, json, time, base64, argparse, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from factory_hmi import FactoryHmi, W, H

# Recovered key map (docs/23). The panel has 4 keys; names are the behaviour
# observed driving the factory menus.
KEY_BUTTONS = [
    ("PC9",  "Up",    "▲"),
    ("PA8",  "Down",  "▼"),
    ("PA11", "Enter", "⏎"),
    ("PC8",  "Esc",   "←"),
]

# FSTN-style palette (dark ink on a pale blue-green panel).
INK = (0x16, 0x24, 0x3a)
BG  = (0xa9, 0xc2, 0xc0)

_LOCK = threading.Lock()      # serialize all emulator access (Unicorn not thread-safe)
_STATE = {"status": "booting", "png": None, "step": 0, "msg": "booting firmware …"}
_HMI = None


def _render_png(mono_img):
    """mono HxW (0/255) -> colorized PNG bytes (RGB, FSTN tint)."""
    rgb = np.zeros((mono_img.shape[0], mono_img.shape[1], 3), dtype=np.uint8)
    ink = mono_img == 0
    rgb[...] = BG
    rgb[ink] = INK
    im = Image.fromarray(rgb, "RGB")
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


def _publish(msg=None):
    img = _HMI.screen()
    _STATE["png"] = base64.b64encode(_render_png(img)).decode()
    if msg is not None:
        _STATE["msg"] = msg


def _boot():
    global _HMI
    with _LOCK:
        _HMI = FactoryHmi(verbose=True)
        _STATE["msg"] = "booting firmware through its RTOS … (~90s)"
        _HMI.boot()
        _publish("ready")
        _STATE["status"] = "ready"


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EG4 factory HMI</title>
<style>
 :root{--bg:#0e1116;--panel:#171c24;--edge:#2a323d;--ink:#d7dee8;--muted:#8b97a7;--accent:#5ad19a}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  display:flex;flex-direction:column;align-items:center;min-height:100vh;gap:16px;padding:22px 16px}
 h1{font-size:14px;font-weight:600;color:var(--muted);margin:2px 0} h1 b{color:var(--ink)}
 .device{background:var(--panel);border:1px solid var(--edge);border-radius:16px;padding:20px;
  width:min(440px,96vw);box-shadow:0 10px 40px rgba(0,0,0,.45)}
 .bezel{background:#0a0d11;border:1px solid #05070a;border-radius:10px;padding:12px;position:relative}
 .screen{width:100%;aspect-ratio:128/160;image-rendering:pixelated;border-radius:3px;display:block;
  background:#a9c2c0}
 .overlay{position:absolute;inset:12px;display:none;align-items:center;justify-content:center;
  flex-direction:column;gap:12px;background:rgba(10,13,17,.72);border-radius:3px;color:#cfe}
 .overlay.on{display:flex}
 .spin{width:34px;height:34px;border:3px solid #2a3b49;border-top-color:var(--accent);border-radius:50%;
  animation:spin .8s linear infinite} @keyframes spin{to{transform:rotate(360deg)}}
 .ovmsg{font-size:12px;color:#9fb8c9;max-width:80%;text-align:center}
 .keys{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:18px}
 .key{background:#222a35;border:1px solid var(--edge);border-radius:10px;color:var(--ink);
  padding:12px 6px;cursor:pointer;user-select:none;display:flex;flex-direction:column;align-items:center;gap:5px;
  transition:transform .05s,background .1s} .key:hover{background:#2d3744}
 .key:active,.key.flash{transform:translateY(1px);background:var(--accent);color:#0b0f14}
 .key[disabled]{opacity:.4;pointer-events:none}
 .key .ic{font-size:18px;line-height:1} .key .lb{font-size:10px;color:var(--muted);letter-spacing:.3px;text-align:center}
 .key:active .lb,.key.flash .lb{color:#0b0f14} .key .pin{font:10px ui-monospace,monospace;color:var(--accent)}
 .foot{font-size:12px;color:var(--muted);text-align:center;max-width:440px}
</style></head><body>
 <h1>EG4 <b>12000XP</b> &mdash; factory HMI, running in the emulator</h1>
 <div class="device">
  <div class="bezel">
   <img class="screen" id="screen" alt="LCD">
   <div class="overlay on" id="ov"><div class="spin"></div><div class="ovmsg" id="ovmsg">booting …</div></div>
  </div>
  <div class="keys" id="keys"></div>
 </div>
 <div class="foot">Every pixel is the factory firmware's own draw code, running under the Unicorn
  harness; each key press drives the real GPIO and runs the firmware until its display task repaints
  the 128&times;160 LCD. It is slow because it is really executing the image.</div>
<script>
const KEYS=__KEYS__;
const keysEl=document.getElementById('keys'), img=document.getElementById('screen'),
      ov=document.getElementById('ov'), ovmsg=document.getElementById('ovmsg');
KEYS.forEach(k=>{const d=document.createElement('div');d.className='key';d.dataset.k=k.pin;
  d.innerHTML=`<span class="ic">${k.ic}</span><span class="lb">${k.label}</span><span class="pin">${k.pin}</span>`;
  d.addEventListener('click',()=>press(k.pin));keysEl.appendChild(d);});
function setBusy(on,msg){ov.classList.toggle('on',on); if(msg)ovmsg.textContent=msg;
  document.querySelectorAll('.key').forEach(b=>b.disabled=on);}
function show(s){ if(s.png) img.src='data:image/png;base64,'+s.png;
  if(s.status==='ready'){setBusy(false);} else {setBusy(true,s.msg);} }
async function poll(){ try{const s=await(await fetch('/api/state')).json(); show(s);
  if(s.status!=='ready') setTimeout(poll,1500);}catch(e){setTimeout(poll,2000);} }
async function press(pin){ const el=document.querySelector(`.key[data-k="${pin}"]`);
  if(el) el.classList.add('flash');
  setBusy(true,'running firmware …');
  try{const s=await(await fetch('/api/key',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:pin})})).json(); show(s);}catch(e){setBusy(true,'error — retry');}
  if(el) el.classList.remove('flash'); }
const KMAP={ArrowUp:'PC9',ArrowDown:'PA8',Enter:'PA11',Escape:'PC8',Backspace:'PC8'};
document.addEventListener('keydown',e=>{const p=KMAP[e.key]; if(p){e.preventDefault();
  if(!document.querySelector('.key').disabled) press(p);}});
poll();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            page = PAGE.replace("__KEYS__", json.dumps(
                [{"pin": p, "label": l, "ic": ic} for (p, l, ic) in KEY_BUTTONS]))
            return self._send(200, page, "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self._send(200, json.dumps(_STATE))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/key":
            return self._send(404, json.dumps({"error": "not found"}))
        if _STATE["status"] != "ready":
            return self._send(200, json.dumps(_STATE))
        n = int(self.headers.get("Content-Length") or 0)
        try: key = json.loads(self.rfile.read(n) or b"{}").get("key", "")
        except Exception: key = ""
        if key not in [p for (p, _l, _i) in KEY_BUTTONS]:
            return self._send(400, json.dumps({"error": "bad key"}))
        with _LOCK:
            _STATE["status"] = "busy"; _STATE["msg"] = "running firmware …"
            _HMI.press(key)
            _STATE["step"] += 1
            _publish("ready"); _STATE["status"] = "ready"
        return self._send(200, json.dumps(_STATE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    threading.Thread(target=_boot, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("factory HMI app on http://localhost:%d/  (booting; ~90s to first paint)" % args.port, flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nbye")


if __name__ == "__main__":
    main()

"""Asistan programının durumu: ölçümler programın içinde toplanır, masaüstü widget'ına yerel HTTP ile verilir.

Eskiden widget her saniye `veri.py`'yi yeni bir Python süreci olarak çalıştırıyordu (her seferinde ~0,5 sn işlemci,
çoğu açılış maliyeti). Artık toplama tek, sürekli açık bir süreçte (Asistan programı) ve önbellekli: ~20 ms/sn.
Pahalı olanlar (testler, projeler, git, adımlar) 5 sn'de bir; kimse bakmıyorsa (pencere gizli, widget sormuyor)
her şey 5 sn'de bir.

Widget `GET http://127.0.0.1:PORT/durum?v=N` ile sorar: elindeki sürüm (N) günceldeyse cevap bir değişiklik olana dek
(en çok 25 sn) bekletilir (uzun yoklama). Böylece widget yeni süreç başlatmaz, veri yalnızca değişince gelir.
Yalnızca 127.0.0.1'i dinler ve Host başlığını denetler (bir web sayfası DNS yeniden bağlama ile okuyamasın).
"""

from __future__ import annotations

import collections
import json
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import arka
import testler
import veri

PORT = 47600
HIST_N = 40
SLOW_S = 5.0  # testler, projeler, git, adımlar
IDLE_AFTER_S = 30.0  # widget bu kadar süre sormadıysa ve pencere gizliyse yavaş tempo
LONG_POLL_S = 25.0
# Widget'a gidenler (programın kendi kullandığı projeler listesi gibi büyük alanlar gitmez)
WIDGET_KEYS = ("activity", "sekmeler", "secili", "voice", "testler", "steps", "git", "exams", "gates",
               "eksikler", "metrics", "hist", "pencere", "dikte")  # fmt: skip
EMPTY_GIT = {"branch": "", "commits": [], "today": 0, "dirty": False}
EMPTY_STEPS = {"total": 0, "done_n": 0, "done": [], "left": []}


class Olcum:
    """İşlemci, ağ ve disk hızı: iki okuma arasındaki fark (süreç açık kaldığı için bekleme gerekmez)."""

    def __init__(self) -> None:
        self.prev: tuple[float, int, int, int, int, int, int] | None = None

    def oku(self) -> dict[str, Any]:
        t = time.monotonic()
        v = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        busy, total = sum(v) - v[3] - v[4], sum(v)
        rx, tx = veri._net_bytes()
        dr, dw = veri._disk_bytes()
        cur = (t, busy, total, rx, tx, dr, dw)
        prev, self.prev = self.prev or cur, cur
        dt = max(t - prev[0], 0.05)
        cpu = round(100 * (busy - prev[1]) / (total - prev[2]), 1) if total > prev[2] else 0.0

        def kbs(i: int) -> float:
            return round(max(cur[i] - prev[i], 0) / dt / 1024, 1)

        gd = veri.gpu_details()  # ayrı kart uykudaysa uyandırmaz; nvidia-smi en çok 15 sn'de bir
        du = shutil.disk_usage(Path.home())
        return {"cpu": cpu, "ram": veri.ram_pct(), "gpu": gd["util"],
                "cpu_detail": veri.cpu_details(), "ram_detail": veri.ram_details(), "gpu_detail": gd,
                "net_down_kbs": kbs(3), "net_up_kbs": kbs(4), "disk_read_kbs": kbs(5), "disk_write_kbs": kbs(6),
                "disk_free_gib": round(du.free / 2**30, 1)}  # fmt: skip


def eksikler(snap: dict[str, Any], proje: str) -> list[dict[str, str]]:
    """Tamamlanması ya da ilgilenilmesi gerekenler: onay bekleyen Claude, engelli adımlar, kaydedilmemiş iş,
    önizlemeye aktarılmamış commit'ler, kurulu olmayan sürümler, sessizleşen işler. tur: bekliyor|engel|uyari|bilgi."""
    out: list[dict[str, str]] = []
    for t in snap.get("sekmeler", []):
        if t.get("durum") == "waiting":
            out.append({"tur": "bekliyor", "yazi": f"{t['baslik']}: Claude onay bekliyor"})
    for x in snap.get("steps", {}).get("left", []):
        if x["kind"] == "blocked":
            out.append({"tur": "engel", "yazi": f"{x['id']} {x['title']}: engelli"})
        elif x["kind"] == "approval":
            out.append({"tur": "bekliyor", "yazi": f"{x['id']} {x['title']}: onay bekliyor"})
    if snap.get("git", {}).get("dirty"):
        out.append({"tur": "uyari", "yazi": f"{proje or 'proje'}: kaydedilmemiş (commit'lenmemiş) değişiklikler"})
    for j in snap.get("exams", []) + snap.get("gates", []):
        if j.get("state") == "silent":
            out.append({"tur": "uyari", "yazi": f"{j['name']}: bir süredir çıktı yok, takılmış olabilir"})
    for p in snap.get("testler", []):
        f, son = p.get("farklar", {}), p["surumler"]["son"]
        if f.get("geride"):
            out.append({"tur": "uyari", "yazi": f"{p['ad']}: önizlemeye aktarılmamış {f['geride']} commit"})
        if f.get("kirli"):
            out.append({"tur": "bilgi", "yazi": f"{p['ad']}: önizlemede commit'lenmemiş değişiklik"})
        if son.get("tur") == "yok":
            out.append({"tur": "bilgi", "yazi": f"{p['ad']}: son sürüm yok ({son.get('neden', '')})"})
    return out


class Toplayici:
    """Programın ve widget'ın gördüğü her şey; `topla()` çalışan iş parçacığından çağrılır."""

    def __init__(self) -> None:
        self.olcum = Olcum()
        self.hist: dict[str, collections.deque[float]] = {
            k: collections.deque(maxlen=HIST_N) for k in ("cpu", "ram", "gpu", "net", "disk")
        }
        self.slow_at = 0.0
        self.slow: dict[str, Any] = {"testler": [], "projeler": [], "git": EMPTY_GIT, "steps": EMPTY_STEPS,
                                     "exams": [], "gates": [], "procs": []}  # fmt: skip
        self.slow_cwd = ""
        self.titles: dict[str, str] = {}

    def _title(self, s: dict[str, Any]) -> str:
        sid = s["session"] or s["resume"]
        if not sid:
            return f"{s['project']} · yeni sohbet"
        if sid not in self.titles or not self.titles[sid]:
            self.titles[sid] = arka.session_title(sid)
        return self.titles[sid] or s["project"]

    def topla(self, pencere: bool, force_slow: bool = False) -> dict[str, Any]:
        now = time.time()
        live = arka.sessions()
        cur = arka.selected(live)
        cwd = str(cur["cwd"]) if cur else ""
        if force_slow or now - self.slow_at >= SLOW_S or cwd != self.slow_cwd:
            self.slow_at, self.slow_cwd = now, cwd
            project = veri.project_of(cwd)
            self.slow = {"testler": testler.listing(), "projeler": arka.projects(),
                         "git": veri.git_info(project) if project else EMPTY_GIT,
                         "steps": veri.project_steps(project) if project else EMPTY_STEPS,
                         **veri.jobs(project, now)}  # fmt: skip
        act = veri.claude_activity(now, (str(cur["session"] or "") or None) if cur else None)
        veri.gate_progress(act, self.slow["gates"])
        m = self.olcum.oku()
        for k, val in (("cpu", m["cpu"]), ("ram", m["ram"]), ("gpu", m["gpu"] or 0),
                       ("net", m["net_down_kbs"] + m["net_up_kbs"]), ("disk", m["disk_read_kbs"] + m["disk_write_kbs"])):  # fmt: skip
            self.hist[k].append(val)
        tabs = [{"ad": s["name"], "baslik": self._title(s), "proje": s["project"], "durum": s["status"],
                 "cwd": s["cwd"], "oturum": s["session"] or s["resume"], "bagli": s["attached"]} for s in live]  # fmt: skip
        snap = {**self.slow, "activity": act, "metrics": m, "hist": {k: list(v) for k, v in self.hist.items()},
                "sekmeler": tabs, "secili": cur["name"] if cur else "", "voice": veri.voice_state(now),
                "istek": testler.pop_request(), "pencere": pencere, "zaman": now}  # fmt: skip
        snap["eksikler"] = eksikler(snap, cur["project"] if cur else "")
        return snap


class Yayin:
    """Son durumu widget'a verir; sürüm numarası yalnızca içerik değişince artar."""

    def __init__(self, port: int = PORT) -> None:
        self.cond = threading.Condition()
        self.body = b"{}"
        self.v = 0
        self.last_ask = 0.0
        self.port = port
        self.server: ThreadingHTTPServer | None = None

    def yayinla(self, snap: dict[str, Any]) -> None:
        body = json.dumps({k: snap.get(k) for k in WIDGET_KEYS}, ensure_ascii=False).encode()
        with self.cond:
            if body == self.body:
                return
            self.body = body
            self.v += 1
            self.cond.notify_all()

    def izleniyor(self) -> bool:
        return time.monotonic() - self.last_ask < IDLE_AFTER_S

    def baslat(self) -> bool:
        yayin = self
        allowed = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                url = urllib.parse.urlsplit(self.path)
                if url.path != "/durum" or self.headers.get("Host", "") not in allowed:
                    self.send_error(404)
                    return
                try:
                    have = int(urllib.parse.parse_qs(url.query).get("v", ["-1"])[0])
                except ValueError:
                    have = -1
                yayin.last_ask = time.monotonic()
                with yayin.cond:
                    yayin.cond.wait_for(lambda: yayin.v != have, timeout=LONG_POLL_S)
                    v, body = yayin.v, yayin.body
                out = b'{"v":%d,' % v + body[1:] if body != b"{}" else b'{"v":%d}' % v
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(out)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(out)
                except OSError:
                    pass

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError:
            return False
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, name="asistan-yayin", daemon=True).start()
        return True

#!/usr/bin/env python3
"""Bir pencereyi KWin'e yerleştirtir (Wayland'de program kendi penceresinin yerini seçemez).

Pencere sınıfı (Wayland app_id / resourceClass) ya da başlığının bir parçasıyla bulunur. Açıksa hemen yerleşir;
henüz açılmadıysa KWin betiği onu bekler, bulunca bir kez yerleştirip bırakır (başlığı sonradan konan pencereler
için başlık değişimi de izlenir). Betik her çağrıda aynı adla yeniden yüklenir: eskisi kalıp beklemeye devam etmez.

Kullanım:  pencere.py sinif|baslik|tam DEĞER X Y GENİŞLİK YÜKSEKLİK   (tam: başlığın tamamı)

icine(): programları Asistan penceresinin içindeki bir alana yerleştirir ve onunla senkron tutar: Asistan taşınınca,
boyutlanınca ya da küçültülünce onlar da birlikte gider; Asistan öne gelince onlar da üstünde kalır (gömülmüş gibi).
Alan Asistan'ın iç alanına göre verilir (sol/üst/alt piksel, sağ kenar genişliğin oranı). birak() bağı çözer.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_NAME = "asistan-yerlestir"
SCRIPT_FILE = Path.home() / ".cache/asistan/yerlestir.js"

_JS = """
const hedef = %(hedef)s;
const g = {x: %(x)d, y: %(y)d, width: %(w)d, height: %(h)d};
function uyar(w) {
    if (!w.normalWindow) return false;
    if (hedef.sinif) return w.resourceClass === hedef.sinif || w.desktopFileName === hedef.sinif;
    if (hedef.tam) return w.caption === hedef.tam;
    return w.caption.indexOf(hedef.baslik) >= 0;
}
function yerles(w) {
    w.setMaximize(false, false);
    w.minimized = false;
    w.frameGeometry = g;
    workspace.activeWindow = w;
}
let bitti = false;
for (const w of workspace.windowList()) {
    if (uyar(w)) { yerles(w); bitti = true; }
}
if (!bitti) {
    const dene = function (w) {
        if (bitti || !uyar(w)) return;
        bitti = true;
        yerles(w);
    };
    workspace.windowAdded.connect(function (w) {
        dene(w);
        if (!bitti) w.captionChanged.connect(function () { dene(w); });
    });
}
"""


SYNC_NAME = "asistan-icine"
SYNC_FILE = Path.home() / ".cache/asistan/icine.js"
_SYNC_JS = """
const hedefler = %(hedefler)s;   // [{tur: sinif|baslik|tam, deger, bas, son}] yatay pay (0..1)
const alan = %(alan)s;           // {sol, ust, alt, oran}: Asistan'ın iç alanına göre
const ANA = %(ana)s;
function uyar(w, h) {
    if (!w.normalWindow) return false;
    if (h.tur === "sinif") return w.resourceClass === h.deger || w.desktopFileName === h.deger;
    if (h.tur === "tam") return w.caption === h.deger;
    return w.caption.indexOf(h.deger) >= 0;
}
function ana() {
    for (const w of workspace.windowList()) if (w.resourceClass === ANA || w.desktopFileName === ANA) return w;
    return null;
}
const bagli = [];
function yer(h) {
    const a = ana();
    if (!a) return null;
    const c = a.clientGeometry;
    const gen = Math.round(c.width * alan.oran) - alan.sol;
    const x0 = c.x + alan.sol + Math.round(gen * h.bas);
    return {x: x0, y: c.y + alan.ust, width: Math.round(gen * (h.son - h.bas)) - (h.son < 1 ? 6 : 0),
            height: c.height - alan.ust - alan.alt};
}
function yerles(b, etkin) {
    const g = yer(b.h);
    if (!g) return;
    b.w.setMaximize(false, false);
    b.w.minimized = false;
    b.w.frameGeometry = g;
    if (etkin) workspace.activeWindow = b.w;
}
function bagla(w, h) {
    if (bagli.some(function (b) { return b.w === w; })) return;
    const b = {w: w, h: h};
    bagli.push(b);
    yerles(b, true);
}
for (const w of workspace.windowList()) for (const h of hedefler) if (uyar(w, h)) bagla(w, h);
workspace.windowAdded.connect(function (w) {
    for (const h of hedefler) {
        if (uyar(w, h)) { bagla(w, h); return; }
        w.captionChanged.connect(function () { if (uyar(w, h)) bagla(w, h); });
    }
});
workspace.windowRemoved.connect(function (w) {
    const i = bagli.findIndex(function (b) { return b.w === w; });
    if (i >= 0) bagli.splice(i, 1);
});
const a = ana();
if (a) {
    a.frameGeometryChanged.connect(function () { for (const b of bagli) yerles(b, false); });
    a.minimizedChanged.connect(function () { for (const b of bagli) b.w.minimized = a.minimized; });
}
workspace.windowActivated.connect(function (w) {
    if (w && w === ana()) for (const b of bagli) workspace.raiseWindow(b.w);
});
"""
_FREE_JS = """
const hedefler = %(hedefler)s;
function uyar(w, h) {
    if (!w.normalWindow) return false;
    if (h.tur === "sinif") return w.resourceClass === h.deger || w.desktopFileName === h.deger;
    if (h.tur === "tam") return w.caption === h.deger;
    return w.caption.indexOf(h.deger) >= 0;
}
for (const w of workspace.windowList()) for (const h of hedefler) if (uyar(w, h)) w.minimized = true;
"""


def _load(name: str, path: Path, code: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    qdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", name)
    number = qdbus("/Scripting", "org.kde.kwin.Scripting.loadScript", str(path), name)
    if not number.lstrip("-").isdigit() or int(number) < 0:
        return 1
    qdbus(f"/Scripting/Script{number}", "org.kde.kwin.Script.run")
    return 0


def icine(hedefler: list[dict[str, object]], alan: dict[str, float], ana: str = "asistan") -> int:
    """hedefler: [{"tur": "sinif"|"baslik"|"tam", "deger": "...", "bas": 0.0, "son": 1.0}]."""
    return _load(SYNC_NAME, SYNC_FILE, _SYNC_JS % {"hedefler": json.dumps(hedefler, ensure_ascii=False),
                                                   "alan": json.dumps(alan), "ana": json.dumps(ana)})  # fmt: skip


def birak(hedefler: list[dict[str, object]], gizle: bool = True) -> None:
    """Senkronu çözer; gizle: o programları küçültür (Test çekmecesi kapanınca)."""
    qdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", SYNC_NAME)
    if gizle and hedefler:
        _load("asistan-birak", SCRIPT_FILE.with_name("birak.js"),
              _FREE_JS % {"hedefler": json.dumps(hedefler, ensure_ascii=False)})


def qdbus(*args: str) -> str:
    r = subprocess.run(["qdbus6", "org.kde.KWin", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    return r.stdout.strip()


def yerlestir(kind: str, value: str, x: int, y: int, w: int, h: int) -> int:
    hedef = {"sinif": value} if kind == "sinif" else {"tam": value} if kind == "tam" else {"baslik": value}
    SCRIPT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT_FILE.write_text(_JS % {"hedef": json.dumps(hedef, ensure_ascii=False), "x": x, "y": y, "w": w, "h": h})
    qdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", SCRIPT_NAME)
    number = qdbus("/Scripting", "org.kde.kwin.Scripting.loadScript", str(SCRIPT_FILE), SCRIPT_NAME)
    if not number.lstrip("-").isdigit() or int(number) < 0:
        return 1
    qdbus(f"/Scripting/Script{number}", "org.kde.kwin.Script.run")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 7 or argv[1] not in ("sinif", "baslik", "tam") or not all(a.lstrip("-").isdigit() for a in argv[3:]):
        print(__doc__)
        return 2
    x, y, w, h = (int(a) for a in argv[3:])
    return yerlestir(argv[1], argv[2], x, y, w, h)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

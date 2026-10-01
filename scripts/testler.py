#!/usr/bin/env python3
"""Asistan for Claude Code'un "Test" bölümü: üzerinde çalışılan projelerin iki sürümünü yan yana açar.

Her projede "son sürüm" (kararlı, en son kurulan) ve "önizleme" (üzerinde çalışılan, en son kod) vardır;
"karşılaştır" ikisini yan yana açar ve aralarındaki commit'leri gösterir. Web arayüzleri programın içinde,
terminalin yanındaki panelde açılır (`hazirla` yalnızca sunucuyu başlatıp adresi verir); masaüstü programları kendi
pencerelerinde açılır ve scripts/pencere.py ile yerleştirilir (`ac`).

Projeler kullanıcıya özeldir: ~/.config/asistan/testler.py içindeki projects() işlevi verir (yoksa bölüm görünmez):
  [{"id": "web", "ad": "Web sitesi", "depo": Path(...),        depo: farkları göstermek için git deposu
    "surumler": {
      "son":      {"tur": "web", "port": 8080, "token": Path(...) | None, "baslat": ["komut", ...],
                   "etiket": "1.2.0", "commit": "abc1234"},
      "onizleme": {"tur": "uygulama", "program": Path(...), "pencere": ["baslik"|"sinif"|"tam", "eşleşme"],
                   "iz": "süreç komut satırında aranan yazı", "yenile": ["komut", ...], "etiket": "en son kod",
                   "commit": "def5678", "kirli": False}}}]
  tur: "web" (yerel sunucu; /api/health'te started_at varsa yeniden başlayınca sayfa yenilenir), "uygulama" ya da
  "yok" ("neden" ile: ör. kurulu değil).

Sunucular ve programlar `systemd-run --scope` ile başlatılır: başlatanla (program ya da Plasma) birlikte kapanmasınlar.

Komutlar:
  liste                                  projeler, sürümleri, durumları ve farklar (json)
  hazirla PROJE son|onizleme|karsilastir web sürümlerin panel ayarı (json: adresler token'lı, farklar);
                                         kapalı sunucuyu başlatır (panel açılınca bekler)
  ac PROJE son|onizleme|karsilastir X Y G Y
                                         masaüstü programlarını açar ve verilen alana yerleştirir
  yenile PROJE                           önizlemeyi en son kodla yeniden başlatır
  goster PROJE son|onizleme|karsilastir  programa o sürümü açtırır (ör. Claude bir değişikliği bitirince);
                                         program bir sonraki okumada (≤1 sn) açar, istek tek seferliktir
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import ayarlar

HOME = Path.home()
HERE = Path(__file__).resolve().parent
CACHE = HOME / ".cache/asistan/testler.json"
CACHE_S = 10.0
REQUEST = HOME / ".cache/asistan/istek.json"  # goster → veri.py → widget


def desktop() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=False).stdout.strip()  # noqa: S603, S607
    except OSError:
        out = ""
    return Path(out) if out else HOME / "Masaüstü"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    return r.stdout.strip() if r.returncode == 0 else ""


def _commit_in(text: str) -> str:
    m = re.search(r"\b([0-9a-f]{7,40})\b", text)
    return m.group(1) if m else ""


def _read(p: Path | None) -> str:
    try:
        return p.read_text(errors="replace").strip() if p else ""
    except OSError:
        return ""


def projects() -> list[dict[str, Any]]:
    """Test bölümünün projeleri: kullanıcının ~/.config/asistan/testler.py dosyasındaki projects(); yoksa boş."""
    mod = ayarlar.test_modulu()
    if mod is None or not hasattr(mod, "projects"):
        return []
    try:
        return list(mod.projects())
    except Exception as e:  # noqa: BLE001 - kullanıcının tanımındaki bir hata Asistan'ı durdurmasın
        print(f"uyarı: test projeleri okunamadı: {e}", file=sys.stderr)
        return []


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


# Komut satırında yalnızca geçtiği için "çalışıyor" sayılmasın: kabuk komutları, arama araçları, düzenleyiciler
_ARACLAR = {"grep", "pgrep", "rg", "ugrep", "ps", "pkill", "kill", "less", "cat", "sed", "awk", "tail", "head"}


def _cmdlines() -> list[str]:
    """Çalışan programların kendisi: argv[0] ve (yorumlayıcılar için) argv[1]; kabukların -c komutu ve arama
    araçları sayılmaz (iz onların komut satırında geçse bile o program çalışmıyordur)."""
    out = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            argv = [a.decode(errors="replace") for a in (p / "cmdline").read_bytes().split(b"\0") if a]
        except OSError:
            continue
        if not argv or Path(argv[0]).name in _ARACLAR:
            continue
        out.append(" ".join(a for a in argv[:2] if a != "-c"))
    return out


def differences(p: dict[str, Any]) -> dict[str, Any]:
    """Son sürümle önizleme arasındaki commit'ler (depoda ikisi de varsa)."""
    son, oniz = p["surumler"]["son"].get("commit", ""), p["surumler"]["onizleme"].get("commit", "")
    out: dict[str, Any] = {"son": son, "onizleme": oniz, "sayi": 0, "commitler": [],
                           "kirli": bool(p["surumler"]["onizleme"].get("kirli"))}  # fmt: skip
    if son and oniz and son != oniz:
        log = _git(p["depo"], "log", "--format=%h\t%s", f"{son}..{oniz}")
        rows = [ln.split("\t", 1) for ln in log.splitlines() if "\t" in ln]
        out["sayi"] = len(rows)
        out["commitler"] = [{"hash": h, "konu": s} for h, s in rows[:30]]
    head = _git(p["depo"], "rev-parse", "--short", "HEAD")
    if oniz and head and oniz != head:  # önizleme depodaki son koddan geride (ör. TEST'e aktarılmamış commit'ler)
        out["geride"] = len(_git(p["depo"], "rev-list", f"{oniz}..HEAD").split())
    return out


def _static() -> list[dict[str, Any]]:
    """Sürümlerin git'e dayanan kısmı (commit'ler, farklar); widget her saniye sorduğu için önbellekten gelir."""
    try:
        cached = json.loads(CACHE.read_text())
        if time.time() - float(cached["t"]) < CACHE_S:
            return list(cached["projeler"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    out = []
    for p in projects():
        vers = {key: {"tur": v["tur"], "etiket": v.get("etiket", ""), "commit": v.get("commit", ""),
                      "neden": v.get("neden", ""), "yenilenir": bool(v.get("yenile")),
                      "port": v.get("port", 0), "iz": v.get("iz", "")}
                for key, v in p["surumler"].items()}  # fmt: skip
        out.append({"id": p["id"], "ad": p["ad"], "surumler": vers, "farklar": differences(p)})
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"t": time.time(), "projeler": out}, ensure_ascii=False))
    except OSError:
        pass
    return out


def listing() -> list[dict[str, Any]]:
    """Projeler, sürümleri ve farklar; "çalışıyor mu" her seferinde yeniden bakılır."""
    procs = _cmdlines()
    out = _static()
    for p in out:
        for v in p["surumler"].values():
            v["calisiyor"] = (_port_open(v["port"]) if v["tur"] == "web"
                              else any(v["iz"] in c for c in procs) if v["tur"] == "uygulama" else False)  # fmt: skip
    return out


def _spawn(args: list[str], cwd: Path | None = None) -> None:
    """Plasma'dan bağımsız, kendi systemd kapsamında başlatır."""
    scope = shutil.which("systemd-run")
    pre = [scope, "--user", "--scope", "--quiet", "--collect", "--"] if scope else []
    subprocess.Popen([*pre, *args], cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL,  # noqa: S603
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip


def _place(match: list[str], x: int, y: int, w: int, h: int) -> None:
    subprocess.run([sys.executable, str(HERE / "pencere.py"), match[0], match[1], str(x), str(y), str(w), str(h)],  # noqa: S603
                   check=False, capture_output=True)  # fmt: skip


def _versions(pid: str, which: str) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]] | None:
    p = next((p for p in projects() if p["id"] == pid), None)
    if p is None or which not in ("son", "onizleme", "karsilastir"):
        return None
    keys = ["son", "onizleme"] if which == "karsilastir" else [which]
    return p, [(k, p["surumler"][k]) for k in keys if p["surumler"][k]["tur"] != "yok"]


def prepare(pid: str, which: str) -> dict[str, Any] | None:
    """Web sürümlerinin panel ayarı; kapalı sunucular başlatılır (beklenmez, panel açılana dek yeniden dener)."""
    found = _versions(pid, which)
    if found is None:
        return None
    p, vers = found
    web = [(k, v) for k, v in vers if v["tur"] == "web"]
    if not web:
        return None
    views = []
    for k, v in web:
        if not _port_open(v["port"]):
            _spawn(v["baslat"])
        token = _read(Path(v["token"]))
        views.append({"ad": "Son sürüm" if k == "son" else "Önizleme", "etiket": v.get("etiket", ""),
                      "commit": v.get("commit", ""), "port": v["port"], "yenilenir": bool(v.get("yenile")),
                      "adres": f"http://127.0.0.1:{v['port']}/" + (f"#token={token}" if token else "")})  # fmt: skip
    return {"kimlik": f"{pid}:{which}", "proje": pid, "baslik": p["ad"], "gorunumler": views,
            "farklar": differences(p) if len(web) == 2 else None}  # fmt: skip


def open_apps(pid: str, which: str, x: int, y: int, w: int, h: int) -> int:
    """Masaüstü programı sürümlerini açar (açıksa öne getirir) ve Asistan'ın solundaki alana yerleştirir."""
    found = _versions(pid, which)
    if found is None:
        return 2
    apps = [(k, v) for k, v in found[1] if v["tur"] == "uygulama"]
    if not apps:
        return 3
    procs = _cmdlines()
    slot = w // len(apps)
    for i, (_, v) in enumerate(apps):
        if not v.get("program") or not Path(v["program"]).exists():
            return 3
        if not any(v["iz"] in c for c in procs):
            _spawn([str(v["program"])], cwd=v.get("cwd"))
        _place(v["pencere"], x + i * slot, y, slot - (8 if len(apps) > 1 else 0), h)
    return 0


def open_apps_inside(pid: str, which: str, alan: dict[str, float]) -> tuple[int, list[dict[str, object]]]:
    """Masaüstü programı sürümlerini açar ve Asistan penceresinin içindeki alana yerleştirip onunla senkron tutar
    (karşılaştırmada ikisi yan yana). Dönüş: (kod, bağlanan pencereler: çekmece kapanınca bırakmak için)."""
    import pencere

    found = _versions(pid, which)
    if found is None:
        print(f"testler: {pid} {which} bulunamadı", file=sys.stderr)
        return 2, []
    apps = [(k, v) for k, v in found[1] if v["tur"] == "uygulama"]
    if not apps:
        print(f"testler: {pid} {which} masaüstü programı değil", file=sys.stderr)
        return 3, []
    procs = _cmdlines()
    hedefler: list[dict[str, object]] = []
    for i, (_, v) in enumerate(apps):
        if not v.get("program") or not Path(v["program"]).exists():
            print(f"testler: {pid} {which} programı yok: {v.get('program')}", file=sys.stderr)
            return 3, []
        if not any(v["iz"] in c for c in procs):
            _spawn([str(v["program"])], cwd=v.get("cwd"))
        hedefler.append({"tur": v["pencere"][0], "deger": v["pencere"][1], "bas": i / len(apps), "son": (i + 1) / len(apps)})
    return pencere.icine(hedefler, alan), hedefler


def refresh(pid: str) -> int:
    p = next((p for p in projects() if p["id"] == pid), None)
    cmd = p["surumler"]["onizleme"].get("yenile") if p else None
    if not cmd:
        return 2
    _spawn(cmd)
    return 0


def request(pid: str, which: str) -> int:
    if which not in ("son", "onizleme", "karsilastir") or not any(p["id"] == pid for p in projects()):
        return 2
    REQUEST.parent.mkdir(parents=True, exist_ok=True)
    REQUEST.write_text(json.dumps({"test": [pid, which], "t": time.time()}))
    return 0


def pop_request(max_age_s: float = 30.0) -> dict[str, Any] | None:
    """veri.py her okumada çağırır: bekleyen "goster" isteğini bir kez verir ve siler."""
    try:
        req = json.loads(REQUEST.read_text())
        REQUEST.unlink()
    except (OSError, ValueError):
        return None
    return dict(req) if time.time() - float(req.get("t", 0)) < max_age_s else None


def main(argv: list[str]) -> int:
    cmd, rest = (argv[1], argv[2:]) if len(argv) > 1 else ("liste", [])
    if cmd == "liste":
        print(json.dumps(listing(), ensure_ascii=False))
        return 0
    if cmd == "hazirla" and len(rest) == 2:
        cfg = prepare(rest[0], rest[1])
        print(json.dumps(cfg, ensure_ascii=False) if cfg else "{}")
        return 0 if cfg else 3
    if cmd == "ac" and len(rest) == 6 and all(a.lstrip("-").isdigit() for a in rest[2:]):
        x, y, w, h = (int(a) for a in rest[2:])
        return open_apps(rest[0], rest[1], x, y, w, h)
    if cmd == "yenile" and rest:
        return refresh(rest[0])
    if cmd == "goster" and len(rest) == 2:
        return request(rest[0], rest[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

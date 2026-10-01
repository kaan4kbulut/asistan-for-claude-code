"""Kullanıcıya özel ayarlar: ~/.config/asistan/ altında durur; yayınlanan kodda kişisel proje adı ya da yol yoktur.

ayarlar.json (hepsi isteğe bağlı):
  {
    "proje_koku": "~/Projeler",          projelerin durduğu klasör: alt klasörlerinin her biri bir proje
    "projeler": [                        gruplama: bir projeye sayılan klasörler ve ev klasöründe açılmış sohbetleri
      {"id": "web", "ad": "Web sitesi",   o projeye ayırmak için içerik izleri (Claude'un değindiği yollar)
       "klasor": "web-sitesi",           yeni sohbetin açılacağı klasör (proje_koku'na göre ya da tam yol)
       "klasorler": ["web-sitesi"], "izler": ["web-sitesi/"]}
    ],
    "adlar": {"klasor-adi": "Görünen ad"}
  }
Ayar yoksa: ev klasöründe açılan sohbetler "Genel"de, öteki her klasör kendi adıyla bir projedir.

testler.py (isteğe bağlı): `projects()` işlevi Test bölümünün projelerini ve sürümlerini verir (biçimi scripts/testler.py
başında anlatılır). Yoksa Test bölümü görünmez.

sohbetler.json (Asistan yazar, Sohbetler panelinden): sohbet başına Asistan'daki ad, proje ve gizleme:
  {"<sohbet kimliği>": {"baslik": "Yeni ad", "proje": "web", "gizli": true}}
Claude'un kendi sohbet kayıtlarına dokunulmaz.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "asistan"
AYAR = CONFIG / "ayarlar.json"
TESTLER = CONFIG / "testler.py"
SOHBETLER = CONFIG / "sohbetler.json"

_cache: dict[str, tuple[float, Any]] = {}


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return -1.0


def oku() -> dict[str, Any]:
    """ayarlar.json (değişince yeniden okunur); yoksa ya da bozuksa boş."""
    m = _mtime(AYAR)
    hit = _cache.get("ayar")
    if hit and hit[0] == m:
        return dict(hit[1])
    try:
        data = json.loads(AYAR.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    _cache["ayar"] = (m, data)
    return dict(data)


def proje_koku() -> Path | None:
    kok = oku().get("proje_koku")
    return Path(str(kok)).expanduser() if kok else None


def aileler() -> list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]]:
    """(kimlik, ad, klasör, o projeye sayılan klasör adları, içerik izleri)."""
    out = []
    for p in oku().get("projeler", []):
        try:
            out.append((str(p["id"]), str(p.get("ad") or p["id"]), str(p.get("klasor") or p["id"]),
                        tuple(p.get("klasorler") or [p.get("klasor") or p["id"]]), tuple(p.get("izler") or [])))  # fmt: skip
        except (KeyError, TypeError):
            continue
    return out


def adlar() -> dict[str, str]:
    a = oku().get("adlar", {})
    return {str(k): str(v) for k, v in a.items()} if isinstance(a, dict) else {}


def test_modulu() -> ModuleType | None:
    """~/.config/asistan/testler.py (değişince yeniden yüklenir); yoksa None."""
    m = _mtime(TESTLER)
    if m < 0:
        return None
    hit = _cache.get("testler")
    if hit and hit[0] == m:
        return hit[1]  # type: ignore[no-any-return]
    spec = importlib.util.spec_from_file_location("asistan_kullanici_testleri", TESTLER)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 - kullanıcının dosyasındaki bir hata programı durdurmasın
        print(f"uyarı: {TESTLER} yüklenemedi: {e}")
        return None
    _cache["testler"] = (m, mod)
    return mod


def sohbetler() -> dict[str, dict[str, Any]]:
    """Sohbetlerin Asistan'daki ayarları (ad, proje, gizli); değişince yeniden okunur."""
    m = _mtime(SOHBETLER)
    hit = _cache.get("sohbetler")
    if hit and hit[0] == m:
        return dict(hit[1])
    try:
        data = json.loads(SOHBETLER.read_text())
        data = {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    _cache["sohbetler"] = (m, data)
    return dict(data)


def sohbet(sid: str) -> dict[str, Any]:
    return dict(sohbetler().get(sid, {}))


def sohbet_ayarla(sid: str, **alanlar: Any) -> None:
    """Bir sohbetin ayarını değiştirir; değeri None ya da boş olan alan silinir (kayıt boşalırsa kaldırılır)."""
    data = sohbetler()
    cur = dict(data.get(sid, {}))
    for k, v in alanlar.items():
        if v is None or v == "" or v is False:
            cur.pop(k, None)
        else:
            cur[k] = v
    if cur:
        data[sid] = cur
    else:
        data.pop(sid, None)
    CONFIG.mkdir(parents=True, exist_ok=True)
    tmp = SOHBETLER.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(SOHBETLER)
    _cache.pop("sohbetler", None)

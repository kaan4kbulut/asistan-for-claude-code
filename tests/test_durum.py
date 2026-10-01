"""durum.py (widget yayını, eksikler), ayarlar.py (ayarsız çalışma) ve veri.py (tur ölçümü) testleri."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ayarlar  # noqa: E402
import durum  # noqa: E402
import veri  # noqa: E402


def _get(port: int, v: int, host: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/durum?v={v}")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def test_yayin_yalnizca_degisince_surum_artar_ve_uzun_yoklama_bekler() -> None:
    y = durum.Yayin(port=47691)
    assert y.baslat()
    y.yayinla({"activity": {"state": "idle"}})
    code, d = _get(47691, -1)
    assert code == 200 and d["v"] == 1 and d["activity"]["state"] == "idle"
    y.yayinla({"activity": {"state": "idle"}})  # aynı içerik: sürüm artmaz
    assert y.v == 1
    got: dict = {}
    t = threading.Thread(target=lambda: got.update(_get(47691, 1)[1]))
    t.start()
    time.sleep(0.3)
    assert t.is_alive()  # elindeki sürüm güncel: cevap bekletilir
    y.yayinla({"activity": {"state": "tool"}})
    t.join(3)
    assert got["v"] == 2 and got["activity"]["state"] == "tool"
    y.server.shutdown()


def test_yayin_baska_host_basligini_reddeder() -> None:
    y = durum.Yayin(port=47692)
    assert y.baslat()
    assert _get(47692, -1, host="kotu.example:47692")[0] == 404
    y.server.shutdown()


def test_yayin_widgete_programin_buyuk_alanlarini_gondermez() -> None:
    y = durum.Yayin(port=47693)
    assert y.baslat()
    y.yayinla({"activity": {}, "projeler": [{"cok": "büyük"}], "istek": {"test": ["a", "son"]}})
    d = _get(47693, -1)[1]
    assert "projeler" not in d and "istek" not in d
    y.server.shutdown()


def test_eksikler() -> None:
    snap = {
        "sekmeler": [{"baslik": "Sohbet", "durum": "waiting"}],
        "steps": {"left": [{"id": "NG-1", "title": "a", "kind": "blocked"}, {"id": "NG-2", "title": "b", "kind": "ready"}]},
        "git": {"dirty": True},
        "exams": [{"name": "exam-1", "state": "silent"}],
        "gates": [],
        "testler": [{"ad": "Web", "farklar": {"geride": 2, "kirli": True},
                     "surumler": {"son": {"tur": "yok", "neden": "kurulu değil"}, "onizleme": {}}}],  # fmt: skip
    }
    out = durum.eksikler(snap, "web")
    turler = [x["tur"] for x in out]
    assert turler.count("bekliyor") == 1 and turler.count("engel") == 1
    assert any("kaydedilmemiş" in x["yazi"] for x in out)
    assert any("2 commit" in x["yazi"] for x in out)
    assert any("kurulu değil" in x["yazi"] for x in out)
    assert not any("NG-2" in x["yazi"] for x in out)  # hazır adım eksik sayılmaz


def test_ayarsiz_calisir(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(ayarlar, "AYAR", tmp_path / "yok.json")
    monkeypatch.setattr(ayarlar, "TESTLER", tmp_path / "yok.py")
    ayarlar._cache.clear()
    assert ayarlar.oku() == {} and ayarlar.proje_koku() is None and ayarlar.aileler() == []
    assert ayarlar.test_modulu() is None


def test_tur_olcumu() -> None:
    def line(kind: str, ts: str, **extra: object) -> str:
        return json.dumps({"type": kind, "timestamp": ts, **extra})

    def tool(i: int, ts: str) -> str:
        return line("assistant", ts, message={"content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash",
                                                            "input": {"command": "x", "description": f"iş {i}"}}]})  # fmt: skip

    def result(i: int, ts: str) -> str:
        return line("user", ts, message={"content": [{"type": "tool_result", "tool_use_id": f"t{i}"}]})

    lines = [
        line("user", "2026-01-01T10:00:00Z", message={"content": "birinci istem"}),
        tool(1, "2026-01-01T10:00:05Z"), result(1, "2026-01-01T10:00:15Z"),
        line("assistant", "2026-01-01T10:01:00Z", message={"content": [{"type": "text", "text": "bitti."}]}),
        line("user", "2026-01-01T10:05:00Z", message={"content": "ikinci istem"}),
        tool(2, "2026-01-01T10:05:10Z"),
    ]  # fmt: skip
    now = veri._ts("2026-01-01T10:05:40Z")
    a = veri.parse_activity(lines, now)
    t = a["turn"]
    assert t["live"] and t["ops"] == 1 and t["elapsed_s"] == 40
    assert t["typical_s"] == 60 and t["eta_s"] == 20 and t["pct"] == 66
    assert a["running_op"]["elapsed_s"] == 30

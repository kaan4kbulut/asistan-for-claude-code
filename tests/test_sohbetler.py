"""Sohbet yönetimi: Asistan'daki ad, taşıma, gizleme ve çöpe atma (gerçek sohbetlere dokunmadan, sahte klasörde)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import arka  # noqa: E402
import ayarlar  # noqa: E402


def _sohbet(d: Path, sid: str, cwd: Path, ilk: str, ek: list[dict] | None = None) -> Path:
    lines = [{"type": "user", "entrypoint": "cli", "cwd": str(cwd), "message": {"content": ilk}},
             *(ek or [])]  # fmt: skip
    f = d / f"{sid}.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n" + "x" * 25_000 + "\n")
    return f


@pytest.fixture
def ortam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    home, proj_root = tmp_path / "ev", tmp_path / "ev/Projeler"
    (proj_root / "web").mkdir(parents=True)
    (proj_root / "api").mkdir(parents=True)
    claude = tmp_path / "claude/projects/x"
    claude.mkdir(parents=True)
    cfg = tmp_path / "ayar"
    cfg.mkdir()
    (cfg / "ayarlar.json").write_text(json.dumps({"proje_koku": str(proj_root)}))
    monkeypatch.setattr(arka, "TEMP_DIRS", ())  # pytest'in klasörü /tmp altında
    monkeypatch.setattr(arka, "HOME", home)
    monkeypatch.setattr(arka, "PROJECTS", claude.parent)
    monkeypatch.setattr(arka, "SESSIONS", tmp_path / "claude/sessions")
    monkeypatch.setattr(arka, "CACHE", tmp_path / "onbellek.json")
    monkeypatch.setattr(arka, "sessions", lambda: [])
    monkeypatch.setattr(arka, "open_elsewhere", lambda sid: False)
    monkeypatch.setattr(ayarlar, "AYAR", cfg / "ayarlar.json")
    monkeypatch.setattr(ayarlar, "SOHBETLER", cfg / "sohbetler.json")
    monkeypatch.setattr(ayarlar, "CONFIG", cfg)
    ayarlar._cache.clear()
    _sohbet(claude, "s-web", proj_root / "web", "sayfayı düzelt",
            [{"type": "ai-title", "aiTitle": "Web sayfası düzeltmesi"}])  # fmt: skip
    _sohbet(claude, "s-api", proj_root / "api", "uç noktayı ekle",
            [{"type": "custom-title", "customTitle": "Benim adım"}, {"type": "ai-title", "aiTitle": "Sonra gelen"}])  # fmt: skip
    return {"claude": claude, "tmp": tmp_path}


def _bul(projs: list[dict], sid: str) -> tuple[str, dict] | None:
    for p in projs:
        for s in p["sessions"]:
            if s["id"] == sid:
                return p["id"], s
    return None


def test_basliklar_claude_adi_ve_asistan_adi(ortam: dict[str, Path]) -> None:
    projs = arka.projects(max_age_s=0)
    assert _bul(projs, "s-web")[1]["title"] == "Web sayfası düzeltmesi"
    assert _bul(projs, "s-api")[1]["title"] == "Benim adım"  # /rename, sonraki ai-title'a üstün
    ayarlar.sohbet_ayarla("s-web", baslik="Ana sayfa")
    assert _bul(arka.projects(), "s-web")[1]["title"] == "Ana sayfa"  # önbellekten sonra da anında
    assert arka.session_title("s-web") == "Ana sayfa"
    assert arka.rename("s-web", "") == 0  # boş: Claude'un başlığına döner
    assert arka.session_title("s-web") == "Web sayfası düzeltmesi"


def test_tasima_ve_gizleme(ortam: dict[str, Path]) -> None:
    arka.projects(max_age_s=0)
    ayarlar.sohbet_ayarla("s-web", proje="api")
    proje, _ = _bul(arka.projects(), "s-web")
    assert proje == "api"
    web = next(p for p in arka.projects() if p["id"] == "web")
    assert web["sessions"] == [] and web["mtime"] == 0  # taşınan sohbet eski projenin tarihini taşımaz
    ayarlar.sohbet_ayarla("s-web", gizli=True)
    assert _bul(arka.projects(), "s-web") is None
    assert _bul(arka.projects(gizliler=True), "s-web")[1]["gizli"] is True
    ayarlar.sohbet_ayarla("s-web", gizli=False, proje=None)
    assert _bul(arka.projects(), "s-web")[0] == "web"
    assert ayarlar.sohbetler() == {}  # boşalan kayıt silinir


def test_cope_atma(ortam: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arka.shutil, "which", lambda name: None)  # gio yok: elle çöp kutusu
    monkeypatch.setenv("XDG_DATA_HOME", str(ortam["tmp"] / "veri"))
    (ortam["claude"] / "s-web").mkdir()
    ayarlar.sohbet_ayarla("s-web", baslik="x")
    arka.projects(max_age_s=0)
    assert arka.trash_session("s-web") == 0
    trash = ortam["tmp"] / "veri/Trash"
    assert (trash / "files/s-web.jsonl").exists() and (trash / "files/s-web").is_dir()
    assert (trash / "info/s-web.jsonl.trashinfo").read_text().startswith("[Trash Info]")
    assert not (ortam["claude"] / "s-web.jsonl").exists()
    assert _bul(arka.projects(), "s-web") is None  # önbellek eskitildi: listeden hemen düşer
    assert "s-web" not in ayarlar.sohbetler()
    assert arka.trash_session("yok") == 4


def test_acik_sohbet_silinmez(ortam: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arka, "sessions", lambda: [{"session": "s-api", "resume": "", "name": "claude-1"}])
    assert arka.trash_session("s-api") == 5
    assert (ortam["claude"] / "s-api.jsonl").exists()

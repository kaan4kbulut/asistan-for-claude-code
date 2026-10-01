#!/usr/bin/env python3
"""Ölçümler ve Claude'un durumu: programın veri katmanı (durum.py) bu işlevleri kullanır; komut olarak da çalışır.

Claude Code'un oturumu (durum, çalışan araç ve tahmini, turlar, son konuşma, sürüm/model), sistem ölçümleri (ekran
kartı uyuyorsa uyandırılmadan), mikrofon düğmesinin durumu ve isteğe bağlı bir projenin adımları/git geçmişi
(BACKLOG.md tabloları ve .devloop/logs altındaki sınav/kalite kapısı kayıtları olan projelerde).
Kullanım:  veri.py [--proje KLASÖR]      |  veri.py --gpu   (yalnızca ekran kartı)
Yalnızca okur; hiçbir şeyi değiştirmez/başlatmaz. Yalnızca standart kütüphane.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import arka  # aynı klasörde: arka plandaki Claude'un ekranı
import testler  # aynı klasörde: projelerin test sürümleri (son sürüm / önizleme)

CARD_TIMEOUT_S = 900  # acquisition_exam.py: izin kartı bekleme üst sınırı
GATE_TYPICAL_S = 185  # tam kalite kapısı (son ölçümler ≈185 sn)
EXAM_STEPS = 15  # acquisition_exam.py içindeki check() sayısı
SILENT_WARN_S = 120
# nvidia-smi her çağrıda ayrı ekran kartını uyandırır ve birkaç saniye uyanık tutar: uyuyan kart hiç sorulmaz
# (sysfs okuması uyandırmaz), uyanık kart da en çok bu sıklıkta sorulur, arada son okuma kullanılır.
NV_EVERY_S = 15.0
NV_CACHE = Path.home() / ".cache/claude-widget/gpu.json"
VOICE_STATE = Path.home() / ".cache/claude-widget/sesli-istem.json"  # scripts/sesli_istem.py yazar


def parse_exam(text: str) -> tuple[int, int, bool]:
    """(geçen, kalan, bitti) — sınav logundaki GEÇTİ/KALDI satırlarından."""
    ok = len(re.findall(r"^GEÇTİ ", text, re.M))
    bad = len(re.findall(r"^KALDI ", text, re.M))
    return ok, bad, bool(re.search(r"^(CIKIS=|SONUÇ:)", text, re.M))


def parse_pytest(text: str) -> tuple[int | None, bool, str]:
    """(son yüzde, bitti mi, özet satırı)."""
    pct = re.findall(r"\[\s*(\d+)%\]|\s(\d+)%\]?$", text, re.M)
    last = None
    for a, b in pct:
        last = int(a or b)
    done = re.search(
        r"^.*\d+ passed.*$|^.*\d+ failed.*$|TÜM KONTROLLER GEÇTİ|BAŞARISIZ:", text, re.M
    )
    summary = re.findall(r"^=*\s*((?:\d+ (?:passed|failed)[^=]*))=*$", text, re.M)
    return last, bool(done), (summary[-1].strip() if summary else "")


def estimate_exam(
    state: str, quiet_s: float, done: int, total: int, age_s: float | None
) -> tuple[int | None, str]:
    """(kalan sn, tür). Tür: 'en_gec' = kesin üst sınır (zaman aşımı), 'tahmin' = adım hızından kaba tahmin."""
    if state == "silent":
        if quiet_s > CARD_TIMEOUT_S:  # söz verilen üst sınır aşıldı: tahmin uydurma
            return None, "asildi"
        return int(CARD_TIMEOUT_S - quiet_s), "en_gec"
    if state == "running" and age_s and done > 0:
        return int(age_s / done * max(total - done, 0)), "tahmin"
    return None, ""


def estimate_gate(state: str, pct: int, age_s: float | None) -> int | None:
    if state not in ("running", "silent") or age_s is None:
        return None
    if pct > 0:
        return int(age_s * (100 - pct) / pct)
    return max(int(GATE_TYPICAL_S - age_s), 0)


def fmt_eta(sn: int | None, kind: str = "tahmin") -> str:
    if kind == "asildi":
        return "zaman aşımı aşıldı, takılmış olabilir"
    if sn is None:
        return ""
    return ("en geç ~" if kind == "en_gec" else "~") + fmt_dur(sn) + " kaldı"


# ── canlı etkinlik: Claude Code oturum transkripti (anlık yazılır) ─────────────
TAIL_BYTES = 3_000_000
BIG_LINE = 60_000  # görüntü içeren sonuç satırları: tam ayrıştırılmaz
_RX_ID = re.compile(r'"tool_use_id":\s*"([^"]+)"')
_RX_TS = re.compile(r'"timestamp":\s*"([^"]+)"')
ACTIVE_WINDOW_S = 15 * 60  # bu süreden eski sınav/kapı kayıtları ana alanda gösterilmez


def _ts(s: str | None) -> float | None:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _label(name: str, inp: dict) -> str:  # type: ignore[type-arg]
    if name == "Bash":
        cmd = str(inp.get("command", "")).strip().split("\n")[0]
        cmd = re.sub(r"^(?:cd\s+\S+\s*&&\s*|export\s+\S+=\S+[;\s]+|[A-Z_]+=\S+\s+)+", "", cmd)
        d = inp.get("description") or cmd
    elif name in ("Read", "Edit", "Write"):
        d = Path(str(inp.get("file_path", ""))).name
    else:
        d = str(inp.get("description") or inp.get("prompt") or inp.get("pattern") or "")
    d = " ".join(str(d).split())
    return f"{name}: {d[:68]}" if d else name


def parse_activity(lines: list[str], now: float) -> dict:  # type: ignore[type-arg]
    """Transkript satırlarından: anlık durum, çalışan araç, son tamamlananlar."""
    open_tools: dict[str, dict] = {}  # type: ignore[type-arg]
    done: list[dict] = []  # type: ignore[type-arg]
    last_ts, last_kind, last_text = None, "", ""
    # turlar: kullanıcının yazdığı her istemden, Claude'un o istem için son yazdığı ana kadar
    turns: list[float] = []
    turn_start: float | None = None
    turn_ops = 0
    last_asst: float | None = None
    for ln in lines:
        if len(ln) > BIG_LINE:  # büyük satır = görüntülü araç sonucu: yalnızca eşleştirme bilgisi
            mid, mts = _RX_ID.search(ln), _RX_TS.search(ln)
            if mid and mts and mid.group(1) in open_tools:
                t = _ts(mts.group(1))
                o = open_tools.pop(mid.group(1))
                if o["start"] and t:
                    done.append({"label": o["label"], "dur_s": round(t - o["start"], 1), "end": t})
                last_kind, last_ts = "result", t or last_ts
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        t = _ts(e.get("timestamp"))
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            last_asst = t or last_asst
            for b in content:
                if b.get("type") == "tool_use":
                    turn_ops += 1
                    open_tools[b["id"]] = {
                        "label": _label(b.get("name", "?"), b.get("input") or {}),
                        "start": t,
                    }
                    last_kind = "tool"
                elif b.get("type") == "thinking":
                    last_kind = "think"
                elif b.get("type") == "text":
                    last_kind = "text"
                    last_text = str(b.get("text", "")).strip()
            last_ts = t or last_ts
        elif e.get("type") == "user":
            if isinstance(content, list):
                for b in content:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in open_tools:
                        o = open_tools.pop(b["tool_use_id"])
                        if o["start"] and t:
                            done.append(
                                {"label": o["label"], "dur_s": round(t - o["start"], 1), "end": t}
                            )
                        last_kind = "result"
            else:
                last_kind = "user"
            prompt = content if isinstance(content, str) else " ".join(
                str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
            ) if isinstance(content, list) and not any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ) else ""  # fmt: skip
            if t and not e.get("isMeta") and _typed(prompt):
                if turn_start and last_asst and last_asst > turn_start:
                    turns.append(last_asst - turn_start)
                turn_start, turn_ops, last_asst = t, 0, None
            last_ts = t or last_ts
    running = [o for o in open_tools.values() if o["start"]]
    cur = max(running, key=lambda o: o["start"]) if running else None
    idle_s = now - last_ts if last_ts else None
    asking = next((o for o in running if o["label"].startswith("AskUserQuestion")), None)
    if asking:  # açık seçenekli soru: gerçekten yanıt bekleniyor
        state, detail = "ask", "sana bir soru sordu: " + asking["label"].split(":", 1)[-1].strip()
    elif cur:
        state, detail = "tool", cur["label"]
    elif last_kind in ("user", "result", "think") and idle_s is not None and idle_s < 600:
        state, detail = "think", "düşünüyor / sonraki adımı hazırlıyor"
    elif last_kind == "text":
        q = last_text.rstrip().rstrip('*_`" ').endswith("?")  # son cümle soru mu?
        if q:
            state, detail = "ask", "sana soru sordu: " + last_text.strip().splitlines()[-1][:90]
        else:
            state, detail = "done", "tur bitti — soru yok, yeni talimat bekleniyor"
    else:
        state, detail = "idle", "boşta"
    hist: dict[str, list[float]] = {}
    for d in done:
        hist.setdefault(op_key(d["label"]), []).append(d["dur_s"])
    progress = None
    if cur and cur["start"]:
        el = now - cur["start"]
        past = sorted(hist.get(op_key(cur["label"]), []))
        if past:  # aynı tür işlemin bu oturumdaki medyan süresi → tahmini geri sayım
            typical = past[len(past) // 2]
            progress = {"pct": min(99, int(100 * el / typical)) if typical > 0 else None,
                        "eta_s": max(int(typical - el), 0), "kind": "tahmin", "basis": len(past),
                        "over": el > typical, "elapsed_s": int(el)}  # fmt: skip
    turn = None
    if turn_start:  # bu tur: ne kadardır sürüyor, kaç işlem; önceki turların ortancasına göre kalan süre
        live = state in ("tool", "think")
        el = (now if live else (last_asst or now)) - turn_start
        past = sorted(x for x in turns[-12:] if x > 5)
        typical = past[len(past) // 2] if past else None
        turn = {"elapsed_s": int(el), "ops": turn_ops, "live": live, "typical_s": int(typical) if typical else None,
                "eta_s": max(int(typical - el), 0) if typical and live else None, "basis": len(past),
                "over": bool(typical and live and el > typical),
                "pct": min(99, int(100 * el / typical)) if typical and live else None}  # fmt: skip
    return {
        "progress": progress,
        "turn": turn,
        "state": state, "detail": detail,
        "elapsed_s": int(now - cur["start"]) if cur else (int(idle_s) if idle_s is not None and state == "think" else None),
        "running_op": {"label": cur["label"], "elapsed_s": int(now - cur["start"])} if cur else None,
        "recent": [{"label": d["label"], "dur_s": d["dur_s"], "ago_s": int(now - d["end"])} for d in done[-20:]][::-1],
        "calls_10m": sum(1 for d in done if now - d["end"] < 600) + len(running),
    }  # fmt: skip


# ── proje adımları: BACKLOG.md tablolarından yapılan / kalan ───────────────────
_ID = re.compile(r"^(WP-\d+[a-c]?|NG-\d+[a-c]?|PLAT-\d+)$")
DONE_WORDS = ("DONE", "VALIDATED", "IMPLEMENTED")


def classify(status: str) -> str:
    """done | partial | blocked | approval | ready  (BACKLOG 'Durum' hücresinden)."""
    u = status.replace("*", "").upper()
    if u.startswith("BLOCKED") or "BLOCKED:" in u[:20]:
        return "blocked"
    if "ONAY BEKL" in u:
        return "approval"
    if u.startswith("KISMEN"):
        return "partial"
    if u.startswith("READY"):  # "READY (… VALIDATED …)" yapıldı demek değildir
        return "ready"
    if any(w in u[:40] for w in DONE_WORDS):
        return "done"
    return "ready"


def parse_backlog(text: str) -> dict:  # type: ignore[type-arg]
    rows: dict[str, dict] = {}  # type: ignore[type-arg]
    for ln in text.splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        ident = next((c for c in cells[:2] if _ID.match(c)), None)
        if not ident or len(cells) < 3:
            continue
        title = re.sub(r"[*`]", "", cells[cells.index(ident) + 1])
        status = cells[-1]
        m = re.match(r"^READY → \*\*(NG-\d+) içinde", status)
        rows[ident] = {
            "id": ident,
            "title": title[:46],
            "status": status,
            "ref": m.group(1) if m else None,
        }
    for r in rows.values():  # "→ NG-02 içinde": bağlı işin durumunu izle
        src = rows.get(r["ref"]) if r["ref"] else None
        r["kind"] = classify(src["status"]) if src else classify(r["status"])
    done = [r for r in rows.values() if r["kind"] == "done"]
    order = {"partial": 0, "ready": 1, "approval": 3, "blocked": 4}

    def rank(r: dict) -> float:  # type: ignore[type-arg]
        deferred = r["kind"] == "ready" and "ertelen" in r["status"].lower()
        return 2 if deferred else order[r["kind"]]  # ertelenmiş işler hazırların arkasında

    left = sorted((r for r in rows.values() if r["kind"] != "done"), key=rank)
    return {
        "total": len(rows), "done_n": len(done),
        "done": [{"id": r["id"], "title": r["title"]} for r in done],
        "left": [{"id": r["id"], "title": r["title"], "kind": r["kind"]} for r in left],
    }  # fmt: skip


def project_steps(home: Path) -> dict:  # type: ignore[type-arg]
    f = home / "BACKLOG.md"
    try:
        return parse_backlog(f.read_text(encoding="utf-8"))
    except OSError:
        return {"total": 0, "done_n": 0, "done": [], "left": []}


def op_key(label: str) -> str:
    """Aynı tür işlemi tanıyan kaba anahtar: araç + ilk iki sözcük (ör. 'Bash: uv run')."""
    tool, _, rest = label.partition(":")
    return tool + ":" + " ".join(rest.split()[:2])


def find_transcript(session: str | None = None) -> Path | None:
    base = Path.home() / ".claude/projects"
    files = list(base.glob(f"*/{session}.jsonl")) if session else list(base.glob("*/*.jsonl"))
    files = [f for f in files if f.is_file()]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def _first_line(text: str, limit: int = 160) -> str:
    for ln in str(text).splitlines():
        if ln.strip():
            return ln.strip()[:limit]
    return ""


def _typed(text: str) -> bool:
    """Kullanıcının gerçekten yazdığı istem mi (komut çıktıları, hatırlatmalar, özetler değil)."""
    t = text.strip()
    return bool(t) and not t.startswith(("<", "Caveat:", "This session is being continued"))


def conversation(lines: list[str], n: int = 14) -> list[dict[str, str]]:
    """Claude Code ekranındaki gibi son konuşma: > istem, ● cevap, ● Araç(…), ⎿ sonuç."""
    out: list[dict[str, str]] = []
    for ln in lines[-800:]:
        if len(ln) > BIG_LINE:  # görüntülü araç sonucu
            if '"tool_result"' in ln:
                out.append({"kind": "result", "text": "(görüntü)"})
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("isSidechain") or e.get("isMeta"):
            continue
        att = e.get("attachment") or {}
        if (
            e.get("type") == "attachment" and att.get("type") == "queued_command"
        ):  # çalışırken yazılan
            if _typed(str(att.get("prompt", ""))):
                out.append({"kind": "user", "text": _first_line(att["prompt"])})
            continue
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "user":
            if isinstance(content, str):
                if _typed(content):
                    out.append({"kind": "user", "text": _first_line(content)})
                continue
            for b in content if isinstance(content, list) else []:
                if b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
                    kind = "error" if b.get("is_error") else "result"
                    out.append({"kind": kind, "text": _first_line(str(c or "")) or "(boş)"})
                elif b.get("type") == "text" and _typed(str(b.get("text", ""))):
                    out.append({"kind": "user", "text": _first_line(b["text"])})
        elif e.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if b.get("type") == "text" and str(b.get("text", "")).strip():
                    out.append({"kind": "assistant", "text": _first_line(b["text"], 240)})
                elif b.get("type") == "tool_use":
                    name = str(b.get("name", "?"))
                    what = _label(name, b.get("input") or {}).partition(": ")[2]
                    out.append({"kind": "tool", "text": f"{name}({what})" if what else name})
    return out[-n:]


def model_name(model: str) -> str:
    """'claude-opus-5-5' → 'Opus 5.5', 'claude-haiku-4-5-20251001' → 'Haiku 4.5'."""
    m = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-|$)", model)
    if not m:
        return "" if model.startswith("<") else model
    family, major, minor = m.groups()
    return f"{family.capitalize()} {major}" + (f".{minor}" if minor else "")


def session_info(lines: list[str]) -> dict[str, str]:
    """Claude Code başlığındaki bilgiler: sürüm, model, çalışma klasörü."""
    info = {"version": "", "model": "", "cwd": ""}
    for ln in reversed(lines[-800:]):
        if len(ln) > BIG_LINE:
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        info["version"] = info["version"] or str(e.get("version") or "")
        info["cwd"] = info["cwd"] or str(e.get("cwd") or "")
        if not info["model"] and e.get("type") == "assistant":
            info["model"] = model_name(str((e.get("message") or {}).get("model") or ""))
        if all(info.values()):
            break
    home = str(Path.home())
    if info["cwd"] == home or info["cwd"].startswith(home + "/"):
        info["cwd"] = "~" + info["cwd"][len(home) :]
    return info


def claude_activity(now: float | None = None, session: str | None = None) -> dict:  # type: ignore[type-arg]
    now = now or time.time()
    f = find_transcript(session)
    if not f:
        return {
            "state": "idle",
            "detail": "oturum bulunamadı",
            "elapsed_s": None,
            "recent": [],
            "calls_10m": 0,
            "chat": [],
            "session": {"version": "", "model": "", "cwd": ""},
        }
    with f.open("rb") as fh:
        fh.seek(max(f.stat().st_size - TAIL_BYTES, 0))
        data = fh.read().decode("utf-8", errors="replace").splitlines()[1:]
    act = parse_activity(data, now)
    act["chat"] = conversation(data)
    act["session"] = session_info(data)
    return act


_prev_cpu: tuple[int, int] | None = None


def cpu_pct(sample_s: float = 0.0) -> float:
    """Toplam CPU % (iki /proc/stat okuması arasındaki fark)."""
    global _prev_cpu

    def read() -> tuple[int, int]:
        v = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return sum(v) - v[3] - v[4], sum(v)  # (meşgul, toplam) — idle+iowait hariç

    if _prev_cpu is None:
        _prev_cpu = read()
        if sample_s:
            time.sleep(sample_s)
    b0, t0 = _prev_cpu
    b1, t1 = read()
    _prev_cpu = (b1, t1)
    return round(100 * (b1 - b0) / (t1 - t0), 1) if t1 > t0 else 0.0


def ram_pct() -> float:
    m = {
        k: int(v.split()[0])
        for k, v in (ln.split(":", 1) for ln in Path("/proc/meminfo").read_text().splitlines())
    }
    return round(100 * (1 - m["MemAvailable"] / m["MemTotal"]), 1)


def _net_bytes() -> tuple[int, int]:
    rx = tx = 0
    for ln in Path("/proc/net/dev").read_text().splitlines()[2:]:
        name, data = ln.split(":", 1)
        if name.strip() == "lo":
            continue
        f = data.split()
        rx, tx = rx + int(f[0]), tx + int(f[8])
    return rx, tx


_DISK = re.compile(r"(nvme\d+n\d+|sd[a-z]+|vd[a-z]+|mmcblk\d+)$")  # bölümler değil, fiziksel diskler


def _disk_bytes() -> tuple[int, int]:
    """Fiziksel disklerden okunan ve yazılan toplam bayt (/proc/diskstats: 512 baytlık kesimler)."""
    rd = wr = 0
    try:
        for ln in Path("/proc/diskstats").read_text().splitlines():
            f = ln.split()
            if len(f) > 9 and _DISK.match(f[2]):
                rd, wr = rd + int(f[5]) * 512, wr + int(f[9]) * 512
    except OSError:
        pass
    return rd, wr


def cpu_details() -> dict[str, float | None]:
    mhz = [
        float(ln.split(":")[1])
        for ln in Path("/proc/cpuinfo").read_text().splitlines()
        if ln.startswith("cpu MHz")
    ]
    temp = None
    for h in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (h / "name").read_text().strip() in ("coretemp", "k10temp", "zenpower"):
                temp = int((h / "temp1_input").read_text()) / 1000
                break
        except OSError:
            continue
    # En hızlı çekirdek: ortalama, boştaki verimli çekirdeklerle o an çalışan çekirdeğin hızını gizliyordu.
    return {
        "freq_ghz": round(max(mhz) / 1000, 2) if mhz else None,
        "temp": temp,
        "cores": len(mhz) or None,
    }


def ram_details() -> dict[str, float]:
    m = {
        k: int(v.split()[0])
        for k, v in (ln.split(":", 1) for ln in Path("/proc/meminfo").read_text().splitlines())
    }
    g = 1024 * 1024
    return {
        "used_gib": round((m["MemTotal"] - m["MemAvailable"]) / g, 1),
        "total_gib": round(m["MemTotal"] / g, 1),
        "swap_gib": round((m.get("SwapTotal", 0) - m.get("SwapFree", 0)) / g, 1),
    }


def nvidia_sleeping(pci: Path = Path("/sys/bus/pci/devices")) -> bool | None:
    """NVIDIA ekran kartı güç tasarrufunda mı; kart yoksa None. Yalnızca sysfs okur, kartı uyandırmaz."""
    for dev in pci.glob("*"):
        try:
            if (dev / "vendor").read_text().strip() != "0x10de" or not (
                dev / "class"
            ).read_text().startswith("0x03"):
                continue
            return (dev / "power/runtime_status").read_text().strip() == "suspended"
        except OSError:
            continue
    return None


def gpu_details() -> dict[str, Any]:
    empty: dict[str, Any] = {
        "util": None,
        "temp": None,
        "power": None,
        "vram": None,
        "vram_total": None,
    }
    sleeping = nvidia_sleeping()
    if sleeping or not shutil.which("nvidia-smi"):
        return {**empty, "sleeping": sleeping}
    try:
        cached = json.loads(NV_CACHE.read_text())
        if time.time() - float(cached["t"]) < NV_EVERY_S:
            return {**cached["d"], "sleeping": False}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        r = subprocess.run(  # noqa: S603, S607
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,clocks.gr",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=False,
        )  # fmt: skip
        u, t, pw, vu, vt, clk = (float(x) for x in r.stdout.splitlines()[0].split(","))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {**empty, "sleeping": sleeping}
    d = {"util": u, "temp": t, "power": pw, "vram": vu, "vram_total": vt, "clock_ghz": round(clk / 1000, 2)}
    try:
        NV_CACHE.parent.mkdir(parents=True, exist_ok=True)
        NV_CACHE.write_text(json.dumps({"t": time.time(), "d": d}))
    except OSError:
        pass
    return {**d, "sleeping": False}


def voice_state(now: float) -> dict[str, Any]:
    """Masaüstündeki mikrofon düğmesinin son durumu (scripts/sesli_istem.py)."""
    try:
        v = json.loads(VOICE_STATE.read_text())
        v["age_s"] = round(now - float(v.get("ts", 0)), 1)
        return v if isinstance(v, dict) else {"state": "", "age_s": None}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"state": "", "age_s": None}


def git_info(repo: Path) -> dict[str, Any]:
    def g(*a: str) -> str:
        r = subprocess.run(
            ["git", *a], cwd=repo, capture_output=True, text=True, timeout=5, check=False
        )  # noqa: S603, S607
        return r.stdout.strip() if r.returncode == 0 else ""

    log = g("log", "-6", "--format=%h\x1f%s\x1f%ct")
    commits = []
    for ln in log.splitlines():
        h, subj, ts = ln.split("\x1f")
        commits.append({"hash": h, "subject": subj[:90], "ago_s": int(time.time() - int(ts))})
    today = g("log", "--since=midnight", "--oneline")
    return {"branch": g("rev-parse", "--abbrev-ref", "HEAD"), "commits": commits,
            "today": len(today.splitlines()) if today else 0, "dirty": bool(g("status", "--porcelain", "-uno"))}  # fmt: skip


def _metrics() -> dict[str, Any]:
    """CPU, ağ ve disk hızı aynı 0,25 sn örnekleme penceresinde ölçülür."""
    rx0, tx0 = _net_bytes()
    dr0, dw0 = _disk_bytes()
    t0 = time.monotonic()
    cpu = cpu_pct(0.25)
    dt = max(time.monotonic() - t0, 0.05)
    rx1, tx1 = _net_bytes()
    dr1, dw1 = _disk_bytes()
    gd = gpu_details()
    du = shutil.disk_usage(Path.home())
    return {
        "cpu": cpu, "ram": ram_pct(), "gpu": gd["util"],
        "cpu_detail": cpu_details(), "ram_detail": ram_details(), "gpu_detail": gd,
        "net_down_kbs": round((rx1 - rx0) / dt / 1024, 1), "net_up_kbs": round((tx1 - tx0) / dt / 1024, 1),
        "disk_read_kbs": round((dr1 - dr0) / dt / 1024, 1), "disk_write_kbs": round((dw1 - dw0) / dt / 1024, 1),
        "disk_free_gib": round(du.free / 2**30, 1),
    }  # fmt: skip


def gpu_pct() -> float | None:
    util = gpu_details()["util"]
    return None if util is None else float(util)


def fmt_dur(sn: float) -> str:
    sn = int(max(sn, 0))
    return (
        f"{sn // 3600}sa {sn % 3600 // 60:02d}dk" if sn >= 3600 else f"{sn // 60}dk {sn % 60:02d}sn"
    )


def running(pattern: str) -> list[tuple[int, float]]:
    """argv'sinde `pattern` ile biten bir öğe olan süreçler (pid, yaş sn). Kendini eşleştirmez."""
    out: list[tuple[int, float]] = []
    me = os.getpid()
    hz = os.sysconf("SC_CLK_TCK")
    try:
        up = float(Path("/proc/uptime").read_text().split()[0])
    except OSError:
        return out
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            argv = p.joinpath("cmdline").read_bytes().split(b"\0")[:-1]
            if (
                len(argv) >= 2
                and "python" in Path(argv[0].decode()).name
                and any(a.decode(errors="ignore").endswith(pattern) for a in argv[1:3])
            ):
                start = int(p.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]) / hz
                out.append((int(p.name), up - start))
        except (OSError, ValueError, IndexError):
            continue
    return out


def gpu() -> str:
    gd = gpu_details()
    if gd["sleeping"]:
        return "GPU: uykuda"
    if gd["util"] is None:
        return "GPU: yok" if not shutil.which("nvidia-smi") else "GPU: okunamadı"
    return f"GPU %{gd['util']:.0f}  VRAM {gd['vram']:.0f}/{gd['vram_total']:.0f} MiB"


def jobs(project: Path | None, now: float) -> dict[str, Any]:
    """Projenin süren ve yeni biten işleri (sınav, kalite kapısı) .devloop/logs'tan."""
    logs = (project or Path("/nonexistent")) / ".devloop/logs"
    exam_procs = running("acquisition_exam.py")
    exam_age = max((age for _, age in exam_procs), default=None)
    exams: list[dict[str, Any]] = []
    for p in sorted(logs.glob("exam-*.log"), key=lambda p: p.stat().st_mtime)[-4:]:
        text = p.read_text(errors="replace")
        ok, bad, done = parse_exam(text)
        quiet = now - p.stat().st_mtime
        if done:
            state = "done_ok" if bad == 0 and "SONUÇ: TÜM" in text else "done_fail"
        else:
            state = "silent" if quiet > SILENT_WARN_S else "running"
        eta, kind = estimate_exam(state, quiet, ok + bad, EXAM_STEPS, exam_age)
        exams.append({"name": p.stem, "ok": ok, "bad": bad, "total": EXAM_STEPS,
                      "state": state, "quiet_s": int(quiet), "eta_s": eta, "eta_kind": kind})  # fmt: skip
    gate_procs = running("check.py")
    live_gate = bool(gate_procs)
    gate_age = max((age for _, age in gate_procs), default=None)
    gates: list[dict[str, Any]] = []
    for p in sorted(logs.glob("check-*.log"), key=lambda p: p.stat().st_mtime)[-2:]:
        pct, done, summary = parse_pytest(p.read_text(errors="replace"))
        quiet = now - p.stat().st_mtime
        state = (
            "done"
            if done
            else (
                "silent"
                if live_gate and quiet > SILENT_WARN_S
                else ("running" if live_gate else "stale")
            )
        )
        gates.append({"name": p.stem, "pct": 100 if done else (pct or 0), "state": state, "summary": summary,
                      "eta_s": estimate_gate(state, pct or 0, gate_age)})  # fmt: skip
    fresh_exams = [
        e for e in exams if e["state"] in ("running", "silent") or e["quiet_s"] < ACTIVE_WINDOW_S
    ]
    fresh_gates = [
        g
        for g in gates
        if g["state"] in ("running", "silent")
        or g["pct"] < 100
        or now - (logs / (g["name"] + ".log")).stat().st_mtime < ACTIVE_WINDOW_S
    ]
    last_old = None
    olds = [e for e in exams if e not in fresh_exams]
    if olds:
        last_old = f"{olds[-1]['name']} ({fmt_dur(olds[-1]['quiet_s'])} önce)"
    return {"exams": fresh_exams, "gates": fresh_gates, "last_old_exam": last_old, "logs": str(logs),
            "procs": [{"pid": pid, "age_s": int(age)} for pid, age in exam_procs]}  # fmt: skip


def gate_progress(act: dict[str, Any], gates: list[dict[str, Any]]) -> None:
    """Claude kalite kapısını çalıştırıyorsa tahmin yerine testlerin gerçek ilerlemesi."""
    live = next((g for g in gates if g["state"] in ("running", "silent")), None)
    if live and act["state"] == "tool" and "check.py" in act["detail"]:
        act["progress"] = {"pct": live["pct"], "eta_s": live["eta_s"], "kind": "gerçek", "basis": 0}


def project_of(cwd: str) -> Path | None:
    """Adımları ve git geçmişi izlenen proje: klasörde BACKLOG.md varsa."""
    here = Path(cwd) if cwd else None
    return here if here and (here / "BACKLOG.md").exists() else None


def collect(project: Path | None, now: float | None = None) -> dict:  # type: ignore[type-arg]
    """Widget'ın verisi (JSON'a çevrilebilir). Arka planda seçili bir Claude oturumu varsa konuşma, adımlar ve
    git onun projesini izler; yoksa son oturumu ve verilen projeyi. Proje yoksa proje bölümleri boş gelir."""
    now = now or time.time()
    ekran = arka.screen()
    if ekran.get("cwd"):
        project = project_of(str(ekran["cwd"]))
    j = jobs(project, now)
    act = claude_activity(now, str(ekran.get("session") or "") or None)
    gate_progress(act, j["gates"])
    return {
        "activity": act,
        "metrics": _metrics(),
        "git": git_info(project) if project else {"branch": "", "commits": [], "today": 0, "dirty": False},
        "steps": project_steps(project) if project else {"total": 0, "done_n": 0, "done": [], "left": []},
        "time": time.strftime("%H:%M:%S", time.localtime(now)),
        "gpu": gpu(),
        "load": round(os.getloadavg()[0], 1),
        **j,
        "voice": voice_state(now),
        "arka": ekran,
        "projeler": arka.projects(),
        "testler": testler.listing(),
        "istek": testler.pop_request(),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proje", default="", help="adımları ve git geçmişi gösterilecek proje klasörü")
    ap.add_argument("--gpu", action="store_true", help="yalnızca ekran kartı (üst çubuk öğesi için)")
    a = ap.parse_args(argv)
    if a.gpu:
        print(json.dumps(gpu_details()))
        return 0
    print(json.dumps(collect(Path(a.proje).expanduser() if a.proje else None), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

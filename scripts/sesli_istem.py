#!/usr/bin/env python3
"""Sesli istem: konuşarak terminaldeki Claude Code oturumuna mesaj gönderir.

Masaüstü widget'ındaki mikrofon düğmesi `ac-kapa` ile çalıştırır. Birinci basış Dikte'de kaydı
yapıştırmadan başlatır; ikinci basış durdurur. Arka planda bekleyen süreç metni alır ve Claude Code'a
yazıp Enter'a basar: arka plandaki oturuma (bin/claude-arka, tmux) ya da o yoksa Konsole'da açık olana.
Claude o sırada çalışıyorsa mesaj sıraya girer.

Güvenlik: Claude bir onay penceresi ya da soruda bekliyorsa (oturum durumu "waiting") hiçbir şey
yazılmaz, Enter'a basılmaz: Enter bekleyen işlemi onaylayabilir. Metin panoya kopyalanır.

Widget'taki yazı kutusu da aynı yoldan gönderir: `yaz <yüzde-kodlu metin>` (kabukta tırnak derdi olmasın diye
metin URL biçiminde kodlanır).

Durum ~/.cache/claude-widget/sesli-istem.json dosyasında; veri.py bunu widget'a taşır.
Kullanım:  sesli_istem.py ac-kapa | yaz <metin> | iptal | durum | hedef
Dikte (github.com/yusufipk/dikte) kendi kurulumunun .desktop kaydından bulunur; DIKTE_DIR ile de verilebilir.
Dikte kurulu değilse mikrofon gösterilmez (available()).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import arka  # aynı klasörde: arka plandaki Claude (tmux)



def _find_dikte() -> Path | None:
    """Dikte'nin klasörü: DIKTE_DIR ya da Dikte'nin install.sh'inin yazdığı dikte.desktop'taki başlatma yolu."""
    if os.environ.get("DIKTE_DIR"):
        return Path(os.environ["DIKTE_DIR"]).expanduser()
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    try:
        for line in (data / "applications/dikte.desktop").read_text().splitlines():
            if line.startswith("Exec="):
                for part in line[5:].split():
                    if part.endswith("dikte/__main__.py"):
                        return Path(part).parent.parent
    except OSError:
        pass
    return None


DIKTE_DIR = _find_dikte()


def available() -> bool:
    return DIKTE_DIR is not None and (DIKTE_DIR / "dikte/ipc.py").exists()
STATE = Path.home() / ".cache/claude-widget/sesli-istem.json"
SESSIONS = Path.home() / ".claude/sessions"
WAIT_LIMIT_S = 420  # Dikte'nin en uzun kaydı (300 sn) + yazıya çevirme payı
SAFE = (
    "idle",
    "busy",
)  # Claude istem satırında ya da çalışıyor: yazılan metin istem kutusuna gider
ENTER_DELAY_S = 0.3  # metinle aynı parçada gelen Enter yapıştırılan satır sonu sayılır


def write_state(state: str, **extra: Any) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"state": state, "ts": time.time(), **extra}, ensure_ascii=False))
    tmp.replace(STATE)


def read_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def notify(title: str, body: str = "") -> None:
    subprocess.run(  # noqa: S603, S607
        ["notify-send", "-a", "Sesli istem", "-i", "audio-input-microphone", "-t", "5000", title, body],
        check=False, capture_output=True,
    )  # fmt: skip


def to_clipboard(text: str) -> None:
    subprocess.run(["wl-copy"], input=text, text=True, check=False, capture_output=True)  # noqa: S603, S607


def clean(text: str) -> str:
    """Tek satır: satır sonu istem kutusunda mesajı erken gönderir, denetim karakterleri tuş olur."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return " ".join(text.split())


def dikte(cmd: str, **args: Any) -> dict[str, Any] | None:
    """Çalışan Dikte'ye bir istek; Dikte kapalıysa (ya da kurulu değilse) None."""
    if not available():
        return None
    sys.path.insert(0, str(DIKTE_DIR))
    # Dikte'nin kendi deposundan ve sistemin PyQt6'sından; bu projenin ortamında yoklar.
    from dikte import ipc  # type: ignore[import-not-found]  # noqa: PLC0415
    from PyQt6.QtCore import QCoreApplication  # type: ignore[import-not-found]  # noqa: PLC0415

    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    reply = ipc.send(cmd, **args)
    return reply if isinstance(reply, dict) else None


def qdbus(*args: str) -> str:
    r = subprocess.run(["qdbus6", *args], capture_output=True, text=True, timeout=5, check=False)  # noqa: S603, S607
    return r.stdout.strip() if r.returncode == 0 else ""


def claude_sessions() -> dict[int, dict[str, Any]]:
    """Açık etkileşimli Claude Code oturumları, pid → ~/.claude/sessions/<pid>.json."""
    found: dict[int, dict[str, Any]] = {}
    for f in SESSIONS.glob("*.json"):
        try:
            info = json.loads(f.read_text())
            pid = int(info["pid"])
            alive = Path(f"/proc/{pid}/comm").read_text().strip() == "claude"
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if alive and info.get("kind") == "interactive":
            found[pid] = info
    return found


def session_status(pid: int) -> str:
    try:
        return str(json.loads((SESSIONS / f"{pid}.json").read_text()).get("status", ""))
    except (OSError, ValueError):
        return ""


def find_target() -> dict[str, Any] | None:
    """Claude Code'un ön planda çalıştığı Konsole oturumu; birden çoksa en son etkin olanı."""
    sessions = claude_sessions()
    if not sessions:
        return None
    targets = []
    for service in sorted(set(re.findall(r"org\.kde\.konsole-\d+", qdbus()))):
        for path in qdbus(service).splitlines():
            if not re.fullmatch(r"/Sessions/\d+", path):
                continue
            fg = qdbus(service, path, "org.kde.konsole.Session.foregroundProcessId")
            if fg.isdigit() and int(fg) in sessions:
                info = sessions[int(fg)]
                targets.append({"service": service, "path": path, "pid": int(fg),
                                "cwd": info.get("cwd", ""), "updated": info.get("updatedAt", 0)})  # fmt: skip
    return max(targets, key=lambda t: t["updated"]) if targets else None


def send_text(target: dict[str, Any], text: str) -> bool:
    """Konsole oturumuna yazar. Konsole'da 'güvenliğe duyarlı DBus API' kapalıysa AccessDenied döner;
    --print-reply olmadan dbus-send cevabı beklemez ve reddi de başarı sayar."""
    r = subprocess.run(  # noqa: S603, S607
        ["dbus-send", "--session", "--print-reply", "--type=method_call", f"--dest={target['service']}",
         target["path"], "org.kde.konsole.Session.sendText", f"string:{text}"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    return r.returncode == 0


def deliver(text: str) -> tuple[str, str]:
    """Metni Claude Code'a gönderir; (durum, açıklama). Önce arka plandaki oturum denenir."""
    if arka.running():
        code = arka.type_text(urllib.parse.quote(text, safe=""))
        if code == 0:
            return "gonderildi", ""
        to_clipboard(text)
        if code == 3:
            return "bekliyor", "Claude bir onay ya da cevap bekliyor; widget'taki tuşlarla cevap ver. Metin panoda."
        return "hata", "Arka plandaki Claude'a yazılamadı; metin panoda."
    target = find_target()
    if target is None:
        to_clipboard(text)
        return "hata", "Konsole'da açık Claude Code oturumu bulunamadı; metin panoda."
    status = session_status(target["pid"])
    if status not in SAFE:
        to_clipboard(text)
        return (
            "bekliyor",
            "Claude bir onay ya da cevap bekliyor; hiçbir şey yazılmadı, metin panoda.",
        )
    if not send_text(target, text):
        to_clipboard(text)
        return "hata", (
            "Konsole metni kabul etmedi; metin panoda. Konsole → Ayarlar → Konsole'u Yapılandır → Genel → "
            "'Güvenliğe duyarlı DBus API bölümlerini etkinleştir'"
        )
    time.sleep(ENTER_DELAY_S)
    if session_status(target["pid"]) not in SAFE:
        return "yazildi", "Metin yazıldı ama Claude bu arada bir onay istedi; Enter'a basılmadı."
    send_text(target, "\r")
    return "gonderildi", ""


def send_typed(encoded: str) -> int:
    """Widget'taki yazı kutusundan gelen metni gönderir."""
    text = clean(urllib.parse.unquote(encoded))
    if not text:
        return 2
    write_state("gonderiliyor", text=text)
    state, message = deliver(text)
    write_state(state, text=text, message=message)
    if message:
        notify("Claude'a yaz", message)
    return 0 if state == "gonderildi" else 1


def wait_and_send() -> int:
    """Kaydı başlatır ve bitmesini bekler (kim durdurursa durdursun), sonra metni gönderir."""
    reply = dikte("start", paste=False, wait=True, timeout=WAIT_LIMIT_S)
    if reply is None:
        write_state("hata", message="Dikte çalışmıyor")
        return 1
    if reply.get("cancelled"):
        write_state("iptal")
        return 0
    if not reply.get("ok"):
        write_state("hata", message=str(reply.get("error") or "kayıt yapılamadı"))
        notify("Sesli istem", str(reply.get("error") or "kayıt yapılamadı"))
        return 1
    text = clean(str(reply.get("text") or ""))
    if not text:
        write_state("bos", message="Ses algılanmadı")
        return 0
    write_state("gonderiliyor", text=text)
    state, message = deliver(text)
    write_state(state, text=text, message=message)
    if message:
        notify("Sesli istem", message)
    return 0 if state == "gonderildi" else 1


def waiter_alive(state: dict[str, Any]) -> bool:
    pid = state.get("pid")
    try:
        return isinstance(pid, int) and "sesli_istem" in Path(f"/proc/{pid}/cmdline").read_text()
    except OSError:
        return False


def toggle() -> int:
    status = dikte("status")
    if status is None:
        why = "Dikte çalışmıyor; önce Dikte'yi aç." if available() else "Dikte kurulu değil (github.com/yusufipk/dikte)."
        write_state("hata", message=why)
        notify("Sesli istem", why)
        return 1
    mine = read_state()
    if status.get("dictation") == "recording":
        if mine.get("state") == "kayit" and waiter_alive(mine):
            write_state("yaziliyor", pid=mine["pid"])
            dikte("stop")  # bekleyen süreç metni alıp gönderir
            return 0
        notify("Sesli istem", "Dikte şu an kendi kaydını yapıyor.")
        return 1
    if status.get("dictation") != "idle":
        notify("Sesli istem", "Dikte önceki kaydı bitiriyor, birazdan tekrar dene.")
        return 1
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(Path(__file__).resolve()), "_bekle"],
        start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    write_state("kayit", pid=proc.pid)
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "durum"
    if cmd == "ac-kapa":
        return toggle()
    if cmd == "_bekle":
        return wait_and_send()
    if cmd == "yaz":
        return send_typed(argv[2] if len(argv) > 2 else "")
    if cmd == "iptal":
        return 0 if dikte("cancel") is not None else 1
    if cmd == "hedef":
        print(json.dumps(find_target(), ensure_ascii=False))
        return 0
    if cmd == "durum":
        print(json.dumps(read_state(), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

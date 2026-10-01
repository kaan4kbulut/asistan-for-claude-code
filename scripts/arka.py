#!/usr/bin/env python3
"""claude-arka (bin/claude-arka bunu çağırır): Claude Code'u görünmez tmux oturumlarında çalıştırır; masaüstündeki
"Claude" widget'ı seçili oturumun ekranını gösterir ve ona yazar. Açık bir terminal penceresi gerekmez.

Her proje ya da sohbet ayrı bir arka plan oturumudur ("claude-1", "claude-2"...): birine geçmek ötekini kapatmaz,
Claude birinde çalışırken başka bir projeye bakılabilir. Widget'ın gösterdiği, "seçili" olandır.

Komutlar:
  liste                 arka plan oturumları, seçili olan ve projeler (json)
  gec KLASÖR KİMLİK|yeni [SÜTUN SATIR]
                        o sohbeti (ya da o klasörde yeni bir sohbeti) arka planda açar ve seçer;
                        zaten açıksa yalnızca seçer
  sec AD                açık bir arka plan oturumunu seçer
  kapat [AD]            oturumu kapatır (varsayılan: seçili)
  terminal              seçili oturumu bir Konsole penceresinde gösterir (kapatınca arka planda sürer)
  calisiyor             seçili bir oturum açıksa 0
  ekran                 seçili oturumun o anki görüntüsü, renkli HTML (json)
  boyut SÜTUN SATIR     terminal boyutu (widget'ın genişliğine göre); bir pencere bağlıyken dokunmaz
  yaz METİN             yüzde kodlu metni seçili oturuma yazar ve Enter'a basar
  tus TUŞ...            esc, enter, up, down, btab, tab, ctrl-c, 1..9
  gir PARÇA...          widget terminaline klavyeyle yazılanlar, olduğu gibi: t.METİN (yüzde kodlu),
                        k.TUŞ (tmux adı: Enter, BSpace, C-c…), p.METİN (yapıştırma)
  adlandir KİMLİK [AD]  sohbetin Asistan'daki adı (yüzde kodlu; boşsa Claude'un başlığına döner); Claude'a sohbet
                        bir sonraki açılışında bu adla verilir
  tasi KİMLİK PROJE|-   sohbeti Asistan'da başka bir projenin altında göster (- : kendi projesine dön)
  gizle KİMLİK evet|hayir
                        sohbeti listelerden gizle ya da geri getir
  sil KİMLİK            sohbeti çöp kutusuna taşır (geri alınabilir); açıksa 5
  guven evet|hayir [AD] "bu klasöre güveniyor musun" sorusunu cevaplar (hayır: oturumu kapatır); AD verilirse
                        o oturumda (widget ekranda gördüğünü verir), yoksa seçili olanda

Güvenlik: Claude bir onay penceresinde ya da soruda bekliyorsa (oturum durumu "waiting") `yaz` hiçbir şey
yazmaz: yazılan harfler seçenek seçebilir, Enter bekleyen işlemi onaylayabilir. Cevap `tus` ile verilir.
`gir` bu denetimi yapmaz: kullanıcı ekranı görerek yazar, gerçek bir terminaldeki gibi.
Aynı sohbet iki süreçte açılmaz (kayıt karışır): başka bir terminalde açık olan sohbete geçilmez.
Klasöre güven sorusu Claude'un durum dosyasından önce gelir (durum boş kalır); ekrandan tanınır. Ev klasörü
için Claude cevabı kaydetmez, soru her açılışta gelir.
Sohbet kimliği de durum dosyasıyla gelir; o zamana kadar oturumun hangi sohbeti açtığı tmux'taki başlatma komutundan
(--resume) okunur: güven sorusundayken Oturum'a yeniden basmak aynı sohbeti ikinci kez açmaz.
Oturumlar Claude'da da Asistan'daki başlıklarıyla adlandırılır (--name): istem kutusu, /resume listesi, Telegram.
Çıkış kodları: 0 tamam, 1 güven sorusu cevaplanamadı, 2 kullanım hatası, 3 Claude bekliyor, 4 oturum kapalı,
5 o sohbet başka bir terminalde ya da sekmede açık (önce onu kapat), 6 ekranda güven sorusu yok.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import string
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import ayarlar  # ~/.config/asistan: projeler, görünen adlar (kişisel bilgi kodda değil)

PREFIX = "claude"
HOME = Path.home()
STATE = HOME / ".local/state/claude-arka"
CACHE = HOME / ".cache/claude-widget/projeler.json"
SESSIONS = HOME / ".claude/sessions"
PROJECTS = HOME / ".claude/projects"
GENEL = "🏠 Genel"  # ev klasöründe açılan, hiçbir projeye ayrılmayan sohbetlerin oturumu
SAFE = ("idle", "busy")
INTERACTIVE = ("cli", "claude-vscode")  # sdk-cli / sdk-ts: başka programların arka plan işleri, listelenmez
TEMP_DIRS = ("/tmp",)  # buralarda açılmış sohbetler geçici denemelerdir, listelenmez
ENTER_DELAY_S = 0.3  # metinle aynı parçada gelen Enter yapıştırılmış satır sonu sayılır
KEYS = {"esc": "Escape", "enter": "Enter", "up": "Up", "down": "Down", "btab": "BTab", "tab": "Tab",
        "ctrl-c": "C-c", **{str(n): str(n) for n in range(1, 10)}}  # fmt: skip
# `gir` ile gönderilebilen tmux tuş adları (M-Enter: Claude Code'da yeni satır)
KEY_NAMES = {"Enter", "M-Enter", "Escape", "BSpace", "Tab", "BTab", "Up", "Down", "Left", "Right", "Home", "End",
             "PPage", "NPage", "DC", *(f"C-{c}" for c in string.ascii_lowercase)}  # fmt: skip
TRUST_YES = "Yes, I trust this folder"
_RESUME = re.compile(r"--resume\s+([0-9a-f-]{36})")


def tmux(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tmux", *args], input=stdin, capture_output=True, text=True, check=False)  # noqa: S603, S607


def _hex(text: str) -> list[str]:
    """send-keys -H için baytlar. -l kullanılmaz: tmux, ';' ile biten argümanı komut ayracı sayıp yutar."""
    return [f"{b:02x}" for b in text.encode()]


def _live_claude(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip() == "claude"
    except OSError:
        return False


def _claude_pid(pane_pid: str) -> str:
    """Sekmedeki Claude süreci. tmux tek parçalı komutu (yeni sohbet: yalnızca `claude`) kabukla çalıştırır
    (`fish -c claude`): o zaman sekmenin süreci kabuktur, Claude onun çocuğudur; durum dosyası Claude'un numarasıyla."""
    if not pane_pid.isdigit() or _live_claude(int(pane_pid)):
        return pane_pid
    try:
        kids = Path(f"/proc/{pane_pid}/task/{pane_pid}/children").read_text().split()
    except OSError:
        kids = []
    return next((k for k in kids if _live_claude(int(k))), pane_pid)


def _info(pid: str) -> dict[str, Any]:
    try:
        return dict(json.loads((SESSIONS / f"{pid}.json").read_text()))
    except (OSError, ValueError):
        return {}


def sessions() -> list[dict[str, Any]]:
    """Açık arka plan oturumları. Claude'u kapanmış (/exit) olanlar temizlenir."""
    r = tmux("list-panes", "-a", "-F",
             "#{session_name}\t#{pane_pid}\t#{pane_dead}\t#{session_attached}\t#{pane_current_path}\t"
             "#{pane_start_command}")  # fmt: skip
    out = []
    for line in r.stdout.splitlines():
        name, pid, dead, attached, path, start = (line.split("\t", 5) + [""] * 6)[:6]
        if not name.startswith(PREFIX):
            continue
        if dead == "1":
            tmux("kill-session", "-t", name)
            continue
        pid = _claude_pid(pid)
        info = _info(pid)  # Claude ilk soruyu (klasöre güven) geçene kadar durum dosyası yazmaz
        cwd = str(info.get("cwd") or path)
        resumed = _RESUME.search(start)
        out.append({"name": name, "pid": pid, "attached": attached not in ("", "0"),
                    "session": info.get("sessionId", ""), "status": info.get("status", ""),
                    "resume": resumed.group(1) if resumed else "",  # durum dosyası yokken de hangi sohbet
                    "cwd": cwd, "project": _project_name(cwd)})  # fmt: skip
    return out


def selected(live: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    live = sessions() if live is None else live
    try:
        want = (STATE / "secili").read_text().strip()
    except OSError:
        want = ""
    return next((s for s in live if s["name"] == want), live[0] if live else None)


def _pick(name: str = "") -> dict[str, Any] | None:
    """Adı verilen oturum (widget ekranda gördüğünü verir); ad yoksa seçili olan."""
    live = sessions()
    return next((s for s in live if s["name"] == name), None) if name else selected(live)


def select(name: str) -> int:
    if not any(s["name"] == name for s in sessions()):
        return 4
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "secili").write_text(name)
    return 0


def open_elsewhere(session_id: str) -> bool:
    """Bu sohbet şu an arka plan dışında bir Claude sürecinde (ör. bir Konsole penceresinde) açık mı."""
    ours = {s["pid"] for s in sessions()}
    for f in SESSIONS.glob("*.json"):
        try:
            info = json.loads(f.read_text())
            pid = int(info["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if str(pid) not in ours and info.get("sessionId") == session_id and _live_claude(pid):
            return True
    return False


def go(cwd: str, session_id: str, cols: int = 80, rows: int = 40) -> int:
    """O sohbeti (ya da "yeni") arka planda açar ve seçer; açıksa yalnızca seçer."""
    live = sessions()
    if session_id != "yeni":  # güven sorusundaki oturumun kimliği henüz yok: başlatma komutundan bakılır
        same = next((s for s in live if session_id in (s["session"], s["resume"])), None)
        if same:
            return select(same["name"])
        if open_elsewhere(session_id):
            return 5
    folder = Path(urllib.parse.unquote(cwd)).expanduser()  # widget yolu yüzde kodlu verir
    if not folder.is_dir():
        return 2
    used = {s["name"] for s in live} | set(tmux("list-sessions", "-F", "#{session_name}").stdout.split())
    name = next(f"{PREFIX}-{n}" for n in range(1, 100) if f"{PREFIX}-{n}" not in used)
    claude = shutil.which("claude") or str(HOME / ".local/bin/claude")
    args = [claude] if session_id == "yeni" else [claude, "--resume", session_id]
    title = "" if session_id == "yeni" else session_title(session_id)
    if title:  # Claude da sohbeti Asistan'daki başlığıyla adlandırsın (yoksa "klasör-ff" gibi rastgele bir ad verir)
        args += ["--name", title]
    # Widget komutları plasmashell'in cgroup'unda çalışır; tmux sunucusu orada başlarsa Plasma yeniden başlatılınca
    # (ya da çökünce) bütün arka plan oturumları ölür. Sunucu kendi systemd kapsamında başlasın.
    scope = shutil.which("systemd-run")
    launcher = [scope, "--user", "--scope", "--quiet", "--collect", "--"] if scope else []
    subprocess.run(  # noqa: S603
        [*launcher, "tmux", "new-session", "-d", "-s", name, "-x", str(cols), "-y", str(rows), "-c", str(folder),
         "-e", "COLORTERM=truecolor", "--", *args],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    # Durum çubuğu ekran görüntüsüne karışmasın; boyutu bağlı bir pencere değil widget belirlesin.
    tmux("set-option", "-t", name, "status", "off")
    tmux("set-option", "-t", name, "window-size", "manual")
    tmux("set-option", "-t", name, "history-limit", "5000")
    for _ in range(25):
        if any(s["name"] == name for s in sessions()):
            return select(name)
        time.sleep(0.2)
    return 1


def stop(name: str = "") -> int:
    target = name or (selected() or {}).get("name", "")
    if not target.startswith(PREFIX):
        return 4
    tmux("kill-session", "-t", target)
    return 0


def prepare_client(name: str) -> None:
    """Bir istemci (Asistan programı ya da terminal penceresi) bağlanmadan önce: pencere boyutunu bağlanan belirlesin;
    tmux'un önek tuşu olmasın (Ctrl+B Claude Code'a gitsin: orada komutu arka plana alır); Claude'un panoya
    kopyaladığı (OSC 52) istemcinin panosuna ulaşsın."""
    tmux("set-option", "-t", name, "window-size", "latest", ";", "set-option", "-t", name, "prefix", "None", ";",
         "set-option", "-t", name, "prefix2", "None", ";", "set-option", "-s", "set-clipboard", "on")  # fmt: skip


def attach_terminal() -> int:
    cur = selected()
    if cur is None:
        return 4
    prepare_client(cur["name"])
    subprocess.Popen(  # noqa: S603, S607
        ["konsole", "--separate", "--profile", "Claude", "-p", f"tabtitle=Claude · {cur['project']}",
         "-e", "tmux", "attach", "-t", cur["name"]],
        start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    return 0


def resize(cols: int, rows: int) -> int:
    cur = selected()
    if cur is None:
        return 4
    if cur["attached"]:  # bir pencerede açıkken boyutu o belirler
        return 0
    tmux("set-option", "-t", cur["name"], "window-size", "manual")
    tmux("resize-window", "-t", cur["name"], "-x", str(max(cols, 40)), "-y", str(max(rows, 10)))
    return 0


def running() -> bool:
    return selected() is not None


def type_text(encoded: str) -> int:
    text = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", urllib.parse.unquote(encoded)).split())
    if not text:
        return 2
    cur = selected()
    if cur is None:
        return 4
    if cur["status"] not in SAFE:
        return 3
    tmux("send-keys", "-t", cur["name"], "-H", *_hex(text))
    time.sleep(ENTER_DELAY_S)
    if _info(cur["pid"]).get("status") not in SAFE:  # bu arada bir onay penceresi açıldıysa Enter'a basma
        return 3
    tmux("send-keys", "-t", cur["name"], "Enter")
    return 0


def press(names: list[str], target: str = "") -> int:
    keys = [KEYS[n] for n in names if n in KEYS]
    if not keys:
        return 2
    cur = _pick(target)
    if cur is None:
        return 4
    tmux("send-keys", "-t", cur["name"], *keys)
    return 0


def send_message(text: str, target: str = "") -> int:
    """Telefondan (Telegram) gelen mesajı oturuma yazıp gönderir: satır sonları korunur (köşeli yapıştırma), sonra
    Enter. Claude bir onay penceresinde ya da soruda bekliyorsa hiçbir şey yazmaz (3): yazılan harfler seçenek
    seçebilir. Claude çalışırken yazılan mesajı Claude Code sıraya alır, iş bitince işler."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text).strip()
    if not text:
        return 2
    cur = _pick(target)
    if cur is None:
        return 4
    if cur["status"] not in SAFE:
        return 3
    if "\n" in text:
        tmux("load-buffer", "-b", "claude-telefon", "-", stdin=text)
        tmux("paste-buffer", "-b", "claude-telefon", "-p", "-d", "-t", cur["name"])
    else:
        tmux("send-keys", "-t", cur["name"], "-H", *_hex(text))
    time.sleep(ENTER_DELAY_S)
    if _info(cur["pid"]).get("status") not in SAFE:  # bu arada bir onay penceresi açıldıysa Enter'a basma
        return 3
    tmux("send-keys", "-t", cur["name"], "Enter")
    return 0


def plain_screen(target: str = "", lines: int = 40) -> str:
    """Oturumun o anki ekranı düz yazı olarak (telefona göndermek için): sondaki boş satırlar atılır."""
    cur = _pick(target)
    if cur is None:
        return ""
    rows = [ln.rstrip() for ln in _plain(cur["name"]).splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return "\n".join(rows[-lines:])


def feed(tokens: list[str]) -> int:
    """Widget terminaline klavyeyle yazılanları sırasıyla gönderir (t.METİN, k.TUŞ, p.YAPIŞTIRILAN)."""
    cur = selected()
    if cur is None:
        return 4
    name = cur["name"]
    cmds: list[str] = []  # tek tmux çağrısı: komutlar ";" ile ayrılır
    for tok in tokens:
        kind, _, val = tok.partition(".")
        if kind == "t":
            data = re.sub(r"[\x00-\x1f\x7f]", "", urllib.parse.unquote(val))
            if data:
                cmds += [*([";"] if cmds else []), "send-keys", "-t", name, "-H", *_hex(data)]
        elif kind == "k" and val in KEY_NAMES:
            cmds += [*([";"] if cmds else []), "send-keys", "-t", name, val]
        elif kind == "p":  # yapıştırma: satır sonları Enter sayılmasın diye köşeli yapıştırma (-p)
            if cmds:
                tmux(*cmds)
                cmds = []
            tmux("load-buffer", "-b", "claude-widget", "-", stdin=urllib.parse.unquote(val))
            tmux("paste-buffer", "-b", "claude-widget", "-p", "-d", "-t", name)
    if cmds:
        tmux(*cmds)
    return 0


def _plain(name: str) -> str:
    return tmux("capture-pane", "-p", "-t", name).stdout


def _trust_prompt(plain: str) -> bool:
    return TRUST_YES in plain and "Enter to confirm" in plain


def _cursor_line(name: str) -> str:
    return next((ln for ln in _plain(name).splitlines() if ln.lstrip().startswith("❯")), "")


def _wait(ok: Any, timeout_s: float, steady: int = 1) -> bool:
    """ok() art arda `steady` yoklamada doğru olana dek bekler."""
    hits, end = 0, time.monotonic() + timeout_s
    while time.monotonic() < end:
        hits = hits + 1 if ok() else 0
        if hits >= steady:
            return True
        time.sleep(0.15)
    return False


def answer_trust(yes: bool, name: str = "") -> int:
    """Klasöre güven sorusu ("No, exit" önde gelir). Oklar başa sarar, rakamlar çalışmaz; Claude açılırken (büyük
    bir sohbeti yüklerken) ekranı saniyelerce geç çizebilir. Bu yüzden ↓ tek kez basılır ve Enter ancak ekran
    "evet"i art arda gösterince gider: ekrana bakıp yeniden ↓ basmak imleci "hayır"a geri götürüp Claude'u kapatabilir."""
    cur = _pick(name)
    if cur is None:
        return 4
    target = cur["name"]
    if not _trust_prompt(_plain(target)):
        return 6
    if not yes:
        return stop(target)
    if cur["resume"] and any(cur["resume"] == s["session"] for s in sessions() if s["name"] != target):
        return 5  # aynı sohbet başka bir sekmede zaten açık: ikinci kopya kayıtları karıştırır
    if TRUST_YES not in _cursor_line(target):
        tmux("send-keys", "-t", target, "Down")
    if not _wait(lambda: TRUST_YES in _cursor_line(target), 8.0, steady=2):
        return 1
    tmux("send-keys", "-t", target, "Enter")
    _wait(lambda: not _trust_prompt(_plain(target)), 3.0)
    return 0


# ── projeler ve sohbetleri ───────────────────────────────────────────────────────────────────
# Klasör adı yerine gösterilen proje adları (kullanıcı: "çok alakasız isimlendirmeler … anlaşılır şekilde")

def _project_name(cwd: str) -> str:
    if not cwd:
        return ""
    if cwd == str(HOME):
        return GENEL
    name = Path(cwd).name
    return ayarlar.adlar().get(name, name)


def _ai_title(path: Path, tail: int = 512 * 1024) -> str:
    """Claude Code'daki başlık (/resume listesindeki): kullanıcının /rename ile verdiği ("custom-title") varsa o,
    yoksa Claude'un verdiği kısa başlık ("ai-title"); ikisi de dosyanın sonundaki en yeni kayıttan."""
    try:
        own = json.loads((path.with_suffix("") / "custom-title.json").read_text()).get("customTitle")
        if own:
            return str(own).strip()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with path.open("rb") as fh:
            fh.seek(max(0, path.stat().st_size - tail))
            chunk = fh.read().decode(errors="ignore")
    except OSError:
        return ""
    ai = ""
    for line in reversed(chunk.splitlines()):
        if '"custom-title"' in line or (not ai and '"ai-title"' in line):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "custom-title" and e.get("customTitle"):
                return str(e["customTitle"]).strip()
            ai = ai or str(e.get("aiTitle") or "").strip()
    return ai


def _typed(text: str) -> bool:
    t = text.strip()
    return bool(t) and not t.startswith(("<", "Caveat:", "This session is being continued"))


_PASTED = re.compile(r"</?pasted_content[^>]*>")


def _head(path: Path) -> dict[str, str]:
    """Bir sohbetin başı: nereden açıldığı (entrypoint), klasörü ve ilk istemi (başlık)."""
    found = {"entrypoint": "", "cwd": "", "title": ""}
    with path.open(errors="ignore") as fh:
        for i, line in enumerate(fh):
            if i > 400 or (found["entrypoint"] and found["cwd"] and found["title"]):
                break
            if len(line) > 60_000:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            found["entrypoint"] = found["entrypoint"] or str(e.get("entrypoint") or "")
            found["cwd"] = found["cwd"] or str(e.get("cwd") or "")
            if not found["title"] and e.get("type") == "user" and not e.get("isMeta"):
                c = (e.get("message") or {}).get("content")
                text = c if isinstance(c, str) else " ".join(
                    str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("type") == "text"
                ) if isinstance(c, list) else ""
                text = _PASTED.sub("", text)  # yapıştırılmış metinle açılan sohbet: başlık onun ilk satırı
                if _typed(text):
                    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
                    found["title"] = first[:80]
    return found


def session_title(session_id: str) -> str:
    """Sohbetin Asistan'daki başlığı: Asistan'da verilen ad, Claude'daki başlık, yoksa ilk istem."""
    own = str(ayarlar.sohbet(session_id).get("baslik") or "")
    if own:
        return own
    f = next(PROJECTS.glob(f"*/{session_id}.jsonl"), None)
    if f is None:
        return ""
    try:
        return _ai_title(f) or _head(f)["title"]
    except OSError:
        return ""


# Asistan'daki projeler: (kimlik, ad, yeni sohbetin açılacağı klasör, o projeye sayılan klasörler, içerik izleri).
# Kullanıcı: "genel oturumlarını projelerin oturumlarının hepsini ayrı ayrı ayır oturumların hepsi her klasöre bağlı
# olmasın". Proje klasöründe açılmış sohbet o projenindir; ev klasöründe açılmış sohbet, Claude'un içinde en çok hangi
# projenin dosyalarıyla çalıştığına göre (izler, eski yollar dahil) o projeye ayrılır, belirgin değilse Genel'de kalır.
# Açarken sohbet yine kendi klasöründe sürdürülür (Claude sohbeti klasörüne göre bulur).
SCAN_CAP = 32 * 1024 * 1024  # bir yenilemede bir sohbetten okunacak en çok yeni bayt


def _folder(folder: str) -> Path:
    """Projenin klasörü: tam yol ya da proje köküne (yoksa ev klasörüne) göre."""
    p = Path(folder).expanduser()
    return p if p.is_absolute() else (ayarlar.proje_koku() or HOME) / p


def _hidden_dir(cwd: str) -> bool:
    """Ayarlarda yok sayılan bir proje klasöründe mi (ör. Arşiv); o sohbetler hiçbir listede görünmez."""
    root = ayarlar.proje_koku()
    if not root or not cwd:
        return False
    try:
        rel = Path(cwd).relative_to(root)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in set(ayarlar.oku().get("yok_say", []))


def _family_of_dir(cwd: str) -> str:
    """Klasörün ait olduğu proje ("" = ev klasörü, içeriğine göre ayrılır). Proje kökü ayarlıysa altındaki ilk
    klasör projedir; değilse (ayarsız kurulum) sohbetin açıldığı klasörün kendisi bir projedir."""
    if not cwd or cwd == str(HOME):
        return ""
    fams = ayarlar.aileler()
    root = ayarlar.proje_koku()
    if root:
        try:
            rel = Path(cwd).relative_to(root)
        except ValueError:
            rel = None
        if rel is not None:
            top = rel.parts[0] if rel.parts else ""
            skip = set(ayarlar.oku().get("yok_say", []))
            return next((fid for fid, _, _, dirs, _ in fams if top in dirs), top if top and top not in skip else "")
    name = Path(cwd).name
    return next((fid for fid, _, _, dirs, _ in fams if name in dirs), cwd)


def _count_hints(path: Path, h: dict[str, Any]) -> None:
    """Sohbetin yeni eklenen kısmında Claude'un (assistant satırları) hangi projeye ne kadar değindiğini sayar."""
    hits: dict[str, int] = h.setdefault("hits", {})
    off = int(h.get("off", 0))
    try:
        with path.open("rb") as fh:
            fh.seek(off)
            data = fh.read(SCAN_CAP)
    except OSError:
        return
    end = data.rfind(b"\n") + 1  # yalnızca tamamlanmış satırlar
    for raw in data[:end].split(b"\n"):
        if b'"type":"assistant"' not in raw:
            continue
        line = raw.decode(errors="ignore")
        for fid, _, _, _, hints in ayarlar.aileler():
            n = sum(line.count(x) for x in hints)
            if n:
                hits[fid] = hits.get(fid, 0) + n
    h["off"] = off + end


def _family_of_session(h: dict[str, Any]) -> str:
    hits = h.get("hits", {})
    total = sum(hits.values())
    if not total:
        return ""
    fid, n = max(hits.items(), key=lambda kv: kv[1])
    return fid if n >= 5 and n / total >= 0.6 else ""


def projects(per_project: int = 8, max_age_s: float = 20.0, gizliler: bool = False) -> list[dict[str, Any]]:
    """Genel ve projeler (sohbeti olmayan projeler de: yeni sohbet açılabilsin); her birinin son sohbetleri.
    Asistan'daki sohbet ayarları (ad, proje, gizli: ayarlar.sohbetler) önbellekten sonra uygulanır, anında görünür;
    gizlenenler yalnızca gizliler=True ile gelir ("gizli": True işaretiyle)."""
    try:
        cached = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cached = {}
    heads: dict[str, Any] = cached.get("heads", {})
    if time.time() - float(cached.get("t", 0)) < max_age_s and "projects" in cached and cached.get("v") == 4:
        projs: list[dict[str, Any]] = cached["projects"]
    else:
        groups: dict[str, list[dict[str, Any]]] = {}
        for f in PROJECTS.glob("*/*.jsonl"):
            try:
                st = f.stat()
            except OSError:
                continue
            key = str(f)
            h = heads.get(key)
            if not h or h.get("mtime") != st.st_mtime and not h.get("title"):
                h = {**_head(f), "mtime": st.st_mtime, **{k: h[k] for k in ("off", "hits", "ai") if h and k in h}}
                heads[key] = h
            if h.get("mtime") != st.st_mtime or "ai" not in h:  # başlık sohbet ilerledikçe güncellenir
                h["ai"] = _ai_title(f) or h.get("ai", "")
            h["mtime"] = st.st_mtime
            if h["entrypoint"] not in INTERACTIVE or not h["cwd"] or h["cwd"].startswith(TEMP_DIRS):
                continue
            if not Path(h["cwd"]).is_dir():  # silinmiş ya da taşınmış klasör: açılamaz
                continue
            if not h["title"] and st.st_size < 20_000:  # hiç mesaj yazılmadan kapatılmış boş sohbet
                continue
            if _hidden_dir(h["cwd"]):
                continue
            fam = _family_of_dir(h["cwd"])
            if not fam:  # ev klasöründe (ya da başka yerde) açılmış: içeriğine göre ayır
                if int(h.get("off", 0)) < st.st_size:
                    _count_hints(f, h)
                fam = _family_of_session(h)
            groups.setdefault(fam, []).append({"id": f.stem, "title": h.get("ai") or h["title"] or "(başlıksız)",
                                                "mtime": st.st_mtime, "cwd": h["cwd"]})  # fmt: skip
        fams, root = ayarlar.aileler(), ayarlar.proje_koku()
        skip = set(ayarlar.oku().get("yok_say", []))
        known = [(fid, name, str(_folder(folder))) for fid, name, folder, _, _ in fams if _folder(folder).is_dir()]
        family_dirs = {d for _, _, _, dirs, _ in fams for d in dirs}
        if root and root.is_dir():  # proje kökünde listede olmayan yeni projeler
            known += [(d.name, _project_name(str(d)), str(d)) for d in sorted(root.iterdir())
                      if d.is_dir() and not d.name.startswith(".") and d.name not in skip and d.name not in family_dirs]  # fmt: skip
        ids = {k[0] for k in known}
        known += [(fid, _project_name(fid), fid) for fid in groups if fid.startswith("/") and fid not in ids]  # ayarsız
        seen: set[str] = set()
        projs = []
        for fid, name, cwd in [("", GENEL, str(HOME)), *known]:
            if fid in seen:
                continue
            seen.add(fid)
            items = sorted(groups.get(fid, []), key=lambda x: -x["mtime"])
            projs.append({"id": fid or "genel", "name": name, "cwd": cwd, "mtime": items[0]["mtime"] if items else 0,
                          "sessions": items})  # fmt: skip
        projs.sort(key=lambda p: -p["mtime"])
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps({"v": 4, "t": time.time(), "projects": projs, "heads": heads}))
        except OSError:
            pass
    projs = _apply_overrides(projs, gizliler, per_project)
    # Hangi sohbet nerede açık: arka planda mı, bir terminalde mi (bu, önbellekten bağımsız her seferinde)
    ours = {s["session"]: s["name"] for s in sessions()}
    elsewhere = set()
    for f in SESSIONS.glob("*.json"):
        try:
            info = json.loads(f.read_text())
            if _live_claude(int(info["pid"])) and info.get("sessionId") not in ours:
                elsewhere.add(info.get("sessionId"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for p in projs:
        for s in p["sessions"]:
            s["where"] = "arka" if s["id"] in ours else "terminal" if s["id"] in elsewhere else ""
    return projs


def _apply_overrides(projs: list[dict[str, Any]], gizliler: bool, per_project: int) -> list[dict[str, Any]]:
    """Asistan'da verilen adlar, taşımalar ve gizlemeler; ardından projeler yine son kullanıma göre sıralanır."""
    ov = ayarlar.sohbetler()
    byid = {p["id"]: p for p in projs}
    moved: list[tuple[str, dict[str, Any]]] = []
    for p in projs:
        keep = []
        for s in p["sessions"]:
            o = ov.get(s["id"], {})
            s = dict(s)
            if o.get("baslik"):
                s["title"], s["adlandirildi"] = str(o["baslik"]), True
            if o.get("gizli"):
                s["gizli"] = True
            if (o.get("gizli") and not gizliler):
                continue
            hedef = str(o.get("proje") or "")
            if hedef and hedef != p["id"] and hedef in byid:
                s["tasindi"] = True
                moved.append((hedef, s))
                continue
            keep.append(s)
        p["sessions"] = keep
    for hedef, s in moved:
        byid[hedef]["sessions"].append(s)
    for p in projs:
        p["sessions"] = sorted(p["sessions"], key=lambda x: -x["mtime"])[:per_project]
        p["mtime"] = max((x["mtime"] for x in p["sessions"]), default=0)
    projs.sort(key=lambda p: -p["mtime"])
    return projs


def _invalidate_projects() -> None:
    """Proje önbelleğini eskit (sohbet silinince listeden hemen düşsün); başlık önbelleği korunur."""
    try:
        cached = json.loads(CACHE.read_text())
        cached["t"] = 0
        CACHE.write_text(json.dumps(cached))
    except (OSError, ValueError):
        pass



def rename(session_id: str, title: str) -> int:
    """Sohbetin Asistan'daki adı (boşsa Claude'un başlığına döner): program, widget ve Telegram'da hemen görünür;
    Claude'a sohbet bir sonraki açılışında --name ile verilir. Açık oturuma /rename yazılmaz: istem kutusu kullanıcının,
    Telegram'ın ve diktenin ortak girişidir, araya yazılan komut bir mesaja karışabilir."""
    title = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", title).split())[:80]
    ayarlar.sohbet_ayarla(session_id, baslik=title or None)
    return 0


def _trash(path: Path) -> bool:
    gio = shutil.which("gio")
    if gio:
        return subprocess.run([gio, "trash", str(path)], capture_output=True, check=False).returncode == 0  # noqa: S603
    trash = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "Trash"
    (trash / "files").mkdir(parents=True, exist_ok=True)
    (trash / "info").mkdir(parents=True, exist_ok=True)
    dest = trash / "files" / path.name
    n = 1
    while dest.exists():
        dest = trash / "files" / f"{path.stem}.{n}{path.suffix}"
        n += 1
    (trash / "info" / f"{dest.name}.trashinfo").write_text(
        f"[Trash Info]\nPath={urllib.parse.quote(str(path))}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    shutil.move(str(path), dest)
    return True


def trash_session(session_id: str) -> int:
    """Sohbeti çöp kutusuna taşır (geri alınabilir). Açıksa dokunmaz: 5; bulunamazsa 4; taşınamazsa 1."""
    if any(session_id in (s["session"], s["resume"]) for s in sessions()) or open_elsewhere(session_id):
        return 5
    f = next(PROJECTS.glob(f"*/{session_id}.jsonl"), None)
    if f is None:
        return 4
    for t in [f, *([f.with_suffix("")] if f.with_suffix("").is_dir() else [])]:
        if not _trash(t):
            return 1
    ayarlar.sohbet_ayarla(session_id, baslik=None, proje=None, gizli=None)
    _invalidate_projects()
    return 0


# ── ekran: ANSI renkleri → HTML ─────────────────────────────────────────────────────────────
BASIC = ["#1C1B19", "#E5484D", "#4EBA65", "#E0B34F", "#5B8DEF", "#C678DD", "#56B6C2", "#D9D6D0",
         "#6E6B66", "#FF6B6F", "#6FD48A", "#F5CC6B", "#7EA8FF", "#D98FEF", "#76D0DB", "#FFFFFF"]  # fmt: skip
_SGR = re.compile(r"\x1b\[([0-9;:]*)m")
_OTHER = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-ln-z]")


def _xterm(n: int) -> str:
    if n < 16:
        return BASIC[n]
    if n >= 232:
        v = 8 + (n - 232) * 10
        return f"#{v:02x}{v:02x}{v:02x}"
    n -= 16
    steps = [0, 95, 135, 175, 215, 255]
    return f"#{steps[n // 36]:02x}{steps[n // 6 % 6]:02x}{steps[n % 6]:02x}"


def _apply(codes: list[int], st: dict[str, Any]) -> None:
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            st.update(fg=None, bg=None, bold=False, dim=False, italic=False, under=False, inverse=False)
        elif c in (1, 2, 3, 4, 7):
            st[{1: "bold", 2: "dim", 3: "italic", 4: "under", 7: "inverse"}[c]] = True
        elif c == 22:
            st["bold"] = st["dim"] = False
        elif c in (23, 24, 27):
            st[{23: "italic", 24: "under", 27: "inverse"}[c]] = False
        elif 30 <= c <= 37 or 90 <= c <= 97:
            st["fg"] = BASIC[c - 30 if c < 90 else c - 82]
        elif 40 <= c <= 47 or 100 <= c <= 107:
            st["bg"] = BASIC[c - 40 if c < 100 else c - 92]
        elif c in (39, 49):
            st["fg" if c == 39 else "bg"] = None
        elif c in (38, 48) and i + 1 < len(codes):
            key = "fg" if c == 38 else "bg"
            if codes[i + 1] == 5 and i + 2 < len(codes):
                st[key] = _xterm(codes[i + 2])
                i += 2
            elif codes[i + 1] == 2 and i + 4 < len(codes):
                r, g, b = codes[i + 2 : i + 5]
                st[key] = f"#{r:02x}{g:02x}{b:02x}"
                i += 4
        i += 1


def to_html(text: str, fg: str = "#E8E5DF", bg: str = "#1C1B19") -> str:
    st: dict[str, Any] = {"fg": None, "bg": None, "bold": False, "dim": False, "italic": False,
                          "under": False, "inverse": False}  # fmt: skip
    out: list[str] = []
    text = _OTHER.sub("", text)
    pos = 0
    for m in [*_SGR.finditer(text), None]:
        chunk = text[pos : m.start() if m else len(text)]
        if chunk:
            f, b = st["fg"] or fg, st["bg"]
            if st["inverse"]:
                f, b = b or bg, f
            style = [f"color:{f}"] + ([f"background-color:{b}"] if b else [])
            style += ["font-weight:bold"] if st["bold"] else []
            style += ["font-style:italic"] if st["italic"] else []
            style += ["text-decoration:underline"] if st["under"] else []
            if st["dim"]:
                style.append("opacity:0.6")
            out.append(f'<span style="{";".join(style)}">{html.escape(chunk, quote=False)}</span>')
        if m is None:
            break
        _apply([int(x or 0) for x in re.split(r"[;:]", m.group(1) or "0")], st)
        pos = m.end()
    return '<pre style="margin:0">' + "".join(out) + "</pre>"


def screen() -> dict[str, Any]:
    live = sessions()
    cur = selected(live)
    tabs = [{"name": s["name"], "project": s["project"], "status": s["status"], "session": s["session"] or s["resume"]}
            for s in live]  # fmt: skip
    if cur is None:
        return {"running": False, "status": "", "html": "", "tabs": tabs, "selected": ""}
    r = tmux("capture-pane", "-p", "-e", "-t", cur["name"])
    size = tmux("display-message", "-p", "-t", cur["name"], "#{window_width} #{window_height}").stdout.split()
    plain = _SGR.sub("", _OTHER.sub("", r.stdout))
    return {"running": True, "status": cur["status"], "html": to_html(r.stdout.rstrip("\n")),
            "prompt": "trust" if _trust_prompt(plain) else "",
            "selected": cur["name"], "session": cur["session"], "cwd": cur["cwd"], "project": cur["project"],
            "tabs": tabs, "cols": int(size[0]) if size else 0,
            "rows": int(size[1]) if len(size) > 1 else 0}  # fmt: skip


def main(argv: list[str]) -> int:
    cmd, rest = (argv[1], argv[2:]) if len(argv) > 1 else ("liste", [])
    nums = [int(x) for x in rest if x.isdigit()]
    if cmd == "liste":
        live = sessions()
        cur = selected(live)
        print(json.dumps({"sessions": live, "selected": cur["name"] if cur else "", "projects": projects()},
                         ensure_ascii=False))  # fmt: skip
        return 0
    if cmd == "gec" and len(rest) >= 2:
        return go(rest[0], rest[1], *nums[-2:]) if len(nums) >= 2 else go(rest[0], rest[1])
    if cmd == "sec" and rest:
        return select(rest[0])
    if cmd == "kapat":
        return stop(rest[0] if rest else "")
    if cmd == "terminal":
        return attach_terminal()
    if cmd == "calisiyor":
        return 0 if running() else 4
    if cmd == "ekran":
        print(json.dumps(screen(), ensure_ascii=False))
        return 0
    if cmd == "boyut" and len(nums) == 2:
        return resize(*nums)
    if cmd == "yaz" and rest:
        return type_text(rest[0])
    if cmd == "tus" and rest:
        return press(rest)
    if cmd == "gir" and rest:
        return feed(rest)
    if cmd == "adlandir" and rest:
        return rename(rest[0], urllib.parse.unquote(rest[1]) if len(rest) > 1 else "")
    if cmd == "tasi" and len(rest) == 2:
        ayarlar.sohbet_ayarla(rest[0], proje=rest[1] if rest[1] != "-" else None)
        return 0
    if cmd == "gizle" and len(rest) == 2 and rest[1] in ("evet", "hayir"):
        ayarlar.sohbet_ayarla(rest[0], gizli=rest[1] == "evet")
        return 0
    if cmd == "sil" and rest:
        return trash_session(rest[0])
    if cmd == "guven" and rest and rest[0] in ("evet", "hayir"):
        return answer_trust(rest[0] == "evet", rest[1] if len(rest) > 1 else "")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

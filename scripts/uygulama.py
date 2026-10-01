"""Asistan for Claude Code programı: arka plandaki Claude Code oturumlarını gerçek bir terminalde kullanmak için.

Claude Code görünmez tmux oturumlarında çalışır (arka.py). Program her oturuma bir tmux istemcisi olarak bağlanır ve
onu xterm.js ile gösterir (web/terminal.html): yazılan anında gider, tekerlekle kaydırılır, seçip kopyalanır.
Pencere kapanınca program sistem tepsisinde sürer; oturumlar zaten tmux'ta yaşar, program kapansa da kapanmaz.

Ölçümler programın içinde toplanır (durum.py) ve masaüstü widget'ına yerel HTTP ile verilir: widget yalnızca bir
önizlemedir, seçeneği yoktur (konuşarak yazma dışında).

Tek kopya çalışır: ikinci kez açılınca var olan pencere öne gelir (yerel soket). Adı APP_NAME'dedir.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import shutil
import struct
import subprocess
import sys
import termios
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (QEasingCurve, QObject, QPropertyAnimation, QRect, QRectF, QSettings, QSocketNotifier, Qt,
                            QThread, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import (QAction, QCloseEvent, QColor, QDesktopServices, QFontDatabase, QGuiApplication, QIcon,
                           QPainter, QPen)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import arka  # noqa: E402
import pencere as kwin  # noqa: E402
import durum  # noqa: E402
import testler  # noqa: E402

APP_NAME = "Asistan for Claude Code"
APP_ID = "asistan"
SOCKET = f"{APP_ID}-{os.getuid()}"
ICON = "utilities-terminal"
C = {"bg": "#1C1B19", "pane": "#141311", "bar": "#23221F", "fg": "#E8E5DF", "dim": "#8F8C86", "clay": "#D77757",
     "ok": "#4EBA65", "warn": "#E0B34F", "bad": "#E5484D"}  # fmt: skip
EXTRA_QSS = """
QWidget#govde { background: #1C1B19; }
QFrame#terminal, QWidget#testpanel { background: #141311; border: 1px solid rgba(255,255,255,23); border-radius: 12px; }
QLabel#baslik { color: #D77757; font-weight: bold; background: transparent; }
QLabel#bos { color: #8F8C86; background: #141311; }
QFrame#cekmece { background: #1C1B19; border: 1px solid rgba(215,119,87,120); border-radius: 12px; }
QListWidget#fark { font-size: 11px; }
"""


def tus(yazi: str, ipucu: str = "", ana: bool = False) -> QPushButton:
    b = QPushButton(yazi)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if ipucu:
        b.setToolTip(ipucu)
    if ana:
        b.setProperty("ana", True)
    return b


# ── tmux istemcisi: bir sözde uçbirimde `tmux attach` ────────────────────────────────────────────────────────
class Uc(QObject):
    def __init__(self, ad: str, cols: int, rows: int, veri: Callable[[str, bytes], None],
                 bitti: Callable[[str], None]) -> None:  # fmt: skip
        super().__init__()
        self.ad, self._veri, self._bitti = ad, veri, bitti
        master, slave = os.openpty()
        self.fd = master
        self.boyut(cols, rows)
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
        env.update(TERM="xterm-256color", COLORTERM="truecolor")
        # setsid -c: tmux istemcisinin denetim uçbirimi bu olsun (boyut değişince SIGWINCH alsın, fd kapanınca çıksın)
        self.proc = subprocess.Popen(["setsid", "-c", "tmux", "attach-session", "-t", ad],  # noqa: S603, S607
                                     stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)  # fmt: skip
        os.close(slave)
        os.set_blocking(master, False)
        self.sn = QSocketNotifier(master, QSocketNotifier.Type.Read, self)
        self.sn.activated.connect(self._oku)
        self.acik = True

    def _oku(self) -> None:
        parts: list[bytes] = []
        ended = False
        for _ in range(32):
            try:
                b = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            except OSError:
                b = b""
            if not b:
                ended = True
                break
            parts.append(b)
        if parts:
            self._veri(self.ad, b"".join(parts))
        if ended:
            self.kapat()
            self._bitti(self.ad)

    def yaz(self, data: bytes) -> None:
        if not self.acik:
            return
        os.set_blocking(self.fd, True)
        try:
            while data:
                n = os.write(self.fd, data)
                data = data[n:]
        except OSError:
            pass
        finally:
            os.set_blocking(self.fd, False)

    def boyut(self, cols: int, rows: int) -> None:
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(rows, 5), max(cols, 20), 0, 0))
        except OSError:
            pass

    def kapat(self) -> None:
        if not self.acik:
            return
        self.acik = False
        self.sn.setEnabled(False)
        try:
            os.close(self.fd)  # tmux istemcisi SIGHUP alır ve ayrılır; oturum sürer
        except OSError:
            pass
        try:
            self.proc.wait(0.5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Kopru(QObject):
    """Terminal sayfasıyla (web/terminal.html) Python arasındaki köprü."""

    cikti = Signal(str, str)  # oturum adı, base64 veri

    def __init__(self, pencere: Pencere) -> None:
        super().__init__()
        self.p = pencere

    @Slot()
    def hazir(self) -> None:
        self.p.sayfa_hazir()

    @Slot(str, str)
    def girdi(self, ad: str, veri: str) -> None:
        uc = self.p.uclar.get(ad)
        if uc:
            uc.yaz(veri.encode())

    @Slot(str, str)
    def ikili(self, ad: str, veri: str) -> None:
        uc = self.p.uclar.get(ad)
        if uc:
            uc.yaz(veri.encode("latin-1", errors="ignore"))

    @Slot(str, int, int)
    def boyut(self, ad: str, cols: int, rows: int) -> None:
        self.p.boyut = (cols, rows)
        uc = self.p.uclar.get(ad)
        if uc:
            uc.boyut(cols, rows)
        elif ad == self.p.secili and ad:
            self.p.baglan(ad)

    @Slot(str, result=str)
    def pano(self, _ad: str) -> str:
        return QGuiApplication.clipboard().text()

    @Slot(str)
    def kopyala(self, yazi: str) -> None:
        QGuiApplication.clipboard().setText(yazi)


class Isci(QThread):
    """Durumu arka planda toplar (arayüz takılmasın) ve widget'a yayınlar."""

    geldi = Signal(object)

    def __init__(self, yayin: durum.Yayin) -> None:
        super().__init__()
        self.yayin = yayin
        self.uyan = threading.Event()
        self.pencere_acik = False
        self.yavas_da = False
        self.dur = False

    def run(self) -> None:
        t = durum.Toplayici()
        while not self.dur:
            try:
                snap = t.topla(self.pencere_acik, force_slow=self.yavas_da)
                snap["dikte"] = dikte_var()
            except Exception as e:  # noqa: BLE001 - bir okuma hatası programı durdurmasın
                print("durum okunamadı:", e, file=sys.stderr)
                snap = None
            self.yavas_da = False
            if snap is not None:
                self.yayin.yayinla(snap)
                self.geldi.emit(snap)
            self.uyan.wait(1.0 if self.pencere_acik or self.yayin.izleniyor() else 5.0)
            self.uyan.clear()

    def simdi(self, yavas_da: bool = False) -> None:
        self.yavas_da = self.yavas_da or yavas_da
        self.uyan.set()


class Arkada(QObject):
    """Uzun süren komutlar (oturum açmak gibi) ayrı iş parçacığında; sonuç ana iş parçacığında işlenir."""

    bitti = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.bitti.connect(lambda cb, r: cb(r))

    def calistir(self, fn: Callable[[], Any], cb: Callable[[Any], None]) -> None:
        threading.Thread(target=lambda: self.bitti.emit(cb, fn()), daemon=True).start()


_dikte: tuple[float, bool] = (0.0, False)


def dikte_var() -> bool:
    """Konuşarak yazma için Dikte kurulu mu (dakikada bir bakılır)."""
    global _dikte
    if time.time() - _dikte[0] > 60:
        try:
            import sesli_istem

            ok = sesli_istem.available()
        except Exception:  # noqa: BLE001
            ok = False
        _dikte = (time.time(), ok)
    return _dikte[1]


# ── test paneli: bir projenin son sürümü, önizlemesi ya da ikisi yan yana ──────────────────────────────────────
class TestGorunumu(QWidget):
    """Bir web sürümü: sunucu açılana dek yeniden dener, yeniden başlayınca sayfayı yeniler (canlı önizleme)."""

    def __init__(self, g: dict[str, Any], yan_yana: bool) -> None:
        super().__init__()
        self.g, self.deneme, self.hazir, self.basladi = g, 0, False, ""
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        if yan_yana:
            renk = C["clay"] if g["ad"] == "Önizleme" else C["ok"]
            ust = QLabel(f"<span style='color:{renk}'>{g['ad'].lower()}</span>  {g['etiket']}  "
                         f"<span style='color:{C['dim']}'>{g['commit']}</span>")  # fmt: skip
            v.addWidget(ust)
        self.stack = QStackedWidget()
        self.bekle = QLabel()
        self.bekle.setObjectName("bos")
        self.bekle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bekle.setWordWrap(True)
        self.web = QWebEngineView()
        self.web.page().setBackgroundColor(QColor(C["pane"]))
        if yan_yana:
            self.web.setZoomFactor(0.8)
        self.web.loadFinished.connect(self._yuklendi)
        self.stack.addWidget(self.bekle)
        self.stack.addWidget(self.web)
        v.addWidget(self.stack, 1)
        self.tekrar = QTimer(self)
        self.tekrar.setSingleShot(True)
        self.tekrar.setInterval(1000)
        self.tekrar.timeout.connect(self._dene)
        self.saglik = QTimer(self)  # canlı önizleme: sunucu yeniden başlayınca sayfayı yenile
        self.saglik.setInterval(3000)
        self.saglik.timeout.connect(self._saglik)
        self.saglik.start()
        self.yukle()

    def yukle(self, neden: str = "") -> None:
        self.deneme, self.hazir = 0, False
        self.bekle.setText(neden or f"{self.g['ad']} başlatılıyor…")
        self.stack.setCurrentIndex(0)
        self.web.setUrl(QUrl(self.g["adres"]))

    def _dene(self) -> None:
        self.deneme += 1
        if self.deneme >= 90:
            self.bekle.setText(f"{self.g['ad']} açılmadı. ↻ ile yeniden dene.")
            return
        self.bekle.setText(f"{self.g['ad']} başlatılıyor… {self.deneme} sn")
        self.web.setUrl(QUrl(self.g["adres"]))

    def _yuklendi(self, ok: bool) -> None:
        if ok:
            self.hazir = True
            self.stack.setCurrentIndex(1)
        else:
            self.hazir = False
            self.stack.setCurrentIndex(0)
            self.tekrar.start()

    def _saglik(self) -> None:
        port = self.g["port"]

        def oku() -> str | None:
            import urllib.request

            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:  # noqa: S310
                    return str(json.loads(r.read()).get("started_at") or "")
            except Exception:  # noqa: BLE001
                return None

        def sonuc(s: str | None) -> None:
            if s is None:
                if self.hazir:
                    self.hazir = False
                    self.stack.setCurrentIndex(0)
                    self.tekrar.start()
                return
            if self.basladi and s and s != self.basladi:
                self.yukle()
            if s:
                self.basladi = s

        ARKADA.calistir(oku, sonuc)


class TestPaneli(QWidget):
    kapandi = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.cfg: dict[str, Any] | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(6)
        ust = QHBoxLayout()
        self.baslik = QLabel()
        self.baslik.setObjectName("baslik")
        self.alt = QLabel()
        self.alt.setTextFormat(Qt.TextFormat.RichText)
        self.fark_tus = tus("Δ", "Son sürümden bu yana gelen commit'ler")
        self.fark_tus.setCheckable(True)
        self.fark_tus.toggled.connect(lambda on: self.fark.setVisible(on))
        yenile = tus("⟲", "Sayfaları yenile")
        yenile.clicked.connect(lambda: [g.yukle() for g in self.gorunumler])
        self.son_kod = tus("↻ en son kod", "Önizlemeyi en son kodla yeniden başlat; hazır olunca sayfa yenilenir")
        self.son_kod.clicked.connect(self._son_kod)
        disari = tus("↗", "Tarayıcıda aç")
        disari.clicked.connect(self._disari)
        kapat = tus("✕", "Paneli kapat")
        kapat.clicked.connect(self.kapandi.emit)
        ust.addWidget(self.baslik)
        ust.addWidget(self.alt, 1)
        for b in (self.fark_tus, yenile, self.son_kod, disari, kapat):
            ust.addWidget(b)
        v.addLayout(ust)
        self.fark = QListWidget()
        self.fark.setObjectName("fark")
        self.fark.setMaximumHeight(160)
        self.fark.hide()
        v.addWidget(self.fark)
        self.alan = QHBoxLayout()
        self.alan.setSpacing(6)
        v.addLayout(self.alan, 1)
        self.gorunumler: list[TestGorunumu] = []

    def ac(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        for g in self.gorunumler:
            g.setParent(None)
            g.deleteLater()
        yan_yana = len(cfg["gorunumler"]) > 1
        self.gorunumler = [TestGorunumu(g, yan_yana) for g in cfg["gorunumler"]]
        for g in self.gorunumler:
            self.alan.addWidget(g, 1)
        self.baslik.setText(cfg["baslik"])
        if yan_yana:
            self.alt.setText(f"<span style='color:{C['ok']}'>son sürüm</span> <span style='color:{C['dim']}'>⇆</span> "
                             f"<span style='color:{C['clay']}'>önizleme</span>")  # fmt: skip
        else:
            g = cfg["gorunumler"][0]
            renk = C["clay"] if g["ad"] == "Önizleme" else C["ok"]
            self.alt.setText(f"<span style='color:{renk}'>{g['ad'].lower()}</span> "
                             f"<span style='color:{C['dim']}'>{g['etiket']} · {g['commit']}</span>")  # fmt: skip
        f = cfg.get("farklar")
        self.fark_tus.setVisible(bool(f))
        self.fark.clear()
        if f:
            self.fark_tus.setText(f"Δ {f['sayi']} değişiklik")
            for c in f["commitler"]:
                self.fark.addItem(f"{c['hash']}  {c['konu']}")
            if f["sayi"] > len(f["commitler"]):
                self.fark.addItem(f"… ve {f['sayi'] - len(f['commitler'])} commit daha")
            if f.get("kirli"):
                self.fark.addItem("+ önizlemede henüz commit'lenmemiş değişiklikler")
            if f.get("geride"):
                self.fark.addItem(f"! depoda önizlemeye aktarılmamış {f['geride']} commit var (↻ en son kod)")
            if not f["sayi"]:
                self.fark.addItem("Son sürüm ile önizleme aynı kodda.")
        self.son_kod.setVisible(any(g["yenilenir"] for g in cfg["gorunumler"]))

    def _son_kod(self) -> None:
        if not self.cfg:
            return
        for g in self.gorunumler:
            if g.g["yenilenir"]:
                g.yukle("En son kodla yeniden başlatılıyor…")
        pid = self.cfg["proje"]
        ARKADA.calistir(lambda: testler.refresh(pid), lambda _r: None)

    def _disari(self) -> None:
        if self.cfg:
            for g in self.cfg["gorunumler"]:
                QDesktopServices.openUrl(QUrl(g["adres"]))

    def bosalt(self) -> None:
        for g in self.gorunumler:
            g.setParent(None)
            g.deleteLater()
        self.gorunumler = []
        self.cfg = None


# ── Test sekmesi ve çekmecesi ──────────────────────────────────────────────────────────────────────────────
SOL = 30  # pencerenin sol boşluğu: Test sekmesi burada durur
KENAR = 10


class Sekme(QWidget):
    """Sol üst kenardaki dikey "Test" sekmesi: basınca Test çekmecesi soldan içeri kayar, yine basınca kapanır."""

    tiklandi = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.acik = False
        self.ustunde = False
        self.setFixedSize(SOL - 6, 76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Test: projelerin son sürümü ve önizlemesi")

    def enterEvent(self, e: Any) -> None:  # noqa: N802
        self.ustunde = True
        self.update()

    def leaveEvent(self, e: Any) -> None:  # noqa: N802
        self.ustunde = False
        self.update()

    def mousePressEvent(self, e: Any) -> None:  # noqa: N802
        self.tiklandi.emit()

    def paintEvent(self, e: Any) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        zemin = QColor(215, 119, 87, 46) if self.acik else QColor(255, 255, 255, 31 if self.ustunde else 15)
        kenar = QColor(C["clay"]) if self.acik else QColor(255, 255, 255, 40)
        p.setPen(QPen(kenar, 1))
        p.setBrush(zemin)
        p.drawRoundedRect(QRectF(-8, 0.5, self.width() + 7.5, self.height() - 1), 6, 6)  # sol köşeler kenara yapışık
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setBold(True)
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.8))
        p.setFont(f)
        p.setPen(QColor(C["clay"]) if self.acik or self.ustunde else QColor(C["fg"]))
        p.translate(self.width() / 2 - 1, self.height() / 2)
        p.rotate(-90)
        p.drawText(QRectF(-self.height() / 2, -self.width() / 2, self.height(), self.width()),
                   Qt.AlignmentFlag.AlignCenter, ("▾ " if self.acik else "▸ ") + "Test")  # fmt: skip


class Cekmece(QFrame):
    """Test çekmecesi: üstte projeler ve sürümleri (qml/TestListesi.qml), bir sürüm açılınca genişleyip pencerenin
    bütün iç alanını kaplar, önizleme listenin altında açılır. Yeri ve boyu pencereye bağlıdır: pencere
    boyutlanınca kenarlarıyla birlikte değişir (Pencere.resizeEvent)."""

    def __init__(self, parent: QWidget, arayuz: QObject) -> None:
        super().__init__(parent)
        self.setObjectName("cekmece")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 8)
        v.setSpacing(4)
        self.liste = QQuickWidget()
        self.liste.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.liste.setClearColor(QColor(C["bg"]))
        qml_baglam(self.liste, arayuz)
        self.liste.setSource(QUrl.fromLocalFile(str(HERE / "qml/TestListesi.qml")))
        for err in self.liste.errors():
            print("qml:", err.toString(), file=sys.stderr)
        root = self.liste.rootObject()
        if root is not None:
            root.implicitHeightChanged.connect(self._liste_boyu)
        self._liste_boyu()
        v.addWidget(self.liste)
        self.panel = TestPaneli()
        self.panel.setObjectName("testpanel")
        self.panel.hide()
        v.addWidget(self.panel, 1)
        self.yer = QLabel()  # masaüstü programları: kendi pencereleri bu alana yerleşir
        self.yer.setObjectName("bos")
        self.yer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.yer.setWordWrap(True)
        self.yer.hide()
        v.addWidget(self.yer, 1)
        self.bos = QWidget()
        v.addWidget(self.bos, 1)

    def _liste_boyu(self) -> None:
        root = self.liste.rootObject()
        h = int(root.property("implicitHeight")) if root is not None else 120
        self.liste.setFixedHeight(max(60, h))

    def ayarla(self, **props: Any) -> None:
        root = self.liste.rootObject()
        for k, val in props.items():
            if root is not None:
                root.setProperty(k, val)

    def kip(self, k: str, yazi: str = "") -> None:
        """liste | web | uygulama"""
        self.panel.setVisible(k == "web")
        self.yer.setVisible(k == "uygulama")
        self.bos.setVisible(k == "liste")
        self.yer.setText(yazi)
        self.ayarla(genis=k != "liste")


def qml_baglam(w: QQuickWidget, arayuz: QObject) -> None:
    ctx = w.rootContext()
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    ctx.setContextProperty("arka", arayuz)
    ctx.setContextProperty("appName", APP_NAME)
    ctx.setContextProperty("yaziAilesi", QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())
    ctx.setContextProperty("yaziBoyu", font.pointSizeF() if font.pointSizeF() > 0 else 10.0)


# ── ana pencere ─────────────────────────────────────────────────────────────────────────────────────────────
class Arayuz(QObject):
    """Sol panelin (qml/YanPanel.qml) arka ucu: durum `veri` ile gider, düğmeler yuvaları çağırır."""

    veri = Signal(str)
    bildirim = Signal(str, str)  # alan ("oturum" | "test"), yazı

    def __init__(self, pencere: Pencere) -> None:
        super().__init__()
        self.p = pencere

    @Slot(str)
    def sekmeSec(self, ad: str) -> None:  # noqa: N802
        self.p.sec(ad)

    @Slot(str)
    def sekmeKapat(self, ad: str) -> None:  # noqa: N802
        self.p.kapat(ad)

    @Slot(str, str)
    def oturumAc(self, cwd: str, sid: str) -> None:  # noqa: N802
        self.p.oturum_ac(cwd, sid)

    @Slot(str, str)
    def testAc(self, pid: str, which: str) -> None:  # noqa: N802
        self.p.test_ac(pid, which)

    @Slot(str)
    def testYenile(self, pid: str) -> None:  # noqa: N802
        ARKADA.calistir(lambda: testler.refresh(pid), lambda _r: self.p.isci.simdi(yavas_da=True))

    @Slot()
    def mikrofon(self) -> None:
        # Dikte'nin istemcisi PyQt6 kullanır: bu süreçte (PySide6) değil, ayrı süreçte çalışır
        subprocess.Popen([sys.executable, str(HERE / "sesli_istem.py"), "ac-kapa"], start_new_session=True,  # noqa: S603
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        QTimer.singleShot(400, self.p.isci.simdi)


class Pencere(QMainWindow):
    def __init__(self, yayin: durum.Yayin) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon.fromTheme(ICON))
        self.uclar: dict[str, Uc] = {}
        self.adlar: list[str] = []
        self.secili = ""
        self.boyut = (120, 36)
        self.hazir = False
        self.snap: dict[str, Any] = {}
        self.cikiyor = False
        self.aciliyor = False

        govde = QWidget()
        govde.setObjectName("govde")
        h = QHBoxLayout(govde)
        h.setContentsMargins(SOL, KENAR, KENAR, KENAR)
        h.setSpacing(10)
        self.setCentralWidget(govde)

        self.arayuz = Arayuz(self)
        self.yan = QQuickWidget()
        self.yan.setObjectName("yan")
        self.yan.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.yan.setClearColor(QColor(C["bg"]))
        qml_baglam(self.yan, self.arayuz)
        self.yan.setSource(QUrl.fromLocalFile(str(HERE / "qml/YanPanel.qml")))
        for err in self.yan.errors():
            print("qml:", err.toString(), file=sys.stderr)
        self.yan.setFixedWidth(330)
        h.addWidget(self.yan)

        cerceve = QFrame()
        cerceve.setObjectName("terminal")
        cv = QVBoxLayout(cerceve)
        cv.setContentsMargins(8, 8, 4, 6)
        self.orta = QStackedWidget()
        self.bos = QLabel("Arka planda açık Claude yok.\nSoldan bir proje ve sohbet seçip “Oturum ❯”a bas.")
        self.bos.setObjectName("bos")
        self.bos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.web = QWebEngineView()
        self.web.page().setBackgroundColor(QColor(C["pane"]))
        s = self.web.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.kopru = Kopru(self)
        self.kanal = QWebChannel(self)
        self.kanal.registerObject("kopru", self.kopru)
        self.web.page().setWebChannel(self.kanal)
        self.web.setUrl(QUrl.fromLocalFile(str(HERE / "web/terminal.html")))
        self.orta.addWidget(self.bos)
        self.orta.addWidget(self.web)
        cv.addWidget(self.orta)
        h.addWidget(cerceve, 1)

        # Test: sol üstte sekme, soldan içeri kayan çekmece (pencerenin üstünde, yerleşimin dışında)
        self.cekmece_kipi = "kapali"  # kapali | liste | web | uygulama
        self.yan_yana = False
        self.uygulamalar: list[dict[str, object]] = []
        self.cekmece = Cekmece(govde, self.arayuz)
        self.cekmece.panel.kapandi.connect(lambda: self.cekmece_ac("liste"))
        self.cekmece.hide()
        self.sekme = Sekme(govde)
        self.sekme.move(0, KENAR + 6)
        self.sekme.tiklandi.connect(lambda: self.cekmece_ac("kapali" if self.cekmece_kipi != "kapali" else "liste"))
        self.anim = QPropertyAnimation(self.cekmece, b"geometry", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(lambda: self.cekmece.setVisible(self.cekmece_kipi != "kapali"))

        ayar = QSettings(APP_ID, APP_ID)
        if ayar.value("geometri"):
            self.restoreGeometry(ayar.value("geometri"))
        else:
            self.resize(1320, 820)

        self.isci = Isci(yayin)
        self.isci.geldi.connect(self.guncelle)
        self.isci.start()

    # ── terminal sayfası ve tmux istemcileri ──
    def sayfa_hazir(self) -> None:
        self.hazir = True
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        px = max(11, round(f.pointSizeF() * self.logicalDpiY() / 72)) if f.pointSizeF() > 0 else 13
        self._js(f"Asistan.ayar({json.dumps(f.family() + ', monospace')}, {px})")
        if self.secili:
            self._goster(self.secili)

    def _js(self, kod: str) -> None:
        self.web.page().runJavaScript(kod)

    def _veri(self, ad: str, b: bytes) -> None:
        self.kopru.cikti.emit(ad, base64.b64encode(b).decode())

    def _bitti(self, ad: str) -> None:
        self.uclar.pop(ad, None)
        self.isci.simdi()

    def baglan(self, ad: str) -> None:
        if ad in self.uclar or not ad:
            return
        arka.prepare_client(ad)
        self.uclar[ad] = Uc(ad, *self.boyut, self._veri, self._bitti)

    def _goster(self, ad: str) -> None:
        if self.hazir:
            self._js(f"Asistan.goster({json.dumps(ad)})")  # sayfa boyutu bildirir → Kopru.boyut → baglan()

    # ── veri geldi ──
    @Slot(object)
    def guncelle(self, snap: dict[str, Any]) -> None:
        self.snap = snap
        tabs = snap["sekmeler"]
        adlar = [t["ad"] for t in tabs]
        if adlar != self.adlar:
            self.adlar = adlar
            for ad in list(self.uclar):
                if ad not in adlar:
                    self.uclar.pop(ad).kapat()
            if self.hazir:
                self._js(f"Asistan.eszamanla({json.dumps(adlar)})")
        self.orta.setCurrentIndex(1 if tabs else 0)
        if not tabs:
            self.secili = ""
        elif self.secili not in adlar:
            self.secili = snap["secili"] if snap["secili"] in adlar else adlar[0]
            arka.select(self.secili)
            self._goster(self.secili)
        elif self.secili not in self.uclar:
            self._goster(self.secili)
        ui = {k: v for k, v in snap.items() if k != "istek"}
        ui["secili"] = self.secili
        self.arayuz.veri.emit(json.dumps(ui, ensure_ascii=False, default=str))
        istek = snap.get("istek")
        if istek and istek.get("test"):
            self.test_ac(*istek["test"])
            self.goster()

    def sec(self, ad: str) -> None:
        if ad not in self.adlar:
            return
        self.secili = ad
        arka.select(ad)
        self._goster(ad)
        self.isci.simdi()

    def kapat(self, ad: str) -> None:
        uc = self.uclar.pop(ad, None)
        if uc:
            uc.kapat()
        ARKADA.calistir(lambda: arka.stop(ad), lambda _r: self.isci.simdi())

    def oturum_ac(self, cwd: str, sid: str) -> None:
        if self.aciliyor:
            return
        self.aciliyor = True
        self.arayuz.bildirim.emit("oturum", "Açılıyor…")
        cols, rows = self.boyut
        ARKADA.calistir(lambda: arka.go(urllib.parse.quote(cwd), sid, cols, rows), self._acildi)

    def _acildi(self, kod: int) -> None:
        self.aciliyor = False
        self.arayuz.bildirim.emit("oturum", "" if kod == 0 else "Bu sohbet şu an bir terminal penceresinde açık: "
                                  "önce onu kapat." if kod == 5 else f"Açılamadı ({kod})")  # fmt: skip
        if kod == 0:
            cur = arka.selected()
            if cur:
                self.secili = cur["name"]
                self._goster(self.secili)
        self.isci.simdi(yavas_da=True)

    # ── testler ──
    def test_ac(self, pid: str, which: str) -> None:
        proj = next((p for p in self.snap.get("testler", []) if p["id"] == pid), None)
        if not proj:
            return
        kimlik = f"{pid}:{which}"
        if self.cekmece.panel.cfg and self.cekmece.panel.cfg["kimlik"] == kimlik and self.cekmece_kipi == "web" \
                or self.cekmece_kipi == "uygulama" and getattr(self, "acik_kimlik", "") == kimlik:  # fmt: skip
            self.cekmece_ac("liste")  # aynı sürüme yine basınca önizleme kapanır, liste kalır
            return
        self.acik_kimlik = kimlik
        self.yan_yana = which == "karsilastir"
        tur = proj["surumler"]["son" if which == "son" else "onizleme"]["tur"]
        self.arayuz.bildirim.emit("test", "Açılıyor…")
        if tur == "web":
            ARKADA.calistir(lambda: testler.prepare(pid, which), self._test_hazir)
            return
        ad = proj["ad"] + (" · yan yana" if self.yan_yana else "")
        self.cekmece_ac("uygulama", f"{ad} kendi penceresinde, bu alanda açılıyor…\n"
                        f"Pencere Asistan'la birlikte taşınır ve boyutlanır; çekmeceyi kapatınca küçülür.")  # fmt: skip
        alan = self._uygulama_alani()
        ARKADA.calistir(lambda: testler.open_apps_inside(pid, which, alan), self._uygulama_acildi)

    def _uygulama_alani(self) -> dict[str, float]:
        """Çekmecenin önizleme alanı, pencerenin iç alanına göre (KWin betiği programları buraya yerleştirir)."""
        r = self._cekmece_yeri("uygulama")
        ust = r.y() + self.cekmece.liste.height() + 10
        return {"sol": r.x() + 6, "ust": ust, "alt": self.centralWidget().height() - r.bottom() + 10,
                "oran": (r.right() - 4) / max(1, self.centralWidget().width())}  # fmt: skip

    def _uygulama_acildi(self, sonuc: tuple[int, list[dict[str, object]]]) -> None:
        kod, hedefler = sonuc
        self.uygulamalar = hedefler or self.uygulamalar
        self.arayuz.bildirim.emit("test", "" if kod == 0 else "Bu sürüm kurulu değil." if kod == 3 else f"Açılamadı ({kod})")
        self.cekmece.ayarla(acik=self.acik_kimlik if kod == 0 else "")
        if kod != 0:
            self.cekmece_ac("liste")

    def _test_hazir(self, cfg: dict[str, Any] | None) -> None:
        self.arayuz.bildirim.emit("test", "" if cfg else "Açılamadı")
        if not cfg:
            return
        self._uygulamalari_birak()
        self.cekmece.panel.ac(cfg)
        self.cekmece.ayarla(acik=cfg["kimlik"])
        self.cekmece_ac("web")

    def _uygulamalari_birak(self) -> None:
        if self.uygulamalar:
            hedefler, self.uygulamalar = self.uygulamalar, []
            ARKADA.calistir(lambda: kwin.birak(hedefler), lambda _r: None)

    def _cekmece_yeri(self, kip: str) -> QRect:
        g = self.centralWidget()
        W, H = g.width(), g.height()
        ic = W - SOL - KENAR
        w = min(440, ic) if kip in ("liste", "kapali") else ic  # önizleme: pencerenin bütün iç alanı
        x = SOL if kip != "kapali" else -w - 4
        return QRect(x, KENAR, w, H - 2 * KENAR)

    def cekmece_ac(self, kip: str, yazi: str = "") -> None:
        """kapali | liste | web | uygulama: çekmece kayarak açılır, genişler ya da kapanır."""
        onceki, self.cekmece_kipi = self.cekmece_kipi, kip
        if kip in ("kapali", "liste"):
            self._uygulamalari_birak()
            if kip == "liste" or onceki == "web":
                self.cekmece.ayarla(acik="")
        if kip != "web" and self.cekmece.panel.cfg:
            self.cekmece.panel.bosalt()
        if kip != "kapali":
            self.cekmece.kip(kip, yazi)
        self.sekme.acik = kip != "kapali"
        self.sekme.update()
        hedef = self._cekmece_yeri(kip)
        if onceki == "kapali":
            self.cekmece.setGeometry(QRect(-hedef.width() - 4, hedef.y(), hedef.width(), hedef.height()))  # soldan kayarak
            self.cekmece.show()
        self.cekmece.raise_()
        self.sekme.raise_()
        self.anim.stop()
        self.anim.setStartValue(self.cekmece.geometry())
        self.anim.setEndValue(hedef if kip != "kapali" else QRect(-self.cekmece.width() - 4, KENAR, self.cekmece.width(), hedef.height()))
        self.anim.start()

    def resizeEvent(self, e: Any) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.cekmece_kipi != "kapali":  # pencere kenarlarıyla birlikte
            self.anim.stop()
            self.cekmece.setGeometry(self._cekmece_yeri(self.cekmece_kipi))

    # ── pencere ──
    def goster(self) -> None:
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        if self.hazir:
            self._js("Asistan.odak()")

    def showEvent(self, e: Any) -> None:  # noqa: N802
        self.isci.pencere_acik = True
        self.isci.simdi()
        super().showEvent(e)

    def hideEvent(self, e: Any) -> None:  # noqa: N802
        self.isci.pencere_acik = False
        super().hideEvent(e)

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        QSettings(APP_ID, APP_ID).setValue("geometri", self.saveGeometry())
        if self.cikiyor or not QSystemTrayIcon.isSystemTrayAvailable():
            self.cik()
            e.accept()
            return
        e.ignore()
        self.hide()

    def cik(self) -> None:
        self.cikiyor = True
        QSettings(APP_ID, APP_ID).setValue("geometri", self.saveGeometry())
        for uc in self.uclar.values():
            uc.kapat()
        self.isci.dur = True
        self.isci.simdi()
        self.isci.wait(2000)
        QApplication.quit()


ARKADA: Arkada


def tumlesik_karta_yonlendir() -> None:
    """İki ekran kartlı dizüstülerde program tümleşik kartta (Intel/AMD, Mesa) çizsin: OpenGL açılırken NVIDIA'nın
    EGL/GLX kitaplığı yüklenirse ayrı kart uyanır ve program açık kaldıkça uyumaz (pil ve ısı). Yalnızca makinede
    Mesa kullanan bir kart da varsa; tek kart NVIDIA ise dokunulmaz. Değişkenler web sürecine de geçer."""
    mesa = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")
    if not mesa.exists():
        return
    vendors = set()
    for dev in Path("/sys/bus/pci/devices").glob("*"):
        try:
            if (dev / "class").read_text().startswith("0x03"):
                vendors.add((dev / "vendor").read_text().strip())
        except OSError:
            continue
    if "0x10de" in vendors and vendors & {"0x8086", "0x1002"}:
        os.environ.setdefault("__EGL_VENDOR_LIBRARY_FILENAMES", str(mesa))
        os.environ.setdefault("__GLX_VENDOR_LIBRARY_NAME", "mesa")


def widget_kur() -> int:
    """Masaüstü widget'ını (plasmoid) kurar ya da günceller."""
    tool = shutil.which("kpackagetool6")
    if not tool:
        print("KDE Plasma 6 bulunamadı (kpackagetool6 yok): widget yalnızca Plasma masaüstünde çalışır.")
        return 3
    pkg = str(HERE.parent / "plasmoid/claude")
    r = subprocess.run([tool, "-t", "Plasma/Applet", "-u", pkg], capture_output=True, text=True, check=False)  # noqa: S603
    if r.returncode != 0:
        r = subprocess.run([tool, "-t", "Plasma/Applet", "-i", pkg], capture_output=True, text=True, check=False)  # noqa: S603
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode


def main(argv: list[str]) -> int:
    gizli = "--arka-planda" in argv
    # Zaten açıksa: onu öne getir (ya da arka planda açılıyorsa hiçbir şey yapma)
    sock = QLocalSocket()
    sock.connectToServer(SOCKET)
    if sock.waitForConnected(300):
        if not gizli:
            sock.write(b"goster")
            sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return 0

    tumlesik_karta_yonlendir()
    QApplication.setApplicationName(APP_ID)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setDesktopFileName(APP_ID)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    qss = (HERE / "tema.qss").read_text() if (HERE / "tema.qss").exists() else ""
    app.setStyleSheet(qss + EXTRA_QSS)

    global ARKADA
    ARKADA = Arkada()
    yayin = durum.Yayin()
    if not yayin.baslat():
        print(f"uyarı: widget bağlantısı açılamadı (127.0.0.1:{durum.PORT} kullanımda)", file=sys.stderr)
    pencere = Pencere(yayin)

    QLocalServer.removeServer(SOCKET)
    server = QLocalServer()
    server.listen(SOCKET)

    def gelen() -> None:
        c = server.nextPendingConnection()
        c.readyRead.connect(lambda: pencere.goster() if b"goster" in bytes(c.readAll()) else None)

    server.newConnection.connect(gelen)

    tray = QSystemTrayIcon(QIcon.fromTheme(ICON), app)
    tray.setToolTip(APP_NAME)
    menu = QMenu()
    menu.addAction(QAction(f"{APP_NAME} penceresini göster", menu, triggered=pencere.goster))
    menu.addSeparator()
    menu.addAction(QAction("Çık (oturumlar arka planda sürer)", menu, triggered=pencere.cik))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: (pencere.hide() if pencere.isVisible() and pencere.isActiveWindow() else pencere.goster())
                           if r == QSystemTrayIcon.ActivationReason.Trigger else None)  # fmt: skip
    tray.show()
    if not gizli:
        pencere.goster()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

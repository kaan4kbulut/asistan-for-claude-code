import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

// Asistan for Claude Code widget'ı: programın (Asistan for Claude Code, bin/asistan) masaüstündeki önizlemesi. Seçeneği yoktur:
// durumu, seçili oturumun konuşmasını, açık oturumları, test sürümlerini, ilerlemeyi ve sistemi gösterir; yalnızca
// konuşarak yazma (Dikte) ve kilit çalışır. Önizlemeye tıklamak programı açar.
// Veri programdan gelir: http://127.0.0.1:47600/durum?v=N uzun yoklaması (scripts/durum.py). Değişiklik yoksa cevap
// bekletilir; widget hiç süreç başlatmaz, veri yalnızca değişince işlenir. Program kapalıysa "kapalı" yazar.
// Görünüm programın sol paneliyle aynı (Asistan teması, scripts/qml/YanPanel.qml): terminal renkleri, eş aralıklı yazı.
PlasmoidItem {
    id: root
    readonly property string url: "http://127.0.0.1:47600/durum"
    readonly property string cmd: "\"$HOME/.local/bin/asistan\""
    property var d: ({ activity: { state: "idle", detail: "", elapsed_s: null, progress: null, chat: [] },
                       sekmeler: [], secili: "", testler: [], voice: {}, dikte: false, pencere: false,
                       steps: { total: 0, done_n: 0, done: [], left: [] }, exams: [], gates: [],
                       git: { branch: "", commits: [], today: 0, dirty: false },
                       metrics: { cpu: 0, ram: 0, gpu: 0, cpu_detail: {}, ram_detail: {}, gpu_detail: {},
                                  net_down_kbs: 0, net_up_kbs: 0, disk_free_gib: 0 },
                       hist: { cpu: [], ram: [], gpu: [], net: [], disk: [] } })
    property int v: -1
    property bool online: false
    property bool everOnline: false
    property var chat: []
    property string chatKey: ""
    property string pressed: ""
    property real pressedAt: 0
    property bool relock: false
    readonly property bool locked: Plasmoid.containment ? Plasmoid.containment.immutable : false

    readonly property color clay: "#D77757"
    readonly property color termBg: "#1C1B19"
    readonly property color termFg: "#E8E5DF"
    readonly property color termDim: "#8F8C86"
    readonly property color paneBg: "#141311"
    readonly property color green: "#4EBA65"
    readonly property color red: "#E5484D"
    readonly property color amber: "#E0B34F"
    readonly property color edge: Qt.rgba(1, 1, 1, 0.09)
    readonly property string mono: Kirigami.Theme.fixedWidthFont.family
    readonly property real fs: Kirigami.Theme.defaultFont.pointSize
    readonly property real gu: Kirigami.Units.gridUnit
    readonly property real gap: Kirigami.Units.smallSpacing * 1.5
    readonly property int histN: 40
    readonly property var turn: d.activity.turn || ({})
    readonly property bool hasTurn: online && d.activity.turn !== null && d.activity.turn !== undefined
    readonly property var runOp: d.activity.running_op || ({ label: "", elapsed_s: 0 })
    readonly property bool hasOp: online && d.activity.running_op !== null && d.activity.running_op !== undefined
    readonly property var running: (d.exams || []).concat(d.gates || []).filter(function (x) { return x.state === "running" || x.state === "silent" })
    readonly property bool gpuSleeping: d.metrics.gpu_detail && d.metrics.gpu_detail.sleeping === true
    readonly property var curTab: (d.sekmeler || []).find(function (t) { return t.ad === root.d.secili }) || null

    preferredRepresentation: fullRepresentation
    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground

    function n(v, dgt) { return (v === null || v === undefined) ? "?" : Number(v).toFixed(dgt === undefined ? 0 : dgt) }
    function dur(sn) {
        if (sn === null || sn === undefined) return ""
        var h = Math.floor(sn / 3600), m = Math.floor(sn % 3600 / 60), s = Math.floor(sn % 60)
        return h > 0 ? h + " sa " + m + " dk" : m > 0 ? m + " dk " + s + " sn" : s + " sn"
    }
    function secs(sn) { return sn < 10 ? n(sn, 1) + " sn" : sn < 90 ? n(sn) + " sn" : dur(sn) }
    function clock(sn) { var s = Math.max(0, Math.floor(sn || 0)); return Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2) }
    function rate(k) { return k >= 1024 ? n(k / 1024, 1) + " MiB/s" : n(k, 0) + " KiB/s" }
    function rateShort(k) { return k >= 1024 ? n(k / 1024, 1) + "M" : n(k, 0) + "K" }
    function stateText(s) {
        return s === "tool" ? "Çalışıyor" : s === "think" ? "Düşünüyor" : s === "ask" ? "Senden cevap bekliyor" : s === "done" ? "Tur bitti" : "Boşta"
    }
    function stateColor(s) { return s === "tool" || s === "done" ? green : s === "think" || s === "ask" ? clay : termDim }
    function stepIcon(k) { return k === "partial" ? "◐" : k === "ready" ? "○" : k === "approval" ? "⏸" : "⛔" }
    function stepColor(k) { return k === "blocked" ? red : k === "partial" ? clay : k === "approval" ? amber : termFg }
    function remain(sn, kind) {
        if (kind === "asildi") return "takılmış olabilir"
        if (sn === null || sn === undefined) return "süre hesaplanıyor"
        return (kind === "en_gec" ? "en geç ~" : "~") + dur(sn) + " kaldı"
    }
    function prefix(k) { return k === "user" ? ">" : k === "result" || k === "error" ? "  ⎿" : "●" }
    function prefixColor(k) { return k === "tool" ? green : k === "error" ? red : k === "user" || k === "result" ? termDim : termFg }
    function lineColor(k) { return k === "result" ? termDim : k === "error" ? "#F08A8D" : k === "user" ? "#BDB9B2" : termFg }
    function run(c) { runner.connectSource(c + " #" + Date.now()) }
    function openApp() { run(root.cmd) }
    function toggleMic() {
        root.pressed = root.voiceState === "kayit" ? "yaziliyor" : "kayit"
        root.pressedAt = Date.now()
        run(root.cmd + " dikte")
    }
    function setLocked(lock) {
        var c = Plasmoid.containment
        if (!c) return
        if (lock) { root.relock = false; c.corona.editMode = false; c.immutability = PlasmaCore.Types.UserImmutable }
        else { c.immutability = PlasmaCore.Types.Mutable; root.relock = true; c.corona.editMode = true }
    }
    Connections {
        target: Plasmoid.containment ? Plasmoid.containment.corona : null
        function onEditModeChanged() { if (root.relock && !Plasmoid.containment.corona.editMode) root.setLocked(true) }
    }

    readonly property string voiceState: {
        if (pressed && Date.now() - pressedAt < 2500) return pressed
        var v = d.voice || {}
        var s = v.state || "", age = (v.age_s === null || v.age_s === undefined) ? 1e9 : v.age_s
        if (s === "kayit") return age < 420 ? s : ""
        if (s === "yaziliyor" || s === "gonderiliyor") return age < 120 ? s : ""
        return age < 10 ? s : ""
    }
    readonly property string voiceLine: {
        var v = d.voice || {}, s = voiceState
        if (s === "kayit") return "Dinliyorum " + clock(pressed ? 0 : v.age_s) + " · bitirmek için tekrar bas"
        if (s === "yaziliyor") return "Yazıya çevriliyor…"
        if (s === "gonderiliyor") return "Claude'a gönderiliyor…"
        if (s === "gonderildi") return "Gönderildi: “" + (v.text || "") + "”"
        if (s === "bos") return "Ses algılanmadı"
        if (s === "iptal") return "İptal edildi"
        if (s) return v.message || ""
        return ""
    }
    readonly property color voiceColor: {
        var s = voiceState
        return s === "kayit" || s === "hata" ? red : s === "gonderildi" ? green : s === "bekliyor" || s === "yazildi" ? amber : termDim
    }

    // ── programdan veri: uzun yoklama (değişince gelir; program kapalıysa 3 sn'de bir yeniden dener) ──
    function poll() {
        var x = new XMLHttpRequest()
        var asked = Date.now()
        x.onreadystatechange = function () {
            if (x.readyState !== XMLHttpRequest.DONE) return
            watchdog.stop()
            if (x.status === 200) {
                try {
                    var j = JSON.parse(x.responseText)
                    root.v = j.v
                    if (j.activity) {
                        root.d = j
                        var key = JSON.stringify(j.activity.chat || [])
                        if (key !== root.chatKey) { root.chatKey = key; root.chat = j.activity.chat || [] }
                    }
                    root.online = true
                    root.everOnline = true
                    if (root.pressed && Date.now() - root.pressedAt > 1200) root.pressed = ""
                    Qt.callLater(root.poll)
                    return
                } catch (e) {}
            }
            root.online = false
            root.v = -1
            retry.restart()
        }
        x.open("GET", root.url + "?v=" + root.v)
        x.send()
        watchdog.restart()
        root.lastXhr = x
    }
    property var lastXhr: null
    Timer { id: retry; interval: 3000; onTriggered: root.poll() }
    Timer {  // cevap 30 sn'de gelmezse (program asılı kaldıysa) isteği bırak, yeniden dene
        id: watchdog
        interval: 30000
        onTriggered: { if (root.lastXhr) root.lastXhr.abort() }
    }
    Component.onCompleted: poll()

    P5Support.DataSource {
        id: runner
        engine: "executable"
        onNewData: (source, data) => disconnectSource(source)
    }

    // ── yapı taşları (programın sol paneliyle aynı) ─────────────────────────────────────────────
    component T: Text {
        color: root.termFg
        font.family: root.mono
        font.pointSize: root.fs * 0.8
        elide: Text.ElideRight
    }

    // collapsible: başlığa tıklayınca içi açılır/kapanır (▸ kapalı, ▾ açık)
    component Section: ColumnLayout {
        id: sec
        default property alias content: body.data
        property string title: ""
        property string trailing: ""
        property color trailingColor: root.termDim
        property bool collapsible: false
        property bool open: true
        Layout.fillWidth: true
        spacing: root.gap * 0.7
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap * 0.7
            T { text: sec.collapsible ? (sec.open ? "▾" : "▸") : "──"; color: sec.collapsible ? root.clay : Qt.rgba(1, 1, 1, 0.25) }
            T { text: sec.title; color: root.clay; font.bold: true }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Qt.rgba(1, 1, 1, 0.12) }
            T { text: sec.trailing; color: sec.trailingColor; visible: text !== ""; Layout.maximumWidth: root.gu * 10 }
            TapHandler { enabled: sec.collapsible; onTapped: sec.open = !sec.open }
            HoverHandler { enabled: sec.collapsible; cursorShape: Qt.PointingHandCursor }
        }
        ColumnLayout { id: body; visible: sec.open; Layout.fillWidth: true; spacing: root.gap * 0.7 }
    }

    // son işlemlerin süreleri: eskisi solda, yenisi sağda; yükseklik logaritmik (1 sn ile 5 dk aynı grafikte okunur)
    component OpsChart: Item {
        id: oc
        property var ops: []  // en yenisi başta (veri.py recent)
        readonly property int slots: 20
        readonly property real step: width / slots
        readonly property real peak: { var m = 10; for (var i = 0; i < ops.length; i++) m = Math.max(m, ops[i].dur_s); return Math.log(1 + m) }
        Layout.fillWidth: true
        Layout.preferredHeight: Math.round(root.gu * 1.4)
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Qt.rgba(1, 1, 1, 0.10) }
        Repeater {
            model: oc.ops.length
            delegate: Rectangle {
                id: bar
                required property int index
                readonly property var op: oc.ops[oc.ops.length - 1 - index]
                x: Math.round((oc.slots - oc.ops.length + index) * oc.step)
                width: Math.max(2, Math.round(oc.step) - 2)
                height: Math.max(2, Math.round(Math.log(1 + bar.op.dur_s) / oc.peak * (oc.height - 1)))
                y: oc.height - 1 - height
                radius: 1
                color: bar.op.dur_s >= 60 ? root.amber : bar.op.dur_s >= 10 ? root.clay : root.green
                opacity: barHover.hovered ? 1 : 0.55 + 0.45 * (index / Math.max(1, oc.ops.length))
                HoverHandler { id: barHover }
                QQC2.ToolTip.visible: barHover.hovered
                QQC2.ToolTip.text: bar.op.label + "\n" + root.secs(bar.op.dur_s) + " · " + root.dur(bar.op.ago_s) + " önce"
            }
        }
    }

    component TermBar: Rectangle {
        property real frac: 0
        property color tint: root.clay
        Layout.fillWidth: true
        implicitHeight: 4
        radius: 2
        color: Qt.rgba(1, 1, 1, 0.08)
        Rectangle { width: Math.round(parent.width * Math.max(0, Math.min(1, parent.frac))); height: parent.height; radius: 2; color: parent.tint }
    }

    // Çubuklu eğri: çubuklar piksele hizalı, yerleri sabit, animasyonsuz (boyut değişince kaymaz, boşta çizim yok)
    component Spark: Item {
        id: sp
        property var values: []
        property bool percent: true
        property color tint: root.clay
        Layout.fillWidth: true
        Layout.minimumWidth: root.histN
        Layout.preferredHeight: Math.round(root.gu * 0.55)
        readonly property real step: width / root.histN
        readonly property real scaleMax: {
            var m = sp.percent ? 10 : 1
            for (var i = 0; i < sp.values.length; i++) m = Math.max(m, sp.values[i] * 1.3)
            return sp.percent ? Math.min(m, 100) : m
        }
        Repeater {
            model: root.histN
            delegate: Rectangle {
                required property int index
                readonly property real v: { var i = index - (root.histN - sp.values.length); return i >= 0 ? sp.values[i] : 0 }
                x: Math.round(index * sp.step)
                width: Math.max(1, Math.round((index + 1) * sp.step) - x - 1)
                height: Math.max(1, Math.round(v / sp.scaleMax * sp.height))
                y: sp.height - height
                color: sp.tint
                opacity: 0.25 + 0.75 * (index / root.histN)
            }
        }
    }

    component MiniMetric: RowLayout {
        id: mm
        property string name: ""
        property string value: ""
        property string detail: ""
        property alias values: msk.values
        property alias percent: msk.percent
        property alias tint: msk.tint
        Layout.fillWidth: true
        spacing: root.gap
        T { text: mm.name; color: root.termDim; Layout.preferredWidth: nameW.width }
        Spark { id: msk }
        T { text: mm.value; horizontalAlignment: Text.AlignRight; font.features: { "tnum": 1 }; Layout.preferredWidth: valW.width }
        HoverHandler { id: mmHover }
        QQC2.ToolTip.visible: mm.detail !== "" && mmHover.hovered
        QQC2.ToolTip.delay: 500
        QQC2.ToolTip.text: mm.detail
    }
    TextMetrics { id: nameW; font.family: root.mono; font.pointSize: root.fs * 0.8; text: "DİSK " }
    TextMetrics { id: valW; font.family: root.mono; font.pointSize: root.fs * 0.8; text: "↓999.9M ↑999.9M" }

    // salt okunur rozet: ince kenar, rengi durumu söyler (tuş değil)
    component Badge: Rectangle {
        id: bd
        property string label: ""
        property color tint: root.termFg
        property bool on: false
        implicitWidth: bt.implicitWidth + root.gap * 2
        implicitHeight: bt.implicitHeight + root.gap * 0.8
        width: Math.min(implicitWidth, root.gu * 16)  // sabit üst sınır: kapsayıcının genişliğine bağlanırsa yerleşim döngüye girer
        radius: 4
        color: bd.on ? Qt.rgba(0.84, 0.47, 0.34, 0.16) : "transparent"
        border.width: 1
        border.color: bd.on ? root.clay : Qt.rgba(1, 1, 1, 0.13)
        Text {
            id: bt
            anchors.fill: parent
            anchors.leftMargin: root.gap; anchors.rightMargin: root.gap
            verticalAlignment: Text.AlignVCenter
            text: bd.label
            color: bd.on ? root.clay : bd.tint
            font.family: root.mono
            font.pointSize: root.fs * 0.72
            elide: Text.ElideRight
        }
    }

    component TermKey: Rectangle {
        id: tk
        property string label: ""
        property string tip: ""
        property bool dim: false
        signal clicked()
        implicitWidth: Math.max(root.gu * 1.5, keyText.implicitWidth + root.gap * 2)
        implicitHeight: keyText.implicitHeight + root.gap
        radius: 4
        color: tkMouse.pressed ? Qt.rgba(1, 1, 1, 0.18) : tkMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : Qt.rgba(1, 1, 1, 0.05)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.13)
        opacity: tk.dim ? 0.45 : 1
        Text { id: keyText; anchors.centerIn: parent; text: tk.label; color: root.termFg; font.family: root.mono; font.pointSize: root.fs * 0.76 }
        MouseArea { id: tkMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tk.clicked() }
        QQC2.ToolTip.visible: tk.tip !== "" && tkMouse.containsMouse
        QQC2.ToolTip.delay: 500
        QQC2.ToolTip.text: tk.tip
    }

    component MicButton: Item {
        id: mb
        readonly property string st: root.voiceState
        readonly property bool busy: st === "yaziliyor" || st === "gonderiliyor"
        implicitWidth: Math.round(root.gu * 1.6)
        implicitHeight: implicitWidth
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: mb.st === "kayit" ? root.red : mb.st === "gonderildi" ? root.green
                 : ma.containsMouse ? Qt.lighter(root.clay, 1.12) : root.clay
            opacity: mb.busy ? 0.6 : 1
            Kirigami.Icon {
                anchors.centerIn: parent
                width: Math.round(parent.width * 0.55); height: width
                source: mb.st === "gonderildi" ? "dialog-ok-apply" : mb.st === "kayit" ? "media-playback-stop" : "audio-input-microphone"
                isMask: true
                color: root.termBg
            }
        }
        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.toggleMic() }
        QQC2.ToolTip.visible: ma.containsMouse
        QQC2.ToolTip.delay: 600
        QQC2.ToolTip.text: mb.st === "kayit" ? "Bitir ve Claude Code'a gönder" : "Konuşarak Claude Code'a yaz"
    }

    fullRepresentation: Rectangle {
        id: full
        Layout.minimumWidth: root.gu * 14
        Layout.minimumHeight: root.gu * 14
        Layout.preferredWidth: root.gu * 20
        Layout.preferredHeight: root.gu * 40
        radius: Kirigami.Units.largeSpacing * 2
        color: root.termBg
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.10)
        readonly property bool wide: width >= root.gu * 21

        MouseArea {  // tekerlek masaüstü simgelerini kaydırmasın
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            onWheel: (wheel) => { wheel.accepted = true }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing * 1.5
            spacing: root.gap * 1.4

            // durum, mikrofon, kilit
            RowLayout {
                Layout.fillWidth: true
                spacing: root.gap
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: root.gap
                        Rectangle {
                            Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4
                            color: root.online ? root.stateColor(root.d.activity.state) : root.termDim
                        }
                        T { text: "Asistan for Claude Code"; color: root.clay; font.bold: true; font.pointSize: root.fs * 0.9; Layout.fillWidth: true }
                        TermKey {
                            label: root.locked ? "🔒" : "🔓"
                            dim: root.locked
                            onClicked: root.setLocked(!root.locked)
                            tip: root.locked ? "Kilitli · tıkla: yeri ve boyutu değiştirilebilir, bitince üstteki 'Bitti'"
                                             : "Kilidi açık · tıkla: yeri ve boyutu kilitlenir"
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: root.gap
                        T {
                            text: root.online ? root.stateText(root.d.activity.state) : root.everOnline ? "program kapandı" : "program kapalı"
                            color: root.online ? root.stateColor(root.d.activity.state) : root.termDim
                        }
                        T { text: root.online ? root.dur(root.d.activity.elapsed_s) : ""; color: root.termDim; font.features: { "tnum": 1 }; Layout.fillWidth: true }
                    }
                }
                MicButton { visible: root.d.dikte === true || !root.online; Layout.alignment: Qt.AlignTop }
            }
            T {
                visible: root.online && text !== ""
                text: root.d.activity.detail || ""
                color: root.termDim
                Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2
                Layout.topMargin: -root.gap * 0.6
            }
            T {
                visible: text !== ""
                text: root.voiceLine
                color: root.voiceColor
                Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2
            }
            // önizleme: seçili oturumun konuşması; tıklayınca program açılır
            Rectangle {
                id: preview
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: root.gu * 5
                radius: Kirigami.Units.largeSpacing * 1.2
                color: root.paneBg
                border.width: 1
                border.color: pvMouse.containsMouse ? Qt.rgba(0.84, 0.47, 0.34, 0.6) : root.edge
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    spacing: root.gap * 0.6
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: root.gap
                        T {
                            text: root.curTab ? (root.curTab.durum === "busy" ? "◐ " : root.curTab.durum === "waiting" ? "⏸ " : "● ") + root.curTab.baslik
                                  : root.online ? "arka planda açık oturum yok" : "Asistan for Claude Code kapalı"
                            color: root.curTab ? root.clay : root.termDim
                            Layout.fillWidth: true
                        }
                        T { text: root.curTab ? root.curTab.proje : ""; color: root.termDim; Layout.maximumWidth: preview.width * 0.4 }
                    }
                    ListView {
                        id: chatView
                        visible: root.online
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 3
                        model: root.chat
                        interactive: false
                        boundsBehavior: Flickable.StopAtBounds
                        property bool follow: true
                        onCountChanged: if (follow) positionViewAtEnd()
                        onModelChanged: if (follow) Qt.callLater(positionViewAtEnd)
                        onHeightChanged: if (follow) Qt.callLater(positionViewAtEnd)
                        delegate: RowLayout {
                            required property var modelData
                            width: chatView.width
                            spacing: root.gap * 0.7
                            T { Layout.alignment: Qt.AlignTop; text: root.prefix(modelData.kind); color: root.prefixColor(modelData.kind) }
                            T {
                                Layout.fillWidth: true
                                text: modelData.text
                                color: root.lineColor(modelData.kind)
                                wrapMode: modelData.kind === "assistant" || modelData.kind === "user" ? Text.Wrap : Text.NoWrap
                                maximumLineCount: modelData.kind === "assistant" ? 4 : modelData.kind === "user" ? 2 : 1
                            }
                        }
                    }
                    T {
                        visible: !root.online
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        wrapMode: Text.Wrap
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: "Önizleme programdan gelir.\nTıkla: Asistan for Claude Code açılsın."
                        color: root.termDim
                    }
                    T {
                        visible: root.online && root.curTab !== null && root.curTab.durum === "waiting"
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "⏸ Claude onay bekliyor · cevaplamak için tıkla"
                        color: root.amber
                    }
                }
                MouseArea {
                    id: pvMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.openApp()
                    onWheel: (wheel) => {  // konuşmada geri git; en alta inince yine izler
                        var vw = chatView
                        var bottom = vw.originY + Math.max(0, vw.contentHeight - vw.height)
                        vw.contentY = Math.max(vw.originY, Math.min(bottom, vw.contentY - wheel.angleDelta.y / 2))
                        vw.follow = vw.contentY >= bottom - 2
                        wheel.accepted = true
                    }
                }
                QQC2.ToolTip.visible: pvMouse.containsMouse
                QQC2.ToolTip.delay: 900
                QQC2.ToolTip.text: "Asistan for Claude Code'u aç"
            }

            // açık oturumlar (salt okunur)
            Section {
                visible: root.online && root.d.sekmeler.length > 1
                title: "Oturumlar"
                trailing: root.d.sekmeler.length + " açık"
                Flow {
                    Layout.fillWidth: true
                    spacing: root.gap * 0.7
                    Repeater {
                        model: root.d.sekmeler
                        delegate: Badge {
                            required property var modelData
                            label: (modelData.durum === "busy" ? "◐ " : modelData.durum === "waiting" ? "⏸ " : "● ") + modelData.baslik
                            on: modelData.ad === root.d.secili
                            tint: modelData.durum === "waiting" ? root.amber : root.termFg
                        }
                    }
                }
            }

            // test sürümleri (yalnızca durum; açmak programdan)
            Section {
                visible: root.online && (root.d.testler || []).length > 0
                title: "Test"
                collapsible: true
                open: false
                trailing: (root.d.testler || []).length + " proje · "
                          + (root.d.testler || []).filter(function (p) { return p.surumler.son.calisiyor || p.surumler.onizleme.calisiyor }).length + " çalışıyor"
                Repeater {
                    model: root.d.testler || []
                    delegate: RowLayout {
                        id: tr
                        required property var modelData
                        readonly property var son: modelData.surumler.son
                        readonly property var oniz: modelData.surumler.onizleme
                        readonly property var fark: modelData.farklar
                        Layout.fillWidth: true
                        spacing: root.gap
                        T { text: tr.modelData.ad; Layout.fillWidth: true; Layout.minimumWidth: root.gu * 2 }
                        T {
                            text: tr.son.tur === "yok" ? "–" : (tr.son.calisiyor ? "●" : "○") + " son"
                            color: tr.son.calisiyor ? root.green : root.termDim
                        }
                        T { text: (tr.oniz.calisiyor ? "●" : "○") + " önizleme"; color: tr.oniz.calisiyor ? root.clay : root.termDim }
                        T {
                            text: tr.fark.sayi ? "Δ" + tr.fark.sayi : tr.son.tur === "yok" ? "" : "="
                            color: tr.fark.sayi ? root.clay : root.termDim
                            horizontalAlignment: Text.AlignRight
                            Layout.preferredWidth: deltaW.width
                        }
                    }
                }
            }
            TextMetrics { id: deltaW; font.family: root.mono; font.pointSize: root.fs * 0.8; text: "Δ999" }

            // işlem: bu tur ve tahmini kalan süre, süren araç, son işlemlerin süre grafiği
            Section {
                visible: root.online && (root.hasTurn || root.hasOp || (root.d.activity.recent || []).length > 0) && full.height >= root.gu * 24
                title: "İşlem"
                trailing: root.hasTurn ? (root.turn.live ? root.dur(root.turn.elapsed_s) + " · " + root.turn.ops + " işlem" : "tur bitti")
                                       : (root.d.activity.calls_10m || 0) + " işlem / 10 dk"
                RowLayout {
                    visible: root.hasTurn && root.turn.live === true
                    Layout.fillWidth: true
                    spacing: root.gap
                    TermBar { frac: (root.turn.pct || 0) / 100; tint: root.turn.over ? root.amber : root.clay; visible: root.turn.pct !== null && root.turn.pct !== undefined }
                    T {
                        text: root.turn.over ? "tahmini aştı" : root.turn.eta_s !== null && root.turn.eta_s !== undefined ? "~" + root.dur(root.turn.eta_s) + " kaldı" : "tahmin yok"
                        color: root.turn.over ? root.amber : root.clay
                    }
                }
                RowLayout {
                    visible: root.hasOp
                    Layout.fillWidth: true
                    spacing: root.gap
                    T { text: "▶ " + root.runOp.label; Layout.fillWidth: true; color: root.green }
                    T { text: root.dur(root.runOp.elapsed_s); color: root.termDim }
                }
                OpsChart { visible: (root.d.activity.recent || []).length > 0; ops: root.d.activity.recent || [] }
                Repeater {  // süren işler (sınav, kalite kapısı)
                    model: root.running
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 2
                        RowLayout {
                            Layout.fillWidth: true
                            T { text: "▶ " + modelData.name; Layout.fillWidth: true }
                            T { text: modelData.total ? (modelData.ok + modelData.bad) + "/" + modelData.total : "%" + modelData.pct; color: root.clay }
                            T { text: root.remain(modelData.eta_s, modelData.eta_kind || ""); color: root.termDim }
                        }
                        TermBar { frac: modelData.total ? (modelData.ok + modelData.bad) / modelData.total : modelData.pct / 100 }
                    }
                }
            }

            // adımlar: projenin BACKLOG.md'si
            Section {
                visible: root.online && root.d.steps.total > 0 && full.height >= root.gu * 34
                title: "Adımlar"
                trailing: root.d.steps.done_n + "/" + root.d.steps.total + " · %" + Math.round(100 * root.d.steps.done_n / Math.max(root.d.steps.total, 1))
                TermBar { frac: root.d.steps.done_n / Math.max(root.d.steps.total, 1); tint: root.green }
                Repeater {
                    model: root.d.steps.left.filter(function (x) { return x.kind === "partial" || x.kind === "ready" }).slice(0, 3)
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: root.gap
                        T { text: root.stepIcon(modelData.kind); color: root.stepColor(modelData.kind) }
                        T { text: modelData.id; color: root.stepColor(modelData.kind) }
                        T { text: modelData.title; color: modelData.kind === "partial" ? root.termFg : root.termDim; Layout.fillWidth: true }
                    }
                }
            }

            // eksikler: ilgilenilmesi gerekenler (ilk üçü)
            Section {
                visible: root.online && (root.d.eksikler || []).length > 0 && full.height >= root.gu * 29
                title: "Eksikler"
                trailing: (root.d.eksikler || []).length + ""
                Repeater {
                    model: (root.d.eksikler || []).slice(0, 3)
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: root.gap
                        T {
                            text: modelData.tur === "engel" ? "⛔" : modelData.tur === "bekliyor" ? "⏸" : modelData.tur === "uyari" ? "!" : "·"
                            color: modelData.tur === "engel" ? root.red : modelData.tur === "bilgi" ? root.termDim : root.amber
                        }
                        T { text: modelData.yazi; Layout.fillWidth: true; color: modelData.tur === "bilgi" ? root.termDim : root.termFg }
                    }
                }
            }

            // sistem: her zaman en altta; genişse iki, darsa tek sütun
            Section {
                visible: root.online
                title: "Sistem"
                trailing: "disk " + root.n(root.d.metrics.disk_free_gib) + " GiB boş"
                GridLayout {
                    Layout.fillWidth: true
                    columns: full.wide ? 2 : 1
                    columnSpacing: root.gap * 2
                    rowSpacing: 2
                    MiniMetric {
                        name: "CPU"; values: root.d.hist.cpu
                        value: "%" + root.n(root.d.metrics.cpu) + " " + root.n(root.d.metrics.cpu_detail.temp) + "°"
                        detail: "İşlemci %" + root.n(root.d.metrics.cpu, 1) + " · en hızlı çekirdek " + root.n(root.d.metrics.cpu_detail.freq_ghz, 2) + " GHz · " + root.n(root.d.metrics.cpu_detail.temp) + " °C"
                    }
                    MiniMetric {
                        name: "RAM"; values: root.d.hist.ram; tint: root.amber
                        value: root.n(root.d.metrics.ram_detail.used_gib, 0) + "/" + root.n(root.d.metrics.ram_detail.total_gib, 0) + "G"
                        detail: "Bellek %" + root.n(root.d.metrics.ram) + " · " + root.n(root.d.metrics.ram_detail.used_gib, 1) + " / " + root.n(root.d.metrics.ram_detail.total_gib, 1) + " GiB"
                    }
                    MiniMetric {
                        name: "GPU"; values: root.d.hist.gpu; tint: root.green
                        value: root.gpuSleeping ? "uyku" : "%" + root.n(root.d.metrics.gpu) + " " + root.n(root.d.metrics.gpu_detail.temp) + "°"
                        detail: root.gpuSleeping ? "Ayrı ekran kartı güç tasarrufunda (uyandırılmadan okunuyor)" : "Ekran kartı %" + root.n(root.d.metrics.gpu)
                    }
                    MiniMetric {
                        name: "AĞ"; values: root.d.hist.net; percent: false; tint: "#5B8DEF"
                        value: "↓" + root.rateShort(root.d.metrics.net_down_kbs) + " ↑" + root.rateShort(root.d.metrics.net_up_kbs)
                        detail: "Ağ · indirme " + root.rate(root.d.metrics.net_down_kbs) + " · yükleme " + root.rate(root.d.metrics.net_up_kbs)
                    }
                    MiniMetric {
                        name: "DİSK"; values: root.d.hist.disk; percent: false; tint: root.clay
                        value: "↓" + root.rateShort(root.d.metrics.disk_read_kbs || 0) + " ↑" + root.rateShort(root.d.metrics.disk_write_kbs || 0)
                        detail: "Disk · okuma " + root.rate(root.d.metrics.disk_read_kbs || 0) + " · yazma " + root.rate(root.d.metrics.disk_write_kbs || 0)
                    }
                }
            }
        }
    }
}

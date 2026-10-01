import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts

// Asistan for Claude Code programının sol paneli. Görünümü masaüstü widget'ıyla aynı (Asistan teması: Claude Code terminali):
// "── Başlık ───" bölümleri, ince çerçeveli küçük tuşlar, çubuklu eğriler. Veri ve komutlar Python'dan: bağlam
// nesnesi `arka` (uygulama.py Arayuz): arka.veri(json) sinyaliyle durum gelir, yuvaları (sekmeSec, oturumAc…) çağrılır.
Rectangle {
    id: root
    color: termBg

    // Asistan teması
    readonly property color clay: "#D77757"
    readonly property color termBg: "#1C1B19"
    readonly property color termFg: "#E8E5DF"
    readonly property color termDim: "#8F8C86"
    readonly property color paneBg: "#141311"
    readonly property color green: "#4EBA65"
    readonly property color red: "#E5484D"
    readonly property color amber: "#E0B34F"
    readonly property string mono: yaziAilesi
    readonly property real fs: yaziBoyu
    readonly property real gu: Math.round(fs * 1.9)
    readonly property real gap: 6

    property var d: ({ activity: { state: "idle", detail: "bağlanıyor…", elapsed_s: null, progress: null },
                       sekmeler: [], secili: "", projeler: [], testler: [], voice: {}, dikte: false,
                       steps: { total: 0, done_n: 0, done: [], left: [] }, exams: [], gates: [],
                       git: { branch: "", commits: [], today: 0, dirty: false },
                       metrics: { cpu: 0, ram: 0, gpu: 0, cpu_detail: {}, ram_detail: {}, gpu_detail: {},
                                  net_down_kbs: 0, net_up_kbs: 0, disk_free_gib: 0 },
                       hist: { cpu: [], ram: [], gpu: [], net: [], disk: [] } })
    property var projList: []
    property string projKey: ""
    property string projCwd: ""
    property string sessId: ""
    property string notice: ""
    property string testNotice: ""
    property string confirmClose: ""
    property bool opening: false
    property string pressed: ""
    property real pressedAt: 0
    readonly property int histN: 40
    // İşlem bölümü: bu tur, süren araç ve tahmini (veri.py parse_activity); yoksa boş nesne
    readonly property var turn: d.activity.turn || ({})
    readonly property bool hasTurn: d.activity.turn !== null && d.activity.turn !== undefined
    readonly property var runOp: d.activity.running_op || ({ label: "", elapsed_s: 0 })
    readonly property bool hasOp: d.activity.running_op !== null && d.activity.running_op !== undefined
    readonly property var prog: d.activity.progress || ({})
    readonly property bool hasProg: d.activity.progress !== null && d.activity.progress !== undefined
    readonly property var running: (d.exams || []).concat(d.gates || []).filter(function (x) { return x.state === "running" || x.state === "silent" })
    readonly property bool gpuSleeping: d.metrics.gpu_detail && d.metrics.gpu_detail.sleeping === true
    readonly property int projIndex: {
        var i = projList.findIndex(function (p) { return p.cwd === root.projCwd })
        return i < 0 ? 0 : i
    }
    readonly property var curProj: projList.length ? projList[projIndex] : null
    readonly property var sessList: curProj ? curProj.sessions : []
    readonly property int sessIndex: {
        if (sessId === "yeni") return 0
        var i = sessList.findIndex(function (s) { return s.id === root.sessId })
        return i < 0 ? (sessList.length ? 1 : 0) : i + 1
    }

    function n(v, dgt) { return (v === null || v === undefined) ? "?" : Number(v).toFixed(dgt === undefined ? 0 : dgt) }
    function dur(sn) {
        if (sn === null || sn === undefined) return ""
        var h = Math.floor(sn / 3600), m = Math.floor(sn % 3600 / 60), s = Math.floor(sn % 60)
        return h > 0 ? h + " sa " + m + " dk" : m > 0 ? m + " dk " + s + " sn" : s + " sn"
    }
    function ago(t) {
        var s = Math.max(0, Date.now() / 1000 - t)
        return s < 90 ? "şimdi" : s < 3600 ? Math.round(s / 60) + " dk önce" : s < 86400 ? Math.round(s / 3600) + " sa önce"
             : Math.round(s / 86400) + " gün önce"
    }
    function secs(sn) { return sn < 10 ? n(sn, 1) + " sn" : sn < 90 ? n(sn) + " sn" : dur(sn) }
    function clock(sn) { var s = Math.max(0, Math.floor(sn || 0)); return Math.floor(s / 60) + ":" + ("0" + s % 60).slice(-2) }
    function rateShort(k) { return k >= 1024 ? n(k / 1024, 1) + "M" : n(k, 0) + "K" }
    function rate(k) { return k >= 1024 ? n(k / 1024, 1) + " MiB/s" : n(k, 0) + " KiB/s" }
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

    Connections {
        target: arka
        function onVeri(json) {
            try {
                var j = JSON.parse(json)
                root.d = j
                var pk = JSON.stringify((j.projeler || []).map(function (p) {
                    return [p.cwd, p.sessions.map(function (s) { return [s.id, s.title, s.where] })] }))
                if (pk !== root.projKey) { root.projKey = pk; root.projList = j.projeler || [] }
                if (!root.projCwd && j.sekmeler.length) {
                    var cur = j.sekmeler.find(function (t) { return t.ad === j.secili })
                    if (cur) root.projCwd = cur.cwd
                }
                if (root.pressed && Date.now() - root.pressedAt > 1200) root.pressed = ""
            } catch (e) {}
        }
        function onBildirim(alan, yazi) {
            if (alan === "oturum") { root.notice = yazi; root.opening = yazi === "Açılıyor…" }
            else if (alan === "test") root.testNotice = yazi
        }
    }
    Timer { id: closeReset; interval: 4000; onTriggered: root.confirmClose = "" }

    // ── yapı taşları (widget'takilerle aynı) ────────────────────────────────────────────────────────
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
            T { text: sec.trailing; color: sec.trailingColor; visible: text !== ""; Layout.maximumWidth: root.width * 0.55 }
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
                Basic.ToolTip.visible: barHover.hovered
                Basic.ToolTip.text: bar.op.label + "\n" + root.secs(bar.op.dur_s) + " · " + root.dur(bar.op.ago_s) + " önce"
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

    // Çubuklu eğri: her çubuk piksele hizalı sabit yerinde (boyut değişince kaymaz), animasyonsuz
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
        T {
            text: mm.value; horizontalAlignment: Text.AlignRight; font.features: { "tnum": 1 }
            Layout.preferredWidth: valW.width
        }
        HoverHandler { id: mmHover }
        Basic.ToolTip.visible: mm.detail !== "" && mmHover.hovered
        Basic.ToolTip.delay: 500
        Basic.ToolTip.text: mm.detail
    }
    TextMetrics { id: nameW; font.family: root.mono; font.pointSize: root.fs * 0.8; text: "DİSK " }
    TextMetrics { id: valW; font.family: root.mono; font.pointSize: root.fs * 0.8; text: "↓999.9M ↑999.9M" }

    component TermKey: Rectangle {
        id: tk
        property string label: ""
        property string tip: ""
        property color tint: root.termFg
        property bool active: false
        property bool dim: false
        signal clicked()
        implicitWidth: Math.max(root.gu, keyText.implicitWidth + root.gap * 2.2)
        implicitHeight: keyText.implicitHeight + root.gap * 1.1
        radius: 4
        color: tk.active ? Qt.rgba(0.84, 0.47, 0.34, 0.16)
             : tkMouse.pressed ? Qt.rgba(1, 1, 1, 0.18) : tkMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : Qt.rgba(1, 1, 1, 0.05)
        border.width: 1
        border.color: tk.active ? root.clay : Qt.rgba(1, 1, 1, 0.13)
        opacity: tk.dim ? 0.45 : 1
        Text {
            id: keyText
            anchors.fill: parent
            anchors.leftMargin: root.gap; anchors.rightMargin: root.gap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: tk.label
            color: tk.active ? root.clay : tk.tint
            font.family: root.mono
            font.pointSize: root.fs * 0.76
            elide: Text.ElideRight
        }
        MouseArea { id: tkMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tk.clicked() }
        Basic.ToolTip.visible: tk.tip !== "" && tkMouse.containsMouse
        Basic.ToolTip.delay: 500
        Basic.ToolTip.text: tk.tip
    }

    component TermCombo: Basic.ComboBox {
        id: cb
        Layout.fillWidth: true
        implicitHeight: Math.round(root.gu * 1.25)
        font.family: root.mono
        font.pointSize: root.fs * 0.8
        background: Rectangle {
            radius: 4
            color: cb.hovered ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(1, 1, 1, 0.05)
            border.width: 1
            border.color: cb.popup.visible ? root.clay : Qt.rgba(1, 1, 1, 0.13)
        }
        contentItem: T {
            leftPadding: root.gap * 1.5
            rightPadding: cb.indicator.width + root.gap
            text: cb.displayText
            verticalAlignment: Text.AlignVCenter
        }
        indicator: T {
            x: cb.width - width - root.gap * 1.5
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"; color: root.termDim
        }
        delegate: Basic.ItemDelegate {
            id: cbItem
            required property int index
            required property var modelData
            width: ListView.view ? ListView.view.width : cb.width
            highlighted: cb.highlightedIndex === index
            contentItem: T { text: cbItem.modelData; color: cbItem.index === cb.currentIndex ? root.clay : root.termFg }
            background: Rectangle { color: cbItem.highlighted ? Qt.rgba(1, 1, 1, 0.10) : "transparent" }
        }
        popup: Basic.Popup {
            y: cb.height + 2
            width: Math.max(cb.width, root.width - root.gap * 4)
            implicitHeight: Math.min(contentItem.implicitHeight + 2, root.height * 0.6)
            padding: 1
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: cb.popup.visible ? cb.delegateModel : null
                currentIndex: cb.highlightedIndex
                Basic.ScrollIndicator.vertical: Basic.ScrollIndicator {}
            }
            background: Rectangle { color: root.termBg; border.width: 1; border.color: root.clay; radius: 4 }
        }
    }

    component MicButton: Item {
        id: mb
        readonly property string st: root.voiceState
        readonly property bool busy: st === "yaziliyor" || st === "gonderiliyor"
        implicitWidth: Math.round(root.gu * 1.15)
        implicitHeight: implicitWidth
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: mb.st === "kayit" ? root.red : mb.st === "gonderildi" ? root.green
                 : ma.containsMouse ? Qt.lighter(root.clay, 1.12) : root.clay
            opacity: mb.busy ? 0.6 : 1
            T {
                anchors.centerIn: parent
                text: mb.st === "kayit" ? "■" : mb.busy ? "…" : "●"
                color: root.termBg
                font.pointSize: root.fs * 0.8
            }
        }
        MouseArea {
            id: ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                root.pressed = root.voiceState === "kayit" ? "yaziliyor" : "kayit"
                root.pressedAt = Date.now()
                arka.mikrofon()
            }
        }
        Basic.ToolTip.visible: ma.containsMouse
        Basic.ToolTip.delay: 600
        Basic.ToolTip.text: mb.st === "kayit" ? "Bitir ve Claude Code'a gönder" : "Konuşarak Claude Code'a yaz"
    }

    // ── düzen ─────────────────────────────────────────────────────────────────────────────────────
    Flickable {
        anchors.fill: parent
        anchors.margins: root.gap * 2
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        Basic.ScrollBar.vertical: Basic.ScrollBar { policy: Basic.ScrollBar.AsNeeded; width: 6 }

        ColumnLayout {
            id: col
            width: parent.width
            height: Math.max(implicitHeight, root.height - root.gap * 4)
            spacing: root.gap * 1.6

            // durum: ne yapıyor, ne kadardır; mikrofon
            RowLayout {
                Layout.fillWidth: true
                spacing: root.gap
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: root.gap
                        Rectangle { Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4; color: root.stateColor(root.d.activity.state) }
                        T { text: appName; color: root.clay; font.bold: true; font.pointSize: root.fs * 0.9; Layout.fillWidth: true }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: root.gap
                        T { text: root.stateText(root.d.activity.state); color: root.stateColor(root.d.activity.state) }
                        T { text: root.dur(root.d.activity.elapsed_s); color: root.termDim; font.features: { "tnum": 1 }; Layout.fillWidth: true }
                    }
                }
                MicButton { visible: root.d.dikte === true; Layout.alignment: Qt.AlignTop }
            }
            T {
                text: root.d.activity.detail || ""
                color: root.termDim
                Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 3
                Layout.topMargin: -root.gap
            }
            T {
                visible: text !== ""
                text: root.voiceLine
                color: root.voiceColor
                Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2
            }
            ColumnLayout {
                visible: root.d.activity.progress !== null && root.d.activity.progress !== undefined
                Layout.fillWidth: true
                spacing: 2
                TermBar { frac: root.d.activity.progress ? (root.d.activity.progress.pct || 0) / 100 : 0 }
                T {
                    color: root.termDim; Layout.fillWidth: true
                    text: {
                        var p = root.d.activity.progress
                        if (!p) return ""
                        if (p.over) return "tahmini süreyi aştı · " + root.dur(p.elapsed_s) + " sürüyor"
                        return "%" + root.n(p.pct) + " · " + root.remain(p.eta_s, "")
                    }
                }
            }

            // açık arka plan oturumları: tıkla, terminalde göster
            Section {
                title: "Oturumlar"
                trailing: root.d.sekmeler.length ? root.d.sekmeler.length + " açık" : "açık oturum yok"
                Flow {
                    Layout.fillWidth: true
                    spacing: root.gap * 0.7
                    Repeater {
                        model: root.d.sekmeler
                        delegate: TermKey {
                            required property var modelData
                            width: Math.min(implicitWidth, col.width)
                            label: (modelData.durum === "busy" ? "◐ " : modelData.durum === "waiting" ? "⏸ " : "● ") + modelData.baslik
                            active: modelData.ad === root.d.secili
                            tint: modelData.durum === "waiting" ? root.amber : root.termFg
                            tip: modelData.proje + " · " + (modelData.durum === "busy" ? "çalışıyor" : modelData.durum === "waiting" ? "onay bekliyor" : "boşta")
                            onClicked: arka.sekmeSec(modelData.ad)
                        }
                    }
                    TermKey {
                        visible: root.d.secili !== ""
                        label: root.confirmClose === root.d.secili ? "Emin misin? ✕" : "✕"
                        tint: root.confirmClose === root.d.secili ? root.red : root.termDim
                        tip: "Seçili oturumu kapat (sohbet kaydı kalır, sonra yine açılabilir)"
                        onClicked: {
                            if (root.confirmClose !== root.d.secili) { root.confirmClose = root.d.secili; closeReset.restart(); return }
                            root.confirmClose = ""
                            arka.sekmeKapat(root.d.secili)
                        }
                    }
                }
            }

            // proje ve sohbet seç, arka planda aç
            Section {
                title: "Sohbet aç"
                TermCombo {
                    model: root.projList.map(function (p) { return p.name + "  ·  " + (p.mtime ? root.ago(p.mtime) : "henüz sohbet yok") })
                    onActivated: (i) => { root.projCwd = root.projList[i].cwd; root.sessId = "" }
                    Binding on currentIndex { value: root.projIndex }
                }
                TermCombo {
                    model: ["+ Yeni sohbet"].concat(root.sessList.map(function (s) {
                        return (s.where === "arka" ? "● " : s.where === "terminal" ? "▣ " : "") + s.title + "  ·  " + root.ago(s.mtime) }))
                    onActivated: (i) => { root.sessId = i === 0 ? "yeni" : root.sessList[i - 1].id }
                    Binding on currentIndex { value: root.sessIndex }
                }
                TermKey {
                    Layout.fillWidth: true
                    label: "Oturum ❯"
                    tint: root.clay
                    dim: root.opening || !root.curProj
                    tip: "Seçili sohbeti (ya da yeni sohbeti) arka planda aç ve terminalde göster"
                    onClicked: {
                        if (root.opening || !root.curProj) return
                        var s = root.sessIndex === 0 ? null : root.sessList[root.sessIndex - 1]
                        arka.oturumAc(s ? (s.cwd || root.curProj.cwd) : root.curProj.cwd, s ? s.id : "yeni")
                    }
                }
                T { visible: root.notice !== ""; text: root.notice; color: root.amber; Layout.fillWidth: true; wrapMode: Text.Wrap }
            }

            // işlem: bu tur, süren araç, tahminler ve son işlemlerin süre grafiği
            Section {
                title: "İşlem"
                trailing: (root.d.activity.calls_10m || 0) + " işlem / 10 dk"
                ColumnLayout {
                    visible: root.hasTurn
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        T { text: root.turn.live ? "Bu tur" : "Son tur"; color: root.termDim }
                        T { text: root.dur(root.turn.elapsed_s) + " · " + (root.turn.ops || 0) + " işlem"; Layout.fillWidth: true; font.features: { "tnum": 1 } }
                        T {
                            text: !root.turn.live ? "bitti" : root.turn.over ? "tahmini aştı"
                                  : root.turn.eta_s !== null && root.turn.eta_s !== undefined ? "~" + root.dur(root.turn.eta_s) + " kaldı" : ""
                            color: root.turn.over ? root.amber : root.clay
                        }
                    }
                    TermBar {
                        visible: root.turn.live === true && root.turn.pct !== null && root.turn.pct !== undefined
                        frac: (root.turn.pct || 0) / 100
                        tint: root.turn.over ? root.amber : root.clay
                    }
                    T {
                        visible: root.turn.live === true
                        Layout.fillWidth: true
                        color: root.termDim
                        font.pointSize: root.fs * 0.72
                        text: root.turn.typical_s ? "önceki " + root.turn.basis + " turun ortancası " + root.dur(root.turn.typical_s)
                                                  : "bu sohbette önceki tur yok, tahmin edilemiyor"
                    }
                }
                ColumnLayout {
                    visible: root.hasOp
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        T { text: "▶ " + root.runOp.label; Layout.fillWidth: true; color: root.green }
                        T { text: root.dur(root.runOp.elapsed_s); color: root.termDim; font.features: { "tnum": 1 } }
                    }
                    TermBar { visible: root.hasProg; frac: (root.prog.pct || 0) / 100; tint: root.prog.over ? root.amber : root.green }
                    T {
                        visible: root.hasProg
                        Layout.fillWidth: true
                        color: root.termDim
                        font.pointSize: root.fs * 0.72
                        text: root.prog.over ? "benzer işlemlerden uzun sürüyor" : root.prog.kind === "gerçek" ? "%" + root.prog.pct + " · testlerin gerçek ilerlemesi"
                              : "%" + root.prog.pct + " · ~" + root.dur(root.prog.eta_s) + " kaldı · benzer " + root.prog.basis + " işleme göre"
                    }
                }
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
                        }
                        TermBar { frac: modelData.total ? (modelData.ok + modelData.bad) / modelData.total : modelData.pct / 100 }
                        T { text: root.remain(modelData.eta_s, modelData.eta_kind || ""); color: root.termDim; font.pointSize: root.fs * 0.72 }
                    }
                }
                OpsChart { visible: (root.d.activity.recent || []).length > 0; ops: root.d.activity.recent || [] }
                Repeater {
                    model: (root.d.activity.recent || []).slice(0, 3)
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: root.gap
                        T { text: "✔"; color: root.green; font.pointSize: root.fs * 0.72 }
                        T { text: modelData.label; color: root.termDim; Layout.fillWidth: true; font.pointSize: root.fs * 0.72 }
                        T { text: root.secs(modelData.dur_s); color: modelData.dur_s >= 60 ? root.amber : root.termDim; font.pointSize: root.fs * 0.72; font.features: { "tnum": 1 } }
                    }
                }
            }

            // adımlar: projenin BACKLOG.md'si (süren, sıradaki, tamamlanan)
            Section {
                visible: root.d.steps.total > 0
                title: "Adımlar"
                trailing: root.d.steps.done_n + "/" + root.d.steps.total + " · %" + Math.round(100 * root.d.steps.done_n / Math.max(root.d.steps.total, 1))
                TermBar { frac: root.d.steps.done_n / Math.max(root.d.steps.total, 1); tint: root.green }
                Repeater {
                    model: root.d.steps.left.filter(function (x) { return x.kind === "partial" || x.kind === "ready" }).slice(0, 5)
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: root.gap
                        T { text: root.stepIcon(modelData.kind); color: root.stepColor(modelData.kind) }
                        T { text: modelData.id; color: root.stepColor(modelData.kind) }
                        T { text: modelData.title; color: modelData.kind === "partial" ? root.termFg : root.termDim; Layout.fillWidth: true }
                    }
                }
                T {
                    Layout.fillWidth: true
                    color: root.termDim
                    font.pointSize: root.fs * 0.72
                    text: "✔ " + root.d.steps.done_n + " tamamlandı · ◐ " + root.d.steps.left.filter(function (x) { return x.kind === "partial" }).length
                          + " sürüyor · ○ " + root.d.steps.left.filter(function (x) { return x.kind === "ready" }).length + " sırada"
                          + (root.d.steps.done.length ? " · son: " + root.d.steps.done[root.d.steps.done.length - 1].id : "")
                }
                T {
                    visible: root.d.git.branch !== ""
                    Layout.fillWidth: true
                    font.pointSize: root.fs * 0.72
                    color: root.termDim
                    text: "⎇ " + root.d.git.branch + " · bugün " + root.d.git.today + " commit"
                          + (root.d.git.commits.length ? " · son: " + root.d.git.commits[0].subject : "")
                }
            }

            // eksikler: tamamlanması ya da ilgilenilmesi gerekenler
            Section {
                visible: (root.d.eksikler || []).length > 0
                title: "Eksikler"
                trailing: (root.d.eksikler || []).length + ""
                trailingColor: (root.d.eksikler || []).some(function (x) { return x.tur === "engel" || x.tur === "bekliyor" }) ? root.amber : root.termDim
                Repeater {
                    model: root.d.eksikler || []
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: root.gap
                        T {
                            Layout.alignment: Qt.AlignTop
                            text: modelData.tur === "engel" ? "⛔" : modelData.tur === "bekliyor" ? "⏸" : modelData.tur === "uyari" ? "!" : "·"
                            color: modelData.tur === "engel" ? root.red : modelData.tur === "bilgi" ? root.termDim : root.amber
                        }
                        T {
                            text: modelData.yazi
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            color: modelData.tur === "bilgi" ? root.termDim : root.termFg
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }

            // sistem: her zaman en altta
            Section {
                title: "Sistem"
                trailing: "disk " + root.n(root.d.metrics.disk_free_gib) + " GiB boş"
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
            T {
                Layout.fillWidth: true
                text: "Ctrl+Shift+C kopyala · Ctrl+V yapıştır · Shift+Enter yeni satır"
                color: root.termDim
                font.pointSize: root.fs * 0.68
                wrapMode: Text.Wrap
            }
        }
    }
}

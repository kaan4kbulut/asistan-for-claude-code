import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts

// Sohbetler paneli: bütün projelerin sohbetleri; aç, yeniden adlandır, başka projeye taşı, gizle, çöpe at.
// Sol kenardaki "Sohbetler" sekmesiyle soldan kayan çekmecede açılır (uygulama.py). Veri `arka.veri`'den (projeler,
// gizlenenler dahil), komutlar Arayuz yuvalarına gider; ayarlar ~/.config/asistan/sohbetler.json'da tutulur.
Rectangle {
    id: root
    color: termBg

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

    property var projeler: []
    property string projKey: ""
    property string filtre: ""
    property bool gizlileriGoster: false
    property string secili: ""      // tuşları görünen sohbet
    property string adlandirilan: ""
    property string tasinan: ""
    property string silinecek: ""   // iki aşamalı silme
    property string bildirim: ""
    property color bildirimRenk: termDim

    readonly property int toplam: projeler.reduce(function (n, p) { return n + p.sessions.filter(function (s) { return !s.gizli }).length }, 0)
    readonly property int gizliSayi: projeler.reduce(function (n, p) { return n + p.sessions.filter(function (s) { return s.gizli }).length }, 0)
    // Liste: proje başlıkları ve altlarında (aramaya uyan) sohbetler, tek düz model
    readonly property var satirlar: {
        var out = [], f = filtre.toLocaleLowerCase()
        projeler.forEach(function (p) {
            var ss = p.sessions.filter(function (s) {
                return (gizlileriGoster || !s.gizli) && (!f || s.title.toLocaleLowerCase().indexOf(f) >= 0 || p.name.toLocaleLowerCase().indexOf(f) >= 0)
            })
            if (!ss.length && f) return
            out.push({ tip: "proje", p: p, sayi: ss.length })
            ss.forEach(function (s) { out.push({ tip: "sohbet", p: p, s: s }) })
        })
        return out
    }

    function ago(t) {
        var s = Math.max(0, Date.now() / 1000 - t)
        return s < 90 ? "şimdi" : s < 3600 ? Math.round(s / 60) + " dk önce" : s < 86400 ? Math.round(s / 3600) + " sa önce"
             : Math.round(s / 86400) + " gün önce"
    }

    Connections {
        target: arka
        function onVeri(json) {
            try {
                var p = JSON.parse(json).projeler || []
                var key = JSON.stringify(p.map(function (x) {
                    return [x.id, x.sessions.map(function (s) { return [s.id, s.title, s.where, s.gizli === true, s.tasindi === true] })] }))
                if (key !== root.projKey) { root.projKey = key; root.projeler = p }
            } catch (e) {}
        }
        function onBildirim(alan, yazi) {
            if (alan !== "sohbet") return
            root.bildirim = yazi
            root.bildirimRenk = yazi.indexOf("!") === 0 ? root.amber : root.termDim
            bildirimSil.restart()
        }
    }
    Timer { id: bildirimSil; interval: 6000; onTriggered: root.bildirim = "" }
    Timer { id: silSifirla; interval: 4000; onTriggered: root.silinecek = "" }

    component T: Text {
        color: root.termFg
        font.family: root.mono
        font.pointSize: root.fs * 0.8
        elide: Text.ElideRight
    }
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
            anchors.centerIn: parent
            text: tk.label
            color: tk.active ? root.clay : tk.tint
            font.family: root.mono
            font.pointSize: root.fs * 0.76
        }
        MouseArea { id: tkMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tk.clicked() }
        Basic.ToolTip.visible: tk.tip !== "" && tkMouse.containsMouse
        Basic.ToolTip.delay: 500
        Basic.ToolTip.text: tk.tip
    }
    component Giris: Basic.TextField {  // çerçeveli giriş kutusu, odakta turuncu
        id: gi
        color: root.termFg
        selectionColor: root.clay
        selectedTextColor: root.termBg
        placeholderTextColor: root.termDim
        font.family: root.mono
        font.pointSize: root.fs * 0.8
        leftPadding: root.gap * 1.5
        background: Rectangle {
            radius: 6
            color: root.paneBg
            border.width: 1
            border.color: gi.activeFocus ? root.clay : Qt.rgba(1, 1, 1, 0.22)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.gap * 2
        spacing: root.gap

        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap * 0.7
            T { text: "──"; color: Qt.rgba(1, 1, 1, 0.25) }
            T { text: "Sohbetler"; color: root.clay; font.bold: true }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Qt.rgba(1, 1, 1, 0.12) }
            T { text: root.toplam + " sohbet" + (root.gizliSayi ? " · " + root.gizliSayi + " gizli" : ""); color: root.termDim }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap
            Giris {
                Layout.fillWidth: true
                placeholderText: "❯ ara: sohbet ya da proje adı"
                onTextChanged: root.filtre = text
            }
            TermKey {
                visible: root.gizliSayi > 0
                label: root.gizlileriGoster ? "◌ gizlenenler açık" : "◌ gizlenenler"
                active: root.gizlileriGoster
                tip: "Gizlenen sohbetleri de göster (geri getirmek için)"
                onClicked: root.gizlileriGoster = !root.gizlileriGoster
            }
        }
        T {
            visible: root.bildirim !== ""
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: root.bildirim.replace(/^!/, "")
            color: root.bildirimRenk
        }

        ListView {
            id: liste
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: root.satirlar
            boundsBehavior: Flickable.StopAtBounds
            Basic.ScrollBar.vertical: Basic.ScrollBar { policy: Basic.ScrollBar.AsNeeded; width: 6 }
            delegate: Loader {
                required property var modelData
                width: liste.width - 8
                sourceComponent: modelData.tip === "proje" ? projeSatiri : sohbetSatiri
                property var veri: modelData
            }
        }
    }

    Component {
        id: projeSatiri
        RowLayout {
            spacing: root.gap * 0.7
            height: implicitHeight + root.gap
            T { text: "▸"; color: root.clay; Layout.topMargin: root.gap }
            T {
                text: parent.parent.veri.p.name
                color: root.clay
                font.bold: true
                Layout.topMargin: root.gap
            }
            T { text: parent.parent.veri.sayi + " sohbet"; color: root.termDim; Layout.fillWidth: true; Layout.topMargin: root.gap }
            TermKey {
                Layout.topMargin: root.gap
                label: "+ yeni"
                tint: root.clay
                tip: "Bu projede yeni bir sohbet aç (" + parent.parent.veri.p.cwd + ")"
                onClicked: arka.oturumAc(parent.parent.veri.p.cwd, "yeni")
            }
        }
    }

    Component {
        id: sohbetSatiri
        Rectangle {
            id: sat
            readonly property var s: parent ? parent.veri.s : ({})
            readonly property var p: parent ? parent.veri.p : ({})
            readonly property bool acik: root.secili === s.id || hover.hovered || root.adlandirilan === s.id || root.tasinan === s.id
            implicitHeight: kol.implicitHeight + root.gap
            radius: 4
            color: root.secili === s.id ? Qt.rgba(1, 1, 1, 0.06) : hover.hovered ? Qt.rgba(1, 1, 1, 0.04) : "transparent"
            HoverHandler { id: hover }
            TapHandler { onTapped: root.secili = root.secili === sat.s.id ? "" : sat.s.id }
            ColumnLayout {
                id: kol
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: root.gap * 0.5; leftMargin: root.gap * 2 }
                spacing: 3
                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.gap
                    T {
                        text: sat.s.where === "arka" ? "●" : sat.s.where === "terminal" ? "▣" : sat.s.gizli ? "◌" : "·"
                        color: sat.s.where === "arka" ? root.green : sat.s.where === "terminal" ? root.amber : root.termDim
                    }
                    T {
                        visible: root.adlandirilan !== sat.s.id
                        text: sat.s.title + (sat.s.tasindi ? "  ⇄" : "")
                        color: sat.s.gizli ? root.termDim : root.termFg
                        Layout.fillWidth: true
                    }
                    Giris {
                        id: adKutusu
                        visible: root.adlandirilan === sat.s.id
                        Layout.fillWidth: true
                        placeholderText: "yeni ad (boş: Claude'un başlığı)"
                        onVisibleChanged: if (visible) { text = sat.s.adlandirildi ? sat.s.title : ""; forceActiveFocus(); selectAll() }
                        onAccepted: { arka.sohbetAdlandir(sat.s.id, text); root.adlandirilan = "" }
                        Keys.onEscapePressed: root.adlandirilan = ""
                    }
                    T { text: root.ago(sat.s.mtime); color: root.termDim; font.pointSize: root.fs * 0.72 }
                }
                Flow {
                    visible: sat.acik && root.tasinan !== sat.s.id
                    Layout.fillWidth: true
                    spacing: root.gap * 0.7
                    TermKey {
                        label: sat.s.where === "arka" ? "Göster ❯" : "Aç ❯"
                        tint: root.clay
                        tip: sat.s.where === "terminal" ? "Bu sohbet bir terminal penceresinde açık: önce onu kapat" : "Arka planda aç ve terminalde göster"
                        dim: sat.s.where === "terminal"
                        onClicked: if (sat.s.where !== "terminal") arka.oturumAc(sat.s.cwd || sat.p.cwd, sat.s.id)
                    }
                    TermKey {
                        label: root.adlandirilan === sat.s.id ? "✓ kaydet" : "✎ ad"
                        active: root.adlandirilan === sat.s.id
                        tip: "Yeniden adlandır (Asistan'da hemen; Claude'a sohbet bir sonraki açılışında bu adla açılır)"
                        onClicked: {
                            if (root.adlandirilan === sat.s.id) { arka.sohbetAdlandir(sat.s.id, adKutusu.text); root.adlandirilan = "" }
                            else { root.tasinan = ""; root.adlandirilan = sat.s.id }
                        }
                    }
                    TermKey {
                        label: "⇄ taşı"
                        tip: "Başka bir projenin altında göster"
                        onClicked: { root.adlandirilan = ""; root.tasinan = sat.s.id }
                    }
                    TermKey {
                        label: sat.s.gizli ? "◉ göster" : "◌ gizle"
                        tip: sat.s.gizli ? "Listelere geri getir" : "Listelerden gizle (silinmez; '◌ gizlenenler' ile görünür)"
                        onClicked: arka.sohbetGizle(sat.s.id, !sat.s.gizli)
                    }
                    TermKey {
                        label: root.silinecek === sat.s.id ? "Emin misin? ✕" : "✕ sil"
                        tint: root.silinecek === sat.s.id ? root.red : root.termDim
                        dim: sat.s.where !== ""
                        tip: sat.s.where !== "" ? "Açık sohbet silinemez: önce kapat" : "Çöp kutusuna taşı (oradan geri alınabilir)"
                        onClicked: {
                            if (sat.s.where !== "") return
                            if (root.silinecek !== sat.s.id) { root.silinecek = sat.s.id; silSifirla.restart(); return }
                            root.silinecek = ""
                            arka.sohbetSil(sat.s.id)
                        }
                    }
                }
                Flow {  // taşı: hedef proje
                    visible: root.tasinan === sat.s.id
                    Layout.fillWidth: true
                    spacing: root.gap * 0.7
                    T { text: "taşı →"; color: root.termDim; height: root.gu * 0.9; verticalAlignment: Text.AlignVCenter }
                    Repeater {
                        model: root.projeler.filter(function (x) { return x.id !== sat.p.id })
                        delegate: TermKey {
                            required property var modelData
                            label: modelData.name
                            onClicked: { arka.sohbetTasi(sat.s.id, modelData.id); root.tasinan = "" }
                        }
                    }
                    TermKey {
                        visible: sat.s.tasindi === true
                        label: "↩ kendi projesi"
                        tint: root.clay
                        onClicked: { arka.sohbetTasi(sat.s.id, "-"); root.tasinan = "" }
                    }
                    TermKey { label: "vazgeç"; tint: root.termDim; onClicked: root.tasinan = "" }
                }
            }
        }
    }
}

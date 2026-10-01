import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts

// Test çekmecesinin üstü: projelerin son sürümü / önizlemesi / yan yana / en son kodla yenile. Sol üstteki "Test"
// sekmesine basınca soldan içeri kayan panelde görünür (uygulama.py Cekmece); bir sürüm seçilince panel genişler ve
// önizleme bunun altında açılır. Veri: `arka.veri` (testler), açık olan: `acik` ("proje:hangisi", Python verir).
Rectangle {
    id: root
    color: termBg
    implicitHeight: col.implicitHeight + gap * 3

    readonly property color clay: "#D77757"
    readonly property color termBg: "#1C1B19"
    readonly property color termFg: "#E8E5DF"
    readonly property color termDim: "#8F8C86"
    readonly property color green: "#4EBA65"
    readonly property color amber: "#E0B34F"
    readonly property string mono: yaziAilesi
    readonly property real fs: yaziBoyu
    readonly property real gu: Math.round(fs * 1.9)
    readonly property real gap: 6
    property var testler: []
    property string acik: ""
    property string uyari: ""
    property bool genis: false  // önizleme açıkken satırlar yan yana (yer var)

    Connections {
        target: arka
        function onVeri(json) {
            try {
                var t = JSON.parse(json).testler || []
                if (JSON.stringify(t) !== JSON.stringify(root.testler)) root.testler = t
            } catch (e) {}
        }
        function onBildirim(alan, yazi) { if (alan === "test") root.uyari = yazi }
    }

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

    ColumnLayout {
        id: col
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: root.gap * 2 }
        spacing: root.gap * 1.2

        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap * 0.7
            T { text: "──"; color: Qt.rgba(1, 1, 1, 0.25) }
            T { text: "Test"; color: root.clay; font.bold: true }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Qt.rgba(1, 1, 1, 0.12) }
            T {
                text: root.uyari || (root.testler.length ? root.testler.length + " proje · son sürüm · önizleme · ⇆ yan yana"
                                                          : "test projesi tanımlı değil")
                color: root.uyari ? root.amber : root.termDim
                Layout.maximumWidth: root.width * 0.7
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: root.gap * 2
            Repeater {
                model: root.testler
                delegate: ColumnLayout {
                    id: tr
                    required property var modelData
                    readonly property var son: modelData.surumler.son
                    readonly property var oniz: modelData.surumler.onizleme
                    readonly property var fark: modelData.farklar
                    width: root.genis ? Math.max(implicitWidth, root.gu * 13) : col.width
                    spacing: 3
                    RowLayout {
                        Layout.fillWidth: true
                        T { text: tr.modelData.ad; Layout.fillWidth: true }
                        T {
                            text: tr.fark.sayi ? "Δ" + tr.fark.sayi : tr.son.tur === "yok" ? "" : "="
                            color: tr.fark.sayi ? root.clay : root.termDim
                            HoverHandler { id: dh }
                            Basic.ToolTip.visible: dh.hovered && text !== ""
                            Basic.ToolTip.delay: 400
                            Basic.ToolTip.text: tr.fark.sayi ? "Önizleme son sürümden " + tr.fark.sayi + " commit ileride:\n"
                                  + tr.fark.commitler.slice(0, 8).map(function (c) { return c.hash + "  " + c.konu }).join("\n")
                                  : "Son sürüm ile önizleme aynı kodda"
                        }
                    }
                    Row {
                        spacing: root.gap * 0.7
                        TermKey {
                            label: (tr.son.calisiyor ? "● " : "○ ") + "son"
                            tint: tr.son.calisiyor ? root.green : root.termFg
                            active: root.acik === tr.modelData.id + ":son"
                            dim: tr.son.tur === "yok"
                            tip: tr.son.tur === "yok" ? "Son sürüm: " + tr.son.neden
                                 : "Son sürüm · " + tr.son.etiket + (tr.son.commit ? " · " + tr.son.commit : "")
                                   + (tr.son.calisiyor ? " · çalışıyor" : " · kapalı, açınca başlar")
                            onClicked: if (tr.son.tur !== "yok") arka.testAc(tr.modelData.id, "son")
                        }
                        TermKey {
                            label: (tr.oniz.calisiyor ? "● " : "○ ") + "önizleme"
                            tint: tr.oniz.calisiyor ? root.clay : root.termFg
                            active: root.acik === tr.modelData.id + ":onizleme"
                            tip: "Önizleme · " + tr.oniz.etiket + (tr.oniz.commit ? " · " + tr.oniz.commit : "")
                                 + (tr.fark.kirli ? " + kaydedilmemiş değişiklikler" : "")
                                 + (tr.oniz.calisiyor ? " · çalışıyor" : " · kapalı, açınca başlar")
                            onClicked: arka.testAc(tr.modelData.id, "onizleme")
                        }
                        TermKey {
                            label: "⇆"
                            active: root.acik === tr.modelData.id + ":karsilastir"
                            dim: tr.son.tur === "yok"
                            tip: tr.son.tur === "yok" ? "Karşılaştırmak için son sürüm gerekli" : "Son sürüm ile önizleme yan yana · aradaki " + tr.fark.sayi + " commit"
                            onClicked: if (tr.son.tur !== "yok") arka.testAc(tr.modelData.id, "karsilastir")
                        }
                        TermKey {
                            visible: tr.oniz.yenilenir
                            label: "↻" + (tr.fark.geride ? " " + tr.fark.geride : "")
                            tint: tr.fark.geride ? root.amber : root.termDim
                            tip: tr.fark.geride ? "Depoda önizlemeye aktarılmamış " + tr.fark.geride + " commit var · önizlemeyi en son kodla yeniden başlat"
                                                : "Önizlemeyi en son kodla yeniden başlat"
                            onClicked: arka.testYenile(tr.modelData.id)
                        }
                    }
                }
            }
        }
    }
}

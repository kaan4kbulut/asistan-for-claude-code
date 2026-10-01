import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

// Üst çubukta CPU sıcaklığının yanında "RTX 53 °C". Sistem monitörünün NVIDIA algılayıcısı kartı hiç uyutmuyordu
// (nvidia-smi dmon sürekli açık kalır); bu öğe scripts/veri.py --gpu okur: uyuyan kart sorulmaz, uyanık kart en çok
// 15 sn'de bir sorulur.
PlasmoidItem {
    id: root
    property var g: ({ sleeping: null })
    readonly property bool asleep: root.g.sleeping === true
    readonly property string value: root.asleep ? "uykuda" : (root.g.temp === null || root.g.temp === undefined) ? "—" : Math.round(root.g.temp) + " °C"

    preferredRepresentation: compactRepresentation
    toolTipMainText: "NVIDIA ekran kartı"
    toolTipSubText: root.asleep
        ? "Güç tasarrufunda. Uyandırmamak için sıcaklığı okunmuyor."
        : root.g.util === null || root.g.util === undefined ? "Okunamadı"
        : "Kullanım %" + Math.round(root.g.util) + " · " + Math.round(root.g.temp) + " °C · " + Number(root.g.power).toFixed(0)
          + " W · VRAM " + (root.g.vram / 1024).toFixed(1) + " / " + (root.g.vram_total / 1024).toFixed(0) + " GiB"

    P5Support.DataSource {
        engine: "executable"
        connectedSources: ["\"$HOME/.local/bin/asistan\" gpu"]
        interval: 5000
        onNewData: (source, data) => { try { root.g = JSON.parse(data["stdout"]) } catch (e) {} }
    }

    compactRepresentation: MouseArea {
        Layout.minimumWidth: row.implicitWidth + Kirigami.Units.smallSpacing
        Layout.preferredWidth: Layout.minimumWidth
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded
        RowLayout {
            id: row
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing
            Rectangle {  // yanındaki CPU öğesinin renkli çizgisi gibi
                Layout.preferredWidth: 3
                Layout.preferredHeight: label.implicitHeight * 0.9
                radius: 1
                color: "#D67047"
            }
            PlasmaComponents.Label { id: label; text: "RTX" }
            PlasmaComponents.Label { text: root.value; opacity: root.asleep ? 0.6 : 1; font.features: { "tnum": 1 } }
        }
    }
    fullRepresentation: PlasmaComponents.Label {
        text: root.toolTipSubText
        padding: Kirigami.Units.largeSpacing
    }
}

import QtQuick
import qs.Commons

// The pad as it actually looks: a yellow body, four columns by three rows, the
// top row in yellow caps and the other eight dark, and a dark right-hand panel
// carrying two knobs with the 1/2/3 layer legend between them.
//
// Drawn rather than photographed so it can respond: a bound control is lit, the
// hovered one lifts, and the whole thing recolours with the desktop theme. A
// screenshot would be prettier for one theme and wrong for every other.
Item {
  id: root

  property var service
  property int layerIndex: 0
  property string selected: ""
  signal picked(string control)

  // 21 units across: 0.7 margin, the 4×3 keys, a 0.7 gap, the knob panel,
  // 0.74 margin. The gap after the fourth column is the same as the margin
  // before the first, as it is on the real pad.
  readonly property real unit: Math.min(width / 21, height / 11)
  implicitWidth: 560
  implicitHeight: 300

  // Body
  Rectangle {
    id: body
    anchors.centerIn: parent
    width: root.unit * 20.4
    height: root.unit * 10.6
    radius: root.unit * 1.1
    color: "#E8C33A"
    border.width: Math.max(1, root.unit * 0.08)
    border.color: Qt.darker("#E8C33A", 1.25)

    // ---------------------------------------------------------------- keys
    Grid {
      id: keys
      columns: 4
      rows: 3
      spacing: root.unit * 0.32
      x: root.unit * 0.7
      y: root.unit * 0.7

      Repeater {
        model: 12
        delegate: Item {
          required property int index
          width: root.unit * 2.85
          height: root.unit * 2.85

          readonly property string control: "k" + (index + 1)
          readonly property bool topRow: index < 4
          readonly property var action: root.service
            ? root.service.bindingFor(root.layerIndex, control) : null
          readonly property bool bound: !!action
          readonly property bool isSelected: root.selected === control

          Rectangle {
            id: cap
            anchors.fill: parent
            anchors.margins: mouse.containsMouse ? -root.unit * 0.08 : 0
            radius: root.unit * 0.42
            // Keycap colours are the physical ones. The top row really is
            // yellow on this pad, and keeping that makes the picture findable
            // at a glance rather than a generic grid of squares.
            color: topRow ? "#F0CE4E" : "#2E2E2E"
            border.width: isSelected ? Math.max(2, root.unit * 0.16)
                                     : Math.max(1, root.unit * 0.06)
            border.color: isSelected ? Color.accent
              : (bound ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.55)
                       : Qt.darker(cap.color, 1.4))
            Behavior on anchors.margins { NumberAnimation { duration: 90 } }

            // A bound control gets a dot. The label underneath says what it
            // does, but the dot survives being too small to read.
            Rectangle {
              visible: bound && !label.visible
              anchors.centerIn: parent
              width: root.unit * 0.5; height: width; radius: width / 2
              color: Color.accent
            }

            Text {
              id: label
              anchors.fill: parent
              anchors.margins: root.unit * 0.28
              visible: bound && root.unit > 13
              text: action ? (action.label || action.keys || action.run || "") : ""
              color: topRow ? "#1A1A1A" : "#F2F2F2"
              font.family: Style.font.family
              font.pixelSize: Math.max(8, root.unit * 0.52)
              wrapMode: Text.Wrap
              horizontalAlignment: Text.AlignHCenter
              verticalAlignment: Text.AlignVCenter
              elide: Text.ElideRight
              maximumLineCount: 3
            }

            MouseArea {
              id: mouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.picked(control)
            }
          }
        }
      }
    }

    // -------------------------------------------------------- right panel
    Rectangle {
      id: sidePanel
      x: root.unit * 13.76
      y: root.unit * 0.55
      width: root.unit * 5.9
      height: root.unit * 9.5
      radius: root.unit * 0.5
      color: "#12211C"

      // The green LED. Lit for layer one on the real pad; here it tracks OUR
      // layer, which is the one that actually decides anything.
      Rectangle {
        x: root.unit * 0.45; y: root.unit * 0.45
        width: root.unit * 0.55; height: width; radius: width / 2
        color: root.service && root.service.daemonRunning ? "#3BE06B" : "#2A4034"
        Rectangle {
          anchors.centerIn: parent
          width: parent.width * 2.4; height: width; radius: width / 2
          color: parent.color
          opacity: root.service && root.service.daemonRunning ? 0.18 : 0
        }
      }

      // The 1 2 3 legend, silkscreened on the real thing. The active layer is
      // the bright one.
      Column {
        x: root.unit * 0.5
        anchors.verticalCenter: parent.verticalCenter
        spacing: root.unit * 0.1
        Repeater {
          model: root.service ? Math.max(1, root.service.layers.length) : 3
          delegate: Text {
            required property int index
            text: index + 1
            font.family: Style.font.family
            font.pixelSize: root.unit * 0.85
            font.bold: index === root.layerIndex
            color: index === root.layerIndex ? "#5FD3FF" : "#2C5A6B"
          }
        }
      }

      KnobGraphic {
        id: knobTop
        service: root.service
        layerIndex: root.layerIndex
        selected: root.selected
        knob: 1
        capColor: "#F0B93E"
        unit: root.unit
        x: parent.width - root.unit * 4.3
        y: root.unit * 0.35
        onPicked: function (c) { root.picked(c) }
      }

      KnobGraphic {
        id: knobBottom
        service: root.service
        layerIndex: root.layerIndex
        selected: root.selected
        knob: 2
        capColor: "#3A3A3A"
        unit: root.unit
        x: parent.width - root.unit * 4.3
        y: parent.height - root.unit * 4.35
        onPicked: function (c) { root.picked(c) }
      }
    }
  }
}

import QtQuick
import qs.Commons

// One knob, and the three things it can do. The two arrows are its rotations
// and the cap itself is its press, so all three are hit targets rather than a
// single control with hidden extras — a knob press is easy to forget exists.
Item {
  id: root

  property var service
  property int layerIndex: 0
  property string selected: ""
  property int knob: 1
  property color capColor: "#3A3A3A"
  property real unit: 14
  signal picked(string control)

  width: unit * 3.9
  height: unit * 3.9

  function control(part) { return "knob" + knob + "_" + part }
  function bound(part) {
    return service ? !!service.bindingFor(layerIndex, control(part)) : false
  }

  // Cap = press
  Rectangle {
    id: cap
    anchors.centerIn: parent
    width: root.unit * 2.5
    height: width
    radius: width / 2
    color: root.capColor
    border.width: root.selected === root.control("press")
      ? Math.max(2, root.unit * 0.16) : Math.max(1, root.unit * 0.07)
    border.color: root.selected === root.control("press") ? Color.accent
      : (root.bound("press") ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.6)
                             : Qt.darker(root.capColor, 1.5))
    scale: pressMouse.containsMouse ? 1.06 : 1.0
    Behavior on scale { NumberAnimation { duration: 90 } }

    Rectangle {
      visible: root.bound("press")
      anchors.centerIn: parent
      width: root.unit * 0.42; height: width; radius: width / 2
      color: Color.accent
    }

    MouseArea {
      id: pressMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.picked(root.control("press"))
    }
  }

  Repeater {
    model: [
      { part: "left",  glyph: "◀", side: -1 },
      { part: "right", glyph: "▶", side: 1 }
    ]
    delegate: Item {
      required property var modelData
      width: root.unit * 0.95
      height: root.unit * 1.5
      anchors.verticalCenter: parent.verticalCenter
      x: modelData.side < 0
        ? root.width / 2 - root.unit * 2.15
        : root.width / 2 + root.unit * 1.2

      readonly property string c: root.control(modelData.part)

      Rectangle {
        anchors.fill: parent
        radius: root.unit * 0.22
        color: arrowMouse.containsMouse
          ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.22)
          : "transparent"
        border.width: root.selected === c ? Math.max(2, root.unit * 0.13) : 0
        border.color: Color.accent

        Text {
          anchors.centerIn: parent
          text: modelData.glyph
          font.pixelSize: root.unit * 0.8
          color: root.bound(modelData.part) ? Color.accent : "#4A6B60"
        }

        MouseArea {
          id: arrowMouse
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: root.picked(c)
        }
      }
    }
  }
}

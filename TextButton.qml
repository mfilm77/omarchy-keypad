import QtQuick
import qs.Commons
import qs.Ui

// A button with a word on it. `PanelActionButton` is icon-only — it has no
// `text` property at all — and an editor whose actions are three unlabelled
// glyphs would be a guessing game.
BorderSurface {
  id: root

  property string text: ""
  property bool primary: false
  signal clicked()

  implicitWidth: label.implicitWidth + Style.space(28)
  implicitHeight: Style.space(32)
  radius: Style.cornerRadius > 0 ? Style.cornerRadius : 4
  color: primary
    ? Style.selectedFillFor(Color.foreground, Color.accent)
    : Style.controlFill(false, mouse.containsMouse, Color.foreground, Color.accent)
  borderSpec: Border.controlSpec(
    primary ? "selected" : (mouse.containsMouse ? "hover-cursor" : "normal"),
    Color.foreground, Color.accent)

  Text {
    id: label
    anchors.centerIn: parent
    text: root.text
    color: root.primary ? Color.accent : Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.bold: root.primary
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: root.clicked()
  }
}

import QtQuick
import qs.Commons
import qs.Ui

// Which layer is live, in the bar. Without it a software layer is invisible:
// the pad's own 1/2/3 light tracks its firmware layer, which no longer decides
// anything once this plugin is driving it.
BarWidget {
  id: root
  moduleName: "vlad.keypad"

  // The shell hands a plugin service to panels by assignment, but a bar
  // widget has to ask for it.
  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor("vlad.keypad") : null
  readonly property bool showName: setting("showName", true)
  readonly property bool live: service ? (service.daemonRunning && service.padConnected) : false
  readonly property string transport: service
    ? [service.usbConnected ? "USB" : "", service.bluetoothConnected ? "Bluetooth" : ""].filter(Boolean).join(" + ")
    : ""
  // NOT `layer`: Item already has a FINAL property by that name and shadowing
  // it stops the widget loading at all.
  readonly property int layerIndex: service ? service.activeLayer : 0
  readonly property string layerName: service ? service.activeLayerName : ""

  // Computed in a function with a catch: while the shell reloads a plugin the
  // service is deleted under a live binding, and QML then reads its
  // properties as "of null" even past a null check.
  function tooltip() {
    try {
      if (!root.live) {
        return root.service && root.service.daemonRunning
          ? "Keypad · no pad connected" : "Keypad · not running"
      }
      var b = root.service.bluetoothBattery
      return "Keypad over " + root.transport
        + (b >= 0 ? " (battery " + b + "%)" : "")
        + " · layer " + (root.layerIndex + 1)
        + (root.layerName ? " (" + root.layerName + ")" : "")
        + "\nClick to edit what the keys do"
    } catch (e) {
      return "Keypad"
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: root.vertical ? button.implicitHeight : root.barSize

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: {
      var icon = "󰌌"
      if (root.vertical) return icon
      var n = String(root.layerIndex + 1)
      if (root.showName && root.layerName) return icon + " " + root.layerName
      return icon + " " + n
    }
    dimmed: !root.live
    useActiveColor: true
    activeColor: bar ? bar.urgent : Color.urgent
    fontSize: Style.font.body
    horizontalMargin: 6
    verticalPadding: 2
    tooltipText: root.tooltip()
    onPressed: {
      if (!bar || !bar.shell) return
      if (typeof bar.shell.toggle === "function") bar.shell.toggle("vlad.keypad", "{}")
      else if (typeof bar.shell.summon === "function") bar.shell.summon("vlad.keypad", "{}")
    }
  }
}

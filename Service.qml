import QtQuick
import Quickshell
import Quickshell.Io

// The bit that is always loaded: it owns the config file and the running state,
// so the panel can be summoned and dismissed without losing either.
//
// It does NOT read the pad. That happens in `bin/keypadd.py`, because grabbing
// an input device exclusively needs a real file descriptor held open for the
// life of the session, and the grab is the whole point — without it the pad
// keeps typing `a`-`l` into whatever has focus.
Item {
  id: root

  // Headless. The shell instantiates one of these per plugin and hands it to
  // the panel and the bar widget through `shell.serviceFor(...)`.
  visible: false
  width: 0
  height: 0

  readonly property string configDir: Quickshell.env("HOME") + "/.config/omarchy-keypad"
  readonly property string configPath: configDir + "/config.json"
  readonly property string statePath: Quickshell.env("XDG_RUNTIME_DIR") + "/omarchy-keypad.state"

  // The whole config, as the file has it. Written back wholesale on save.
  property var config: ({ device: { vendor: "1189", product: "8840" }, layers: [] })
  property int activeLayer: 0
  property string activeLayerName: ""
  property bool daemonRunning: false
  property string lastError: ""

  readonly property var layers: config && config.layers ? config.layers : []

  // Every control the pad has, in the order the panel draws them. The names are
  // the daemon's too, so what the file says and what the picture shows agree.
  readonly property var keyIds: [
    "k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8", "k9", "k10", "k11", "k12"
  ]
  readonly property var knobIds: [
    "knob1_left", "knob1_press", "knob1_right",
    "knob2_left", "knob2_press", "knob2_right"
  ]

  function bindingFor(layerIndex, control) {
    if (layerIndex < 0 || layerIndex >= layers.length) return null
    var b = layers[layerIndex].bindings
    return b && b[control] ? b[control] : null
  }

  function setBinding(layerIndex, control, action) {
    if (layerIndex < 0 || layerIndex >= layers.length) return
    // Rebuilt rather than mutated: QML does not see a property change when the
    // inside of a var object is edited, so the panel would keep the old label.
    var next = JSON.parse(JSON.stringify(config))
    if (!next.layers[layerIndex].bindings) next.layers[layerIndex].bindings = ({})
    if (action === null) delete next.layers[layerIndex].bindings[control]
    else next.layers[layerIndex].bindings[control] = action
    config = next
    save()
  }

  function renameLayer(layerIndex, name) {
    if (layerIndex < 0 || layerIndex >= layers.length) return
    var next = JSON.parse(JSON.stringify(config))
    next.layers[layerIndex].name = name
    config = next
    save()
  }

  function save() {
    configFile.setText(JSON.stringify(config, null, 2))
    // The daemon rereads on SIGHUP, so a change is live without dropping the
    // grab — restarting the unit would release the pad for a moment and let a
    // keypress through as a stray letter.
    reloadProc.running = true
  }

  FileView {
    id: configFile
    path: root.configPath
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        var parsed = JSON.parse(text())
        if (parsed && parsed.layers) root.config = parsed
        root.lastError = ""
      } catch (e) {
        // Keep whatever is already loaded. A half-written file during an
        // external edit must not wipe the bindings the panel is showing.
        root.lastError = "config.json is not valid JSON"
      }
    }
  }

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        var s = JSON.parse(text())
        root.activeLayer = s.layer || 0
        root.activeLayerName = s.name || ""
        root.daemonRunning = true
      } catch (e) {
        root.daemonRunning = false
      }
    }
  }

  Process { id: reloadProc; command: ["systemctl", "--user", "reload-or-restart", "omarchy-keypad.service"] }

  Process {
    id: statusProc
    command: ["systemctl", "--user", "is-active", "omarchy-keypad.service"]
    stdout: StdioCollector {
      onStreamFinished: root.daemonRunning = text.trim() === "active"
    }
  }

  Timer {
    interval: 5000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: if (!statusProc.running) statusProc.running = true
  }
}

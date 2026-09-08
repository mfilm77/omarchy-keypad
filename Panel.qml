import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// The editor. A picture of the pad, a row of layer tabs, and an action form for
// whichever control is selected.
//
// Clicking the thing you want to change is the whole design: these pads have no
// legends, so a list of eighteen rows called "k7" would need the user to press
// keys to find out which is which.
//
// A control can run a shell command or press a keyboard shortcut. Shortcuts are
// recorded, not typed: click the box, press the chord, done.
PanelWindow {
  id: root

  property var service
  property var shell: null
  property var manifest: null
  property int layerIndex: 0
  property string selected: ""

  // The editor's own state. "command" or "shortcut"; the recorded chord as
  // shown to the user ("SUPER + 1") and as evdev codes for the daemon.
  property string mode: "command"      // "command" | "shortcut" | "app"
  property string appId: ""            // desktop id chosen in app mode
  property bool recording: false
  property string recKeys: ""
  property var recCodes: []
  property string recPending: ""

  readonly property string pluginId: manifest && manifest.id ? manifest.id : "io.github.mfilm77.keypad"

  // The shell summons a panel by calling open() and hides it by calling
  // close(). Closing from inside goes back through shell.hide() rather than
  // just hiding the window, or the shell still believes this panel is open and
  // the next summon toggles it shut instead of showing it.
  function open(payloadJson) { root.visible = true; root.syncEditor(); root.syncLayerName() }
  function close() { root.cancelRecording(); root.visible = false }
  function dismiss() {
    root.cancelRecording()
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else root.visible = false
  }

  visible: false
  anchors { top: true; bottom: true; left: true; right: true }
  color: "transparent"
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.namespace: "omarchy-keypad"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

  readonly property var action: service && selected
    ? service.bindingFor(layerIndex, selected) : null

  onSelectedChanged: syncEditor()
  onLayerIndexChanged: { syncEditor(); syncLayerName() }
  onActionChanged: syncEditor()

  // Watch the layer list through a binding rather than a Connections element:
  // the service is assigned after creation, and Connections warns about a
  // handler with no matching signal while its target is still null.
  readonly property var layersWatch: service ? service.layers : null
  onLayersWatchChanged: syncLayerName()

  // The fields are set, not bound: a TextField binding breaks the moment the
  // user types, so a bound `text:` would go stale on the next selection.
  function syncEditor() {
    cancelRecording()
    var a = root.action
    labelField.text = a ? (a.label || "") : ""
    runField.text = a && a.type !== "shortcut" ? (a.run || "") : ""
    if (a && a.type === "shortcut") {
      mode = "shortcut"
      recKeys = a.keys || ""
      recCodes = a.codes || []
      appId = ""
    } else if (a && a.app) {
      mode = "app"
      appId = a.app
      recKeys = ""
      recCodes = []
    } else {
      mode = "command"
      appId = ""
      recKeys = ""
      recCodes = []
    }
    appPicker.value = appId
  }

  // Every installed app with a launcher entry, for the "Open an app" picker.
  // Read from the same DesktopEntries the shell's own launcher uses, so what
  // is offered here is exactly what SUPER+SPACE offers.
  readonly property var appOptions: {
    var values = DesktopEntries.applications.values || []
    var out = []
    for (var i = 0; i < values.length; i++) {
      var e = values[i]
      if (!e || e.noDisplay) continue
      out.push({ value: String(e.id), label: String(e.name || e.id),
                 description: String(e.genericName || e.comment || "") })
    }
    out.sort(function (a, b) { return a.label.toLowerCase() < b.label.toLowerCase() ? -1 : 1 })
    return out
  }
  function shellQuote(value) {
    return "'" + String(value || "").replace(/'/g, "'\\''") + "'"
  }
  function appName(id) {
    for (var i = 0; i < appOptions.length; i++)
      if (appOptions[i].value === id) return appOptions[i].label
    return id
  }

  function syncLayerName() {
    if (!service || layerIndex < 0 || layerIndex >= service.layers.length) return
    if (!nameField.activeFocus) nameField.text = service.layers[layerIndex].name || ""
  }

  function prettyName(control) {
    if (!control) return ""
    if (control.indexOf("k") === 0 && control.length <= 3)
      return "Key " + control.substring(1)
    var parts = control.split("_")
    var knob = parts[0] === "knob1" ? "Top knob" : "Bottom knob"
    if (parts[1] === "left") return knob + " · turn left"
    if (parts[1] === "right") return knob + " · turn right"
    return knob + " · press"
  }

  // ------------------------------------------------------------ recording
  //
  // Hyprland runs its binds before a key reaches any window, and a consumed
  // key never arrives: press SUPER+1 here and the panel would see SUPER go
  // down, then the workspace change. So while recording, a Hyprland submap
  // with no useful binds is entered (bin/keypad-record-mode) and every chord
  // falls through to us. It is left again the instant a chord lands, on
  // Escape, on close, or after 20 seconds in case something goes wrong.
  function startRecording() {
    if (recording) return
    recPending = ""
    recording = true
    recordModeStart.running = true
    recorder.forceActiveFocus()
    recordTimeout.restart()
  }
  function stopRecording() {
    if (!recording) return
    recording = false
    recPending = ""
    recordTimeout.stop()
    recordModeStop.running = true
    catcher.forceActiveFocus()
  }
  function cancelRecording() { stopRecording() }

  function isModifierKey(key) {
    return key === Qt.Key_Shift || key === Qt.Key_Control || key === Qt.Key_Alt
      || key === Qt.Key_AltGr || key === Qt.Key_Meta || key === Qt.Key_Super_L
      || key === Qt.Key_Super_R || key === Qt.Key_Hyper_L || key === Qt.Key_Hyper_R
  }

  function keyName(event) {
    var k = event.key
    var names = {}
    names[Qt.Key_Return] = "RETURN"; names[Qt.Key_Enter] = "ENTER"
    names[Qt.Key_Space] = "SPACE"; names[Qt.Key_Tab] = "TAB"
    names[Qt.Key_Backtab] = "TAB"; names[Qt.Key_Backspace] = "BACKSPACE"
    names[Qt.Key_Delete] = "DELETE"; names[Qt.Key_Insert] = "INSERT"
    names[Qt.Key_Home] = "HOME"; names[Qt.Key_End] = "END"
    names[Qt.Key_PageUp] = "PAGE UP"; names[Qt.Key_PageDown] = "PAGE DOWN"
    names[Qt.Key_Up] = "UP"; names[Qt.Key_Down] = "DOWN"
    names[Qt.Key_Left] = "LEFT"; names[Qt.Key_Right] = "RIGHT"
    names[Qt.Key_Print] = "PRINT"; names[Qt.Key_Menu] = "MENU"
    names[Qt.Key_VolumeUp] = "VOLUME UP"; names[Qt.Key_VolumeDown] = "VOLUME DOWN"
    names[Qt.Key_VolumeMute] = "MUTE"; names[Qt.Key_MediaPlay] = "PLAY"
    names[Qt.Key_MediaNext] = "NEXT"; names[Qt.Key_MediaPrevious] = "PREVIOUS"
    if (names[k]) return names[k]
    if (k >= Qt.Key_F1 && k <= Qt.Key_F35) return "F" + (k - Qt.Key_F1 + 1)
    if (k >= 0x20 && k < 0x100) return String.fromCharCode(k).toUpperCase()
    if (event.text && event.text.length === 1) return event.text.toUpperCase()
    return "KEY " + k
  }

  // Only used when the compositor gives no scancode. Qt's Wayland backend
  // reports the xkb keycode (evdev + 8) as nativeScanCode, which covers every
  // key, so this is the safety net rather than the path.
  function fallbackCode(key) {
    var m = {}
    var letters = "QWERTYUIOP"; var codes = [16,17,18,19,20,21,22,23,24,25]
    for (var i = 0; i < letters.length; i++) m[letters.charCodeAt(i)] = codes[i]
    letters = "ASDFGHJKL"; codes = [30,31,32,33,34,35,36,37,38]
    for (i = 0; i < letters.length; i++) m[letters.charCodeAt(i)] = codes[i]
    letters = "ZXCVBNM"; codes = [44,45,46,47,48,49,50]
    for (i = 0; i < letters.length; i++) m[letters.charCodeAt(i)] = codes[i]
    letters = "1234567890"; codes = [2,3,4,5,6,7,8,9,10,11]
    for (i = 0; i < letters.length; i++) m[letters.charCodeAt(i)] = codes[i]
    m[Qt.Key_Space] = 57; m[Qt.Key_Return] = 28; m[Qt.Key_Tab] = 15
    m[Qt.Key_Backspace] = 14; m[Qt.Key_Delete] = 111; m[Qt.Key_Home] = 102
    m[Qt.Key_End] = 107; m[Qt.Key_PageUp] = 104; m[Qt.Key_PageDown] = 109
    m[Qt.Key_Up] = 103; m[Qt.Key_Down] = 108; m[Qt.Key_Left] = 105
    m[Qt.Key_Right] = 106; m[Qt.Key_Insert] = 110; m[Qt.Key_Minus] = 12
    m[Qt.Key_Equal] = 13
    if (key >= Qt.Key_F1 && key <= Qt.Key_F10) return 59 + (key - Qt.Key_F1)
    if (key === Qt.Key_F11) return 87
    if (key === Qt.Key_F12) return 88
    return m[key] || 0
  }

  function captureKey(event) {
    event.accepted = true
    if (event.key === Qt.Key_Escape) { cancelRecording(); return }
    var mods = event.modifiers
    var names = [], codes = []
    if (mods & Qt.MetaModifier)    { names.push("SUPER"); codes.push(125) }
    if (mods & Qt.ControlModifier) { names.push("CTRL");  codes.push(29) }
    if (mods & Qt.AltModifier)     { names.push("ALT");   codes.push(56) }
    if (mods & Qt.ShiftModifier)   { names.push("SHIFT"); codes.push(42) }
    if (isModifierKey(event.key)) {
      // A modifier on its own is not a shortcut yet — show it building up.
      recPending = names.join(" + ")
      return
    }
    var code = event.nativeScanCode >= 9 ? event.nativeScanCode - 8
                                         : fallbackCode(event.key)
    if (code <= 0) { recPending = "That key is not recognised, try another"; return }
    names.push(keyName(event))
    codes.push(code)
    recKeys = names.join(" + ")
    recCodes = codes
    stopRecording()
  }

  function saveBinding() {
    if (!service || !selected) return
    if (mode === "app") {
      if (!appId) { recPending = "Pick an app first"; return }
      // Launched the way the shell's launcher does it: gtk-launch resolves the
      // desktop entry, uwsm-app puts it in its own scope under the session.
      service.setBinding(layerIndex, selected, ({
        type: "command",
        label: labelField.text || appName(appId),
        app: appId,
        run: "uwsm-app -- gtk-launch " + shellQuote(appId + ".desktop")
      }))
      return
    }
    if (mode === "shortcut") {
      if (!recCodes || recCodes.length === 0) {
        recPending = "Record a shortcut first"
        return
      }
      service.setBinding(layerIndex, selected, ({
        type: "shortcut",
        label: labelField.text || recKeys,
        keys: recKeys,
        codes: recCodes
      }))
    } else {
      service.setBinding(layerIndex, selected, ({
        type: "command",
        label: labelField.text,
        run: runField.text
      }))
    }
  }

  Process { id: recordModeStart; command: [Quickshell.env("HOME") + "/.config/omarchy/plugins/io.github.mfilm77.keypad/bin/keypad-record-mode", "start"] }
  Process { id: recordModeStop;  command: [Quickshell.env("HOME") + "/.config/omarchy/plugins/io.github.mfilm77.keypad/bin/keypad-record-mode", "stop"] }
  Timer { id: recordTimeout; interval: 20000; onTriggered: root.cancelRecording() }

  Rectangle {
    anchors.fill: parent
    color: Qt.rgba(0, 0, 0, 0.72)
    MouseArea { anchors.fill: parent; onClicked: root.dismiss() }
  }

  BorderSurface {
    anchors.centerIn: parent
    width: Style.space(880)
    implicitHeight: content.implicitHeight + Style.space(40)
    radius: Style.cornerRadius > 0 ? Style.cornerRadius + 2 : 8
    color: Color.popups.background
    borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border,
      Math.max(1, Style.space(2)))

    MouseArea { anchors.fill: parent; onClicked: {} }

    Column {
      id: content
      anchors { left: parent.left; right: parent.right; top: parent.top
                margins: Style.space(22) }
      spacing: Style.spacing.sm

      // ------------------------------------------------------------ header
      Row {
        width: parent.width
        spacing: Style.spacing.sm

        Column {
          width: parent.width - Style.space(330)
          Text {
            text: "Keypad"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
            font.bold: true
          }
          Text {
            text: {
              if (!root.service || !root.service.daemonRunning)
                return "Not running — the pad is not being read"
              if (!root.service.padConnected)
                return "No pad connected — plug it in or pair it"
              var over = []
              if (root.service.usbConnected) over.push("USB")
              if (root.service.bluetoothConnected) over.push("Bluetooth")
              return "Connected over " + over.join(" + ") + " · layer " + (root.layerIndex + 1)
            }
            color: root.service && root.service.daemonRunning && root.service.padConnected
              ? Qt.darker(Color.foreground, 1.4) : Color.urgent
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        // The two lights. One per transport, lit while the daemon holds a
        // pad on it, so "connected" is never a guess.
        Row {
          spacing: Style.space(28)
          anchors.verticalCenter: parent.verticalCenter
          Repeater {
            model: [
              { glyph: "󰕓", label: "USB", key: "usb" },
              { glyph: "󰂯", label: "Bluetooth", key: "bluetooth" }
            ]
            delegate: Row {
              required property var modelData
              readonly property bool on: root.service
                ? (modelData.key === "usb" ? root.service.usbConnected
                                           : root.service.bluetoothConnected)
                : false
              spacing: Style.spacing.xs
              anchors.verticalCenter: parent.verticalCenter
              Rectangle {
                width: Style.space(9); height: width; radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                color: on ? "#3BE06B" : Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.18)
                border.width: 1
                border.color: on ? Qt.lighter("#3BE06B", 1.3) : Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.3)
                Rectangle {
                  visible: on
                  anchors.centerIn: parent
                  width: parent.width * 2.2; height: width; radius: width / 2
                  color: "#3BE06B"; opacity: 0.18
                }
              }
              Text {
                text: {
                  var t = modelData.glyph + " " + modelData.label
                  if (on && modelData.key === "bluetooth" && root.service.bluetoothBattery >= 0)
                    t += " · " + root.service.bluetoothBattery + "%"
                  return t
                }
                color: on ? Color.foreground : Qt.darker(Color.foreground, 1.8)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                font.bold: on
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }
        }

        Button {
          iconText: "󰅖"
          tooltipText: "Close (Esc)"
          anchors.verticalCenter: parent.verticalCenter
          onClicked: root.dismiss()
        }
      }

      PanelSeparator { foreground: Color.foreground }

      // ------------------------------------------------------- layer tabs
      //
      // One layer per app is the intended use — "Resolve", "Signal", "Blender"
      // — so the tab you are on can be renamed right here.
      Row {
        width: parent.width
        spacing: Style.spacing.xs
        Repeater {
          model: root.service ? root.service.layers.length : 0
          delegate: BorderSurface {
            required property int index
            readonly property bool active: index === root.layerIndex
            width: Style.space(120)
            height: Style.space(34)
            radius: Style.cornerRadius > 0 ? Style.cornerRadius : 4
            color: active ? Style.selectedFillFor(Color.foreground, Color.accent)
                          : Style.controlFill(false, tabMouse.containsMouse,
                              Color.foreground, Color.accent)
            borderSpec: Border.controlSpec(
              active ? "selected" : (tabMouse.containsMouse ? "hover-cursor" : "normal"),
              Color.foreground, Color.accent)

            Text {
              anchors.centerIn: parent
              text: (index + 1) + " · " + (root.service.layers[index].name || "Layer")
              color: active ? Color.accent : Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: active
              elide: Text.ElideRight
              width: parent.width - Style.space(14)
              horizontalAlignment: Text.AlignHCenter
            }
            MouseArea {
              id: tabMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: { root.layerIndex = index; root.selected = "" }
            }
          }
        }

        Item { width: Style.space(12); height: 1 }

        Text {
          text: "Rename"
          color: Qt.darker(Color.foreground, 1.4)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          anchors.verticalCenter: parent.verticalCenter
        }
        TextField {
          id: nameField
          width: Style.space(200)
          placeholderText: "e.g. Resolve"
          foreground: Color.foreground
          accent: Color.accent
          anchors.verticalCenter: parent.verticalCenter
          onAccepted: { root.service.renameLayer(root.layerIndex, text); catcher.forceActiveFocus() }
          onEditingFinished: {
            if (root.service && root.layerIndex < root.service.layers.length
                && text !== (root.service.layers[root.layerIndex].name || ""))
              root.service.renameLayer(root.layerIndex, text)
          }
        }
      }

      // ----------------------------------------------------------- the pad
      PadGraphic {
        width: parent.width
        height: Style.space(300)
        service: root.service
        layerIndex: root.layerIndex
        selected: root.selected
        onPicked: function (control) { root.selected = control }
      }

      PanelSeparator { foreground: Color.foreground }

      // -------------------------------------------------------- the editor
      Column {
        width: parent.width
        spacing: Style.spacing.xs
        visible: root.selected !== ""

        PanelSectionHeader {
          text: root.prettyName(root.selected).toUpperCase()
          foreground: Color.foreground
        }

        Row {
          width: parent.width
          spacing: Style.spacing.sm
          Text {
            text: "Name"
            width: Style.space(70)
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            anchors.verticalCenter: parent.verticalCenter
          }
          TextField {
            id: labelField
            width: parent.width - Style.space(80)
            placeholderText: "What this does, e.g. Open Signal"
            foreground: Color.foreground
            accent: Color.accent
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        // Which kind of job: a command, or a shortcut.
        Row {
          width: parent.width
          spacing: Style.spacing.sm
          Text {
            text: "Does"
            width: Style.space(70)
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            anchors.verticalCenter: parent.verticalCenter
          }
          Row {
            spacing: Style.spacing.xs
            anchors.verticalCenter: parent.verticalCenter
            TextButton {
              text: "Run a command"
              primary: root.mode === "command"
              onClicked: { root.cancelRecording(); root.mode = "command" }
            }
            TextButton {
              text: "Press a shortcut"
              primary: root.mode === "shortcut"
              onClicked: root.mode = "shortcut"
            }
            TextButton {
              text: "Open an app"
              primary: root.mode === "app"
              onClicked: { root.cancelRecording(); root.mode = "app" }
            }
          }
        }

        Row {
          width: parent.width
          spacing: Style.spacing.sm
          visible: root.mode === "app"
          Text {
            text: "Opens"
            width: Style.space(70)
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            anchors.verticalCenter: parent.verticalCenter
          }
          SearchableDropdown {
            id: appPicker
            width: parent.width - Style.space(80)
            showLabel: false
            options: root.appOptions
            placeholderText: "Type to search installed apps…"
            triggerLabel: "Choose an app"
            anchors.verticalCenter: parent.verticalCenter
            onChanged: function (v) {
              root.appId = v
              if (!labelField.text) labelField.text = root.appName(v)
            }
          }
        }

        Row {
          width: parent.width
          spacing: Style.spacing.sm
          visible: root.mode === "command"
          Text {
            text: "Runs"
            width: Style.space(70)
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            anchors.verticalCenter: parent.verticalCenter
          }
          TextField {
            id: runField
            width: parent.width - Style.space(80)
            placeholderText: "A shell command, e.g. signal-desktop"
            foreground: Color.foreground
            accent: Color.accent
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        Row {
          width: parent.width
          spacing: Style.spacing.sm
          visible: root.mode === "shortcut"
          Text {
            text: "Presses"
            width: Style.space(70)
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            anchors.verticalCenter: parent.verticalCenter
          }

          // The recorder. Click it, press the chord.
          BorderSurface {
            id: recorderBox
            width: parent.width - Style.space(80)
            height: Style.space(36)
            radius: Style.cornerRadius > 0 ? Style.cornerRadius : 4
            color: root.recording
              ? Style.selectedFillFor(Color.foreground, Color.accent)
              : Style.controlFill(false, recMouse.containsMouse, Color.foreground, Color.accent)
            borderSpec: Border.controlSpec(
              root.recording ? "focus" : (recMouse.containsMouse ? "hover-cursor" : "normal"),
              Color.foreground, Color.accent)
            anchors.verticalCenter: parent.verticalCenter

            Text {
              anchors.fill: parent
              anchors.leftMargin: Style.spacing.controlPaddingX
              verticalAlignment: Text.AlignVCenter
              text: root.recording
                ? (root.recPending ? root.recPending + " + …"
                                   : "Press the shortcut now…  (Esc cancels)")
                : (root.recKeys ? root.recKeys
                                : "Click here, then press the shortcut")
              color: root.recording ? Color.accent
                : (root.recKeys ? Color.foreground : Qt.darker(Color.foreground, 1.6))
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              font.bold: root.recording || root.recKeys !== ""
              elide: Text.ElideRight
            }

            MouseArea {
              id: recMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.startRecording()
            }

            // Takes keyboard focus while recording. Not a descendant of the
            // key catcher, so nothing else sees the chord.
            Item {
              id: recorder
              Keys.onPressed: function (event) { root.captureKey(event) }
            }
          }
        }

        Row {
          spacing: Style.spacing.xs
          TextButton {
            text: "Save"
            primary: true
            onClicked: root.saveBinding()
          }
          TextButton {
            text: "Make this the layer switch"
            onClicked: {
              root.service.setBinding(root.layerIndex, root.selected, ({
                type: "layer",
                label: "Next layer"
              }))
            }
          }
          TextButton {
            text: "Clear"
            onClicked: root.service.setBinding(root.layerIndex, root.selected, null)
          }
        }
      }

      Text {
        visible: root.selected === ""
        text: "Click a key or a knob above to give it a job."
        color: Qt.darker(Color.foreground, 1.4)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }
    }
  }

  PanelKeyCatcher {
    id: catcher
    anchors.fill: parent
    // While a chord is being recorded, or a field is being typed in, the
    // catcher must not turn keys into "close" or "move".
    blocked: root.recording || labelField.activeFocus || runField.activeFocus
             || nameField.activeFocus
    // `closeRequested`, not `onEscape`: the catcher turns raw keys into
    // intentions, so Escape and any other close key arrive on one signal.
    onCloseRequested: root.dismiss()
  }
}

# omarchy-keypad

Turns a cheap USB macropad into a programmable control surface on Omarchy.

Built for a 12-key, 2-knob pad (USB `1189:8840`, sold as a "Sikai" pad), but the
device id is in the config so any pad that reports plain keycodes will work.

## Why it exists

These pads advertise three hardware layers. On Linux the layers are a fiction:
every layer sends the same keycodes, and pressing the layer button sends nothing
at all — verified by reading the raw HID reports on both the standard and the
vendor-specific interface, where the vendor channel stayed completely silent.
Only the manufacturer's Windows tool can write different keycodes into layers 2
and 3.

So the layers here are ours. The daemon holds the layer, the bar widget shows
it, and any control can be made the switch. Name each layer after an app —
"Resolve", "Signal", "Blender" — and the same twelve keys become a different
set of keys for each.

The keys also send plain letters `a`–`l`, which cannot be used as global
hotkeys without breaking typing. The daemon therefore grabs the pad
**exclusively**, so its keys stop reaching anything else.

## Install

```bash
omarchy plugin add <repo-url> --enable --yes
sudo cp share/70-omarchy-keypad.rules /etc/udev/rules.d/
echo uinput | sudo tee /etc/modules-load.d/omarchy-keypad.conf && sudo modprobe uinput
sudo udevadm control --reload && sudo udevadm trigger
mkdir -p ~/.config/omarchy-keypad && cp share/config.default.json ~/.config/omarchy-keypad/config.json
mkdir -p ~/.config/systemd/user && cp share/omarchy-keypad.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now omarchy-keypad.service
```

The udev rule is the only step that needs root, and it grants access to this one
USB id rather than adding you to the `input` group, which would mean read access
to every keyboard on the machine. The same rule grants `/dev/uinput`, which is
where shortcut bindings are typed from; the `uinput` module has to be loaded for
that node to exist with the right permissions.

## Use

Click the bar widget. Click a key or a knob in the picture, give it a name, and
choose what it does:

- **Run a command** — any shell command, e.g. `hyprctl dispatch 'hl.dsp.focus({ workspace = "3" })'` (Hyprland 0.56+ takes Lua; older setups use `hyprctl dispatch workspace 3`).
- **Press a shortcut** — click the box, press the chord on your keyboard, and
  that is what the key will press. Recorded, not typed, so there is nothing to
  spell.

Save. Changes are live — the daemon rereads on `SIGHUP` and never drops the
grab, so no keypress escapes as a stray letter mid-edit.

To rename the layer you are on, type in the *Rename* field next to the tabs.

### How shortcut recording works

Hyprland runs its binds before a key reaches any window, and a consumed key
never arrives at all — press SUPER+1 in a plain recorder and it would see SUPER
go down, then the workspace change. While recording, the panel therefore enters
a Hyprland submap that has no useful binds (`bin/keypad-record-mode`), so every
chord falls through to it. The submap is registered at runtime the first time
it is needed; nothing is added to your Hyprland config. It is left again the
moment a chord lands, on Escape, on close, or after 20 seconds regardless.

### How shortcuts are pressed

The daemon creates a virtual keyboard through uinput and presses the recorded
keys on it. The compositor sees a real keyboard with your own keymap, so binds
written by keycode (Omarchy binds workspaces as `code:10`…) fire exactly as they
do from the physical keyboard, and app shortcuts arrive as ordinary key events.
That is why uinput rather than `wtype`: a `wtype` keymap carries its own
keycodes and misses every `code:` bind.

## Files

| Path | What |
|---|---|
| `bin/keypadd.py` | Reads the pad, holds the layer, runs commands, presses shortcuts |
| `bin/keypad-record-mode` | Enters/leaves the Hyprland submap used while recording |
| `Service.qml` | Owns the config and the running state |
| `Panel.qml` | The editor |
| `PadGraphic.qml` / `KnobGraphic.qml` | The drawing of the pad |
| `BarWidget.qml` | Current layer in the bar |
| `~/.config/omarchy-keypad/config.json` | Your bindings |

A binding in `config.json` is one of:

```json
{ "type": "command",  "label": "Workspace 3", "run": "hyprctl dispatch 'hl.dsp.focus({ workspace = \"3\" })'" }
{ "type": "shortcut", "label": "Undo", "keys": "CTRL + Z", "codes": [29, 44] }
{ "type": "layer",    "label": "Next layer" }
{ "type": "layer",    "label": "Resolve keys", "to": 1 }
```

`codes` are Linux evdev keycodes, pressed in that order and released in
reverse. `to` on a layer binding jumps to that layer (0-based) instead of
cycling.

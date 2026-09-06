#!/usr/bin/env python3
"""omarchy-keypad — turn a cheap USB macropad into a programmable control surface.

Runs as the desktop user, not root. A udev rule grants access to one device by
its USB id, so nothing here can read any other keyboard.

The pad is grabbed EXCLUSIVELY. That is what stops its keys typing letters into
whatever has focus, and it is the whole reason this exists rather than a set of
global hotkeys: the keys send plain `a`-`l`, which would be unusable as binds.

Layers are ours, not the pad's. The hardware has three, but it reports the same
keycodes on all of them and says nothing when its layer button is pressed, so
the firmware layers are invisible to any operating system. A binding of type
"layer" switches ours instead.

A binding can also be a keyboard shortcut. Those are pressed on a virtual
keyboard of our own (uinput), so the compositor sees an ordinary keyboard with
the user's own keymap and every bind fires as if a real key had been pressed.
"""

import errno
import fcntl
import json
import os
import select
import signal
import struct
import subprocess
import sys
import time

EVENT_FMT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)
EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0
EVIOCGRAB = 0x40044590

# uinput. Request numbers spelled out for the same reason as EVIOCGBIT below:
# the wrong one fails silently, and there is no python-evdev on a stock install.
UINPUT = "/dev/uinput"
UI_SET_EVBIT = 0x40045564      # _IOW('U', 100, int)
UI_SET_KEYBIT = 0x40045565     # _IOW('U', 101, int)
UI_DEV_SETUP = 0x405c5503      # _IOW('U', 3, struct uinput_setup) — 92 bytes
UI_DEV_CREATE = 0x5501         # _IO('U', 1)
UI_DEV_DESTROY = 0x5502        # _IO('U', 2)
BUS_VIRTUAL = 0x06
KEY_MAX = 0x2FF

CONFIG = os.path.expanduser("~/.config/omarchy-keypad/config.json")
STATE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "omarchy-keypad.state"
)

# The controls this pad exposes, by evdev keycode. Names match what the panel
# shows and what the config file uses, so a binding is readable on sight.
KEYCODES = {
    30: "k1", 48: "k2", 46: "k3", 32: "k4", 18: "k5", 33: "k6",
    34: "k7", 35: "k8", 23: "k9", 36: "k10", 37: "k11", 38: "k12",
    2: "knob1_left", 3: "knob1_press", 4: "knob1_right",
    5: "knob2_left", 6: "knob2_press", 7: "knob2_right",
}


def log(msg):
    print("keypadd: %s" % msg, flush=True)


def find_device(vendor, product):
    """Locate the pad's event node by USB id.

    Matched through /sys rather than by name: the product string on these pads
    is the generic "USB Composite Device", which several unrelated things also
    claim, and the event number changes on every replug.
    """
    base = "/sys/bus/usb/devices"
    for entry in sorted(os.listdir(base)):
        path = os.path.join(base, entry)
        try:
            with open(os.path.join(path, "idVendor")) as f:
                if f.read().strip().lower() != vendor.lower():
                    continue
            with open(os.path.join(path, "idProduct")) as f:
                if f.read().strip().lower() != product.lower():
                    continue
        except OSError:
            continue
        for root, dirs, _files in os.walk(path):
            for d in dirs:
                if d.startswith("event"):
                    node = "/dev/input/" + d
                    # The pad presents a keyboard and a mouse interface on the
                    # same id. Only the one that reports keys is ours.
                    if device_has_keys(node):
                        return node
    return None


def device_has_keys(node):
    try:
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        buf = bytearray(96)
        # EVIOCGBIT(EV_KEY, len) — ask which key codes this node can emit.
        # _IOC(READ, 'E', 0x20 + EV_KEY, len); spelled out because getting the
        # request number wrong fails silently as "this device has no keys".
        req = (2 << 30) | (len(buf) << 16) | (ord('E') << 8) | (0x20 + EV_KEY)
        fcntl.ioctl(fd, req, buf, True)
        for code in (30, 48, 46):  # a, b, c — the first three pad keys
            if buf[code // 8] & (1 << (code % 8)):
                return True
        return False
    except Exception:
        return False
    finally:
        os.close(fd)


def load_config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"device": {"vendor": "1189", "product": "8840"}, "layers": []}
    except (OSError, ValueError) as e:
        log("config unreadable, ignoring it: %s" % e)
        return {"device": {"vendor": "1189", "product": "8840"}, "layers": []}


def write_state(layer_index, layers):
    """Publish the current layer so the bar widget can show it.

    Written to XDG_RUNTIME_DIR: it is state about this login, not a setting,
    and it must not survive a reboot into a stale value.
    """
    name = ""
    if 0 <= layer_index < len(layers):
        name = layers[layer_index].get("name", "")
    payload = {"layer": layer_index, "name": name, "count": len(layers)}
    tmp = STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, STATE)
    except OSError as e:
        log("could not publish layer state: %s" % e)


def run_action(action):
    cmd = action.get("run", "").strip()
    if not cmd:
        return
    try:
        # setsid so a long-running program the pad launches is not killed when
        # this daemon restarts, and start_new_session keeps it off our stdin.
        subprocess.Popen(
            ["/bin/sh", "-c", cmd],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log("action failed: %s" % e)


class VirtualKeyboard:
    """A keyboard of our own, for bindings that press a shortcut.

    Made through uinput rather than a Wayland virtual-keyboard tool such as
    wtype, because the compositor then sees a real keyboard carrying the user's
    own keymap. Hyprland binds written by keycode (Omarchy binds its workspaces
    as `code:10`…) fire exactly as they do from the physical keyboard, and app
    shortcuts arrive as ordinary key events. A wtype keymap has keycodes of its
    own and misses every `code:` bind.

    Needs /dev/uinput readable by the user: the plugin's udev rule grants that
    with uaccess, the same way it grants the pad.
    """

    def __init__(self):
        self.fd = None
        self.warned = False

    def open(self):
        if self.fd is not None:
            return True
        try:
            fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if not self.warned:
                log("cannot open %s (%s) — shortcuts need the uinput line of "
                    "the udev rule and the uinput module loaded" % (UINPUT, e))
                self.warned = True
            return False
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            # Keys only. 0x100-0x1ff are the BTN_* mouse buttons; enabling
            # those makes libinput see a pointer as well as a keyboard.
            for code in list(range(1, 0x100)) + list(range(0x200, KEY_MAX + 1)):
                fcntl.ioctl(fd, UI_SET_KEYBIT, code)
            # struct uinput_setup: input_id {bustype, vendor, product, version},
            # char name[80], u32 ff_effects_max.
            setup = struct.pack("HHHH80sI", BUS_VIRTUAL, 0, 0, 1,
                                b"omarchy-keypad virtual keyboard", 0)
            fcntl.ioctl(fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError as e:
            log("could not create the virtual keyboard: %s" % e)
            os.close(fd)
            return False
        self.fd = fd
        # The compositor needs a moment to adopt a new keyboard; events sent
        # before that are dropped on the floor.
        time.sleep(0.3)
        log("virtual keyboard ready")
        return True

    def close(self):
        if self.fd is None:
            return
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None

    def _emit(self, code, value):
        now = time.time()
        sec = int(now)
        usec = int((now - sec) * 1e6)
        os.write(self.fd, struct.pack(EVENT_FMT, sec, usec, EV_KEY, code, value))
        os.write(self.fd, struct.pack(EVENT_FMT, sec, usec, EV_SYN, SYN_REPORT, 0))

    def tap(self, codes):
        """Press the codes in order, release them in reverse — SUPER then 1,
        then 1 up, then SUPER up — which is how a person presses a chord."""
        if not codes or not self.open():
            return False
        try:
            for code in codes:
                self._emit(code, 1)
                time.sleep(0.008)
            for code in reversed(codes):
                self._emit(code, 0)
                time.sleep(0.008)
        except OSError as e:
            log("shortcut failed: %s" % e)
            self.close()
            return False
        return True


def shortcut_codes(action):
    out = []
    for c in action.get("codes") or []:
        try:
            c = int(c)
        except (TypeError, ValueError):
            continue
        if 0 < c <= KEY_MAX:
            out.append(c)
    return out


class Daemon:
    def __init__(self):
        self.config = load_config()
        self.layer = 0
        self.fd = None
        self.node = None
        self.running = True
        self.keyboard = VirtualKeyboard()

    def layers(self):
        return self.config.get("layers") or []

    def binding(self, control):
        layers = self.layers()
        if not layers:
            return None
        layer = layers[self.layer % len(layers)]
        return (layer.get("bindings") or {}).get(control)

    def open_device(self):
        dev = self.config.get("device", {})
        node = find_device(dev.get("vendor", "1189"), dev.get("product", "8840"))
        if not node:
            return False
        try:
            fd = os.open(node, os.O_RDONLY)
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EPERM):
                log("no permission for %s — is the udev rule installed?" % node)
            return False
        try:
            fcntl.ioctl(fd, EVIOCGRAB, 1)
        except OSError as e:
            # Without the grab the pad would still type letters everywhere.
            # Refusing is honest; half-working would look like a bug later.
            log("could not grab %s exclusively: %s" % (node, e))
            os.close(fd)
            return False
        self.fd, self.node = fd, node
        log("grabbed %s (%s)" % (node, dev.get("vendor", "?")))
        return True

    def close_device(self):
        if self.fd is None:
            return
        try:
            fcntl.ioctl(self.fd, EVIOCGRAB, 0)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd, self.node = None, None

    def handle(self, code, value):
        if value != 1:  # presses only; releases and autorepeat are not actions
            return
        control = KEYCODES.get(code)
        if not control:
            return
        action = self.binding(control)
        if not action:
            return
        kind = action.get("type", "command")
        if kind == "layer":
            layers = self.layers()
            if layers:
                target = action.get("to")
                if isinstance(target, int):
                    self.layer = target % len(layers)
                else:
                    self.layer = (self.layer + 1) % len(layers)
                write_state(self.layer, layers)
                log("layer -> %d" % self.layer)
        elif kind == "command":
            run_action(action)
        elif kind == "shortcut":
            codes = shortcut_codes(action)
            if not codes:
                log("shortcut on %s has no keys" % control)
                return
            self.keyboard.tap(codes)

    def reload(self):
        self.config = load_config()
        layers = self.layers()
        if layers:
            self.layer %= len(layers)
        write_state(self.layer, layers)
        log("config reloaded (%d layers)" % len(layers))

    def stop(self, *_):
        self.running = False

    def run(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGHUP, lambda *_: self.reload())
        write_state(self.layer, self.layers())
        # Bring the virtual keyboard up now rather than on the first shortcut,
        # so the adoption pause is paid at login and not on a keypress. If it
        # cannot open yet it is retried on first use.
        self.keyboard.open()
        while self.running:
            if self.fd is None:
                if not self.open_device():
                    # Unplugged, or the rule is not in place yet. Poll rather
                    # than exit: a pad plugged in later should just start working.
                    time.sleep(2.0)
                    continue
            try:
                r, _, _ = select.select([self.fd], [], [], 0.5)
            except (OSError, ValueError):
                self.close_device()
                continue
            if not r:
                continue
            try:
                data = os.read(self.fd, EVENT_SIZE * 64)
            except OSError:
                log("device went away")
                self.close_device()
                continue
            if not data:
                self.close_device()
                continue
            for i in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                _, _, etype, code, value = struct.unpack(
                    EVENT_FMT, data[i:i + EVENT_SIZE]
                )
                if etype == EV_KEY:
                    self.handle(code, value)
        self.close_device()
        self.keyboard.close()
        log("stopped")


if __name__ == "__main__":
    sys.exit(Daemon().run())

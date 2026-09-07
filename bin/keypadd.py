#!/usr/bin/env python3
"""omarchy-keypad — turn a cheap USB macropad into a programmable control surface.

Runs as the desktop user, not root. A udev rule grants access to the pad by its
identity — USB id, or name + id over Bluetooth — so nothing here can read any
other keyboard.

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
import glob
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
EV_REL = 0x02
EV_ABS = 0x03
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


BUS_NAMES = {"0003": "usb", "0005": "bluetooth"}


def list_input_devices():
    """Every event node with its identity, read from sysfs.

    Looked up through /sys/class/input rather than /sys/bus/usb so the same
    pad is found whether it is plugged in or paired: over Bluetooth it is a
    uhid device with no USB ancestry at all, and a different vendor/product
    (this pad claims Apple's 05ac:022c over the air).
    """
    out = []
    for d in sorted(glob.glob("/sys/class/input/event*")):
        dev = os.path.join(d, "device")

        def rd(rel):
            try:
                with open(os.path.join(dev, rel)) as f:
                    return f.read().strip()
            except OSError:
                return ""

        out.append({
            "node": "/dev/input/" + os.path.basename(d),
            "bustype": rd("id/bustype"),
            "vendor": rd("id/vendor"),
            "product": rd("id/product"),
            "name": rd("name"),
            "uniq": rd("uniq"),
        })
    return out


def matches(info, spec):
    """A device spec is any subset of vendor, product, name, bus, uniq."""
    for key in ("vendor", "product", "uniq"):
        want = spec.get(key)
        if want and info[key].lower() != str(want).lower():
            return False
    if spec.get("name") and info["name"] != spec["name"]:
        return False
    if spec.get("bus"):
        bus = BUS_NAMES.get(info["bustype"], info["bustype"])
        if bus != spec["bus"]:
            return False
    return True


def find_devices(specs):
    """All event nodes matching any spec that actually report the pad keys.

    A pad may present a keyboard and a mouse interface on the same id (USB),
    or one combined node (Bluetooth); only nodes that emit the keys count.
    """
    nodes = []
    for info in list_input_devices():
        if any(matches(info, spec) for spec in specs):
            if device_has_keys(info["node"]):
                nodes.append(info["node"])
    return nodes


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


def device_specs(config):
    """`devices` is a list of matchers; the older single `device` still works."""
    specs = config.get("devices")
    if not specs:
        specs = [config.get("device") or {"vendor": "1189", "product": "8840"}]
    return [s for s in specs if isinstance(s, dict)]


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


def session_env():
    """Our environment plus whatever the compositor session needs.

    The daemon starts in the same second as Hyprland, before uwsm has pushed
    HYPRLAND_INSTANCE_SIGNATURE and WAYLAND_DISPLAY into the user's systemd
    environment, so a unit-inherited environment is missing both and every
    `hyprctl` a binding runs fails silently. Resolved fresh per action from
    the runtime dir instead: the newest instance dir is the live compositor.
    """
    env = dict(os.environ)
    runtime = env.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=%s/bus" % runtime)
    try:
        hypr = os.path.join(runtime, "hypr")
        sigs = sorted(
            (d for d in os.listdir(hypr) if os.path.isdir(os.path.join(hypr, d))),
            key=lambda d: os.path.getmtime(os.path.join(hypr, d)),
        )
        if sigs:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = sigs[-1]
    except OSError:
        pass
    if "WAYLAND_DISPLAY" not in env:
        socks = sorted(
            f for f in os.listdir(runtime)
            if f.startswith("wayland-") and not f.endswith(".lock")
        ) if os.path.isdir(runtime) else []
        if socks:
            env["WAYLAND_DISPLAY"] = socks[-1]
    return env


def run_action(action):
    cmd = action.get("run", "").strip()
    if not cmd:
        return
    try:
        # setsid so a long-running program the pad launches is not killed when
        # this daemon restarts, and start_new_session keeps it off our stdin.
        subprocess.Popen(
            ["/bin/sh", "-c", cmd],
            env=session_env(),
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
        self.fds = {}          # node -> fd, every grabbed pad (USB and/or Bluetooth)
        self.last_scan = 0.0
        self.seen_axes = set()
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

    def open_devices(self):
        """Grab every matching pad not already held. Called on a 2 s cadence
        so a pad plugged in or paired later just starts working."""
        self.last_scan = time.time()
        for node in find_devices(device_specs(self.config)):
            if node in self.fds:
                continue
            try:
                fd = os.open(node, os.O_RDONLY)
            except OSError as e:
                if e.errno in (errno.EACCES, errno.EPERM):
                    log("no permission for %s — is the udev rule installed?" % node)
                continue
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
            except OSError as e:
                # Without the grab the pad would still type letters everywhere.
                # Refusing is honest; half-working would look like a bug later.
                log("could not grab %s exclusively: %s" % (node, e))
                os.close(fd)
                continue
            self.fds[node] = fd
            log("grabbed %s" % node)

    def close_device(self, node):
        fd = self.fds.pop(node, None)
        if fd is None:
            return
        try:
            fcntl.ioctl(fd, EVIOCGRAB, 0)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    def handle(self, code, value):
        if value != 1:  # presses only; releases and autorepeat are not actions
            return
        control = KEYCODES.get(code)
        if not control:
            # Logged so a pad that speaks differently on another bus can be
            # mapped from the journal instead of guessed at.
            log("unmapped keycode %d" % code)
            return
        action = self.binding(control)
        if not action:
            log("%s pressed — no binding on layer %d" % (control, self.layer))
            return
        kind = action.get("type", "command")
        log("%s pressed -> %s %r" % (control, kind, action.get("label", "")))
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
            if not self.fds or time.time() - self.last_scan > 2.0:
                self.open_devices()
                if not self.fds:
                    # Unplugged, not paired, or the rule is not in place yet.
                    time.sleep(2.0)
                    continue
            try:
                r, _, _ = select.select(list(self.fds.values()), [], [], 0.5)
            except (OSError, ValueError):
                for node in list(self.fds):
                    self.close_device(node)
                continue
            for fd in r:
                node = next((n for n, f in self.fds.items() if f == fd), None)
                try:
                    data = os.read(fd, EVENT_SIZE * 64)
                except OSError:
                    log("%s went away" % node)
                    self.close_device(node)
                    continue
                if not data:
                    self.close_device(node)
                    continue
                for i in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                    _, _, etype, code, value = struct.unpack(
                        EVENT_FMT, data[i:i + EVENT_SIZE]
                    )
                    if etype == EV_KEY:
                        self.handle(code, value)
                    elif etype in (EV_REL, EV_ABS) and (etype, code) not in self.seen_axes:
                        self.seen_axes.add((etype, code))
                        log("pad sends axis events type=%d code=%d (not mapped)" % (etype, code))
        for node in list(self.fds):
            self.close_device(node)
        self.keyboard.close()
        log("stopped")


if __name__ == "__main__":
    sys.exit(Daemon().run())

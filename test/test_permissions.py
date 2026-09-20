#!/usr/bin/env python3
"""Tests for the permission state and the setup command.

Everything here runs against FAKES: os.open is monkeypatched to raise the
errno we want, and the setup command's paths are pointed at a temporary
directory. No real device, no real udev rule, no sudo, nothing installed.

    python3 test/test_permissions.py
"""
import errno
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import keypadd  # noqa: E402


def load_setup():
    spec = importlib.util.spec_from_loader(
        "keypad_setup",
        importlib.machinery.SourceFileLoader(
            "keypad_setup", os.path.join(ROOT, "bin", "keypad-setup")),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print("  %s  %s%s" % ("ok   " if cond else "FAIL ", name,
                          ("  — " + detail) if detail and not cond else ""))


# ── the defect: EACCES must not look like "no keys" ──────────────────────────

def test_device_has_keys_states():
    real_open = os.open

    def denying(*a, **k):
        raise OSError(errno.EACCES, "Permission denied")

    def absent(*a, **k):
        raise OSError(errno.ENODEV, "No such device")

    os.open = denying
    try:
        check("EACCES on the pad node returns None, not False",
              keypadd.device_has_keys("/dev/input/eventFAKE") is None)
    finally:
        os.open = real_open

    os.open = absent
    try:
        check("a genuinely absent device still returns False",
              keypadd.device_has_keys("/dev/input/eventFAKE") is False)
    finally:
        os.open = real_open


def test_find_devices_splits_denied_from_missing():
    fake = [{"node": "/dev/input/event99", "bustype": "0005", "vendor": "05ac",
             "product": "022c", "name": "MINI_KEYBOARD", "uniq": "aa:bb"}]
    real_list, real_has = keypadd.list_input_devices, keypadd.device_has_keys
    specs = [{"name": "MINI_KEYBOARD", "vendor": "05ac", "product": "022c"}]
    try:
        keypadd.list_input_devices = lambda: fake

        keypadd.device_has_keys = lambda n: None          # not allowed to look
        found, denied = keypadd.find_devices(specs)
        check("a pad we may not read lands in denied, not dropped",
              found == [] and denied == ["/dev/input/event99"],
              "found=%r denied=%r" % (found, denied))

        keypadd.device_has_keys = lambda n: True          # allowed, has keys
        found, denied = keypadd.find_devices(specs)
        check("a readable pad lands in found with its bus",
              denied == [] and found and found[0][0] == "/dev/input/event99"
              and found[0][1] == "bluetooth",
              "found=%r" % (found,))

        keypadd.device_has_keys = lambda n: False         # readable, no keys
        found, denied = keypadd.find_devices(specs)
        check("a matching node with no keys is still ignored",
              found == [] and denied == [])
    finally:
        keypadd.list_input_devices, keypadd.device_has_keys = real_list, real_has


def test_state_file_carries_denied():
    with tempfile.TemporaryDirectory() as d:
        real_state = keypadd.STATE
        keypadd.STATE = os.path.join(d, "state.json")
        try:
            keypadd.write_state(0, [{"name": "L1"}], {}, {},
                                ["/dev/input/event99"])
            payload = json.load(open(keypadd.STATE))
            check("the panel can see the permission problem in the state file",
                  payload.get("denied") == ["/dev/input/event99"],
                  "payload=%r" % payload)
        finally:
            keypadd.STATE = real_state


# ── the setup command ────────────────────────────────────────────────────────

def test_check_reports_each_missing_piece():
    s = load_setup()
    with tempfile.TemporaryDirectory() as d:
        s.UDEV_RULE = os.path.join(d, "no-rule")
        s.MODULES_CONF = os.path.join(d, "no-modconf")
        s.UNIT = os.path.join(d, "no-unit")
        s.CONFIG = os.path.join(d, "no-config")
        s.UINPUT = os.path.join(d, "no-uinput")
        s.pad_nodes = lambda: ([], [])
        by_id = {c["id"]: c for c in s.checks()}
        check("check reports the udev rule missing", by_id["udev"]["state"] == s.MISSING)
        check("check reports the bindings file missing", by_id["config"]["state"] == s.MISSING)
        check("check reports the service missing", by_id["service"]["state"] == s.MISSING)
        check("check reports no pad found", by_id["pad"]["state"] == s.MISSING)
        check("every failing check carries a fix line",
              all(c["fix"] for c in s.checks() if c["state"] != s.OK))


def test_check_distinguishes_denied_pad_from_absent_pad():
    s = load_setup()
    s.pad_nodes = lambda: ([], ["/dev/input/event99"])
    pad = {c["id"]: c for c in s.checks()}["pad"]
    check("a pad we may not read is BROKEN, not 'no pad found'",
          pad["state"] == s.BROKEN and "not allowed to read" in pad["detail"],
          pad["detail"])
    check("and it blames the rule, not the user's cable",
          "udev rule, not the pad" in pad["detail"])


def test_user_steps_never_overwrite():
    s = load_setup()
    with tempfile.TemporaryDirectory() as d:
        s.CONFIG_DIR = os.path.join(d, "cfg")
        s.CONFIG = os.path.join(s.CONFIG_DIR, "config.json")
        s.UNIT_DIR = os.path.join(d, "unit")
        s.UNIT = os.path.join(s.UNIT_DIR, "omarchy-keypad.service")
        os.makedirs(s.CONFIG_DIR)
        os.makedirs(s.UNIT_DIR)
        with open(s.CONFIG, "w") as f:
            f.write("MY BINDINGS")
        with open(s.UNIT, "w") as f:
            f.write("MY UNIT")
        s.run = lambda *a, **k: type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        s.do_user_steps()
        check("an existing bindings file is left untouched",
              open(s.CONFIG).read() == "MY BINDINGS")
        check("an existing service file is left untouched",
              open(s.UNIT).read() == "MY UNIT")


def test_root_steps_skip_when_already_present():
    s = load_setup()
    with tempfile.TemporaryDirectory() as d:
        rule = os.path.join(d, "rule")
        conf = os.path.join(d, "conf")
        uinput = os.path.join(d, "uinput")
        for p in (rule, conf, uinput):
            with open(p, "w") as f:
                f.write("x")
        s.UDEV_RULE, s.MODULES_CONF, s.UINPUT = rule, conf, uinput
        called = []
        s.subprocess = type("S", (), {"run": lambda *a, **k: called.append(a)})()
        ok = s.do_root_steps()
        check("setup is idempotent: no sudo when everything is already there",
              ok is True and not called)


if __name__ == "__main__":
    print("keypad tests (fakes only — no device, no sudo, nothing installed)\n")
    for fn in (test_device_has_keys_states,
               test_find_devices_splits_denied_from_missing,
               test_state_file_carries_denied,
               test_check_reports_each_missing_piece,
               test_check_distinguishes_denied_pad_from_absent_pad,
               test_user_steps_never_overwrite,
               test_root_steps_skip_when_already_present):
        print("%s:" % fn.__name__)
        fn()
    failed = [r for r in results if not r[1]]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    sys.exit(1 if failed else 0)

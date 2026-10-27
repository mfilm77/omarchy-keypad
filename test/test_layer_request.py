#!/usr/bin/env python3
"""Tests for the panel-requests-a-layer mechanism (poll_layer_request).

Everything here runs against a Daemon() built with its config set directly —
no real pad, no real config.json, no real XDG_RUNTIME_DIR. LAYER_REQUEST and
STATE are both pointed at a temp directory before any file is touched.

    python3 test/test_layer_request.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import keypadd  # noqa: E402

TWO_LAYERS = {"layers": [
    {"name": "Main", "bindings": {}},
    {"name": "Blender", "bindings": {}},
]}

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print("  %s  %s%s" % ("ok   " if cond else "FAIL ", name,
                          ("  — " + detail) if detail and not cond else ""))


def new_daemon(tmpdir, request_file, config=None):
    """A Daemon() with LAYER_REQUEST/STATE redirected into tmpdir, built the
    way __init__ wants them: pointed there BEFORE construction, so the
    stale-request-at-startup rule is exercised the same way it would be for
    real.
    """
    keypadd.LAYER_REQUEST = request_file
    keypadd.STATE = os.path.join(tmpdir, "state.json")
    d = keypadd.Daemon()
    d.config = config if config is not None else dict(TWO_LAYERS)
    return d


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def test_no_file_does_nothing():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        dmn = new_daemon(d, req)
        dmn.layer = 0
        dmn.poll_layer_request()
        check("no request file leaves the layer alone", dmn.layer == 0)


def test_valid_request_changes_layer():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        dmn = new_daemon(d, req)
        dmn.layer = 0
        write(req, "1")
        dmn.poll_layer_request()
        check("a fresh, in-range request switches the live layer",
              dmn.layer == 1, "layer=%r" % dmn.layer)
        check("it is published to the state file",
              os.path.exists(keypadd.STATE))


def test_out_of_range_is_ignored():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        dmn = new_daemon(d, req)
        dmn.layer = 0
        write(req, "5")   # only 2 layers configured
        dmn.poll_layer_request()
        check("an index past the end of the layer list is ignored",
              dmn.layer == 0, "layer=%r" % dmn.layer)


def test_negative_is_ignored():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        dmn = new_daemon(d, req)
        dmn.layer = 1
        write(req, "-1")
        dmn.poll_layer_request()
        check("a negative index is ignored", dmn.layer == 1)


def test_garbage_is_ignored_not_raised():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        dmn = new_daemon(d, req)
        dmn.layer = 0
        write(req, "not-a-number\n")
        try:
            dmn.poll_layer_request()
            ok = True
        except Exception as e:
            ok = False
            print("      raised:", e)
        check("garbage in the request file never raises", ok)
        check("...and leaves the layer untouched", dmn.layer == 0)


def test_empty_config_is_ignored():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        dmn = new_daemon(d, req, config={"layers": []})
        dmn.layer = 0
        write(req, "0")
        dmn.poll_layer_request()
        check("a request against an empty layer list is a no-op", dmn.layer == 0)


def test_stale_request_from_before_startup_is_not_applied():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        # Written BEFORE the daemon exists — a leftover from a previous run,
        # or the panel racing the service's own restart.
        write(req, "1")
        dmn = new_daemon(d, req)
        dmn.layer = 0
        dmn.poll_layer_request()
        check("a request already on disk at startup is treated as handled",
              dmn.layer == 0, "layer=%r" % dmn.layer)


def test_same_layer_twice_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "layer-request")
        dmn = new_daemon(d, req)
        dmn.layer = 1
        write(req, "1")
        dmn.poll_layer_request()
        check("requesting the layer already live changes nothing",
              dmn.layer == 1)
        # A second, later write of the same value must not raise or misbehave.
        time.sleep(0.01)
        write(req, "1")
        try:
            dmn.poll_layer_request()
            ok = True
        except Exception as e:
            ok = False
            print("      raised:", e)
        check("a repeat of the same value is harmless", ok and dmn.layer == 1)


if __name__ == "__main__":
    print("layer-request tests (fakes only — no device, no real config, no real XDG_RUNTIME_DIR)\n")
    for fn in (test_no_file_does_nothing,
               test_valid_request_changes_layer,
               test_out_of_range_is_ignored,
               test_negative_is_ignored,
               test_garbage_is_ignored_not_raised,
               test_empty_config_is_ignored,
               test_stale_request_from_before_startup_is_not_applied,
               test_same_layer_twice_is_idempotent):
        print("%s:" % fn.__name__)
        fn()
    failed = [r for r in results if not r[1]]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    sys.exit(1 if failed else 0)

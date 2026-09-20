# Backlog

Work queued for the next release. Nothing here is pushed on its own: the marketplace
listing's verification is pinned to a commit, so **every push to `main` flips the card to
`Update unverified`** until it is re-verified. Batch the work, cut one release, verify once.

Commit locally as you go; push only when cutting a release.

---

## Before the next push — not code

- Author identity on the pre-release commits was reset to the GitHub noreply
  address before this batch was pushed. Nothing else queued here.

---

## Done, waiting for the release

- **1 — the hold bug.** `hold` action type added: the daemon now reads key
  releases, presses the chord on key-down and lets it go on key-up, and drops
  everything held if a pad disappears mid-hold or the daemon stops. The editor
  offers *Tap it* / *Hold while the key is down* on a recorded shortcut.
  **Not yet run on a live machine** — only `py_compile` and `qmllint`.
- **2 — command presets.** 89 commands in `share/presets.json` across 9
  categories, behind a searchable picker in the editor. Every command verified
  on a live Omarchy 4 box: shell commands resolve to real binaries, `hl.dsp.*`
  functions confirmed through `hyprctl eval` (side-effect free, unlike
  dispatching them).

- **4 — a fresh install works first time.** `bin/keypad-setup` does the
  user-level setup itself, prints the three root steps before running them in a
  single `sudo`, and never overwrites an existing rule, unit or bindings file.
  `--check` lists every prerequisite with a fix line; `--json` feeds the panel.
  README rewritten around that one command. **Verified end-to-end on
  omarchy-zeus**, a machine that had the plugin directory and nothing else:
  after setup, all five checks green and the daemon grabbed the Bluetooth pad.

- **5 — a permission problem now says so.** `device_has_keys` answered `False`
  for both "no keys" and "not allowed to look", so a connected pad with no udev
  rule was dropped and the panel said *"No pad connected — plug it in or pair
  it"*. It also made the EACCES branch in `open_devices()` unreachable. Now
  `None` for EACCES/EPERM, carried through `find_devices` → daemon log → state
  file → panel: *"Cannot read the pad — run keypad-setup in a terminal"*.
  Tests in `test/test_permissions.py` (fakes only). **The pad-press path itself
  is still only proven by the daemon grabbing the device** — see gate below.

- **3 — name the hardware, and ask about future keypads.** The marketplace card
  showed only "a cheap USB macropad", so nobody browsing could tell which pad it
  drives. The manifest description now names the Sikai pad and its USB id, and
  the README intro carries the unbranded search terms too, for the case where
  somebody buys one of these pads later and goes looking for Linux support.
  Added a README section asking whether people would want a keypad built for
  this properly — deliberately an interest check, with nothing for sale and
  nothing to pre-order.

Before the release: run 1 and 2 on a real pad, then push once and re-verify the
listing.

---

## Not in the repo — chase separately

- **The `Input` tag was never applied.** The submission suggested it; the
  marketplace registry lists us as `hyprland, quickshell, system` only, so the
  plugin does not appear when browsing for input/keyboard hardware. Tags live in
  the marketplace registry, not in our manifest, so this needs a request to the
  marketplace rather than a commit here.
- **Pinned interest thread — LIVE.** [#1 "Would you want a keypad built properly
  for this?"](https://github.com/mfilm77/omarchy-keypad/issues/1), created and
  pinned 2026-09-12. The README links straight to it. Expect it quiet until the
  release push puts the card in front of people again — early silence is not the
  answer. Check reactions and comments when cutting the release.

---

## Bugs

### 1. A shortcut binding cannot hold a key down — FIXED, UNTESTED ON HARDWARE
`VirtualKeyboard.tap()` (`bin/keypadd.py`) presses the codes in order and releases them in
reverse, 8 ms apart — the whole chord is over in about 16 ms. Any binding whose target
distinguishes key-down from key-up therefore does nothing at all, silently.

Found with Omarchy's own dictation, which is push-to-talk
(`/usr/share/omarchy/default/hypr/bindings/voxtype.lua`):

```lua
o.bind("F9", "Start dictation (push-to-talk)", "voxtype record start")
o.bind("F9", "Stop dictation (push-to-talk)",  "voxtype record stop", { release = true })
```

Binding a pad key to `F9` starts and instantly stops the recorder, so it captures about a
hundredth of a second and transcribes nothing. The editor happily records the chord and the
daemon happily reports `k9 pressed -> shortcut 'Dictation'`, so nothing anywhere says it
failed. Worked around by binding the command `voxtype record toggle` instead, which is the
better answer for a pad key anyway — but the editor should not be able to produce a binding
that cannot work.

Fix needs two pieces:
- **The daemon does not track key release.** It acts on key-down only. Holding a chord for as
  long as the pad key is held means reading the release event and mapping it back to the
  binding that is down.
- **An action that expresses it.** Either a `hold` action type (press on key-down, release on
  key-up) or a `hold_ms` field on `shortcut`. A hold action is the honest one: push-to-talk
  wants the real duration, not a guessed number.

Until then the editor should at least say so — a note under the recorder that a chord is
tapped, not held, and that hold-style binds want a command instead.

---

## Features

### 2. Command presets in the editor — DONE, UNTESTED ON HARDWARE
Right now the command mode is an empty text field: you have to know that
`omarchy-menu toggle capture` exists and type it exactly. Ship a catalogue of ~50+ ready-made
commands (menus, capture, audio, windows, workspaces, apps, system) as
`share/presets.json`, and put a `SearchableDropdown` above the Runs field that fills in both
the label and the command. The dropdown component already exists — the "Open an app" mode
uses it.

Presets are drawn from Omarchy's own binding files, so the labels and commands are its
wording rather than ours. Choosing a preset must stay editable: it fills the field, it does
not lock it.

---

## Documentation / unverified

### 3. Which physical knob is A and which is B
The pad's two knobs send `1`/`2`/`3` and `4`/`5`/`6`. Which of those is the upper (yellow)
knob and which the lower (black) one was never confirmed at the hardware, nor which rotation
direction is "up". The config and the drawing assume one arrangement. One-line swap in
`config.json` if the assumption is backwards.

### 4. Key order is assumed
Key 1 = `a` … key 12 = `l`, read left-to-right, top-to-bottom. Taken from the order the keys
were pressed during the capture session, never verified key by key. If it is wrong, the
drawing's positions do not match the physical pad.

---

## In this batch — knob 1 pauses instead of muting

Vlad, 2026-09-19: *"one of the knobs mutes the sound and I didn't want to mute the
sound, I wanted to pause the sound that is coming from any playback."*

Shipped: `bin/keypad-media-pause-all` — pauses every MPRIS player reporting
`Playing`, remembers exactly which, and resumes only those on the next press.
Pure `busctl`, no playerctl dependency. Bound to `knob1_press` on the Main and
Media default layers; mute stays on the System layer and in the presets.
`keypadd.py` now puts the plugin's `bin/` on PATH for actions, so a binding can
name the script plainly.

**Still worth doing, not done here:**

- The action is a *command* binding like any other. A first-class action type
  (`{"type": "media", "action": "pause-all"}`) would let the editor show it as a
  named behaviour with its own icon rather than a shell string. Bigger change to
  `Panel.qml` and `Service.qml` than this fix warranted.
- The resume state file is `$XDG_RUNTIME_DIR/omarchy-keypad.paused-players`.
  It is not shown anywhere; the panel could surface "3 players paused".
- Untested against Spotify and VLC — both expose MPRIS, but neither was running
  on the machine this was verified on.

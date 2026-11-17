# Anti-Backfire

A small add-on that runs beside the **Rogue Lineage Assist Tool** (Roblox) and keeps you from backfiring spells.

In Rogue Lineage a spell only casts safely while your mana bar is inside that spell's range. Click outside it
and the spell backfires. Anti-Backfire reads the mana bar the same way the Assist Tool does and casts for you
only when it is safe.

## What it does

- **Cast key (X).** With a listed spell in your hand, X sends the real click (right click for a snap, left
  click otherwise) only while mana is inside the spell's range. Outside the range X does nothing. The spell
  never leaves your hand, so mana shield (F) keeps working.
- **Viribus safe backcast.** A spell named "Viribus" is not held back out of range: X backfires it on purpose
  and mana-shields the blast for you (click, then F at a precisely timed moment).
- **Quick cast keys.** One key press equips the chosen spell if needed, charges mana up to just above the
  minimum (or waits for it to drain down into the range) and casts.
- **Chat pause.** `/` pauses every key of the add-on until Enter or a mouse click, like the Assist Tool.
- **Roblox only.** Nothing happens unless Roblox is the active window. F9 switches it on and off.

Your own mouse clicks are not touched and not protected: Roblox reads the mouse directly, so no program can
take a real click away from it without a driver. Cast with the cast key instead.

## Requirements

- Windows, Python 3.11 or newer (only the standard library is used)
- The Rogue Lineage Assist Tool, with its mana bar and hotbar positions set up. Anti-Backfire reads its
  `cooldown_indicator_config.json` from the folder above this one.

## Setup (about 2 minutes)

1. **Set up the Rogue Lineage Assist Tool first.** Start it, use "Find Mana Bar", and make sure all 12 hotbar
   slots are filled so it finds your hotbar. It saves this in `cooldown_indicator_config.json` next to its exe.
2. **Install Python** from [python.org](https://www.python.org/downloads/) if you don't have it (3.11 or newer).
3. **Download this repo** (green "Code" button → "Download ZIP"), unzip it, and put the folder **inside the folder
   that holds the Assist Tool's `.exe`**.
4. **Make the shortcut:** double-click `create_shortcut.py` (or run `py create_shortcut.py`). It finds the Assist
   Tool and puts a shortcut called **Rogue Lineage Assist Tool + Anti-Backfire** in the tool's folder and on your
   Desktop.
5. **Double-click that shortcut.** It starts the Assist Tool and Anti-Backfire together; Anti-Backfire runs
   silently and closes when the tool closes. Double-click it again while they run to open the settings, then list
   your spells, their mana ranges and your quick cast keys.

### Finding the Assist Tool's settings

You don't have to point Anti-Backfire at anything. It finds `cooldown_indicator_config.json` on its own, in
this order:

1. the file you picked before,
2. the folder of the Assist Tool while it is running,
3. the folder this add-on sits in, and the one above it,
4. a short search of your Desktop, Documents and Downloads (3 folders deep).

If it still can't find it (the settings window opens and says so), click **Find main tool config…** and pick
the file yourself. If the tool is started later, Anti-Backfire notices within a few seconds.

### Running it without the shortcut

Start `Anti-Backfire.pyw` (or `anti_backfire.py`). It runs in the background without a window; start it again to
open the settings. `--launch-tool` also starts the Assist Tool and closes together with it.

### Defaults to check

- **Leeway** starts at 2 % (for Fallion training). Set it to 0 if you don't have it.
- **Snap Snarvindur** is pre-filled at 20–30 %. Check every range against your own spells.
- **Viribus backcast timing** (F 488 ms after the click, held 579 ms) was measured on one PC; adjust it in the
  settings if your mana shield comes up too early or too late.

## How it knows things

- **Mana %**: a thin strip of pixels inside the mana bar. The game's empty-bar colour marks where the fill ends.
- **Spell in hand**: the white (held) hotbar slot, with hotbar key presses as a fallback while a cooldown box
  covers the slot.

Nothing it reads is saved or sent anywhere.

## Tests

`tests/` holds simulated-game tests (no screen access, no real input). Each takes the add-on folder and the
path of a `cooldown_indicator_config.json`:

```
python tests/test_cast_key.py . ../cooldown_indicator_config.json
python tests/test_quick_cast.py . ../cooldown_indicator_config.json
python tests/test_viribus_timing.py . ../cooldown_indicator_config.json
```

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

## Running it

Put this folder next to the Assist Tool, then start `Anti-Backfire.pyw` (or `anti_backfire.py`). It runs in the
background without a window. Start it again to open the settings, where you list your spells, their mana
ranges, the quick cast keys and the timings.

`--launch-tool` also starts the Assist Tool and closes together with it.

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

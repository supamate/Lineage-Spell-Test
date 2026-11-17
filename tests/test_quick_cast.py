"""Simulated game for: quick cast, Viribus safe backcast, chat pause. No screen, no real input."""
import sys, types, ctypes
sys.path.insert(0, sys.argv[1])
import anti_backfire as ab

clock = [1000.0]
ab.time = types.SimpleNamespace(time=lambda: clock[0], strftime=lambda *a: '', sleep=lambda s: None)
ab.log = lambda m: None
mc = ab.MainConfig(sys.argv[2])
SPELLS = [{'on': True, 'name': 'Snap Snarvindur', 'key': '-', 'click': 'left', 'lo': 20.0, 'hi': 30.0},   # 'left' on purpose
          {'on': True, 'name': 'Telorum', 'key': '7', 'click': 'left', 'lo': 80.0, 'hi': 90.0},
          {'on': True, 'name': 'Viribus', 'key': '=', 'click': 'left', 'lo': 25.0, 'hi': 35.0}]
REAL = {'-': ('right', 18, 32), '7': ('left', 78, 92), '=': ('left', 23, 37)}
QUICK = [{'key': 'y', 'spell': 'Snap Snarvindur'}, {'key': 'h', 'spell': 'Telorum'}, {'key': 'z', 'spell': 'Viribus'}]
DT = 0.008
X, Y, H, Z, SLASH, ENTER = 0x2D, 0x15, 0x23, 0x2C, 0x35, 0x1C
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += 0 if cond else 1
    print(('ok   ' if cond else 'FAIL ') + name, extra)


class Game:
    def __init__(self, mana=0.0, hand=None, charge=40.0, drain=-12.0, delay=0.020, screen=0.016, **cfg):
        c = self.core = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=2.0, margin=1.0, quick=QUICK, **cfg))
        c.set_main(mc); c.set_spells(SPELLS); c.set_quick(QUICK); c.reader.mask = bytes(mc.strip[3])
        self.focused = True
        c.game_focused = lambda: self.focused
        self.hand, self.mana, self.charge, self.drain = hand, mana, charge, drain
        self.delay, self.screen = delay, screen
        self.g = self.f = False
        self.f_log, self.pending, self.casts, self.backfires, self.clicks, self.keys, self.hist = [], [], [], [], [], [], []
        ab.send_button, ab.send_scan = self.button, self.scan
        if hand:
            c.armed = hand
        self.t0 = clock[0]
        self.run(0.1)                    # let the reader see the bar once
        self.t0 = clock[0]

    def scan(self, scan, up):
        self.keys.append((round(clock[0] - 1000, 3), scan, 'up' if up else 'down'))
        if scan in ab.HOTBAR_SCAN:
            self.core._on_key(0, scan, 0, not up, True)
            if not up:
                self.pending.append((clock[0] + self.delay, 'key', ab.HOTBAR_SCAN[scan]))
        elif scan == ab.G_SCAN:
            self.g = not up
        elif scan == ab.F_SCAN:
            self.f = not up
            self.f_log.append((clock[0], not up))

    def button(self, click, up):
        self.clicks.append((clock[0], click, up))
        if not up:
            self.pending.append((clock[0] + self.delay, 'click', click))

    def key(self, scan, down=True, up=True):
        r = None
        if down:
            r = self.core._on_key(0, scan, 0, True, False)
        if up:
            self.core._on_key(0, scan, 0, False, False)
        return r

    def step(self, n=1):
        for _ in range(n):
            clock[0] += DT
            now = clock[0]
            self.mana = min(100.0, max(0.0, self.mana + (self.charge if self.g else self.drain) * DT))
            for q in [q for q in self.pending if q[0] <= now]:
                self.pending.remove(q)
                if q[1] == 'key':
                    self.hand = None if self.hand == q[2] else q[2]
                elif self.hand in REAL and REAL[self.hand][0] == q[2]:
                    _, lo, hi = REAL[self.hand]
                    (self.casts if lo <= self.mana <= hi else self.backfires).append((now, self.hand, round(self.mana, 1)))
            self.hist.append((now, self.hand, self.mana))
            while len(self.hist) > 2 and self.hist[1][0] <= now - self.screen:
                self.hist.pop(0)
            _, sh, sm = self.hist[0]
            st = ['B'] * 12
            if sh:
                st[ab.HOTBAR_KEYS.index(sh)] = 'W'
            c = self.core
            c.apply_slots(True, st)
            if self.focused:
                c.reading = (now, sm, 'bar'); c._track_rate(now, sm)
                c._advance_job(c.chat or not c.cfg.get('enabled'))
            else:
                c._advance_job(True)

    def run(self, sec):
        self.step(int(sec / DT))


def summary(g):
    return '%d cast%s%s, %d backfires, hand=%r' % (len(g.casts), '' if len(g.casts) == 1 else 's',
            (' at %s %%' % g.casts[0][2]) if g.casts else '', len(g.backfires), g.hand)


# ---------------------------------------------------------------- quick cast
g = Game(); g.key(Y); g.run(3.0)
check('Y from nothing in hand, 0 % mana: equips, charges, casts once', len(g.casts) == 1 and not g.backfires and g.hand == '-'
      and 20.0 <= g.casts[0][2] <= 31 and not g.g, summary(g) + ', G released=%s' % (not g.g))
check('... it used the RIGHT click because the name starts with "Snap"', [c[1] for c in g.clicks if not c[2]] == ['right'])
t_cast = g.casts[0][0] - g.t0
print('     (cast %.0f ms after the key press; charging 0 -> 20 %% alone takes %.0f ms)' % (t_cast * 1000, 20 / 40 * 1000))
g = Game(mana=25.0, hand='-', drain=0.0); g.key(Y); g.run(0.3)
check('already in hand and in range: casts at once, presses no hotbar key', len(g.casts) == 1 and not [k for k in g.keys if k[1] in ab.HOTBAR_SCAN]
      and g.casts[0][0] - g.t0 < 0.06, summary(g) + ', %.0f ms after the key' % ((g.casts[0][0] - g.t0) * 1000 if g.casts else -1))
g = Game(mana=80.0, hand='-'); g.key(Y); g.run(8.0)
check('mana over the range: waits while it drains, then casts', len(g.casts) == 1 and not g.backfires and g.casts[0][2] <= 32
      and not [k for k in g.keys if k[1] == ab.G_SCAN], summary(g))
g = Game(hand='1'); g.key(Y); g.run(3.0)
check('weapon in hand: switches to the spell first', len(g.casts) == 1 and not g.backfires and g.hand == '-', summary(g))
g = Game(); g.key(H); g.run(5.0)
check('H = Telorum (80-90): charges all the way up and casts', len(g.casts) == 1 and not g.backfires and 79 <= g.casts[0][2] <= 92, summary(g))
for rate in (20.0, 80.0, 140.0):
    g = Game(charge=rate); g.key(Y); g.run(6.0)
    check('charge speed %3.0f %%/s: one cast, in range' % rate, len(g.casts) == 1 and not g.backfires, summary(g))
g = Game(delay=0.050, screen=0.033, charge=60.0); g.key(Y); g.run(6.0)
check('laggy game (50 ms / 33 ms): one cast, in range', len(g.casts) == 1 and not g.backfires, summary(g))
g = Game(); g.key(Y); g.run(0.3); g.key(Y); g.run(2.0)
check('Y again while it is charging: stops, lets go of G, no cast', not g.casts and not g.backfires and not g.g and g.core.job is None, summary(g))
g = Game(); g.key(Y); g.run(0.3); g.focused = False; g.run(0.2)
check('tabbing out mid-charge: G is released, sequence dropped', not g.g and g.core.job is None and not g.core._down)
g = Game(); g.key(Y); g.run(0.2); g.key(0x02); g.hand = '1'; g.run(1.5)
check('picking another slot mid-charge: stops, no cast', not g.casts and not g.backfires and not g.g, summary(g))
g = Game(drain=0.0, charge=0.0); g.key(Y); g.run(27.0)
check('mana never moves: gives up after the timeout, G released', g.core.job is None and not g.g and not g.casts)
g = Game(); r = g.key(Y)
check('quick cast key is hidden from the game', r is True)

# ---------------------------------------------------------------- cast key (Viribus timing is in test_vir.py)
g = Game(mana=60.0, hand='-', drain=0.0); g.key(X); g.run(1.0)
check('any other spell out of range + X: still held back', not g.clicks and not g.f_log)
g = Game(mana=60.0); r = g.key(X)
check('X with no listed spell in hand: left alone (the game gets the key)', r is False and not g.clicks)

# ---------------------------------------------------------------- chat pause
g = Game(mana=25.0, hand='-', drain=0.0)
g.key(SLASH); r1 = g.key(X); r2 = g.key(Y); g.key(0x08); g.run(0.5)
check("after '/': X, quick keys and hotbar tracking are all paused", r1 is False and r2 is False and not g.clicks and g.core.armed == '-' and g.core.job is None)
g.key(ENTER); g.key(X); g.run(0.2)
check('Enter resumes', len(g.casts) == 1)
g = Game(mana=25.0, hand='-', drain=0.0); g.key(SLASH)
m = ab.MSLLHOOKSTRUCT(); ab.user32.CallNextHookEx = lambda *a: 0
g.core._ms(0, ab.WM_RBUTTONDOWN, ctypes.addressof(m))
check('a mouse click (left or right) resumes', g.core.chat is False)
g = Game(mana=25.0, hand='-', drain=0.0); g.key(SLASH); m = ab.MSLLHOOKSTRUCT(); m.dwExtraInfo = ab.TAG
g.core._ms(0, ab.WM_LBUTTONDOWN, ctypes.addressof(m))
check("... but not a click this add-on sent itself", g.core.chat is True)
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

"""Simulated game with a mana bar that TRAILS the real mana (as on the real screen while charging).
Covers: X while you hold G, X after letting go, the hidden range shift, and quick cast. No screen, no real input."""
import sys, types
sys.path.insert(0, sys.argv[1])
import anti_backfire as ab

clock = [1000.0]
ab.time = types.SimpleNamespace(time=lambda: clock[0], strftime=lambda *a: '', sleep=lambda s: None)
ab.log = lambda m: None
mc = ab.MainConfig(sys.argv[2])
SPELLS = [{'on': True, 'name': 'Snap Snarvindur', 'key': '-', 'click': 'right', 'lo': 20.0, 'hi': 30.0},
          {'on': True, 'name': 'Telorum', 'key': '7', 'click': 'left', 'lo': 80.0, 'hi': 90.0}]
REAL = {'-': ('right', 19, 31), '7': ('left', 79, 91)}      # true castable range (1 % leeway)
QUICK = [{'key': 'y', 'spell': 'Snap Snarvindur'}, {'key': 'h', 'spell': 'Telorum'}]
DT, X, Y, H, G = 0.004, 0x2D, 0x15, 0x23, ab.G_SCAN
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += 0 if cond else 1
    print(('ok   ' if cond else 'FAIL ') + name, extra)


class Game:
    def __init__(self, charge=80.0, drain=-2.0, bar_lag=0.10, key_delay=0.016, click_delay=0.045, hand='-',
                 mana=0.0, **cfg):
        c = self.core = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=1.0, margin=1.0, quick=QUICK, **cfg))
        c.set_main(mc); c.set_spells(SPELLS); c.set_quick(QUICK); c.reader.mask = bytes(mc.strip[3])
        c.game_focused = lambda: True
        c.armed = hand
        self.hand, self.mana, self.charge, self.drain = hand, mana, charge, drain
        self.bar_lag, self.key_delay, self.click_delay = bar_lag, key_delay, click_delay
        self.game_g = False
        self.pending, self.hist, self.casts, self.backfires = [], [], [], []
        ab.send_button, ab.send_scan = self.button, self.scan

    def scan(self, scan, up):
        if scan == G:
            self.pending.append((clock[0] + self.key_delay, 'g', not up))
        elif scan in ab.HOTBAR_SCAN:
            self.core._on_key(0, scan, 0, not up, True)
            if not up:
                self.pending.append((clock[0] + self.key_delay, 'key', ab.HOTBAR_SCAN[scan]))

    def button(self, click, up):
        if not up:
            self.pending.append((clock[0] + self.click_delay, 'click', click))

    def g(self, down):                                  # YOUR finger on G
        self.core._on_key(0, G, 0, down, False)
        self.pending.append((clock[0] + 0.004, 'g', down))

    def tap(self, scan):
        r = self.core._on_key(0, scan, 0, True, False)
        self.core._on_key(0, scan, 0, False, False)
        return r

    def step(self):
        clock[0] += DT
        now = clock[0]
        for q in [q for q in self.pending if q[0] <= now]:
            self.pending.remove(q)
            if q[1] == 'g':
                self.game_g = q[2]
            elif q[1] == 'key':
                self.hand = None if self.hand == q[2] else q[2]
            elif self.hand in REAL and REAL[self.hand][0] == q[2]:
                _, lo, hi = REAL[self.hand]
                (self.casts if lo <= self.mana <= hi else self.backfires).append(round(self.mana, 1))
                if lo <= self.mana <= hi:
                    self.mana = 0.0
        self.mana = min(100.0, max(0.0, self.mana + (self.charge if self.game_g else self.drain) * DT))
        self.hist.append((now, self.mana))
        while len(self.hist) > 2 and self.hist[1][0] <= now - self.bar_lag:
            self.hist.pop(0)
        shown = self.hist[0][1]
        c = self.core
        st = ['B'] * 12
        if self.hand:
            st[ab.HOTBAR_KEYS.index(self.hand)] = 'W'
        c.apply_slots(True, st)
        c.reading = (now, shown, 'bar'); c._track_rate(now, shown)
        c._advance_job(False)

    def run(self, sec, x_every=None):
        nxt = clock[0]
        end = clock[0] + sec
        while clock[0] < end:
            self.step()
            if x_every and clock[0] >= nxt:
                nxt += x_every
                self.tap(X)


def res(g):
    return '%d casts %s, %d backfires %s' % (len(g.casts), g.casts[:3], len(g.backfires), g.backfires[:3])


# ---------------------------------------------------------------- X while holding G
for rate in (40.0, 80.0, 120.0):
    for lag in (0.05, 0.10, 0.20):
        g = Game(charge=rate, drain=-6.0, bar_lag=lag, charge_lag_ms=(lag + 0.016) * 1000)
        g.g(True); g.run(45.0 / rate, x_every=0.06)         # hold G and mash X right through the range (to ~45 %)
        g.g(False); g.run(8.0, x_every=0.06)                # let go of G and keep mashing while it drains back
        check('hold G + mash X, then let go and keep mashing: %3.0f %%/s, bar %3.0f ms behind' % (rate, lag * 1000),
              not g.backfires and g.casts, res(g))
g = Game(charge=80.0, drain=-6.0, bar_lag=0.2, charge_lag_ms=120.0)
g.g(True); g.run(45.0 / 80, x_every=0.06); g.g(False); g.run(8.0, x_every=0.06)
check('... same, before the lag has been learned (120 ms guess, really 216 ms)', not g.backfires and g.casts, res(g))
g = Game(charge=12.0, bar_lag=0.10, charge_lag_ms=116.0)
g.g(True); g.run(3.0, x_every=0.06)
check('slow charge (12 %/s) while holding G: X casts during the charge', len(g.casts) >= 1 and not g.backfires, res(g))

# ---------------------------------------------------------------- the hidden shift itself
c = Game(bar_lag=0.0).core
c.rate = 0.0; c._hist[:] = []
c.reading = (clock[0], 29.4, 'bar'); c.g_phys = True
top = c.castable()[0] is None
c.g_phys = False
top_free = c.castable()[0] is not None
c.reading = (clock[0], 20.6, 'bar')
bottom = c.castable()[0] is None
c.reading = (clock[0], 21.3, 'bar')
bottom_ok = c.castable()[0] is not None
check('hidden shift: holding G, 29.4 % (range 20-30) is already too late; not holding G it is fine', top and top_free)
check('hidden shift: not holding G, 20.6 % (range 20-30) is still too early; 21.3 % is fine', bottom and bottom_ok)
check('the overlay still shows the normal range (the shift is hidden)', c.window('-')[:2] == (20.0, 30.0), '%g-%g' % c.window('-')[:2])

# ---------------------------------------------------------------- quick cast
for rate in (40.0, 80.0, 120.0):
    for lag in (0.05, 0.10, 0.20):
        g = Game(charge=rate, bar_lag=lag, charge_lag_ms=(lag + 0.016) * 1000)
        g.tap(Y); g.run(5.0)
        check('quick cast Snarvindur from 0 %%: %3.0f %%/s, bar %3.0f ms behind' % (rate, lag * 1000),
              len(g.casts) == 1 and not g.backfires and not g.game_g, res(g))
g = Game(charge=80.0, bar_lag=0.2, charge_lag_ms=120.0)
g.tap(Y); g.run(6.0)
check('quick cast before the lag is learned (guess 120 ms, really 216 ms)', len(g.casts) == 1 and not g.backfires, res(g))
check('... and it learned the lag from that cast', 0.15 < g.core.lag < 0.27, '%.0f ms' % (g.core.lag * 1000))
for start in (5.0, 18.0, 25.0, 45.0):
    g = Game(charge=80.0, bar_lag=0.10, charge_lag_ms=116.0, mana=start)
    g.hist = [(clock[0], start)]
    g.tap(Y); g.run(20.0)
    check('quick cast starting at %2.0f %% mana' % start, len(g.casts) == 1 and not g.backfires, res(g))
g = Game(charge=80.0, bar_lag=0.10, charge_lag_ms=116.0, hand='1')
g.tap(Y); g.run(5.0)
check('quick cast with a weapon in hand: equips, charges, casts', len(g.casts) == 1 and not g.backfires and g.hand == '-', res(g))
g = Game(charge=80.0, bar_lag=0.10, charge_lag_ms=116.0, hand='7')
g.tap(H); g.run(5.0)
check('quick cast Telorum (80-90)', len(g.casts) == 1 and not g.backfires, res(g))
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

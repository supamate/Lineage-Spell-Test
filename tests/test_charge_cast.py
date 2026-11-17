"""Simulated game: holding G (fast charge) and mashing X. The bar on screen trails the real mana.
Does a cast ever land outside the true range? No screen and no real input."""
import sys, types
sys.path.insert(0, sys.argv[1])
import anti_backfire as ab

clock = [1000.0]
ab.time = types.SimpleNamespace(time=lambda: clock[0], strftime=lambda *a: '', sleep=lambda s: None)
ab.log = lambda m: None
mc = ab.MainConfig(sys.argv[2])
SPELLS = [{'on': True, 'name': 'Snap Snarvindur', 'key': '-', 'click': 'right', 'lo': 20.0, 'hi': 30.0},
          {'on': True, 'name': 'Telorum', 'key': '7', 'click': 'left', 'lo': 80.0, 'hi': 90.0}]
REAL = {'-': ('right', 19, 31), '7': ('left', 79, 91)}      # true range with 1 % leeway
DT, X, G = 0.004, 0x2D, ab.G_SCAN
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += 0 if cond else 1
    print(('ok   ' if cond else 'FAIL ') + name, extra)


class Game:
    def __init__(self, charge=80.0, drain=-2.0, bar_lag=0.10, key_delay=0.016, click_delay=0.045, hand='-', **cfg):
        c = self.core = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=1.0, margin=1.0, **cfg))
        c.set_main(mc); c.set_spells(SPELLS); c.reader.mask = bytes(mc.strip[3])
        c.game_focused = lambda: True
        c.armed = hand
        self.hand, self.mana, self.charge, self.drain = hand, 0.0, charge, drain
        self.bar_lag, self.key_delay, self.click_delay = bar_lag, key_delay, click_delay
        self.game_g = False            # what the GAME thinks G is
        self.phys_g = False            # what your finger does
        self.pending, self.hist, self.casts, self.backfires, self.t_rep = [], [], [], [], 0.0
        ab.send_button, ab.send_scan = self.button, self.scan

    def scan(self, scan, up):
        if scan == G:
            self.pending.append((clock[0] + self.key_delay, 'g', not up))

    def button(self, click, up):
        if not up:
            self.pending.append((clock[0] + self.click_delay, 'click', click))

    def hold_g(self, down):
        self.phys_g = down
        if not self.core._on_key(0, G, 0, down, False):
            self.pending.append((clock[0] + 0.004, 'g', down))
        self.t_rep = clock[0] + 0.25

    def tap_x(self):
        self.core._on_key(0, X, 0, True, False)
        self.core._on_key(0, X, 0, False, False)

    def step(self):
        clock[0] += DT
        now = clock[0]
        if self.phys_g and now >= self.t_rep:              # keyboard auto-repeat of the held G
            self.t_rep = now + 0.033
            self.core.keys_down.pop((G, 0), None)
            if not self.core._on_key(0, G, 0, True, False):
                self.pending.append((now + 0.004, 'g', True))
        for q in [q for q in self.pending if q[0] <= now]:
            self.pending.remove(q)
            if q[1] == 'g':
                self.game_g = q[2]
            elif self.hand in REAL and REAL[self.hand][0] == q[2]:
                _, lo, hi = REAL[self.hand]
                (self.casts if lo <= self.mana <= hi else self.backfires).append(round(self.mana, 1))
                if lo <= self.mana <= hi:
                    self.mana = 0.0                         # a cast uses the mana up
        self.mana = min(100.0, max(0.0, self.mana + (self.charge if self.game_g else self.drain) * DT))
        self.hist.append((now, self.mana))
        while len(self.hist) > 2 and self.hist[1][0] <= now - self.bar_lag:
            self.hist.pop(0)
        shown = self.hist[0][1]                             # the bar shows where the mana was a moment ago
        c = self.core
        st = ['B'] * 12
        st[ab.HOTBAR_KEYS.index(self.hand)] = 'W'
        c.apply_slots(True, st)
        c.reading = (now, shown, 'bar'); c._track_rate(now, shown)
        c._charge_control(now)
        c._advance_job(False)

    def mash(self, seconds, every=0.09, start=0.0):
        """hold G the whole time, tap X every `every` seconds"""
        self.hold_g(True)
        nxt = clock[0] + start
        end = clock[0] + seconds
        while clock[0] < end:
            self.step()
            if clock[0] >= nxt:
                nxt += every
                self.tap_x()


def run(label, expect_cast=True, seconds=8.0, **kw):
    every, start = kw.pop('every', 0.09), kw.pop('start', 0.0)
    g = Game(**kw)
    g.mash(seconds, every, start)
    good = not g.backfires and (bool(g.casts) or not expect_cast)
    check('%-66s' % label, good, '%d casts %s, %d backfires %s' % (len(g.casts), g.casts[:4], len(g.backfires), g.backfires[:4]))
    return g


g = Game(settle_spells=[]); g.mash(8.0)
print('     old behaviour (clicks on the moving bar), 80 %%/s charge, bar 100 ms behind: %d casts, %d BACKFIRES %s'
      % (len(g.casts), len(g.backfires), g.backfires[:5]))
check('the simulation reproduces your problem with the old behaviour', len(g.backfires) > 0)
for rate in (40.0, 80.0, 120.0):
    for lag in (0.05, 0.10, 0.20):
        run('hold G + mash X: charge %3.0f %%/s, bar %3.0f ms behind' % (rate, lag * 1000), charge=rate, bar_lag=lag)
for st in (0.0, 0.03, 0.06):
    run('... X taps starting at a different moment (+%d ms)' % (st * 1000), start=st)
run('... slow mashing (X every 200 ms)', every=0.2)
run('... very laggy game (keys 40 ms, click lands 90 ms later)', key_delay=0.040, click_delay=0.090, bar_lag=0.15)
run('first ever use, bar lag still unknown (starts at 20 ms guess)', charge_lag_ms=20.0, bar_lag=0.2)
g = run('Telorum (not on the list): behaves as before', hand='7', expect_cast=False, seconds=4.0)
g = Game(); g.mash(3.0)
check('the add-on learned how far the bar trails', 0.05 < g.core.lag < 0.25, 'learned %.0f ms (bar 100 ms + key 16 ms)' % (g.core.lag * 1000))
g = Game(charge=80.0); g.hold_g(True)
for _ in range(int(0.6 / DT)): g.step()
n = len(g.pending); mana_before = g.mana
check('holding G without pressing X: charging is never interrupted', g.game_g and g.mana > 40 and not g.core.g_hide)
g = Game(charge=80.0); g.hold_g(True)
for _ in range(int(1.2 / DT)): g.step()               # way past the range (96 %), then X
g.tap_x()
for _ in range(int(0.6 / DT)): g.step()
check('X pressed far above the range: charge stopped, nothing cast', not g.casts and not g.backfires and g.core.g_hide and not g.game_g)
g2 = Game(); g2.mash(3.0)
check('after a cast the charge stays stopped until G is pressed again', len(g2.casts) == 1 and not g2.game_g and g2.core.g_hide)
g.hold_g(False)
for _ in range(10): g.step()
g.hold_g(True)
for _ in range(20): g.step()
check('letting go of G and pressing it again charges as normal', g.game_g and not g.core.g_hide)
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

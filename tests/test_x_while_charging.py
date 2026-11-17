"""X while holding G, with the values learned in the real game (speed ~60 %/s, bar ~0.19 s behind) and the real spam
rate (an X press about every 0.17 s). The game's own speed and lag vary a little from charge to charge.
No screen, no real input.  Usage: test_x_while_charging.py <add-on folder> <cooldown_indicator_config.json> [seed]"""
import sys, types, random
sys.path.insert(0, sys.argv[1])
import anti_backfire as ab

clock = [1000.0]
ab.time = types.SimpleNamespace(time=lambda: clock[0], strftime=lambda *a: '', sleep=lambda s: None)
ab.log = lambda m: None
mc = ab.MainConfig(sys.argv[2])
rnd = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 5)
SPELLS = [{'on': True, 'name': 'Snap Snarvindur', 'key': '-', 'click': 'right', 'lo': 20.0, 'hi': 30.0}]
REAL = (18.0, 32.0)                       # 20-30 with the 2 % Fallion leeway
LEARNED_SPEEDS = [61.76, 61.28, 60.83, 48.63, 62.64, 57.11, 49.3, 52.87, 64.43]      # as learned in the game
LEARNED_RISES = [0.212, 0.292, 0.262, 0.192, 0.193, 0.186, 0.175, 0.186, 0.189]
DT, X, G = 0.004, 0x2D, ab.G_SCAN
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += 0 if cond else 1
    print(('ok   ' if cond else 'FAIL ') + name, extra)


class Game:
    def __init__(self, speed=60.0, lag=0.17, key_delay=0.016, click_delay=0.03, read_every=0.012):
        c = self.core = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=2.0, margin=1.0, charge_lag_ms=157.0))
        c.set_main(mc); c.set_spells(SPELLS); c.reader.mask = bytes(mc.strip[3])
        c._speeds, c._rises = list(LEARNED_SPEEDS), list(LEARNED_RISES)
        c.game_focused = lambda: True
        c.armed = '-'
        self.speed, self.lag, self.key_delay, self.click_delay, self.read_every = speed, lag, key_delay, click_delay, read_every
        self.mana, self.game_g, self.last_read = 0.0, False, -1.0
        self.pending, self.hist, self.casts, self.backfires = [], [(clock[0], 0.0)], [], []
        ab.send_button, ab.send_scan = self.button, lambda sc, up: None

    def button(self, click, up):
        if not up:
            self.pending.append((clock[0] + self.click_delay, click))

    def g(self, down):
        self.core._on_key(0, G, 0, down, False)
        self.pending.append((clock[0] + self.key_delay, 'g', down))

    def x(self, down=True, up=True):
        if down:
            self.core._on_key(0, X, 0, True, False)
        if up:
            self.core._on_key(0, X, 0, False, False)

    def step(self):
        clock[0] += DT
        now = clock[0]
        for q in [q for q in self.pending if q[0] <= now]:
            self.pending.remove(q)
            if q[1] == 'g':
                self.game_g = q[2]
            elif q[1] == 'right':
                (self.casts if REAL[0] <= self.mana <= REAL[1] else self.backfires).append(round(self.mana, 1))
                if REAL[0] <= self.mana <= REAL[1]:
                    self.mana = 0.0
        self.mana = min(100.0, max(0.0, self.mana + (self.speed if self.game_g else -2.0) * DT))
        self.hist.append((now, self.mana))
        while len(self.hist) > 2 and self.hist[1][0] <= now - self.lag:
            self.hist.pop(0)
        c = self.core
        if now - self.last_read >= self.read_every - 1e-9:
            self.last_read = now
            c.reading = (now, self.hist[0][1], 'bar'); c._track_rate(now, self.hist[0][1])
        c._advance_job(False)
        c._x_arm_tick(now)

    def run(self, sec, x_every=None, x_from=0.0):
        t0 = clock[0]
        nxt = t0 + x_from
        while clock[0] - t0 < sec:
            self.step()
            if x_every and clock[0] >= nxt:
                nxt += x_every
                self.x()


def trial(**kw):
    g = Game(speed=rnd.uniform(56.0, 64.0), lag=rnd.uniform(0.165, 0.21), **kw)
    return g


def summary(gs):
    casts = [c for g in gs for c in g.casts]
    bf = [b for g in gs for b in g.backfires]
    return casts, bf, '%d/%d charges cast, %d backfires %s, cast at %s' % (
        sum(1 for g in gs if g.casts), len(gs), len(bf), bf[:4],
        ('%.1f-%.1f %%' % (min(casts), max(casts))) if casts else '-')


# 1) hold G from 0 % and spam X like in the game (every ~0.17 s, random phase) up to 60 %
gs = []
for i in range(60):
    g = trial()
    g.g(True); g.run(1.0, x_every=0.17, x_from=rnd.uniform(0.0, 0.17))
    gs.append(g)
casts, bf, txt = summary(gs)
check('hold G + spam X (every 0.17 s): EVERY charge casts, no backfire', not bf and all(g.casts for g in gs), txt)

# 2) one X press early (bar still low) while holding G: it waits and casts on entering the range
gs = []
for i in range(60):
    g = trial()
    g.g(True); g.run(rnd.uniform(0.02, 0.25)); g.x(); g.run(1.0)
    gs.append(g)
casts, bf, txt = summary(gs)
check('hold G, ONE early X press: casts by itself on entering the range', not bf and all(g.casts for g in gs), txt)

# 3) X held down the whole time while charging
gs = []
for i in range(30):
    g = trial()
    g.g(True); g.x(down=True, up=False); g.run(1.2); g.x(down=False, up=True)
    gs.append(g)
casts, bf, txt = summary(gs)
check('hold G and hold X down: casts once, no backfire', not bf and all(len(g.casts) == 1 for g in gs), txt)

# 4) X only once the real mana is already past the range: nothing
gs = []
for i in range(30):
    g = trial()
    g.g(True); g.run(0.75); g.x(); g.run(1.0)
    gs.append(g)
casts, bf, txt = summary(gs)
check('X pressed only after the real mana passed the range: no cast, no backfire', not casts and not bf, txt)

# 5) slower screen readings (busy PC)
gs = []
for i in range(40):
    g = trial(read_every=0.045)
    g.g(True); g.run(1.0, x_every=0.17, x_from=rnd.uniform(0.0, 0.17))
    gs.append(g)
casts, bf, txt = summary(gs)
check('readings only every 45 ms: still casts every charge, no backfire', not bf and all(g.casts for g in gs), txt)

# 6) the click takes longer than assumed (60 ms instead of ~30)
gs = []
for i in range(40):
    g = trial(click_delay=0.06)
    g.g(True); g.run(1.0, x_every=0.17, x_from=rnd.uniform(0.0, 0.17))
    gs.append(g)
casts, bf, txt = summary(gs)
check('slower click (60 ms): no backfire', not bf, txt)
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

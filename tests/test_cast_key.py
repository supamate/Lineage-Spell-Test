"""Simulated game for the cast key: does X ever click while mana is outside the true range?
No screen and no real input: the add-on's senders are replaced by the simulator."""
import sys, types, time as real_time
sys.path.insert(0, sys.argv[1])
import anti_backfire as ab

clock = [1000.0]
ab.time = types.SimpleNamespace(time=lambda: clock[0], strftime=lambda *a: '', sleep=lambda s: None)
ab.log = lambda m: None
mc = ab.MainConfig(sys.argv[2])
SPELLS = [{'on': True, 'name': 'Snap Snarvindur', 'key': '-', 'click': 'right', 'lo': 20.0, 'hi': 30.0},
          {'on': True, 'name': 'Telorum', 'key': '7', 'click': 'left', 'lo': 80.0, 'hi': 90.0},
          {'on': True, 'name': 'Gate', 'key': '=', 'click': 'left', 'lo': 25.0, 'hi': 35.0}]
REAL = {('-', 'right'): (18, 32), ('7', 'left'): (78, 92), ('=', 'left'): (23, 37), ('=', 'right'): (58, 72)}
DT, X = 0.008, 0x2D
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += 0 if cond else 1
    print(('ok   ' if cond else 'FAIL ') + name, extra)


class Game:
    def __init__(self, click_delay=0.020, screen_delay=0.016):
        self.core = c = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=2.0, margin=1.0))
        c.set_main(mc); c.set_spells(SPELLS); c.reader.mask = bytes(mc.strip[3])
        c.game_focused = lambda: True
        self.hand, self.mana, self.hist = None, 0.0, []
        self.click_delay, self.screen_delay = click_delay, screen_delay
        self.pending, self.casts, self.backfires, self.keys_sent, self.downs, self.ups = [], [], [], 0, 0, 0
        ab.send_button = self.button
        ab.send_scan = self.scan

    def scan(self, scan, up):
        self.keys_sent += 0 if scan == ab.F_SCAN else 1                              # the add-on must never press a key any more

    def button(self, click, up):
        if up:
            self.ups += 1
        else:
            self.downs += 1
            self.pending.append((clock[0] + self.click_delay, click))

    def key(self, scan, down=True, up=True):
        if down:
            self.core._on_key(0, scan, 0, True, False)
        if up:
            self.core._on_key(0, scan, 0, False, False)

    def equip(self, key):
        self.key(next(s for s, k in ab.HOTBAR_SCAN.items() if k == key))
        self.hand = None if self.hand == key else key

    def step(self, rate=0.0):
        clock[0] += DT
        now = clock[0]
        self.mana = min(100.0, max(0.0, self.mana + rate * DT))
        for q in [q for q in self.pending if q[0] <= now]:
            self.pending.remove(q)
            if (self.hand, q[1]) in REAL:                # a click landed with a spell in hand: cast or backfire
                lo, hi = REAL[(self.hand, q[1])]
                (self.casts if lo <= self.mana <= hi else self.backfires).append((self.hand, q[1], round(self.mana, 1)))
        self.hist.append((now, self.hand, self.mana))
        while len(self.hist) > 2 and self.hist[1][0] <= now - self.screen_delay:
            self.hist.pop(0)
        _, shown_hand, shown_mana = self.hist[0]
        st = ['B'] * 12
        if shown_hand:
            st[ab.HOTBAR_KEYS.index(shown_hand)] = 'W'
        self.core.apply_slots(True, st)
        self.core.reading = (now, shown_mana, 'bar')
        self.core._track_rate(now, shown_mana)
        self.core._advance_job(False)

    def spam(self, seconds, rate, every=3):
        """charge / drain while mashing X every few steps"""
        for i in range(int(seconds / DT)):
            self.step(rate)
            if i % every == 0:
                self.key(X)


def mash(name, key, up, down=-12.0, **kw):
    g = Game(**kw)
    g.equip(key); g.spam(0.3, 0)
    g.spam(100.0 / up, up); g.spam(100.0 / -down, down)
    got = sorted(set(c[2] for c in g.casts))
    check('%-62s' % name, not g.backfires and g.casts and g.keys_sent == 0 and g.hand == key,
          '%d casts between %s and %s %%, %d backfires%s' % (len(g.casts), got[0] if got else '-', got[-1] if got else '-',
          len(g.backfires), (' at ' + str(g.backfires[:3])) if g.backfires else ''))
    return g


mash('Snarvindur: mash X while charging 40 %/s to 100, then draining', '-', 40.0)
mash('... charging fast, 80 %/s', '-', 80.0)
mash('... charging very fast, 120 %/s, draining 40 %/s', '-', 120.0, -40.0)
mash('... crawling 8 %/s up, 3 %/s down', '-', 8.0, -3.0)
mash('... laggy game (click lands 50 ms later, screen 33 ms late)', '-', 60.0, click_delay=0.050, screen_delay=0.033)
mash('Telorum 80-90 (left click)', '7', 40.0)

g = Game(); g.equip('-'); g.spam(0.3, 0); g.spam(24.0 / 40, 40.0)
n = len(g.casts); g.core.last_cast_t = 0; g.key(X, up=False)
for _ in range(40): g.step()
check('holding X holds the button down (one press, no release yet)', g.downs - g.ups == 1)
g.key(X, down=False); check('releasing X releases it', g.downs == g.ups)
g = Game(); g.spam(3.0, 40.0)
check('nothing in hand: X does nothing at all', g.downs == 0)
g = Game(); g.equip('1'); g.spam(3.0, 40.0)
check('weapon in hand (not a listed spell): X does nothing', g.downs == 0)
g = Game(); g.equip('-'); g.core.chat = True; g.spam(3.0, 40.0)
check("chat line open: typing 'x' never clicks", g.downs == 0)
g = Game(); g.equip('-'); g.core.cfg['enabled'] = False; g.spam(3.0, 40.0)
check('switched off (F9): X does nothing', g.downs == 0)
g = Game(); g.equip('-'); g.spam(0.3, 0); g.spam(24.0 / 40, 40.0); g.core.reading = (clock[0] - 1, 24.0, 'bar'); g.core.last_cast_t = 0; g.key(X)
check("mana bar can't be read: X holds back", g.core.cast_btn is None and 'held back' in g.core.last_event[1])
g = Game(); g.equip('-'); g.spam(0.3, 0); g.spam(1.5, 40.0)
check('X held back out of range: spell is STILL in your hand (mana shield works)', g.hand == '-' and g.keys_sent == 0 and g.core.armed == '-')

# speed of the X decision (real clock)
ab.time = real_time
c = ab.Core(dict(ab.DEFAULTS, spells=SPELLS)); c.set_main(mc); c.set_spells(SPELLS); c.reader.mask = bytes(mc.strip[3])
c.game_focused = lambda: True; c.armed = '-'; ab.send_button = lambda *a: None
worst = tot = 0.0
for i in range(3000):
    c.reading = (real_time.time(), 25.0, 'bar'); c.keys_down.clear(); c.last_cast_t = 0
    t0 = real_time.perf_counter(); c._on_key(0, X, 0, True, False); c._on_key(0, X, 0, False, False)
    dt = real_time.perf_counter() - t0; worst = max(worst, dt); tot += dt
check('X -> click decision is instant', worst < 0.005 and c.casts == 3000, 'avg %.3f ms, worst %.2f ms' % (tot / 3000 * 1000, worst * 1000))
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

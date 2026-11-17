"""Quick cast in a harder simulated game: the bar's lag jitters from cast to cast, and some casts start during a
half-stun (G does nothing until it is pressed again after the stun). Measures time to cast, retries, backfires.
No screen, no real input.  Usage: test_quick_speed.py <add-on folder> <cooldown_indicator_config.json> [seed]"""
import sys, types, random
sys.path.insert(0, sys.argv[1])
import anti_backfire as ab

clock = [1000.0]
ab.time = types.SimpleNamespace(time=lambda: clock[0], strftime=lambda *a: '', sleep=lambda s: None)
ab.log = lambda m: None
mc = ab.MainConfig(sys.argv[2])
rnd = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 7)
SPELLS = [{'on': True, 'name': 'Snap Snarvindur', 'key': '-', 'click': 'right', 'lo': 20.0, 'hi': 30.0}]
REAL = (19.0, 31.0)
QUICK = [{'key': 'y', 'spell': 'Snap Snarvindur'}]
DT, Y, G = 0.004, 0x15, ab.G_SCAN
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += 0 if cond else 1
    print(('ok   ' if cond else 'FAIL ') + name, extra)


class Game:
    def __init__(self, charge=80.0, lag=0.18, jitter=0.025, key_delay=0.016, click_delay=0.045, **cfg):
        c = self.core = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=1.0, margin=1.0, quick=QUICK,
                                     charge_lag_ms=120.0, **cfg))
        c.set_main(mc); c.set_spells(SPELLS); c.set_quick(QUICK); c.reader.mask = bytes(mc.strip[3])
        c.game_focused = lambda: True
        c.armed = '-'
        self.charge, self.base_lag, self.jitter, self.key_delay, self.click_delay = charge, lag, jitter, key_delay, click_delay
        self.lag = lag
        self.mana, self.game_g, self.charging = 0.0, False, False
        self.stun_until = 0.0
        self.pending, self.hist, self.result = [], [], []
        self.g_presses = 0
        ab.send_button, ab.send_scan = self.button, self.scan

    def scan(self, scan, up):
        if scan == G:
            self.pending.append((clock[0] + self.key_delay, 'g', not up))

    def button(self, click, up):
        if not up:
            self.pending.append((clock[0] + self.click_delay, 'click', click))

    def step(self):
        clock[0] += DT
        now = clock[0]
        for q in [q for q in self.pending if q[0] <= now]:
            self.pending.remove(q)
            if q[1] == 'g':
                if q[2] and not self.game_g:             # a G press
                    self.g_presses += 1
                    self.lag = max(0.03, self.base_lag + rnd.uniform(-self.jitter, self.jitter))
                    self.charging = now >= self.stun_until   # pressed during a stun: does nothing
                if not q[2]:
                    self.charging = False
                self.game_g = q[2]
            elif q[2] == 'right':
                self.result.append(('cast' if REAL[0] <= self.mana <= REAL[1] else 'BACKFIRE', round(self.mana, 1), now))
                self.mana = 0.0 if REAL[0] <= self.mana <= REAL[1] else max(0.0, self.mana - 15)
        self.mana = min(100.0, max(0.0, self.mana + (self.charge if self.charging else -2.0) * DT))
        self.hist.append((now, self.mana))
        while len(self.hist) > 2 and self.hist[1][0] <= now - self.lag:
            self.hist.pop(0)
        shown = self.hist[0][1]
        c = self.core
        st = ['B'] * 12
        st[ab.HOTBAR_KEYS.index('-')] = 'W'
        c.apply_slots(True, st)
        c.reading = (now, shown, 'bar'); c._track_rate(now, shown)
        c._advance_job(False)

    def quick(self, stun=0.0, limit=6.0):
        """press Y (optionally right after a dash: half-stun for `stun` s); returns (outcome, mana, seconds, G presses)"""
        self.stun_until = clock[0] + stun
        n0, p0, t0 = len(self.result), self.g_presses, clock[0]
        self.core._on_key(0, Y, 0, True, False); self.core._on_key(0, Y, 0, False, False)
        while clock[0] - t0 < limit and len(self.result) == n0:
            self.step()
        for _ in range(int(0.6 / DT)):                   # let the bar settle / the lag be learned before the next
            self.step()
        if len(self.result) == n0:
            return ('nothing', None, None, self.g_presses - p0)
        o, m, at = self.result[n0]
        return (o, m, at - t0, self.g_presses - p0)


def series(label, n=20, stun_every=0, stun=0.6, **kw):
    g = Game(**kw)
    out = []
    for i in range(n):
        out.append(g.quick(stun=stun if (stun_every and i % stun_every == stun_every - 1) else 0.0))
    bad = [o for o in out if o[0] != 'cast']
    normal = [o for i, o in enumerate(out) if not (stun_every and i % stun_every == stun_every - 1)]
    late = normal[6:]                                     # once the lag has been learned
    secs = sorted(o[2] for o in late if o[2] is not None)
    redo = sum(1 for o in late if o[3] > 1)
    print('     %-50s casts %2d/%d, backfires %d, after warm-up: median %.0f ms, slowest %.0f ms, re-charges %d'
          % (label, n - len(bad), n, sum(1 for o in out if o[0] == 'BACKFIRE'),
             secs[len(secs) // 2] * 1000 if secs else -1, secs[-1] * 1000 if secs else -1, redo))
    return g, out, bad, late


g, out, bad, late = series('80 %/s, lag 180 +/- 25 ms')
check('20 quick casts in a row, jittery lag: all cast, no backfire', not bad, str(bad[:3]))
check('... after warm-up, never a second charge (no "miss, readjust")', all(o[3] == 1 for o in late),
      str([o[3] for o in late]))
check('... after warm-up it casts straight away (under 0.5 s from 0 % mana)', all(o[2] < 0.5 for o in late),
      'slowest %.0f ms' % (max(o[2] for o in late) * 1000))
check('it learned the lag', abs(g.core.lag - 0.18 - 0.016) < 0.04, '%.0f ms' % (g.core.lag * 1000))
for rate, lag, jit in ((40.0, 0.18, 0.025), (120.0, 0.18, 0.025), (80.0, 0.10, 0.01), (80.0, 0.25, 0.04)):
    g, out, bad, late = series('%3.0f %%/s, lag %3.0f +/- %2.0f ms' % (rate, lag * 1000, jit * 1000), charge=rate, lag=lag,
                               jitter=jit)
    check('... no backfires at %3.0f %%/s, lag %3.0f +/- %2.0f ms' % (rate, lag * 1000, jit * 1000),
          not [o for o in out if o[0] == 'BACKFIRE'] and not [o for o in out if o[0] == 'nothing'])
g, out, bad, late = series('very jittery lag (180 +/- 60 ms): should fall back', jitter=0.06)
check('very jittery lag: no backfires (it stays careful instead)', not [o for o in out if o[0] == 'BACKFIRE'])
g, out, bad, late = series('every 3rd cast during a 0.6 s half-stun', stun_every=3)
stunned = [o for i, o in enumerate(out) if i % 3 == 2]
check('casts started during a half-stun still cast (G re-tapped)', all(o[0] == 'cast' for o in stunned),
      str([(o[0], round(o[2], 2) if o[2] else None, o[3]) for o in stunned[:4]]))
check('... soon after the stun ends (within 0.6 s of it)', all(o[2] is not None and o[2] < 0.6 + 0.6 for o in stunned),
      'slowest %.0f ms (stun 600 ms)' % (max(o[2] for o in stunned if o[2]) * 1000))
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

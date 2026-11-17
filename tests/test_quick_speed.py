"""Quick cast in a harder simulated game, modelled on what the real game showed:
- mana charges slowly at first and faster the longer G is held (a re-press starts slow again),
- the bar's lag jitters from cast to cast,
- some casts start during a half-stun (G does nothing until pressed again after the stun),
- the spell is NOT in hand at the start (quick cast must take it out only once mana is in range).
Measures time to cast, overshoot, G presses, backfires. No screen, no real input.
Usage: test_quick_speed.py <add-on folder> <cooldown_indicator_config.json> [seed]"""
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
    def __init__(self, v0=15.0, v1=70.0, ramp=0.4, lag=0.16, jitter=0.02, key_delay=0.016, click_delay=0.045,
                 drain=-3.0, **cfg):
        c = self.core = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=1.0, margin=1.0, quick=QUICK,
                                     charge_lag_ms=120.0, **cfg))
        c.set_main(mc); c.set_spells(SPELLS); c.set_quick(QUICK); c.reader.mask = bytes(mc.strip[3])
        c.game_focused = lambda: True
        self.v0, self.v1, self.ramp, self.drain = v0, v1, ramp, drain
        self.base_lag, self.jitter, self.key_delay, self.click_delay = lag, jitter, key_delay, click_delay
        self.lag = lag
        self.mana, self.game_g, self.charge_from = 0.0, False, None
        self.hand = None
        self.stun_until = 0.0
        self.pending, self.hist, self.result = [], [], []
        self.g_presses, self.key_presses, self.peak = 0, [], 0.0
        ab.send_button, ab.send_scan = self.button, self.scan

    def scan(self, scan, up):
        if scan == G:
            self.pending.append((clock[0] + self.key_delay, 'g', not up))
        elif scan in ab.HOTBAR_SCAN:
            self.core._on_key(0, scan, 0, not up, True)
            if not up:
                self.key_presses.append((clock[0], round(self.mana, 1)))
                self.pending.append((clock[0] + self.key_delay, 'key', ab.HOTBAR_SCAN[scan]))

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
                    self.charge_from = now if now >= self.stun_until else None   # during a stun: nothing
                if not q[2]:
                    self.charge_from = None
                self.game_g = q[2]
            elif q[1] == 'key':
                self.hand = None if self.hand == q[2] else q[2]
            elif q[2] == 'right':
                ok = self.hand == '-' and REAL[0] <= self.mana <= REAL[1]
                self.result.append(('cast' if ok else ('BACKFIRE' if self.hand == '-' else 'no spell'),
                                    round(self.mana, 1), now))
                if ok:
                    self.mana = 0.0
        if self.charge_from is not None:                 # charging gets faster the longer G is held
            v = min(self.v1, self.v0 + (self.v1 - self.v0) * (now - self.charge_from) / self.ramp)
        else:
            v = self.drain
        self.mana = min(100.0, max(0.0, self.mana + v * DT))
        self.peak = max(self.peak, self.mana)
        self.hist.append((now, self.mana))
        while len(self.hist) > 2 and self.hist[1][0] <= now - self.lag:
            self.hist.pop(0)
        shown = self.hist[0][1]
        c = self.core
        st = ['B'] * 12
        if self.hand:
            st[ab.HOTBAR_KEYS.index(self.hand)] = 'W'
        c.apply_slots(True, st)
        c.reading = (now, shown, 'bar'); c._track_rate(now, shown)
        c._advance_job(False)

    def quick(self, stun=0.0, limit=8.0, start=0.0, hand=None):
        """press Y (spell put away, mana at `start`); returns a dict about that cast"""
        self.mana, self.peak, self.hand = start, start, hand
        self.hist = [(clock[0], start)]
        self.core.armed = hand
        self.stun_until = clock[0] + stun
        n0, p0, k0, t0 = len(self.result), self.g_presses, len(self.key_presses), clock[0]
        self.core._on_key(0, Y, 0, True, False); self.core._on_key(0, Y, 0, False, False)
        while clock[0] - t0 < limit and len(self.result) == n0:
            self.step()
        peak = self.peak
        for _ in range(int(0.6 / DT)):
            self.step()
        keys = self.key_presses[k0:]
        if len(self.result) == n0:
            return dict(o='nothing', mana=None, t=None, presses=self.g_presses - p0, peak=peak, keys=keys)
        o, m, at = self.result[n0]
        return dict(o=o, mana=m, t=at - t0, presses=self.g_presses - p0, peak=peak, keys=keys)


def series(label, n=20, stun_every=0, stun=0.6, **kw):
    g = Game(**kw)
    out = [g.quick(stun=stun if (stun_every and i % stun_every == stun_every - 1) else 0.0) for i in range(n)]
    normal = [o for i, o in enumerate(out) if not (stun_every and i % stun_every == stun_every - 1)]
    late = normal[5:]
    secs = sorted(o['t'] for o in late if o['t'] is not None)
    print('     %-44s casts %2d/%d, backfires %d | after warm-up: median %.0f ms, slowest %.0f ms, highest mana %.1f%%, '
          'extra G presses %d' % (label, sum(o['o'] == 'cast' for o in out), n, sum(o['o'] == 'BACKFIRE' for o in out),
                                  secs[len(secs) // 2] * 1000 if secs else -1, secs[-1] * 1000 if secs else -1,
                                  max(o['peak'] for o in late), sum(o['presses'] - 1 for o in late)))
    return g, out, late


g, out, late = series('ramping charge 15 -> 70 %/s, lag 160 +/- 20 ms')
check('20 quick casts: all cast, no backfire', all(o['o'] == 'cast' for o in out), str([o['o'] for o in out if o['o'] != 'cast']))
check('... one G press each (no tap-charging loop)', all(o['presses'] == 1 for o in late), str([o['presses'] for o in late]))
check('... never charged past the range (no "go over, wait for the drain")', all(o['peak'] <= REAL[1] for o in late),
      'highest %.1f%%' % max(o['peak'] for o in late))
check('... the spell key is pressed once, only after mana is in range', all(len(o['keys']) == 1 and REAL[0] <= o['keys'][0][1] <= REAL[1]
      for o in out), str([o['keys'] for o in out[:3]]))
check('it learned how far the bar overshoots', 0.08 < g.core.lag < 0.4, '%.0f ms' % (g.core.lag * 1000))
for kw in (dict(v0=30.0, v1=30.0), dict(v0=10.0, v1=110.0, ramp=0.3), dict(lag=0.10, jitter=0.01),
           dict(lag=0.25, jitter=0.04), dict(drain=-8.0)):
    lab = ', '.join('%s=%g' % kv for kv in kw.items())
    g, out, late = series(lab, **kw)
    check('... no backfire, no loop, no overshoot: ' + lab,
          all(o['o'] == 'cast' for o in out) and all(o['presses'] == 1 for o in late) and all(o['peak'] <= REAL[1] for o in late))
g, out, late = series('jittery lag (160 +/- 60 ms)', jitter=0.06)
check('very jittery lag: still no backfire', not [o for o in out if o['o'] == 'BACKFIRE'])
g, out, late = series('every 3rd cast during a 0.6 s half-stun', stun_every=3)
stunned = [o for i, o in enumerate(out) if i % 3 == 2]
check('casts started during a half-stun still cast (G re-tapped)', all(o['o'] == 'cast' for o in stunned),
      str([(o['o'], round(o['t'], 2) if o['t'] else None, o['presses']) for o in stunned[:4]]))
check('... within 1.3 s of the stun ending (it must not re-tap a charge that is still starting)',
      all(o['t'] is not None and o['t'] < 0.6 + 1.3 for o in stunned),
      'slowest %.0f ms after the key (stun 600 ms)' % (max(o['t'] for o in stunned if o['t']) * 1000))
g = Game()
for _ in range(8):
    g.quick()
r = g.quick(start=25.0, hand='-')
check('spell already in hand and mana in range: casts at once, no key, no G', r['o'] == 'cast' and not r['keys'] and r['presses'] == 0
      and r['t'] < 0.15, '%.0f ms' % (r['t'] * 1000 if r['t'] else -1))
r = g.quick(start=45.0)
check('mana above the range: waits for the drain, then takes the spell out and casts', r['o'] == 'cast' and r['presses'] == 0
      and len(r['keys']) == 1, str(r))
r = g.quick(start=10.0, hand='1')
check('weapon in hand: keeps it while charging, switches only when in range', r['o'] == 'cast' and len(r['keys']) == 1
      and REAL[0] <= r['keys'][0][1] <= REAL[1], str(r['keys']))
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

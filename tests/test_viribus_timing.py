"""Real-clock test of the Viribus backcast timing. Nothing is sent: the add-on's senders are replaced by recorders."""
import sys, time, threading
sys.path.insert(0, sys.argv[1])
import anti_backfire as ab

ab.log = lambda m: None
sys.setswitchinterval(0.001)          # as the add-on itself runs
mc = ab.MainConfig(sys.argv[2])
SPELLS = [{'on': True, 'name': 'Viribus', 'key': '=', 'click': 'left', 'lo': 25.0, 'hi': 35.0},
          {'on': True, 'name': 'Snap Snarvindur', 'key': '-', 'click': 'right', 'lo': 20.0, 'hi': 30.0}]
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += 0 if cond else 1
    print(('ok   ' if cond else 'FAIL ') + name, extra)


def run(mana, key='=', busy=False, **cfg):
    ev = []
    ab.send_button = lambda click, up: ev.append((time.perf_counter(), 'mouse', click, 'up' if up else 'down'))
    ab.send_scan = lambda scan, up: ev.append((time.perf_counter(), 'F' if scan == ab.F_SCAN else scan, '', 'up' if up else 'down'))
    c = ab.Core(dict(ab.DEFAULTS, spells=SPELLS, leeway=2.0, margin=1.0, **cfg))
    c.set_main(mc); c.set_spells(SPELLS); c.reader.mask = bytes(mc.strip[3])
    c.game_focused = lambda: True
    c.armed = key
    c.reading = (time.time(), mana, 'bar')
    stop = threading.Event()
    if busy:                                   # the reader thread's math running flat out at the same time
        def churn():
            r = ab.ManaReader(); buf = [0xFF524049] * (mc.strip[2] * mc.strip[3])
            while not stop.is_set():
                r.read(buf, mc.strip[2], mc.strip[3])
                if busy == 'real':
                    time.sleep(0.008)          # the real reader: ~0.5 ms of work every 8 ms
        threading.Thread(target=churn, daemon=True).start()
    t0 = time.perf_counter()
    eaten = c._on_key(0, 0x2D, 0, True, False)
    time.sleep(0.05)
    c._on_key(0, 0x2D, 0, False, False)
    time.sleep(1.25)
    stop.set()
    return [(round((t - t0) * 1000, 1), a, b, d) for t, a, b, d in ev], eaten, c


ev, eaten, c = run(60.0)
print('     timeline (ms after X):', ev)
m = {(a, d): t for t, a, b, d in ev}
check('out of range: the click goes down at once', m.get(('mouse', 'down'), 99) < 2.0, '%.2f ms' % m.get(('mouse', 'down'), -1))
check('click released at 32 ms (as AutoHotkey does)', abs(m.get(('mouse', 'up'), 0) - 32) < 2.5, '%.1f ms' % m.get(('mouse', 'up'), -1))
check('F down at 488 ms after the click (what viri.ahk really does)', abs(m.get(('F', 'down'), 0) - 488) < 2.5, '%.1f ms' % m.get(('F', 'down'), -1))
check('F released 579 ms later', abs(m.get(('F', 'up'), 0) - 1067) < 3.0, '%.1f ms' % m.get(('F', 'up'), -1))
check('X hidden from the game, no hotbar key pressed', eaten is True and not [e for e in ev if isinstance(e[1], int)])
for mode, label, limit in (('real', 'with the reader working at its normal pace (6 runs)', 2.5),
                           (True, 'extreme: another thread hogging Python flat out (6 runs)', 25.0)):
    errs = []
    for i in range(6):
        ev, _, _ = run(60.0, busy=mode)
        m = {(a, d): t for t, a, b, d in ev}
        errs.append(m.get(('F', 'down'), 0) - 488)
    check(label, max(abs(e) for e in errs) < limit, 'F off by ' + ', '.join('%+.1f' % e for e in errs) + ' ms')
ev, _, _ = run(60.0, vir_wait_ms=450.0, vir_hold_ms=700.0)
m = {(a, d): t for t, a, b, d in ev}
check('timings follow the settings (450 / 700)', abs(m[('F', 'down')] - 450) < 2.5 and abs(m[('F', 'up')] - 1150) < 3.0)
ev, _, _ = run(30.0)
check('Viribus IN range: a normal cast, no F', [e[1:] for e in ev] == [('mouse', 'left', 'down'), ('mouse', 'left', 'up')], str(ev))
ev, _, _ = run(60.0, key='-')
check('another spell out of range: held back, nothing sent', ev == [])
print('\nFAILED: %d' % fails if fails else '\nALL TESTS PASSED')

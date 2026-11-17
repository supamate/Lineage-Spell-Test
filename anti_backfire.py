"""Anti-Backfire: an add-on for the Rogue Lineage Assist Tool.

A real click can't be taken away from Roblox (it reads the mouse directly), so casting gets its own key:
press the CAST KEY (X) instead of clicking. With a listed spell in your hand, X sends the real click (right
click for a snap, left click for a normal cast) only while the mana bar is inside that spell's range; outside
the range X does nothing. The spell is never put away, so mana shield (F) works as always.
Your own mouse clicks are not touched - and not protected: cast with X.

Viribus is special: out of range, X does not hold back - it backfires it on purpose and mana-shields the
blast for you (click, wait, hold F), the way viri.ahk does.
Quick cast keys: one key press equips the chosen spell if needed, charges mana up to its range (or waits for
it to drain down into it) and casts.
Like the main tool, every key of this add-on is paused from '/' (chat) until Enter or a mouse click.
Runs next to the main tool and reads the same
cooldown_indicator_config.json, so it always looks at the same mana bar position.
Nothing it sees is ever saved or sent anywhere: the pixels are looked at and forgotten.

How it knows things:
  * mana %      - reads a thin strip of the screen inside the mana bar (same method as the main tool).
  * spell held  - follows the hotbar keys: a key arms its slot, the same key again un-arms it.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import threading
import time
from time import perf_counter as _perf, sleep as _sleep

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(APP_DIR, 'anti_backfire.json')
LOG_PATH = os.path.join(APP_DIR, 'anti_backfire.log')

# ---- colours of the game's EMPTY mana bar (recovered from the main tool) ----
BAR_EMPTY = ((82, 64, 73), (151, 120, 136))                      # normal UI, bright UI
EMPTY_COLORS = ((82, 64, 73), (91, 72, 79), (65, 51, 58), (151, 120, 136), (167, 132, 145), (120, 94, 107))
EMPTY_TOL = 24        # |dr|+|dg|+|db| to count a pixel as empty
PRESENT_TOL = 12      # ... to count it as EXACTLY the empty bar (proves the bar is on screen)
UNLEARNED_SLACK = 1.7 # extra % kept from each edge until the overlay picture's tick lines are known
FILL_TOL = 60         # ... to the learned fill colour (only used to recognise a completely full bar)
INNER = (0.20, 0.55)  # part of the picture's width that is safely inside the bar (rails are at 12.5 % / 62.5 %)
N_COLS = 7            # pixels looked at per row

# ---- hotbar colours (the main tool's own values) ----
SLOT_WHITE = (254, 247, 237)   # body of the slot that is in your hand (or under the mouse)
SLOT_BEIGE = (215, 203, 191)   # body of every other slot
SLOT_FRAME = (71, 57, 44)      # dark frame line along the top of a normal slot
TAB_CREAM = (255, 221, 162)    # the little number tab above each slot (cooldown boxes never cover it)
KEY_TRUST = 0.18               # seconds a hotbar key press is believed before the screen gets the last word
SAMPLE_EVERY = 0.008           # the background reader looks at the mana bar / hotbar this often (seconds)
STALE = 0.15                   # a reading older than this counts as 'mana bar not readable' at the click
TOOL_EXE = 'Rogue.Lineage.Assist.Tool.exe'
TAG = 0x52414246               # marks the key presses this add-on sends, so it can tell them from yours
PRESS_GAP = 0.12               # seconds before it takes a spell OUT again after its last key press
PUT_GAP = 0.05                 # ... but putting a spell AWAY is urgent: it only waits this long
KEY_HOLD = 0.015               # how long it holds a hotbar key down
F_SCAN, G_SCAN = 0x21, 0x22     # F = block / mana shield, G = charge mana
CLICK_HOLD = 0.03              # how long a click sent by a sequence is held
FAST_AFTER = 0.03              # quick cast, confident: click this long after G goes up (the charge has stopped)
G_TAP_GAP = 0.02               # quick cast re-tapping G: how long G is up between two presses
CAST_LOCK = 0.4                # after a cast, no second click for this long (the bar is still catching up)
HYST = 0.7                     # % deeper inside the range before the spell is taken OUT than to keep it out
INTENT_TIMEOUT = 20.0          # a put-away spell is forgotten after this long with no mana charged

HOTBAR_SCAN = {0x02: '1', 0x03: '2', 0x04: '3', 0x05: '4', 0x06: '5', 0x07: '6', 0x08: '7', 0x09: '8',
               0x0A: '9', 0x0B: '0', 0x0C: '-', 0x0D: '='}
HOTBAR_KEYS = list(HOTBAR_SCAN.values())

DEFAULTS = {
    'enabled': True, 'toggle_key': 'f9', 'leeway': 2.0, 'margin': 1.0, 'block_unknown': False,
    'beep': True, 'show_idle': False, 'use_marks': True, 'indicator': None, 'main_config': '',
    'spells': None, 'fill': None, 'mask': None, 'follow_tool': True, 'cast_key': 'x', 'cast_lead_ms': 70.0,
    # Viribus backcast, as viri.ahk REALLY runs on this PC (measured: its "sleep 425" after the click puts F
    # down ~488 ms after the click goes down, the click is held ~32 ms, F is held ~579 ms)
    'vir_wait_ms': 488.0, 'vir_hold_ms': 579.0, 'vir_click_ms': 32.0,
    # Hidden range shift by direction (never shown on the bar): while you charge (G held) the top of every range is
    # this much lower; while mana is not charging the bottom is this much higher.
    'charge_trim': 1.0, 'drain_trim': 1.0,
    # How far the bar on screen trails your real mana while it moves (learned from every quick cast).
    'charge_lag_ms': 120.0, 'charge_lags': [], 'charge_speeds': [], 'rise_delays': [],
    # Quick cast: when G is pressed but mana doesn't start charging (a half-stun from a dash or a move), G is tapped
    # again - never sooner than this after the last press, and never before a charge would have shown on the bar.
    'g_retry_ms': 110.0,
    # Quick cast: time between pressing the spell's hotbar key and the click (the spell is only taken out once mana
    # is in range).
    'qc_equip_ms': 30.0,
    'quick': [], 'qc_extra': 1.0, 'qc_timeout': 25.0,  # quick cast: [{'key': 'y', 'spell': 'Snap Snarvindur'}]
}


def log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ Win32
user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.GetForegroundWindow.restype = wt.HWND
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.BitBlt.restype = wt.BOOL
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.GetCurrentThread.restype = wt.HANDLE
kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.SetThreadPriority.argtypes = [wt.HANDLE, ctypes.c_int]
kernel32.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.SetEvent.argtypes = [wt.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
                ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt.DWORD),
                ('szExeFile', ctypes.c_wchar * 260)]


kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def process_running(exe_name):
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == wt.HANDLE(-1).value:
        return None
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        want = exe_name.lower()
        while ok:
            if e.szExeFile.lower() == want:
                return True
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
        return False
    finally:
        kernel32.CloseHandle(snap)


def window_exe(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wt.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
        return ''
    finally:
        kernel32.CloseHandle(h)

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_QUIT, WM_TIMER = 0x0012, 0x0113
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP = 0x200, 0x201, 0x202, 0x204, 0x205
SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', wt.DWORD), ('scanCode', wt.DWORD), ('flags', wt.DWORD), ('time', wt.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('pt', wt.POINT), ('mouseData', wt.DWORD), ('flags', wt.DWORD), ('time', wt.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wt.WORD), ('wScan', wt.WORD), ('dwFlags', wt.DWORD), ('time', wt.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wt.LONG), ('dy', wt.LONG), ('mouseData', wt.DWORD), ('dwFlags', wt.DWORD), ('time', wt.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('pad', ctypes.c_byte * 32)]
    _anonymous_ = ('u',)
    _fields_ = [('type', wt.DWORD), ('u', _U)]


def send_scan(scan, up):
    """One key event by scan code (what games read), tagged as ours."""
    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(0, scan, 0x0008 | (0x0002 if up else 0), 0, TAG)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def send_button(click, up):
    """A real mouse button event at the cursor ('left' / 'right'), tagged as ours."""
    flag = {('left', False): 0x0002, ('left', True): 0x0004, ('right', False): 0x0008, ('right', True): 0x0010}[(click, up)]
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(0, 0, 0, flag, 0, TAG)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def precise_until(deadline):
    """Wait until a perf_counter() time, to well under a millisecond (sleep most of it, spin the last bit)."""
    while True:
        rem = deadline - _perf()
        if rem <= 0:
            return
        if rem > 0.003:
            _sleep(rem - 0.002)


def key_scan(name):
    """Scan code of a key given as its character ('x') - 0 if it can't be worked out."""
    name = str(name or '').strip().lower()
    if len(name) != 1:
        return 0
    vk = user32.VkKeyScanW(ord(name)) & 0xFF
    return user32.MapVirtualKeyW(vk, 0) if vk != 0xFF else 0


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG), ('biHeight', wt.LONG), ('biPlanes', wt.WORD),
                ('biBitCount', wt.WORD), ('biCompression', wt.DWORD), ('biSizeImage', wt.DWORD),
                ('biXPelsPerMeter', wt.LONG), ('biYPelsPerMeter', wt.LONG), ('biClrUsed', wt.DWORD),
                ('biClrImportant', wt.DWORD), ('bmiColors', wt.DWORD * 3)]


def set_dpi_aware():
    """Same as the main tool, so its saved screen coordinates mean real pixels here too."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class Grabber:
    """Grabs one fixed rectangle of the screen. Use each instance from one thread only.
    grab() -> pixels as 0xAARRGGBB ints, row by row from the top (or None)."""

    def __init__(self, x, y, w, h):
        self.rect = (int(x), int(y), int(w), int(h))
        self.w, self.h = int(w), int(h)
        self.sdc = user32.GetDC(None)
        self.mdc = gdi32.CreateCompatibleDC(self.sdc)
        self.bmp = gdi32.CreateCompatibleBitmap(self.sdc, self.w, self.h)
        self.old = gdi32.SelectObject(self.mdc, self.bmp)
        self.raw = bytearray(self.w * self.h * 4)
        self.cbuf = (ctypes.c_char * len(self.raw)).from_buffer(self.raw)
        self.px = memoryview(self.raw).cast('I')
        self.bmi = BITMAPINFO()
        self.bmi.biSize = 40
        self.bmi.biWidth, self.bmi.biHeight = self.w, -self.h       # negative height = top row first
        self.bmi.biPlanes, self.bmi.biBitCount, self.bmi.biCompression = 1, 32, 0

    def grab(self):
        x, y, w, h = self.rect
        if not gdi32.BitBlt(self.mdc, 0, 0, w, h, self.sdc, x, y, SRCCOPY):
            return None
        if gdi32.GetDIBits(self.mdc, self.bmp, 0, h, self.cbuf, ctypes.byref(self.bmi), 0) != h:
            return None
        return self.px

    def close(self):
        try:
            self.px.release()
            del self.cbuf
            gdi32.SelectObject(self.mdc, self.old)
            gdi32.DeleteObject(self.bmp)
            gdi32.DeleteDC(self.mdc)
            user32.ReleaseDC(None, self.sdc)
        except Exception:
            pass


# ------------------------------------------------------------------------------------------- mana reading
class ManaReader:
    """Turns the pixels of the strip inside the mana bar (100 % line at row 0, 0 % line at the last row) into a %."""

    def __init__(self, tints=(), alpha=0.6, fill=None):
        self.exact = tuple(BAR_EMPTY)
        emp = list(EMPTY_COLORS)
        # a cast-mark box of the main tool drawn over the EMPTY bar shows a blend of both colours: still empty
        for t in tints:
            for e in EMPTY_COLORS:
                emp.append(tuple(int(round(e[i] * (1 - alpha) + t[i] * alpha)) for i in range(3)))
        self.empties = tuple(emp)
        self.cache = {}
        self.fill = tuple(fill) if fill else None
        self.last_bar = (0.0, 0.0)          # (time, %) of the last reading that saw the empty bar
        self.mask = None                    # rows the main tool's picture draws over (tick lines): they say nothing
        self._mask_cand = None

    def _kind(self, v):
        """0 = something else (mana fill), 1 = empty bar, 2 = exactly the empty bar."""
        r, g, b = (v >> 16) & 255, (v >> 8) & 255, v & 255
        k = 0
        for er, eg, eb in self.exact:
            if abs(r - er) + abs(g - eg) + abs(b - eb) <= PRESENT_TOL:
                k = 2
                break
        if not k:
            for er, eg, eb in self.empties:
                if abs(r - er) + abs(g - eg) + abs(b - eb) <= EMPTY_TOL:
                    k = 1
                    break
        if len(self.cache) > 60000:
            self.cache.clear()
        self.cache[v] = k
        return k

    def read(self, px, w, h, now=None, learn=False):
        """-> (pct or None, source). source: 'bar' = read off the bar, 'full' = bar completely full,
        'none' = the mana bar isn't there (menu, loading, covered)."""
        now = time.time() if now is None else now
        cols = [min(w - 1, int((i + 0.5) * w / N_COLS)) for i in range(N_COLS)]
        half = len(cols) / 2.0
        cache, kind = self.cache, self._kind
        row_empty = bytearray(h)
        exact_rows = total_empty = 0
        for y in range(h):
            base = y * w
            e = ex = 0
            for cx in cols:
                v = px[base + cx] & 0xFFFFFF
                k = cache.get(v)
                if k is None:
                    k = kind(v)
                if k:
                    e += 1
                    if k == 2:
                        ex += 1
            if e > half:
                row_empty[y] = 1
                total_empty += 1
                if ex > half:
                    exact_rows += 1
        if exact_rows >= 2:
            if learn:
                self._learn_mask(row_empty, h)
            mask = self.mask if (self.mask is not None and len(self.mask) == h) else None
            # the fill's top edge = the cut with the fewest rows on the wrong side (above it rows should be
            # empty, below it filled). Rows under a tick line of the overlay picture don't vote; where they
            # leave the edge undecided (it is somewhere under the line) the middle of that stretch is used.
            if mask:
                cost = sum(1 for y in range(h) if row_empty[y] and not mask[y])
            else:
                cost = total_empty
            best, lo_cut, hi_cut = cost, 0, 0
            for y in range(h):
                if not (mask and mask[y]):
                    cost += -1 if row_empty[y] else 1
                if cost < best or (cost == best and hi_cut != y):
                    best, lo_cut, hi_cut = cost, y + 1, y + 1
                elif cost == best:
                    hi_cut = y + 1
            if best > 0.3 * h:
                return None, 'none'
            cut = h if hi_cut == h else (0 if lo_cut == 0 else (lo_cut + hi_cut) / 2.0)
            pct = 100.0 * (1.0 - cut / float(h))
            cut = int(cut)
            self.last_bar = (now, pct)
            if learn and 5.0 <= pct <= 95.0 and h - cut >= 12:
                self._learn_fill(px, w, h, cols, cut)
            return pct, 'bar'
        # no empty bar colour at all: either the bar is completely full, or it isn't on screen
        if total_empty <= max(1, h // 50):
            if self.fill and self._matches_fill(px, w, h, cols) >= 0.85:
                return 100.0, 'full'
            if now - self.last_bar[0] < 2.5 and self.last_bar[1] >= 90.0:
                return 100.0, 'full'
        return None, 'none'

    def _learn_mask(self, row_empty, h):
        """While the bar is empty, the only rows that are NOT empty-coloured are the lines the main tool's picture
        draws over it (ticks every 10 %, the bottom edge). Seen twice in a row the same -> those rows are known."""
        run = longest = filled = 0
        for y in range(h):
            if row_empty[y]:
                run = 0
            else:
                run += 1
                filled += 1
                if run > longest:
                    longest = run
        if longest <= max(3, h // 50) and filled <= h // 5:
            cand = bytes(0 if e else 1 for e in row_empty)
            if cand == self._mask_cand:
                self.mask = cand
            self._mask_cand = cand
        else:
            self._mask_cand = None

    def _learn_fill(self, px, w, h, cols, cut):
        rs, gs, bs = [], [], []
        step = max(1, (h - cut - 6) // 40)
        for y in range(cut + 4, h - 2, step):
            base = y * w
            for cx in cols:
                v = px[base + cx] & 0xFFFFFF
                if not self.cache.get(v, 0):
                    rs.append((v >> 16) & 255)
                    gs.append((v >> 8) & 255)
                    bs.append(v & 255)
        if len(rs) >= 20:
            rs.sort(), gs.sort(), bs.sort()
            m = len(rs) // 2
            self.fill = (rs[m], gs[m], bs[m])

    def _matches_fill(self, px, w, h, cols):
        fr, fg, fb = self.fill
        half = len(cols) / 2.0
        ok = 0
        for y in range(h):
            base = y * w
            n = 0
            for cx in cols:
                v = px[base + cx]
                if abs(((v >> 16) & 255) - fr) + abs(((v >> 8) & 255) - fg) + abs((v & 255) - fb) <= FILL_TOL:
                    n += 1
            if n > half:
                ok += 1
        return ok / float(h)


class Hotbar:
    """The 12 hotbar slots at the positions the main tool saved. read() tells which slot is in your hand."""

    def __init__(self, bar):
        self.x, self.y, self.w, self.h, self.pitch = (float(bar[k]) for k in ('x', 'y', 'w', 'h', 'pitch'))
        if self.w < 20 or self.h < 20 or self.pitch < self.w:
            raise ValueError('odd hotbar geometry')
        top = int(round(self.y - 0.15 * self.h))                    # first row inside the number tabs
        self.rect = (int(round(self.x - self.pitch)), top, int(round(self.pitch * 14)),
                     int(round(self.y + 0.18 * self.h)) - top + 1)
        self.tab_rows = (0, 1, 2)
        self.body_rows = (int(round(self.y + 0.12 * self.h)) - top, int(round(self.y + 0.18 * self.h)) - top)
        # The slot in your hand is drawn a little bigger: just above a normal slot's top edge it is already
        # white, where a normal slot still shows its dark frame. The main tool's cooldown boxes don't reach up here.
        self.edge_row = int(round(self.y - 0.03 * self.h)) - top
        # clicks in here are clicks on the hotbar itself, never casts
        self.zone = (self.x - 12, self.y - 0.35 * self.h, self.x + 11 * self.pitch + self.w + 12, self.y + self.h + 14)

    def contains(self, x, y):
        a, b, c, d = self.zone
        return a <= x <= c and b <= y <= d

    def read(self, px, w, h):
        """-> (layout_ok, states): states[i] for key HOTBAR_KEYS[i] is 'W' (in hand), 'B' (not in hand) or
        'X' (can't tell: a cooldown box of the main tool is over it). layout_ok = all 12 number tabs are where
        they should be and there is none left / right of them, so slot i really is key i."""
        def near(v, c, tol):
            return abs(((v >> 16) & 255) - c[0]) + abs(((v >> 8) & 255) - c[1]) + abs((v & 255) - c[2]) <= tol

        x0 = self.rect[0]
        tabs, states = [], []
        for i in range(-1, 13):
            left = self.x + i * self.pitch - x0
            n = 0
            for ry in self.tab_rows:
                for f in (0.425, 0.47, 0.5, 0.53, 0.575):
                    xx = int(round(left + f * self.w))
                    if 0 <= xx < w and near(px[ry * w + xx], TAB_CREAM, 14):
                        n += 1
            tabs.append(n >= 7)
            if 0 <= i < 12:
                wn = bn = tot = 0
                for ry in self.body_rows:
                    for k in range(9):
                        v = px[ry * w + int(round(left + self.w * (0.2 + 0.075 * k)))]
                        tot += 1
                        if near(v, SLOT_WHITE, 24):
                            wn += 1
                        elif near(v, SLOT_BEIGE, 20):
                            bn += 1
                s = 'W' if wn >= 0.7 * tot else ('B' if bn >= 0.7 * tot else 'X')
                if s == 'X' and 0 <= self.edge_row < h:      # body hidden by a cooldown box: look at the top edge
                    ew = ed = 0
                    for f in (0.2, 0.23, 0.26, 0.7, 0.73, 0.76, 0.8):
                        v = px[self.edge_row * w + int(round(left + f * self.w))]
                        if near(v, SLOT_WHITE, 24):
                            ew += 1
                        elif near(v, SLOT_FRAME, 30):
                            ed += 1
                    s = 'W' if ew >= 5 else ('B' if ed >= 5 else 'X')
                states.append(s)
        return (all(tabs[1:13]) and not tabs[0] and not tabs[13]), states


def effective_range(lo, hi, leeway, margin):
    """The % range a cast is let through in: the spell's range widened by your leeway (Fallion training),
    then pulled in by the safety margin (the screen is always a frame behind the game)."""
    a, b = lo - leeway, hi + leeway
    a = 0.0 if a <= 0 else a + margin
    b = 100.0 if b >= 100 else b - margin
    if a > b:
        a = b = (lo + hi) / 2.0
    return a, b


# --------------------------------------------------------------------------------- the main tool's config
CONFIG_NAME = 'cooldown_indicator_config.json'


def _is_tool_name(name):
    n = name.lower()
    return n.endswith('.exe') and (n == TOOL_EXE.lower() or ('lineage' in n and ('assist' in n or 'tool' in n)))


def running_tool_dirs():
    """Folders of every running copy of the Assist Tool (it keeps its config next to its exe)."""
    out = []
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == wt.HANDLE(-1).value:
        return out
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if _is_tool_name(e.szExeFile):
                h = kernel32.OpenProcess(0x1000, False, e.th32ProcessID)
                if h:
                    try:
                        buf = ctypes.create_unicode_buffer(520)
                        n = wt.DWORD(520)
                        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                            d = os.path.dirname(buf.value)
                            if d not in out:
                                out.append(d)
                    finally:
                        kernel32.CloseHandle(h)
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return out


def _user_folders():
    home = os.path.expanduser('~')
    out = []
    for csidl in (0x10, 0x05):                       # the REAL Desktop and Documents (they can be moved to another drive)
        buf = ctypes.create_unicode_buffer(520)
        try:
            if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and os.path.isdir(buf.value):
                out.append(buf.value)
        except Exception:
            pass
    for sub in ('Desktop', 'Downloads', 'Documents', os.path.join('OneDrive', 'Desktop'),
                os.path.join('OneDrive', 'Documents')):
        d = os.path.join(home, sub)
        if os.path.isdir(d):
            out.append(d)
    return out


def _shallow_find(base, name, depth):
    """`name` in base or up to `depth` folders below it (no deep crawling)."""
    base = os.path.abspath(base)
    lvl0 = base.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(base):
        if name in files:
            return os.path.join(root, name)
        if root.count(os.sep) - lvl0 >= depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not d.startswith(('.', '$')) and d.lower() not in
                       ('node_modules', 'appdata', 'windows', 'program files', '__pycache__')]
    return ''


def find_main_config(hint=''):
    """Where the Assist Tool keeps its settings: the place picked before, the running tool's folder, the folder
    around this add-on, then a short look through Desktop / Downloads / Documents."""
    cands = [hint]
    cands += [os.path.join(d, CONFIG_NAME) for d in running_tool_dirs()]
    cands += [os.path.join(APP_DIR, '..', CONFIG_NAME), os.path.join(APP_DIR, CONFIG_NAME)]
    for p in cands:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    for base in [os.path.abspath(os.path.join(APP_DIR, '..', '..'))] + _user_folders():
        try:
            f = _shallow_find(base, CONFIG_NAME, 3)
        except OSError:
            f = ''
        if f:
            return os.path.abspath(f)
    return ''


def find_tool_exe(config_path=''):
    """The Assist Tool's exe: next to its config (any name with 'lineage' + 'assist'/'tool'), else next to us."""
    for d in [os.path.dirname(config_path) if config_path else '', os.path.abspath(os.path.join(APP_DIR, '..'))]:
        if not d or not os.path.isdir(d):
            continue
        if os.path.isfile(os.path.join(d, TOOL_EXE)):
            return os.path.join(d, TOOL_EXE)
        for f in sorted(os.listdir(d)):
            if _is_tool_name(f):
                return os.path.join(d, f)
    return ''


def tool_running(exe_path=''):
    name = os.path.basename(exe_path) if exe_path else TOOL_EXE
    return process_running(name)


def _num(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


class MainConfig:
    """What this add-on needs out of cooldown_indicator_config.json."""

    def __init__(self, path):
        self.path, self.mtime, self.ok, self.error = path, 0.0, False, ''
        self.strip = None            # (x, y, w, h) of the screen strip inside the mana bar
        self.picture = None          # (x, y, w, h) of the whole mana picture
        self.bar = None              # hotbar geometry as saved by the main tool
        self.hotbar = None           # Hotbar reader built from it (None = not usable)
        self.game_title, self.alpha, self.tints = 'Roblox', 0.6, ()
        self.active, self.marks, self.snaps, self.moves = '', [], [], []
        self.reload()

    def changed(self):
        try:
            return os.path.getmtime(self.path) != self.mtime
        except OSError:
            return False

    def reload(self):
        try:
            self.mtime = os.path.getmtime(self.path)
            with open(self.path, encoding='utf-8') as f:
                c = json.load(f)
            m = c.get('mana') or {}
            x, y, w, h = (_num(m.get(k)) for k in 'xywh')
            zone = m.get('zone') or [0.0191, 0.9844]
            z0, z1 = _num(zone[0], 0.0191), _num(zone[1], 0.9844)
            if None in (x, y, w, h) or w <= 4 or h <= 20 or not 0 <= z0 < z1 <= 1:
                raise ValueError("no usable mana bar position - press 'Find Mana Bar' in the main tool")
            top, bot = y + h * z0, y + h * z1
            sx, sw = int(round(x + w * INNER[0])), max(N_COLS, int(round(w * (INNER[1] - INNER[0]))))
            self.strip = (sx, int(round(top)), sw, max(20, int(round(bot - top))))
            self.picture = (int(x), int(y), int(round(w)), int(round(h)))
            self.bar = c.get('bar') or None
            try:
                self.hotbar = Hotbar(self.bar)
            except Exception:
                self.hotbar = None
            S = c.get('settings') or {}
            self.game_title = str(S.get('game_title', 'Roblox') or '')
            self.alpha = min(1.0, max(0.0, _num(S.get('mana_opacity'), 0.6)))
            self.active = str(c.get('active') or '')
            tints = set()
            for lst in (c.get('marks') or {}).values():
                for mk in lst or []:
                    for v in (mk.values() if isinstance(mk, dict) else ()):
                        if isinstance(v, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v):
                            tints.add(tuple(int(v[i:i + 2], 16) for i in (1, 3, 5)))
            self.tints = tuple(sorted(tints))
            self.marks = [mk for mk in (c.get('marks') or {}).get(self.active, []) if isinstance(mk, dict)]
            self.snaps = [s for s in (c.get('snaps') or {}).get(self.active, []) if isinstance(s, dict)]
            self.moves = [s for s in (c.get('profiles') or {}).get(self.active, []) if isinstance(s, dict)]
            self.ok, self.error = True, ''
        except Exception as e:  # a half-written file while the main tool saves: keep what we had
            self.error = str(e)
            if self.strip is None:
                self.ok = False

    def name_for(self, key, snap):
        for s in (self.snaps if snap else self.moves):
            if str(s.get('key')) == key:
                return ('Snap ' if snap else '') + str(s.get('name', ''))
        return ('Snap ' if snap else 'Spell ') + key

    def mark_spells(self):
        """The main tool's cast marks (Spells tab) of the active profile, as spell entries."""
        out = []
        for mk in self.marks:
            key = str(mk.get('key', ''))
            lo, hi = _num(mk.get('lo')), _num(mk.get('hi'))
            if key not in HOTBAR_KEYS or lo is None or hi is None or hi <= lo:
                continue
            snap = mk.get('kind') == 'snap'
            out.append({'on': True, 'name': self.name_for(key, snap), 'key': key,
                        'click': 'right' if snap else 'left', 'lo': lo, 'hi': hi, 'from_mark': True})
        return out

    def first_run_spells(self):
        """Starting list: the spells the main tool already knows about in the active profile."""
        out = []
        for s in self.snaps:
            key, name = str(s.get('key', '')), str(s.get('name', ''))
            if key in HOTBAR_KEYS:
                snarv = 'snarvindur' in name.lower()
                out.append({'on': snarv, 'name': 'Snap ' + name, 'key': key, 'click': 'right',
                            'lo': 20.0 if snarv else None, 'hi': 30.0 if snarv else None})
        for s in self.moves:
            key = str(s.get('key', ''))
            if s.get('spell') and key in HOTBAR_KEYS:
                out.append({'on': False, 'name': str(s.get('name', '')), 'key': key, 'click': 'left',
                            'lo': None, 'hi': None})
        return out


# ------------------------------------------------------------------------------------------------- core
class Core:
    """Everything that isn't the window: key tracking, mana reading, the click decision, the hooks."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.main = None
        self.reader = ManaReader(fill=cfg.get('fill'))
        self.spells = ()             # ((key, click, lo, hi, name), ...) - what the hook thread uses
        self.armed = None            # hotbar key whose slot is in your hand right now
        self.key_t = 0.0             # time of the last hotbar key press
        self.slots_ok = False        # the hotbar was recognised on screen at the last look
        self._hb_grabs = {}
        self._pt = wt.POINT()
        self.chat = False
        self.keys_down = {}          # (scan, extended) -> time of its last 'down' event
        self._seen_k = self._seen_m = None
        self.swallow = {'left': False, 'right': False}
        self.flash_t = 0.0
        self.last_event = None       # (time, text) of the last cast click
        self.toggle_vk = 0x78
        self.hook_ok = False
        self._hk = self._hm = None
        self._tid = 0
        self._hook_grab = self._ui_grab = None
        self.start_done = True
        self._geo_ver = 0
        self._kb_proc = HOOKPROC(self._kb)
        self._ms_proc = HOOKPROC(self._ms)
        self._title_buf = ctypes.create_unicode_buffer(256)
        self.game_hwnd = None        # the Roblox window, while it is the active window (set by the reader thread)
        self._fg_cache = (None, False, 0.0)
        self.reading = (0.0, None, 'none')   # (time, mana %, source) - the reader thread's latest look
        self._logq = []
        self._stop = threading.Event()
        self._beep_evt = threading.Event()
        self.spell_keys = frozenset()
        self.cast_scan = key_scan(cfg.get('cast_key', 'x')) or 0x2D
        self.cast_btn = None         # the mouse button the cast key is holding down right now
        self.quick = {}
        self.job = None              # a running sequence (Viribus backcast / quick cast), advanced by the reader thread
        self.job_label = ''
        self._cancel = False
        self._down = set()           # keys / buttons a sequence is holding down
        self._bc_active = False      # a Viribus backcast is running (its own precisely timed thread)
        self.g_phys = False          # you are physically holding G
        self.last_cast_t = 0.0       # last click this add-on sent for a cast
        self.lag = min(0.5, max(0.02, _num(cfg.get('charge_lag_ms'), 120.0) / 1000.0))   # how far the bar trails, learned
        self.lag_dirty = False
        self._lags = [min(0.5, max(0.02, float(v))) for v in (cfg.get('charge_lags') or []) if _num(v) is not None][-9:]
        if self._lags:
            self.lag = sorted(self._lags)[len(self._lags) // 2]
        self._probe = None           # after quick cast lets go of G: watch where the bar peaks, to learn the lag
        self._speeds = [float(v) for v in (cfg.get('charge_speeds') or []) if (_num(v) or 0) > 3][-9:]
        self.user_hot_t = 0.0        # last time YOU pressed a hotbar key (a quick cast stops when you pick a slot)
        # how long after a G press the bar visibly starts rising (lag + the charge's slow start), learned
        self._rises = [float(v) for v in (cfg.get('rise_delays') or []) if 0.02 < (_num(v) or 0) < 1.5][-9:]
        self._rise_since = None
        self._speed_t = 0.0
        self._bc_args = None
        self._bc_evt = threading.Event()
        threading.Thread(target=self._backcast_worker, daemon=True).start()
        self._eaten = set()          # keys of ours that are down and hidden from the game
        self.casts = 0
        self.intent = None           # the listed spell (hotbar key) you want to cast: kept in / out of the hand for you
        self.intent_t = 0.0
        self.hold_off = (None, 0.0)  # (key, until): you just put this spell away yourself - make sure it stays away
        self.last_press = 0.0
        self.presses = 0
        self._pending_up = None      # (scan, time): a key this add-on is holding down
        self._hist = []
        self.rate = 0.0              # how fast the mana bar is moving, % per second
        self.set_toggle_key(cfg.get('toggle_key', 'f9'))

    # -- settings ---------------------------------------------------------------------------------------
    def set_toggle_key(self, name):
        m = re.fullmatch(r'f(\d{1,2})', str(name).strip().lower())
        n = int(m.group(1)) if m else 9
        self.toggle_vk = 0x70 + (n if 1 <= n <= 24 else 9) - 1

    def set_main(self, main):
        self.main = main
        fill = self.reader.fill
        self.reader = ManaReader(main.tints, main.alpha, fill)
        m = self.cfg.get('mask') or {}
        if m.get('strip') == list(main.strip):           # the tick lines learned last time, same bar position
            rows = set(m.get('rows') or ())
            self.reader.mask = bytes(1 if y in rows else 0 for y in range(main.strip[3]))
        self._geo_ver += 1

    def mask_state(self):
        """The learned tick-line rows in a form that can be saved (None = not learned yet)."""
        mk = self.reader.mask
        if mk is None or not self.main or len(mk) != self.main.strip[3]:
            return None
        return {'strip': list(self.main.strip), 'rows': [y for y, v in enumerate(mk) if v]}

    def set_spells(self, entries):
        leeway, margin = _num(self.cfg.get('leeway'), 0.0), _num(self.cfg.get('margin'), 0.0)
        out = []
        for e in entries:
            lo, hi = _num(e.get('lo')), _num(e.get('hi'))
            if not e.get('on') or lo is None or hi is None or hi < lo or e.get('key') not in HOTBAR_KEYS:
                continue
            a, b = effective_range(lo, hi, leeway, margin)
            name = str(e.get('name') or e['key'])
            click = 'right' if name.strip().lower().startswith('snap') else e.get('click', 'left')
            out.append((e['key'], click, a, b, name))
        self.spells = tuple(out)
        self.spell_keys = frozenset(s[0] for s in out)

    def set_quick(self, rows):
        """Quick cast keys: {scan code: spell name}."""
        q = {}
        for r in rows or ():
            sc = key_scan(r.get('key'))
            if sc and sc != self.cast_scan and sc not in HOTBAR_SCAN and str(r.get('spell') or '').strip():
                q[sc] = str(r['spell']).strip()
        self.quick = q

    def spell_named(self, name):
        name = name.strip().lower()
        return next((s for s in self.spells if s[4].strip().lower() == name), None)

    # -- state ------------------------------------------------------------------------------------------
    def _roblox_foreground(self):
        """The active window if it is Roblox (title from the main tool's Settings AND a Roblox process), else None."""
        fg = user32.GetForegroundWindow()
        if not fg:
            return None
        hw, ok, at = self._fg_cache
        now = time.time()
        if hw == fg and now - at < 1.0:
            return fg if ok else None
        want = (self.main.game_title if self.main else '') or 'Roblox'
        user32.GetWindowTextW(fg, self._title_buf, 256)
        ok = self._title_buf.value == want
        if ok:
            exe = window_exe(fg)
            ok = (not exe) or 'roblox' in exe or exe == 'windows10universal.exe'
        self._fg_cache = (fg, ok, now)
        return fg if ok else None

    def game_focused(self):
        """Instant: is the Roblox window (as last checked by the reader thread) still the active one?"""
        hw = self.game_hwnd
        return bool(hw) and user32.GetForegroundWindow() == hw

    def held(self, click=None):
        """Spell entries of the armed key (for one mouse button, or both)."""
        k = self.armed
        if k is None:
            return []
        return [s for s in self.spells if s[0] == k and (click is None or s[1] == click)]

    def _read(self, which, learn=False):
        main = self.main
        if not main or not main.ok:
            return None, 'none'
        g = self._hook_grab if which == 'hook' else self._ui_grab
        if g is None or g[0] != self._geo_ver:
            if g:
                g[1].close()
            g = (self._geo_ver, Grabber(*main.strip))
            if which == 'hook':
                self._hook_grab = g
            else:
                self._ui_grab = g
        px = g[1].grab()
        if px is None:
            return None, 'none'
        return self.reader.read(px, g[1].w, g[1].h, learn=learn)

    def read_ui(self):
        """The reader thread's latest mana reading (no screen access here)."""
        at, pct, src = self.reading
        if pct is None or time.time() - at > STALE:
            return None, 'none'
        return pct, src

    def _sample_loop(self):
        """Runs all the time: looks at the mana bar and the hotbar while Roblox is the active window, so a click
        can be decided instantly from what was seen a few milliseconds earlier. (Windows only waits a moment for
        a mouse hook; a hook that looks at the screen itself is too slow and the click slips through.)"""
        while not self._stop.is_set():
            wait = 0.05
            if self._bc_active:                          # a Viribus backcast is being timed: stay out of its way
                self._stop.wait(0.02)
                continue
            try:
                main = self.main
                hw = self._roblox_foreground() if (main and main.ok) else None
                self.game_hwnd = hw
                if hw:
                    self.sync_slots('samp')
                    pct, src = self._read('samp', learn=True)
                    now = time.time()
                    self.reading = (now, pct, src)
                    if pct is not None:
                        self._track_rate(now, pct)
                    else:
                        del self._hist[:]
                        self.rate = 0.0
                    self._advance_job(self.chat or not self.cfg.get('enabled'))
                    wait = SAMPLE_EVERY
                else:
                    self.reading = (time.time(), None, 'none')
                    self._advance_job(True)              # Roblox lost focus: stop and let go of everything
                    if self.cast_btn:                    # never leave a button held when Roblox loses focus
                        send_button(self.cast_btn, True)
                        self.cast_btn = None
                while self._logq:
                    log(self._logq.pop(0))
            except Exception:
                import traceback
                log('reader error:\n' + traceback.format_exc())
                wait = 0.5
            self._stop.wait(wait)

    def sync_slots(self, which, cursor=None):
        """Looks at the hotbar and corrects `armed` from it: the white slot is the one in your hand. Key presses
        are only a guess (chat, menus, clicking a slot, dying all fool them); the screen has the last word,
        except for a slot hidden under a cooldown box of the main tool - there the keys are all there is."""
        hb = self.main.hotbar if (self.main and self.main.ok) else None
        if hb is None:
            self.slots_ok = False
            return
        if cursor is None:
            user32.GetCursorPos(ctypes.byref(self._pt))
            cursor = (self._pt.x, self._pt.y)
        if hb.contains(*cursor):                 # a slot under the mouse turns white too: can't tell them apart
            return
        g = self._hb_grabs.get(which)
        if g is None or g[0] != self._geo_ver:
            if g:
                g[1].close()
            g = self._hb_grabs[which] = (self._geo_ver, Grabber(*hb.rect))
        px = g[1].grab()
        if px is None:
            self.slots_ok = False
            return
        self.apply_slots(*hb.read(px, g[1].w, g[1].h))

    def apply_slots(self, ok, states):
        self.slots_ok = ok
        if not ok or time.time() - self.key_t < KEY_TRUST:
            return
        whites = [HOTBAR_KEYS[i] for i, s in enumerate(states) if s == 'W']
        if len(whites) == 1:
            self.armed = whites[0]
        elif not whites and self.armed is not None and states[HOTBAR_KEYS.index(self.armed)] == 'B':
            self.armed = None                    # its slot is in plain view and not white: it isn't in your hand

    # -- the decision -----------------------------------------------------------------------------------
    def allows(self, pct, sp):
        """True when a cast at this mana % is let through. sp = the spell entries of the held key for the button
        (several entries on one key + button: any of them being in range is enough).
        Until the bar has been seen empty once, the tick lines of the main tool's picture aren't known and a
        reading right under one can be up to 1.6 % too high: stay that much further from the edges."""
        k = 0.0 if self.reader.mask is not None else UNLEARNED_SLACK
        return any((a <= 0 or a + k <= pct) and (b >= 100 or pct <= b - k) for _, _, a, b, _ in sp)

    def window(self, key):
        """(lo, hi, name) shown for a spell key: the widest range of its entries."""
        sp = [s for s in self.spells if s[0] == key]
        if not sp:
            return None
        return min(s[2] for s in sp), max(s[3] for s in sp), sp[0][4]

    def charging(self):
        """G is held for the game: by you, or by a quick cast."""
        return self.g_phys or ('k', G_SCAN) in self._down

    def shifted(self, s, charging):
        """The range actually used (never shown): charging -> the top is lower; not charging -> the bottom is higher."""
        key, click, a, b, name = s
        if charging:
            if b < 100:
                b -= _num(self.cfg.get('charge_trim'), 1.0)
        elif a > 0:
            a += _num(self.cfg.get('drain_trim'), 1.0)
        return key, click, a, b, name

    def castable(self, now=None):
        """-> (spell entry to cast or None, mana %, held entries). An entry is castable while the mana bar is
        inside its (hidden-shifted) range - both where it is now and where it really is when the click lands: while
        the bar rises it trails your real mana, so the look-ahead is at least that learned lag."""
        now = time.time() if now is None else now
        sp = self.held()
        at, pct, src = self.reading
        if not sp or pct is None or now - at > STALE:
            return None, (pct if sp else None), sp
        lead = _num(self.cfg.get('cast_lead_ms'), 70.0) / 1000.0
        if self.rate > 0:
            lead = max(lead, self.lag)
        ahead = min(100.0, max(0.0, pct + self.rate * lead))
        ch = self.charging()
        for s in sp:
            s2 = self.shifted(s, ch)
            if self.allows(pct, [s2]) and self.allows(ahead, [s2]):
                return s, pct, sp
        return None, pct, sp

    def cast_down(self):
        """The cast key went down: click for you, but only if that is safe. True = a listed spell is in your hand
        (the key is ours and hidden from the game)."""
        if not self.cfg.get('enabled') or self.chat or not self.game_focused():
            return False
        s, pct, sp = self.castable()
        if not sp:
            return False                                 # no listed spell in your hand: the key is left alone
        if self.cast_btn or self.job or self._bc_active:
            return True
        if time.time() - self.last_cast_t < CAST_LOCK:
            return True                                  # just cast: the bar on screen hasn't caught up yet
        now = time.time()
        what = 'mana bar not readable' if pct is None else 'mana %.1f%%' % pct
        vir = next((e for e in sp if 'viribus' in e[4].lower()), None)
        if s is not None:
            send_button(s[1], False)
            self.cast_btn = s[1]
            self.casts += 1
            self.last_cast_t = now
            text = 'cast (%s click): %s, %s' % (s[1], s[4], what)
        elif vir is not None and pct is not None:
            # Viribus out of range: backfire it on purpose and mana-shield the blast (viri.ahk)
            t0 = _perf()
            send_button(vir[1], False)
            self._bc_active = True
            self._bc_args = (vir[1], t0)
            self._bc_evt.set()                           # the waiting worker thread takes it from here
            text = 'safe backcast: %s, %s' % (vir[4], what)
        else:
            self.flash_t = now
            text = 'held back: %s, %s (casts at %g-%g%%)' % (sp[0][4], what, sp[0][2], sp[0][3])
        self.last_event = (now, text)
        self._logq.append(text)
        return True

    def cast_up(self):
        if self.cast_btn:
            send_button(self.cast_btn, True)
            self.cast_btn = None

    # -- the moving bar ---------------------------------------------------------------------------------------
    def _steady(self, now):
        """The bar is not rising any more (standing still, or draining slowly) over the last ~70 ms."""
        pts = [(at, v) for at, v in self._hist if now - at <= 0.07]
        return len(pts) >= 3 and pts[-1][1] - pts[0][1] <= 0.4

    def _start_probe(self, now, d0, r0):
        self._probe = [now, d0, r0, d0]                  # time G went up, bar then, its speed, highest bar since

    def _watch_probe(self, now, pct):
        pr = self._probe
        if pr is None or pct is None:
            return
        pr[3] = max(pr[3], pct)
        dropped = pr[3] - pct > 2.0 and now - pr[0] > 0.05      # the cast used the mana: the peak was the rest
        if dropped or now - pr[0] > max(0.5, 2.5 * self.lag):
            self._probe = None
            if pr[2] > 15.0:
                self._add_lag((pr[3] - pr[1]) / pr[2])

    def _add_lag(self, v):
        """How far the bar trails the real mana (incl. the key's trip to the game). Median of the last 9 casts,
        so one odd cast can't throw the next one off."""
        self._lags = (self._lags + [min(0.5, max(0.02, v))])[-9:]
        self.lag = sorted(self._lags)[len(self._lags) // 2]
        self.cfg['charge_lag_ms'] = round(self.lag * 1000.0, 1)
        self.cfg['charge_lags'] = [round(x, 4) for x in self._lags]
        self.lag_dirty = True

    def _add_speed(self, v):
        self._speeds = (self._speeds + [v])[-9:]
        self.cfg['charge_speeds'] = [round(x, 2) for x in self._speeds]
        self.lag_dirty = True

    def charge_speed(self):
        """-> (how fast your mana charges in %/s, its spread) - median of the last 9 steady charges; (None, None)
        until 3 are known."""
        if len(self._speeds) < 3:
            return None, None
        s = sorted(self._speeds)
        m = s[len(s) // 2]
        dev = sorted(abs(x - m) for x in s)
        return m, max(0.01 * m, 1.4826 * dev[len(dev) // 2])

    def _add_rise(self, v):
        self._rises = (self._rises + [min(1.5, max(0.02, v))])[-9:]
        self.cfg['rise_delays'] = [round(x, 3) for x in self._rises]
        self.lag_dirty = True

    def stun_wait(self):
        """How long after pressing G a charge would surely be visible. Re-tapping sooner would restart a charge that
        is working (its slow start makes it show late) - that is how a tap-charging loop happens."""
        if len(self._rises) >= 3:
            r = sorted(self._rises)
            return max(r[len(r) // 2] * 1.5, r[-1]) + 0.05
        return max(self.lag + 0.2, 0.45)

    def lag_spread(self):
        """How much the lag varies between casts (robust standard deviation); None until 4 casts are known."""
        if len(self._lags) < 4:
            return None
        m = self.lag
        dev = sorted(abs(x - m) for x in self._lags)
        return max(0.004, 1.4826 * dev[len(dev) // 2])

    # -- sequences (run step by step by the reader thread, every few ms) --------------------------------------
    def _start(self, gen, label):
        self._cancel = False
        self.job_label = label
        self.job = gen

    def _advance_job(self, stop=False):
        j = self.job
        if j is None:
            return
        try:
            if stop or self._cancel:
                j.close()
                raise StopIteration
            next(j)
        except StopIteration:
            self.job, self.job_label, self._cancel = None, '', False
            self._release_all()
        except Exception:
            import traceback
            self._logq.append('sequence error:\n' + traceback.format_exc())
            self.job, self.job_label, self._cancel = None, '', False
            self._release_all()

    def _release_all(self):
        for kind, x in list(self._down):
            send_button(x, True) if kind == 'm' else send_scan(x, True)
        self._down.clear()

    def _hold(self, kind, x, down):
        if down:
            self._down.add((kind, x))
        else:
            self._down.discard((kind, x))
        send_button(x, not down) if kind == 'm' else send_scan(x, not down)

    def _backcast_worker(self):
        """Viribus backfired on purpose: the click is already down. Let it go, then put F (mana shield) down at
        exactly the moment viri.ahk does, and hold it through the blast. Timed to a fraction of a millisecond,
        on its own thread, because being a few tens of ms early or late gets you stunned."""
        try:                                             # highest priority: the game using every core must not delay it
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 15)
        except Exception:
            pass
        while True:
            self._bc_evt.wait()
            self._bc_evt.clear()
            if self._stop.is_set():
                return
            click, t0 = self._bc_args
            f_down = False
            try:
                self.job_label = 'Viribus backcast'
                wait = _num(self.cfg.get('vir_wait_ms'), 488.0) / 1000.0
                hold = _num(self.cfg.get('vir_hold_ms'), 579.0) / 1000.0
                precise_until(t0 + min(wait, _num(self.cfg.get('vir_click_ms'), 32.0) / 1000.0))
                send_button(click, True)
                precise_until(t0 + wait)
                if self.game_focused():
                    send_scan(F_SCAN, False)
                    f_down = True
                    self.bc_times = (_perf() - t0,)
                    precise_until(t0 + wait + hold)
            except Exception as e:
                self._logq.append('backcast error: %r' % (e,))
            finally:
                if f_down:
                    send_scan(F_SCAN, True)
                self._bc_active = False
                self.job_label = ''

    def _job_quick(self, name):
        """Quick cast: charge mana into the spell's range (hold G, or wait while it drains down), and only then take
        the spell out and cast it."""
        s = self.spell_named(name)
        if s is None:
            self._note('quick cast: no listed spell called "%s"' % name)
            return
        key, click, a, b, name = s
        t0 = time.time()
        user_t = self.user_hot_t
        scan = next(sc for sc, k in HOTBAR_SCAN.items() if k == key)
        low = a if a <= 0 else a + _num(self.cfg.get('qc_extra'), 1.0)     # never cast right at the minimum
        top = b if b >= 100 else b - _num(self.cfg.get('charge_trim'), 1.0)
        center = (max(low, a) + top) / 2.0           # aim for the middle: room on both sides
        s2 = self.shifted(s, False)                  # not charging: the bottom of the range is a bit higher
        lo_ok, hi_ok = max(low, s2[2]), s2[3]
        lead = _num(self.cfg.get('cast_lead_ms'), 70.0) / 1000.0
        charging, released = False, None             # released = (time, bar %, bar speed) when G was let go
        g_t = g_base = 0.0
        g_ok, presses, stun_noted = False, 0, False
        while time.time() - t0 < _num(self.cfg.get('qc_timeout'), 25.0):
            if self.user_hot_t != user_t:
                self._note('quick cast stopped: you picked another slot')
                return
            now = time.time()
            at, pct, src = self.reading
            if pct is None or now - at > STALE:
                if charging:                             # can't see the bar: don't charge blind
                    self._hold('k', G_SCAN, False)
                    charging, released = False, None
                yield
                continue
            if charging:
                if not g_ok:
                    if pct - g_base >= 0.8 or self.rate > 10.0:
                        g_ok = True                      # the bar is rising: the charge took
                        if presses == 1:
                            self._add_rise(now - g_t)
                    elif now - g_t >= max(self.stun_wait(), _num(self.cfg.get('g_retry_ms'), 110.0) / 1000.0):
                        # A charge would have shown by now: G isn't charging (half-stun from a dash / a move).
                        # Tap G again. (Never sooner: a tap restarts the charge's slow start.)
                        if not stun_noted:
                            stun_noted = True
                            self._note('quick cast: mana not charging (stunned?) - tapping G until it does')
                        self._hold('k', G_SCAN, False)
                        t1 = time.time()
                        while time.time() - t1 < G_TAP_GAP:
                            yield
                        self._hold('k', G_SCAN, True)
                        g_t, g_base, presses = time.time(), pct, presses + 1
                        yield
                        continue
                # The bar trails the real mana: let go when it will come to REST in the middle of the range. How far
                # it keeps going after G is let go is learned from every quick cast (median of the last 9).
                if g_ok and (pct + max(self.rate, 0.0) * self.lag >= center or pct >= top):
                    self._hold('k', G_SCAN, False)
                    charging, released = False, (now, pct, max(self.rate, 0.0))
                    if presses == 1:                     # after re-taps the timing says nothing about the lag
                        self._start_probe(now, pct, max(self.rate, 0.0))
                yield
                continue
            if released is not None:
                t_rel, d0, r0 = released
                spread = self.lag_spread()
                if spread is not None and r0 > 15.0:
                    pred = d0 + r0 * self.lag            # the overshoot has proven steady: no need to wait
                    unc = 2.0 * spread * r0 + 0.6
                    if lo_ok + unc <= pred <= hi_ok - unc:
                        while time.time() - t_rel < FAST_AFTER:
                            yield
                        yield from self._take_out_and_cast(key, scan, click)
                        self._note('quick cast (%s click): %s, stopped at ~%.1f%% (fast)' % (click, name, pred))
                        return
                if now - t_rel < 0.06:
                    yield                                # G just went up: the bar is still catching up
                    continue
            if not self._steady(now):
                yield                                    # still rising: wait until it has caught up
                continue
            released = None
            ahead = min(100.0, max(0.0, pct + min(self.rate, 0.0) * lead))
            if pct >= low and self.allows(pct, [s2]) and self.allows(ahead, [s2]):
                yield from self._take_out_and_cast(key, scan, click)      # in range: NOW take the spell out
                self._note('quick cast (%s click): %s, mana %.1f%%' % (click, name, pct))
                return
            if pct < low:                                # below the range (or came to rest short of it): charge
                self._hold('k', G_SCAN, True)
                charging, g_ok, g_t, g_base, presses = True, False, time.time(), pct, 1
            yield                                        # above the range: wait while it drains
        self._note('quick cast gave up on %s (mana never got into its range)' % name)

    def _take_out_and_cast(self, key, scan, click):
        """Mana is in range: take the spell out (only if it isn't in your hand already), then click."""
        if self.armed != key:
            self._hold('k', scan, True)
            t1 = time.time()
            while time.time() - t1 < KEY_HOLD:
                yield
            self._hold('k', scan, False)
            while time.time() - t1 < _num(self.cfg.get('qc_equip_ms'), 30.0) / 1000.0:
                yield
        self._hold('m', click, True)
        self.casts += 1
        self.last_cast_t = time.time()
        t1 = time.time()
        while time.time() - t1 < CLICK_HOLD:
            yield
        self._hold('m', click, False)

    def _note(self, text):
        self.last_event = (time.time(), text)
        self._logq.append(text)

    def quick_down(self, name):
        if not self.cfg.get('enabled') or self.chat or not self.game_focused():
            return False
        if self.job is not None:
            self._cancel = True                          # pressed again while it runs: stop
        else:
            self._start(self._job_quick(name), 'quick cast: ' + name)
        return True

    def _track_rate(self, now, pct):
        h = self._hist
        h.append((now, pct))
        while h and now - h[0][0] > 0.12:
            h.pop(0)
        pts = [(at, v) for at, v in h if now - at <= 0.09]
        if len(pts) < 4 or pts[-1][0] - pts[0][0] < 0.03:
            self.rate = 0.0
        else:                                            # least-squares slope: one noisy reading can't swing it
            n = float(len(pts))
            mt = sum(at for at, _ in pts) / n
            mv = sum(v for _, v in pts) / n
            den = sum((at - mt) ** 2 for at, _ in pts)
            self.rate = sum((at - mt) * (v - mv) for at, v in pts) / den if den > 0 else 0.0
            if self.rate > 10.0 and pct < 97.0 and now - self._speed_t > 0.3 and pts[-1][0] - pts[0][0] >= 0.07:
                # a charge seen on the bar: only a cleanly straight stretch tells the true charge speed (the start
                # and the end of a rise bend, which would make it look slower)
                worst = max(abs(v - (mv + self.rate * (at - mt))) for at, v in pts)
                if worst <= 0.45:
                    self._speed_t = now
                    self._add_speed(self.rate)
        self._watch_probe(now, pct)

    # -- hooks ------------------------------------------------------------------------------------------
    def _kb(self, code, wparam, lparam):
        try:
            if code == 0:
                k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                seen = (k.time, k.scanCode, k.flags, wparam)
                if seen != self._seen_k:         # (while re-hooking, two of our hooks see the same event)
                    self._seen_k = seen
                    if self._on_key(k.vkCode, k.scanCode, k.flags & 1, wparam in (WM_KEYDOWN, WM_SYSKEYDOWN),
                                    k.dwExtraInfo == TAG):
                        return 1                 # one of this add-on's own keys: the game doesn't get it
        except Exception as e:
            self._logq.append('keyboard hook error: %r' % (e,))
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_key(self, vk, scan, ext, down, ours=False):
        """-> True when the key is one of this add-on's own (cast key / quick cast) and is hidden from the game."""
        ident = (scan, ext)
        if scan == G_SCAN and not ext and not ours:
            self.g_phys = down                   # you are charging (only watched, never taken)
        if ident in self._eaten:                 # a key of ours that is down: its repeats and its release
            if not down:
                self._eaten.discard(ident)
                self.keys_down.pop(ident, None)
                if scan == self.cast_scan:
                    self.cast_up()
            return True
        if not down:
            self.keys_down.pop(ident, None)
            return False
        now = time.time()
        last = self.keys_down.get(ident)
        self.keys_down[ident] = now
        if last is not None and now - last < 0.7:    # auto-repeat of a held key (repeats come every ~30 ms)
            return False
        if vk == self.toggle_vk:
            self.cfg['enabled'] = not self.cfg.get('enabled')
            self.cfg['_dirty'] = True
            return False
        if ours or not self.game_focused():
            if ours and not ext and scan in HOTBAR_SCAN and self.game_focused():
                key = HOTBAR_SCAN[scan]              # a hotbar key a sequence of ours pressed
                self.armed = None if self.armed == key else key
                self.key_t = now
            return False
        # Chat, exactly like the main tool: '/' pauses every key of this add-on until Enter or a mouse click.
        if scan == 0x1C:
            self.chat = False
            return False
        if self.chat:
            return False
        if scan == 0x35 and not ext:
            self.chat = True
            return False
        if not ext and scan == self.cast_scan:
            if self.cast_down():
                self._eaten.add(ident)
                return True
            return False
        if not ext and scan in self.quick:
            if self.quick_down(self.quick[scan]):
                self._eaten.add(ident)
                return True
            return False
        if not ext and scan in HOTBAR_SCAN:
            key = HOTBAR_SCAN[scan]
            self.armed = None if self.armed == key else key     # same key again = put away
            self.key_t = now
            self.user_hot_t = now
        return False

    def _ms(self, code, wparam, lparam):
        # Clicks are only watched: a mouse click ends the chat pause, like in the main tool. Nothing is ever
        # swallowed - Roblox reads the mouse directly, so swallowing a click here would not stop it anyway.
        if code == 0 and self.chat and wparam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            m = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if m.dwExtraInfo != TAG and self.game_focused():
                self.chat = False
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _install(self):
        mod = kernel32.GetModuleHandleW(None)
        self._hk = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, mod, 0) or \
            user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, None, 0)
        self._hm = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, mod, 0) or \
            user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, None, 0)
        self.hook_ok = bool(self._hk and self._hm)
        if not self.hook_ok:
            log('could not install the hooks (error %d)' % ctypes.get_last_error())

    def _remove(self):
        for h in (self._hk, self._hm):
            if h:
                user32.UnhookWindowsHookEx(h)
        self._hk = self._hm = None

    def _hook_thread(self, ready):
        self._tid = kernel32.GetCurrentThreadId()
        self._install()
        # Hooks installed last are asked first. Re-installing now and then keeps this add-on in front of the
        # main tool (and AutoHotkey), so they never see a click that was swallowed here.
        user32.SetTimer(None, 0, 10000, None)
        ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_TIMER and not (self.swallow['left'] or self.swallow['right']):
                old = (self._hk, self._hm)
                self._install()
                for h in old:
                    if h:
                        user32.UnhookWindowsHookEx(h)
        self._remove()

    def _beep_loop(self):
        while not self._stop.is_set():
            if self._beep_evt.wait(0.5):
                self._beep_evt.clear()
                _beep()

    def start(self):
        self._sampler = threading.Thread(target=self._sample_loop, daemon=True)
        self._sampler.start()
        threading.Thread(target=self._beep_loop, daemon=True).start()
        ready = threading.Event()
        self._thread = threading.Thread(target=self._hook_thread, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(3.0)
        return self.hook_ok

    def stop(self):
        self._stop.set()
        self._bc_evt.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(1.0)


def _beep():
    try:
        import winsound
        winsound.Beep(700, 45)
    except Exception:
        pass


# ----------------------------------------------------------------------------------------------- settings
def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        with open(CFG_PATH, encoding='utf-8') as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_cfg(cfg):
    data = {k: v for k, v in cfg.items() if not k.startswith('_')}
    tmp = CFG_PATH + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, CFG_PATH)
    except OSError as e:
        log('could not save settings: %r' % (e,))


# ------------------------------------------------------------------------------------------------ window
def run_ui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    set_dpi_aware()
    launch = '--launch-tool' in sys.argv
    early_cfg = {}
    try:
        with open(CFG_PATH, encoding='utf-8') as f:
            early_cfg = json.load(f)
    except (OSError, ValueError):
        pass
    tool = {'path': find_tool_exe(early_cfg.get('main_config') or find_main_config(early_cfg.get('main_config', '')))}

    def start_tool():
        p = tool['path']
        if launch and p and os.path.isfile(p) and tool_running(p) is False:
            os.startfile(p)
            return True
        return False

    show_evt = kernel32.CreateEventW(None, False, False, 'RL_AntiBackfire_show_settings')
    mutex = kernel32.CreateMutexW(None, False, 'RL_AntiBackfire_single_instance')
    if ctypes.get_last_error() == 183:
        # already running: start the tool if it isn't, otherwise this double-click means 'show the settings'
        if not start_tool() and show_evt:
            kernel32.SetEvent(show_evt)
        return
    start_tool()
    try:
        if os.path.getsize(LOG_PATH) > 1_000_000:
            os.remove(LOG_PATH)
    except OSError:
        pass

    cfg = load_cfg()
    core = Core(cfg)
    root = tk.Tk()
    root.withdraw()                                  # runs silently: the settings window only opens on request
    root.title('Anti-Backfire')
    root.resizable(False, False)
    # Rogue Lineage colours: dark leather, bronze frame, cream parchment text
    BG, FG, DIM, OK, BAD, WARN = '#1e1712', '#f1e3c8', '#9c8a70', '#9fc46a', '#d0583e', '#e0a84e'
    FIELD, EDGE, BTN, BTN_HI, BRONZE, CREAM = '#2c221a', '#5b4430', '#3a2c20', '#4a3828', '#b07a45', '#ffdda2'
    SERIF = 'Georgia'
    root.configure(bg=BG)
    st = ttk.Style()
    st.theme_use('clam')
    st.configure('.', background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=EDGE,
                 lightcolor=EDGE, darkcolor=EDGE, font=(SERIF, 10), insertcolor=FG)
    st.configure('TButton', background=BTN, padding=(8, 3))
    st.map('TButton', background=[('active', BTN_HI)])
    st.map('TCheckbutton', background=[('active', BG)])
    st.configure('Dim.TLabel', foreground=DIM)
    st.configure('Head.TLabel', foreground=DIM, font=(SERIF, 9))
    st.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', FG)])
    root.option_add('*TCombobox*Listbox.background', FIELD)
    root.option_add('*TCombobox*Listbox.foreground', FG)
    cfg.pop('settle_spells', None)                   # the old stop-and-settle switch (replaced by the hidden shift)
    if cfg.get('vir_v') != 2:                        # old values were viri.ahk's nominal sleeps, not the real timing
        cfg['vir_v'] = 2
        if _num(cfg.get('vir_wait_ms')) == 425.0:
            cfg['vir_wait_ms'] = 488.0
        if _num(cfg.get('vir_hold_ms')) == 575.0:
            cfg['vir_hold_ms'] = 579.0
    if cfg.get('theme_v') != 2:                      # the overlay got quieter: the idle label is off now
        cfg['theme_v'], cfg['show_idle'] = 2, False

    state = {'main': None, 'save_job': None, 'rows': [], 'mark_spells': [], 'row_no': 0, 'moving': False, 'quick_rows': [],
             'last_top': 0.0, 'last_fill_save': 0.0, 'err_t': 0.0, 'tool_seen': 0.0, 'tool_check': 0.0,
             'shown_once': False}

    # ---- main tool config
    def load_main(path):
        if not path:
            state['main'] = None
            return
        mc = MainConfig(path)
        state['main'] = mc
        cfg['main_config'] = path
        tool['path'] = find_tool_exe(path) or tool['path']
        if mc.ok:
            core.set_main(mc)

    load_main(find_main_config(cfg.get('main_config', '')))
    main = state['main']
    if cfg.get('spells') is None:
        cfg['spells'] = main.first_run_spells() if main and main.ok else []

    # ---- applying / saving
    def apply():
        mc = state['main']
        state['mark_spells'] = mc.mark_spells() if (mc and mc.ok and cfg.get('use_marks')) else []
        own = cfg['spells']
        taken = {(e.get('key'), e.get('click')) for e in own if e.get('on')}
        core.set_spells(own + [m for m in state['mark_spells'] if (m['key'], m['click']) not in taken])
        core.set_quick(cfg.get('quick'))
        names = [s[4] for s in core.spells]
        for qr in state['quick_rows']:
            qr['spell_box'].configure(values=names)
        for row in state['rows']:
            row['update']()
        marks_var.set('Also blocking the %d cast mark(s) of the main tool\'s Spells tab' % len(state['mark_spells'])
                      if state['mark_spells'] else 'Also use the cast marks from the main tool\'s Spells tab')

    def save_soon(*_):
        apply()
        if state['save_job']:
            root.after_cancel(state['save_job'])
        state['save_job'] = root.after(400, lambda: save_cfg(cfg))

    pad = {'padx': 10, 'pady': 4}
    top = ttk.Frame(root)
    top.pack(fill='x', **pad)
    enabled_var = tk.BooleanVar(value=bool(cfg.get('enabled')))

    def on_enabled():
        cfg['enabled'] = enabled_var.get()
        save_soon()

    ttk.Checkbutton(top, text='Anti-Backfire ON', variable=enabled_var, command=on_enabled).pack(side='left')
    ttk.Label(top, text='(%s toggles it in game)' % str(cfg.get('toggle_key', 'f9')).upper(),
              style='Dim.TLabel').pack(side='left', padx=8)

    # ---- spells table
    box = ttk.Frame(root)
    box.pack(fill='x', padx=10, pady=(6, 2))
    for i, (t, w) in enumerate((('On', 3), ('Spell', 20), ('Key', 4), ('Cast with', 14), ('Min %', 6),
                                ('Max %', 6), ('Cast key works at', 16), ('', 3))):
        ttk.Label(box, text=t, style='Head.TLabel', width=w).grid(row=0, column=i, sticky='w', padx=2)
    CLICKS = {'left': 'Left click', 'right': 'Right click (snap)'}

    def fmt(v):
        return '' if v is None else ('%g' % v)

    def add_row(entry):
        v_on = tk.BooleanVar(value=bool(entry.get('on')))
        v_name = tk.StringVar(value=entry.get('name', ''))
        v_key = tk.StringVar(value=entry.get('key', '1'))
        v_click = tk.StringVar(value=CLICKS.get(entry.get('click'), CLICKS['left']))
        v_lo, v_hi = tk.StringVar(value=fmt(entry.get('lo'))), tk.StringVar(value=fmt(entry.get('hi')))
        v_eff = tk.StringVar()
        ws = [ttk.Checkbutton(box, variable=v_on),
              ttk.Entry(box, textvariable=v_name, width=20),
              ttk.Combobox(box, textvariable=v_key, values=HOTBAR_KEYS, width=3, state='readonly'),
              ttk.Combobox(box, textvariable=v_click, values=list(CLICKS.values()), width=16, state='readonly'),
              ttk.Entry(box, textvariable=v_lo, width=6), ttk.Entry(box, textvariable=v_hi, width=6),
              ttk.Label(box, textvariable=v_eff, width=16)]
        row = {'entry': entry, 'widgets': ws}

        def update():
            lo, hi = _num(entry.get('lo')), _num(entry.get('hi'))
            if lo is None or hi is None or hi < lo:
                v_eff.set('type a range')
                ws[6].configure(foreground=WARN)
            elif not entry.get('on'):
                v_eff.set('off')
                ws[6].configure(foreground=DIM)
            else:
                a, b = effective_range(lo, hi, _num(cfg.get('leeway'), 0.0), _num(cfg.get('margin'), 0.0))
                v_eff.set('%g - %g %%' % (round(a, 1), round(b, 1)))
                ws[6].configure(foreground=OK)

        def changed(*_):
            entry['on'], entry['name'], entry['key'] = v_on.get(), v_name.get().strip(), v_key.get()
            entry['click'] = 'right' if v_click.get() == CLICKS['right'] else 'left'
            entry['lo'], entry['hi'] = _num(v_lo.get()), _num(v_hi.get())
            if entry['lo'] is not None:
                entry['lo'] = min(100.0, max(0.0, entry['lo']))
            if entry['hi'] is not None:
                entry['hi'] = min(100.0, max(0.0, entry['hi']))
            save_soon()

        def delete():
            cfg['spells'].remove(entry)
            for w_ in ws + [btn]:
                w_.destroy()
            state['rows'].remove(row)
            save_soon()

        btn = ttk.Button(box, text='x', width=2, command=delete)
        state['row_no'] += 1                      # never reused, so rows stay in order after deletions
        for i, w_ in enumerate(ws + [btn]):
            w_.grid(row=state['row_no'], column=i, sticky='w', padx=2, pady=1)
        row['update'] = update
        state['rows'].append(row)
        for v in (v_on, v_name, v_key, v_click, v_lo, v_hi):
            v.trace_add('write', changed)

    def new_spell():
        e = {'on': True, 'name': 'New spell', 'key': '1', 'click': 'left', 'lo': None, 'hi': None}
        cfg['spells'].append(e)
        add_row(e)
        save_soon()

    ttk.Button(root, text='+ Add spell', command=new_spell).pack(anchor='w', padx=10, pady=(2, 6))
    ttk.Label(root, style='Dim.TLabel', justify='left',
              text="Cast with the CAST KEY (%s) instead of clicking. With a listed spell in your hand it clicks for you "
                   "(right click for a snap,\nleft click otherwise) only while mana is inside the range; outside it "
                   "does nothing. The spell stays in your hand.\nYour own mouse clicks are not protected. "
                   "Viribus out of range: backfired on purpose and mana-shielded for you.\n"
                   "While you hold G the range quietly ends a little earlier (and X allows for how far the bar "
                   "trails), when you don't, it starts a little later."
                   % str(cfg.get('cast_key', 'x')).upper()).pack(anchor='w', padx=10, pady=(0, 6))

    # ---- quick cast menu
    ttk.Separator(root).pack(fill='x', padx=10, pady=4)
    ttk.Label(root, text='Quick cast').pack(anchor='w', padx=10)
    ttk.Label(root, style='Dim.TLabel', justify='left',
              text='One key: equips the spell if it is not in your hand, charges mana into its range (or waits for it '
                   'to drain down into it)\nand casts. Press the key again to stop it.').pack(anchor='w', padx=10)
    qbox = ttk.Frame(root)
    qbox.pack(fill='x', padx=10, pady=(2, 2))
    QKEYS = [c for c in 'YHZTVBNCRUJKLMOPI']

    def add_quick(entry):
        v_key = tk.StringVar(value=str(entry.get('key', 'y')).upper())
        v_spell = tk.StringVar(value=entry.get('spell', ''))
        fr = ttk.Frame(qbox)
        fr.pack(anchor='w', pady=1)
        ttk.Label(fr, text='Key').pack(side='left')
        ttk.Combobox(fr, textvariable=v_key, values=QKEYS, width=3, state='readonly').pack(side='left', padx=(4, 10))
        ttk.Label(fr, text='casts').pack(side='left')
        sb = ttk.Combobox(fr, textvariable=v_spell, values=[s[4] for s in core.spells], width=24, state='readonly')
        sb.pack(side='left', padx=(4, 10))
        qr = {'entry': entry, 'spell_box': sb}

        def changed(*_):
            entry['key'], entry['spell'] = v_key.get().lower(), v_spell.get()
            save_soon()

        def delete():
            cfg['quick'].remove(entry)
            state['quick_rows'].remove(qr)
            fr.destroy()
            save_soon()

        ttk.Button(fr, text='x', width=2, command=delete).pack(side='left')
        state['quick_rows'].append(qr)
        v_key.trace_add('write', changed)
        v_spell.trace_add('write', changed)

    def new_quick():
        used = {str(q.get('key', '')).upper() for q in cfg['quick']}
        e = {'key': next((k for k in QKEYS if k not in used), 'Y').lower(), 'spell': ''}
        cfg['quick'].append(e)
        add_quick(e)
        save_soon()

    if not isinstance(cfg.get('quick'), list):
        cfg['quick'] = []
    if not cfg['quick'] and not cfg.get('quick_seeded'):         # first time: one example row to start from
        snap = next((e.get('name') for e in cfg['spells'] if str(e.get('name', '')).lower().startswith('snap')), None)
        if snap:
            cfg['quick'].append({'key': 'y', 'spell': snap})
    cfg['quick_seeded'] = True
    ttk.Button(root, text='+ Add quick cast key', command=new_quick).pack(anchor='w', padx=10, pady=(2, 6))
    ttk.Separator(root).pack(fill='x', padx=10, pady=4)

    # ---- options
    opt = ttk.Frame(root)
    opt.pack(fill='x', **pad)

    def num_opt(col, label, key, tip):
        v = tk.StringVar(value=fmt(_num(cfg.get(key), 0.0)))
        ttk.Label(opt, text=label).grid(row=0, column=col, sticky='w')
        ttk.Entry(opt, textvariable=v, width=5).grid(row=0, column=col + 1, padx=(4, 4))
        ttk.Label(opt, text=tip, style='Dim.TLabel').grid(row=0, column=col + 2, sticky='w', padx=(0, 14))

        def ch(*_):
            n = _num(v.get())
            if n is not None:
                cfg[key] = min(50.0, max(0.0, n))
                save_soon()
        v.trace_add('write', ch)

    num_opt(0, 'Leeway +/-', 'leeway', '% (Fallion training)')
    num_opt(3, 'Safety margin', 'margin', '% kept from each edge')

    vir = ttk.Frame(root)
    vir.pack(fill='x', padx=10, pady=(0, 4))

    def ms_opt(label, key, dflt):
        v = tk.StringVar(value=fmt(_num(cfg.get(key), dflt)))
        ttk.Label(vir, text=label).pack(side='left')
        ttk.Entry(vir, textvariable=v, width=5).pack(side='left', padx=4)

        def ch(*_):
            n = _num(v.get())
            if n is not None:
                cfg[key] = min(5000.0, max(0.0, n))
                save_soon()
        v.trace_add('write', ch)

    ms_opt('Viribus backcast: F goes down', 'vir_wait_ms', 488.0)
    ms_opt('ms after the click, held for', 'vir_hold_ms', 579.0)
    ttk.Label(vir, text="ms   (what viri.ahk's sleep 425 / 575 really take on this PC)", style='Dim.TLabel').pack(side='left')

    def bool_opt(text, key):
        v = tk.BooleanVar(value=bool(cfg.get(key)))

        def ch():
            cfg[key] = v.get()
            save_soon()
        ttk.Checkbutton(root, text=text, variable=v, command=ch).pack(anchor='w', padx=10)
        return v

    marks_var = tk.StringVar()
    v_marks = tk.BooleanVar(value=bool(cfg.get('use_marks')))

    def ch_marks():
        cfg['use_marks'] = v_marks.get()
        save_soon()

    ttk.Checkbutton(root, textvariable=marks_var, variable=v_marks, command=ch_marks).pack(anchor='w', padx=10)
    lead = ttk.Frame(root)
    lead.pack(fill='x', padx=10, pady=(0, 4))
    v_lead = tk.StringVar(value=fmt(_num(cfg.get('cast_lead_ms'), 70.0)))
    ttk.Label(lead, text='Look ahead').pack(side='left')
    ttk.Entry(lead, textvariable=v_lead, width=5).pack(side='left', padx=4)
    ttk.Label(lead, text='ms  (while mana is moving, the click must still be in range this much later; raise it '
                         'if you lag)', style='Dim.TLabel').pack(side='left')

    def ch_lead(*_):
        n = _num(v_lead.get())
        if n is not None:
            cfg['cast_lead_ms'] = min(300.0, max(0.0, n))
            save_soon()
    v_lead.trace_add('write', ch_lead)
    bool_opt("Show a small mark on screen while no listed spell is held", 'show_idle')
    bool_opt('Close together with the Rogue Lineage Assist Tool (when started with the shortcut)', 'follow_tool')

    # ---- status
    ttk.Separator(root).pack(fill='x', padx=10, pady=6)
    status = tk.StringVar()
    lbl_status = ttk.Label(root, textvariable=status, justify='left')
    lbl_status.pack(anchor='w', padx=10)
    event = tk.StringVar()
    ttk.Label(root, textvariable=event, style='Dim.TLabel', justify='left', wraplength=640).pack(anchor='w', padx=10)

    btns = ttk.Frame(root)
    btns.pack(fill='x', padx=10, pady=8)

    def browse():
        p = filedialog.askopenfilename(title='Pick cooldown_indicator_config.json',
                                       filetypes=[('Main tool config', '*.json')])
        if p:
            load_main(p)
            save_soon()

    def toggle_move():
        state['moving'] = not state['moving']
        ind.set_clickthrough(not state['moving'])
        move_btn.configure(text='Done moving' if state['moving'] else 'Move indicator')

    ttk.Button(btns, text='Find main tool config...', command=browse).pack(side='left')
    move_btn = ttk.Button(btns, text='Move indicator', command=toggle_move)
    move_btn.pack(side='left', padx=6)
    ttk.Button(btns, text='Quit Anti-Backfire', command=lambda: on_close()).pack(side='right')
    ttk.Label(root, text='Closing this window only hides it: Anti-Backfire keeps running in the background.\n'
                         'Double-click the shortcut again to bring this window back.',
              style='Dim.TLabel', justify='left').pack(anchor='w', padx=10, pady=(0, 8))

    def show_settings():
        root.deiconify()
        root.lift()
        root.attributes('-topmost', True)
        root.after(300, lambda: root.attributes('-topmost', False))
        root.focus_force()

    # ---- on-screen indicator
    class Indicator:
        def __init__(self):
            self.win = tk.Toplevel(root)
            self.win.overrideredirect(True)
            self.win.attributes('-topmost', True)
            self.win.attributes('-alpha', 0.0)
            self.win.configure(bg=BRONZE)                 # 1 px bronze frame, like the game's panels
            inner = tk.Frame(self.win, bg='#241b14')
            inner.pack(padx=1, pady=1)
            self.dot = tk.Label(inner, text='\u25c6', font=(SERIF, 9), bg='#241b14', fg=DIM, padx=0, pady=1)
            self.dot.pack(side='left', padx=(6, 3))
            self.lbl = tk.Label(inner, text='', font=(SERIF, 10), bg='#241b14', fg=CREAM, padx=0, pady=1)
            self.lbl.pack(side='left', padx=(0, 7))
            self.shown = None
            self.win.update_idletasks()
            self.hwnd = int(self.win.wm_frame(), 16)
            self.set_clickthrough(True)
            self.lbl.bind('<ButtonPress-1>', self._grab)
            self.lbl.bind('<B1-Motion>', self._drag)
            self.lbl.bind('<ButtonRelease-1>', self._drop)

        def set_clickthrough(self, on):
            ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            ex = (ex | WS_EX_TRANSPARENT) if on else (ex & ~WS_EX_TRANSPARENT)
            user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)

        def place(self, x, y):
            self.win.geometry('+%d+%d' % (x, y))

        def _grab(self, e):
            self._off = (e.x, e.y)

        def _drag(self, e):
            if state['moving']:
                self.place(e.x_root - self._off[0], e.y_root - self._off[1])

        def _drop(self, e):
            if state['moving']:
                cfg['indicator'] = [self.win.winfo_x(), self.win.winfo_y()]
                save_soon()

        def show(self, text, mark_colour, frame=BRONZE, glyph='\u25c6'):
            key = (text, mark_colour, frame, glyph)
            if key != self.shown:
                self.shown = key
                self.lbl.configure(text=text)
                self.dot.configure(text=glyph, fg=mark_colour)
                self.win.configure(bg=frame)
                self.win.attributes('-alpha', 0.88)

        def hide(self):
            if self.shown is not None:
                self.shown = None
                self.win.attributes('-alpha', 0.0)

    ind = Indicator()

    def place_indicator():
        xy = cfg.get('indicator')
        mc = state['main']
        if not xy and mc and mc.ok:
            xy = [mc.picture[0] + mc.picture[2] + 6, mc.strip[1]]
        ind.place(*(xy or [120, 120]))

    place_indicator()
    for e in cfg['spells']:
        add_row(e)
    for e in cfg['quick']:
        add_quick(e)
    apply()

    # ---- the loop
    def tick_body():
        now = time.time()
        mc = state['main']
        if cfg.pop('_dirty', False):                       # toggled with the hotkey
            enabled_var.set(bool(cfg.get('enabled')))
            save_soon()
        if mc and mc.changed():                            # the main tool saved its config
            mc.reload()
            if mc.ok:
                core.set_main(mc)
                apply()
        if show_evt and kernel32.WaitForSingleObject(show_evt, 0) == 0:
            show_settings()
        if mc is None and now - state.get('cfg_look', 0.0) > 5.0:
            state['cfg_look'] = now                  # not found yet: keep looking (e.g. the tool was started later)
            found = find_main_config('')
            if found:
                load_main(found)
                apply()
                save_soon()
                mc = state['main']
        if not state['shown_once'] and ((not mc or not mc.ok) or (core.start_done and not core.hook_ok)):
            state['shown_once'] = True               # something is wrong: say so instead of staying invisible
            show_settings()
        if launch and cfg.get('follow_tool') and now - state['tool_check'] > 2.0:
            state['tool_check'] = now
            if tool_running(tool['path']):
                state['tool_seen'] = now
            elif state['tool_seen'] and now - state['tool_seen'] > 4.0:
                on_close()                           # the main tool was closed: close with it
                return
        focused = core.game_focused()
        pct, src = core.read_ui()
        held = core.held()
        on = bool(cfg.get('enabled'))
        # status lines in the window
        if not mc or not mc.ok:
            status.set("Main tool config not found - click 'Find main tool config...'"
                       + ('\n' + mc.error if mc and mc.error else ''))
            lbl_status.configure(foreground=BAD)
        elif not core.hook_ok:
            status.set('Could not hook the mouse / keyboard - clicks are NOT being blocked.')
            lbl_status.configure(foreground=BAD)
        else:
            mana = 'not visible' if pct is None else ('FULL' if src == 'full' else '%.1f %%' % pct)
            hold = ('key %s' % core.armed) + (' = ' + ' / '.join(s[4] for s in held) if held else ' (not a listed spell)') \
                if core.armed else 'nothing'
            slot = 'hotbar seen' if core.slots_ok else 'hotbar not seen - following key presses only'
            guard = 'no listed spell in hand'
            if held:
                guard = ('%s would CAST' if core.castable()[0] else '%s is held back') % str(cfg.get('cast_key', 'x')).upper()
            status.set('Game focused: %s     Mana: %s     Holding: %s     Cast key: %s\nHeld-slot check: %s'
                       % ('yes' if focused else 'no', mana, hold, guard, slot if focused else '(game not focused)'))
            lbl_status.configure(foreground=FG if on else DIM)
        if core.last_event and now - core.last_event[0] < 20:
            event.set('Last action: ' + core.last_event[1])
        # indicator
        if state['moving']:
            ind.show('drag to place', WARN)
        elif not (focused and mc and mc.ok):
            ind.hide()
        elif not on:
            ind.show('Anti-Backfire off', DIM, EDGE, '\u25c7') if (held or cfg.get('show_idle')) else ind.hide()
        elif core.job_label:
            ind.show(core.job_label + ('' if pct is None else '  \u00b7  %.0f%%' % pct), WARN)
        elif held and now - core.flash_t < 0.4:
            ind.show('held back' + ('' if pct is None else '  \u00b7  %.0f%%' % pct), BAD, BAD, '\u2715')
        elif held:
            a, b, name = core.window(core.armed)
            name = name[5:] if name.lower().startswith('snap ') else name
            txt = '%s  %g\u2013%g  \u00b7  %s' % (name, round(a, 1), round(b, 1), '?' if pct is None else '%.0f%%' % pct)
            ind.show(txt, OK if core.castable()[0] else BAD)
        elif cfg.get('show_idle'):
            ind.show('Anti-Backfire', DIM, EDGE, '\u25c7')
        else:
            ind.hide()
        if now - state['last_top'] > 2.0:
            state['last_top'] = now
            ind.win.attributes('-topmost', True)
            learned = False                               # things the reader worked out: keep them for next time
            if core.lag_dirty:
                core.lag_dirty, learned = False, True
            ms = core.mask_state()
            if ms is not None and ms != cfg.get('mask'):
                cfg['mask'], learned = ms, True
            if core.reader.fill and list(core.reader.fill) != cfg.get('fill'):
                cfg['fill'], learned = list(core.reader.fill), True
            if learned and now - state['last_fill_save'] > 30:
                state['last_fill_save'] = now
                save_cfg(cfg)

    def tick():
        if state.get('closing'):
            return
        try:
            tick_body()
        except Exception:                                  # never let one bad refresh stop the window updating
            if time.time() - state['err_t'] > 10:
                state['err_t'] = time.time()
                import traceback
                log('refresh error:\n' + traceback.format_exc())
        if not state.get('closing'):
            root.after(60, tick)

    def on_close():
        if state.get('closing'):
            return
        state['closing'] = True
        core.stop()
        save_cfg(cfg)
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', root.withdraw)    # closing the window only hides it
    core.start_done = False
    core.start()
    core.start_done = True
    if '--show' in sys.argv:
        show_settings()
    log('started (hooks %s, main config %s)' % ('ok' if core.hook_ok else 'FAILED', cfg.get('main_config')))
    root.after(100, tick)
    if '--smoke' in sys.argv:
        root.after(2500, on_close)
    root.mainloop()
    del mutex


def leave_console():
    """Opened by hand (double-click on the .py / .pyw, or from a command prompt) Python runs inside a console
    window, which would just sit there blank because this add-on has no text output. Start again without a
    console (pythonw) and let this one close; opened by hand also means: show the settings window."""
    if os.path.basename(sys.executable).lower() != 'python.exe' or '--smoke' in sys.argv or '--no-relaunch' in sys.argv:
        return False
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.isfile(pyw):
        try:
            kernel32.FreeConsole()               # no pythonw: at least let go of the console window
        except Exception:
            pass
        return False
    import subprocess
    args = [a for a in sys.argv[1:] if a != '--show']
    if '--launch-tool' not in args:
        args.append('--show')
    subprocess.Popen([pyw, os.path.abspath(__file__)] + args + ['--no-relaunch'], cwd=APP_DIR, close_fds=True,
                     creationflags=0x00000008 | 0x00000200)      # detached, own process group
    return True


def main():
    if leave_console():
        return
    try:
        sys.setswitchinterval(0.001)
        try:                                             # like your AHK macros ("Process, Priority,, High")
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x80)
        except Exception:
            pass
        run_ui()
    except Exception:
        import traceback
        log('crash:\n' + traceback.format_exc())
        raise


if __name__ == '__main__':
    main()

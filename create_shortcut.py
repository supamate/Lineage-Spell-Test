"""Makes the shortcut 'Rogue Lineage Assist Tool + Anti-Backfire' that starts both programs with one double-click.

Run it once after putting this folder next to the Assist Tool:  py create_shortcut.py
It goes into the Assist Tool's folder and onto your Desktop (paths of THIS computer, which is why it isn't in
the download itself). Nothing else is changed.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import anti_backfire as ab   # noqa: E402  (only uses its "find the Assist Tool" helpers)

NAME = 'Rogue Lineage Assist Tool + Anti-Backfire.lnk'


def windowless_python():
    for c in (shutil.which('pyw'), os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'),
              os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Python', 'Launcher', 'pyw.exe')):
        if c and os.path.isfile(c):
            return c
    return ''


def make(lnk, target, args, workdir, icon):
    ps = ('$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:AB_LNK); $s.TargetPath = $env:AB_TARGET; '
          '$s.Arguments = $env:AB_ARGS; $s.WorkingDirectory = $env:AB_DIR; '
          'if ($env:AB_ICON) { $s.IconLocation = $env:AB_ICON }; '
          '$s.Description = "Starts the Rogue Lineage Assist Tool with Anti-Backfire running silently beside it"; '
          '$s.Save()')
    env = dict(os.environ, AB_LNK=lnk, AB_TARGET=target, AB_ARGS=args, AB_DIR=workdir, AB_ICON=icon)
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], env=env, check=True,
                   creationflags=0x08000000)


def main():
    pyw = windowless_python()
    if not pyw:
        print('Could not find pythonw / pyw. Install Python from python.org (tick "Add python.exe to PATH").')
        return 1
    cfg = ab.find_main_config('')
    exe = ab.find_tool_exe(cfg)
    if not exe:
        print('Could not find the Rogue Lineage Assist Tool exe.\n'
              'Put this AntiBackfire folder inside the folder that holds the tool\'s .exe, then run this again.')
        return 1
    tool_dir = os.path.dirname(exe)
    script = os.path.join(HERE, 'Anti-Backfire.pyw')
    args = ('-3 ' if os.path.basename(pyw).lower() == 'pyw.exe' else '') + '"%s" --launch-tool' % script
    places = [tool_dir]
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    if os.path.isdir(desktop):
        places.append(desktop)
    for d in places:
        lnk = os.path.join(d, NAME)
        make(lnk, pyw, args, tool_dir, exe + ',0')
        print('Made  ' + lnk)
    print('\nAssist Tool:  ' + exe)
    print('Its settings: ' + (cfg or "not found yet - start the Assist Tool once and set up its mana bar / hotbar"))
    print('\nDouble-click the shortcut to start both. Double-click it again while they run to open the settings.')
    return 0


if __name__ == '__main__':
    code = main()
    if os.environ.get('PROMPT') is None and sys.stdin and sys.stdin.isatty():
        input('\nPress Enter to close.')
    sys.exit(code)

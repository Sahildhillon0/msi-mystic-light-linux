"""Keeping the lights going when the panel is closed.

The board never animates on its own, so an animated effect only lasts as long
as something keeps pushing frames. ``msirgb play`` is that something: it puts
the saved lighting back and, if any zone is animated, keeps running.

It is started two ways:

* at login, so the lighting survives a reboot -- by the ``msirgb-lighting``
  systemd user unit on Linux, and by a ``Run`` registry value on Windows;
* by the panel when it closes, so an effect carries on after the window goes.

Only one writer may drive the board at a time, so the panel stops the player
when it opens, and so do the CLI commands that set colours.
"""

import os
import pathlib
import signal
import subprocess
import sys
import time

WINDOWS = sys.platform == "win32"
FROZEN = bool(getattr(sys, "frozen", False))   # a PyInstaller build

UNIT = "msirgb-lighting.service"
UNIT_PATH = pathlib.Path("~/.config/systemd/user").expanduser() / UNIT
if WINDOWS:
    _RUNTIME = pathlib.Path(os.environ.get("LOCALAPPDATA")
                            or pathlib.Path.home()) / "msi-rgb"
else:
    _RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/msirgb-{os.getuid()}"
PIDFILE = pathlib.Path(_RUNTIME) / "msirgb-play.pid"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MSI Mystic Light"
GUI_EXE = "MSI Mystic Light.exe"


# ------------------------------------------------------------ processes
def _win_image(pid):
    """Executable path of a live Windows process, or None if it is gone."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(wintypes.DWORD)]
    k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)]
    h = k32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) \
                or code.value != 259:          # STILL_ACTIVE
            return None
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return buf.value or "?"
    finally:
        k32.CloseHandle(h)


def _alive(pid):
    if WINDOWS:
        return _win_image(pid) is not None
    return pathlib.Path(f"/proc/{pid}").exists()


def _player_pid():
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return None
    # Guard against a recycled PID belonging to something else entirely.
    if WINDOWS:
        image = (_win_image(pid) or "").lower()
        return pid if image and ("msi" in image or "python" in image) \
            else None
    try:
        cmd = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return pid if b"play" in cmd and (b"msi" in cmd) else None


def write_pidfile():
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))


def remove_pidfile():
    try:
        if PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink()
    except OSError:
        pass


# ------------------------------------------------------- login restore
def _systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=8).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def _player_command():
    """argv that runs ``msirgb play`` without a console window."""
    if FROZEN:
        exe = pathlib.Path(sys.executable)
        gui = exe.with_name(GUI_EXE)
        # The panel's exe is windowed, so it plays without flashing a console.
        return [str(gui if gui.exists() else exe), "play"]
    py = pathlib.Path(sys.executable)
    if WINDOWS and py.with_name("pythonw.exe").exists():
        py = py.with_name("pythonw.exe")
    return [str(py), "-m", "msi_rgb", "play"]


def unit_installed():
    """Is lighting restored at login?"""
    if not WINDOWS:
        return UNIT_PATH.exists()
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
        return True
    except OSError:
        return False


def set_login_restore(enabled):
    """Windows: add or remove the Run value that plays the lighting at login.

    Returns True on success. On Linux this is the installer's systemd unit,
    so it is left alone here.
    """
    if not WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                cmd = subprocess.list2cmdline(_player_command())
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# ------------------------------------------------------------- player
def player_running():
    """Is a background player driving the board (unit or loose process)?"""
    if not WINDOWS and unit_installed() \
            and _systemctl("is-active", "--quiet", UNIT) == 0:
        return True
    return _player_pid() is not None


def stop_background():
    """Stop any running player so the caller can drive the board alone."""
    if not WINDOWS and unit_installed():
        _systemctl("stop", UNIT)
    pid = _player_pid()
    if pid is None or pid == os.getpid():
        return
    try:
        # TerminateProcess on Windows: the player holds nothing that needs
        # tidying, and the next writer re-sends the configuration anyway.
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(40):
        if not _alive(pid):
            break
        time.sleep(0.05)


def start_background():
    """Hand the board to a detached ``msirgb play``."""
    if not WINDOWS and unit_installed() and _systemctl("restart", UNIT) == 0:
        return "unit"
    env = dict(os.environ)
    if not FROZEN:
        pkg_parent = str(pathlib.Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = pkg_parent + os.pathsep + env.get("PYTHONPATH", "")
    kw = {}
    if WINDOWS:
        kw["creationflags"] = (subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.CREATE_NO_WINDOW)
    else:
        kw["start_new_session"] = True
    subprocess.Popen(_player_command(), env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **kw)
    return "process"

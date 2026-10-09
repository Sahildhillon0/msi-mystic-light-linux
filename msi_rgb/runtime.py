"""Keeping the lights going when the panel is closed.

The board never animates on its own, so an animated effect only lasts as long
as something keeps pushing frames. ``msirgb play`` is that something: it puts
the saved lighting back and, if any zone is animated, keeps running.

It is started two ways:

* at login, by the ``msirgb-lighting`` systemd user unit, so the lighting
  survives a reboot;
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

UNIT = "msirgb-lighting.service"
UNIT_PATH = pathlib.Path("~/.config/systemd/user").expanduser() / UNIT
_RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/msirgb-{os.getuid()}"
PIDFILE = pathlib.Path(_RUNTIME) / "msirgb-play.pid"


def unit_installed():
    return UNIT_PATH.exists()


def _systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=8).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def _player_pid():
    try:
        pid = int(PIDFILE.read_text().strip())
        cmd = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return None
    # Guard against a recycled PID belonging to something else entirely.
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


def player_running():
    """Is a background player driving the board (unit or loose process)?"""
    if unit_installed() and _systemctl("is-active", "--quiet", UNIT) == 0:
        return True
    return _player_pid() is not None


def stop_background():
    """Stop any running player so the caller can drive the board alone."""
    if unit_installed():
        _systemctl("stop", UNIT)
    pid = _player_pid()
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(20):
        if not pathlib.Path(f"/proc/{pid}").exists():
            break
        time.sleep(0.05)


def start_background():
    """Hand the board to a detached ``msirgb play``."""
    if unit_installed() and _systemctl("restart", UNIT) == 0:
        return "unit"
    pkg_parent = str(pathlib.Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = pkg_parent + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.Popen([sys.executable, "-m", "msi_rgb", "play"], env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return "process"

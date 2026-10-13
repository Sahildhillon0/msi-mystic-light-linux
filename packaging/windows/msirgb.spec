# PyInstaller spec for the Windows build. Run from an MSYS2 UCRT64 shell:
#
#   pyinstaller --noconfirm packaging/windows/msirgb.spec
#
# Produces dist/MSI Mystic Light/ with two executables sharing one runtime:
#   MSI Mystic Light.exe  the panel (windowed), also runs `play` headless
#   msirgb.exe            the CLI (console)
import os
import shutil

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
HERE = SPECPATH
ICON = os.path.join(HERE, "msirgb.ico")

# The direct backend loads hidapi through ctypes, so PyInstaller cannot see
# the dependency; ship the MSYS2 DLL explicitly.
hidapi = shutil.which("libhidapi-0.dll") or os.path.join(
    os.environ.get("MINGW_PREFIX", "C:/msys64/ucrt64"), "bin", "libhidapi-0.dll")

gi_config = {"gi": {
    "module-versions": {"Gtk": "4.0", "Gdk": "4.0"},
    "icons": ["Adwaita"],
    "themes": ["Adwaita"],
    "languages": ["en_US", "en_GB"],
}}

common = dict(pathex=[ROOT], binaries=[(hidapi, ".")], hooksconfig=gi_config,
              excludes=["tkinter", "unittest", "pydoc_data"])

gui = Analysis([os.path.join(HERE, "gui_main.py")],
               hiddenimports=["msi_rgb.direct"], **common)
cli = Analysis([os.path.join(HERE, "cli_main.py")],
               hiddenimports=["msi_rgb.direct"], **common)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True,
              name="MSI Mystic Light", console=False, icon=ICON,
              version=os.path.join(HERE, "version.txt"))
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True,
              name="msirgb", console=True, icon=ICON,
              version=os.path.join(HERE, "version.txt"))

COLLECT(gui_exe, gui.binaries, gui.datas,
        cli_exe, cli.binaries, cli.datas,
        name="MSI Mystic Light")

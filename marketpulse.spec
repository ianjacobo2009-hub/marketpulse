# PyInstaller spec: builds Market Pulse.app (macOS) or Market Pulse.exe (Windows)
import sys
from PyInstaller.utils.hooks import collect_submodules
a = Analysis(["run_marketpulse.py"], pathex=["."], datas=[("assets", "assets")],
             hiddenimports=collect_submodules("yfinance") + ["keyring.backends"],
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "scipy"])
pyz = PYZ(a.pure)
icon = "assets/icon.icns" if sys.platform == "darwin" else None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Market Pulse", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="Market Pulse")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Market Pulse.app", icon=icon, bundle_identifier="com.bluepeak.marketpulse",
                 info_plist={"CFBundleShortVersionString": "1.0.0", "NSHighResolutionCapable": True})

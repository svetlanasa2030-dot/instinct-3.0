from PyInstaller.utils.hooks import collect_submodules

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (\
    collect_submodules("app")\
    + collect_submodules("aiogram")\
    + collect_submodules("apscheduler")\
)

a = Analysis(
    ["app/gui.py"],
    pathex=["."],
    binaries=[],
    datas=[("config", "config"), ("knowledge", "knowledge")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="instinct-bot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

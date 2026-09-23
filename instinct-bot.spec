from PyInstaller.utils.hooks import collect_submodules

# app.main загружается из GUI динамически, поэтому PyInstaller не видит
# его зависимости обычным статическим анализом. Явно включаем весь пакет app.
hiddenimports = (
    collect_submodules("app")
    + [
        "app.main",
        "app.storage",
        "app.ai",
        "app.config",
        "app.reminders",
        "app.knowledge",
        "app.knowledge_ui",
        "app.source_sync",
        "app.game_features",
        "app.forum_search",
        "app.youtube_monitor",
        "app.web_search",
    ]
    + collect_submodules("aiogram")
    + collect_submodules("apscheduler")
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

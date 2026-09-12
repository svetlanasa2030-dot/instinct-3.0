from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('aiogram') + collect_submodules('apscheduler')

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('config', 'config'), ('knowledge', 'knowledge')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='instinct-bot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

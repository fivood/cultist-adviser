# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('cultist_adviser/achievement_guide.txt', 'cultist_adviser'),
           ('cultist_adviser/achievement_guide_en.txt', 'cultist_adviser'),
           ('cultist_adviser/lexicon_cache_bundled.json', 'cultist_adviser'),
           ('cultist_adviser/knowledge_cache_bundled.json', 'cultist_adviser')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CultistAdviser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

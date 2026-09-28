# Build on each target OS; PyInstaller includes Python and native libraries.
import sys

a = Analysis(
    ['desktop_launcher.py'],
    pathex=[], binaries=[], datas=[('web', 'web'), ('build/notices', 'notices'), ('LICENSE', '.'), ('docs/QUICKSTART.txt', '.')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'playwright'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='FreeP2P',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None, icon='assets/icon.ico' if sys.platform == 'win32' else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FreeP2P')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='FreeP2P.app', icon='assets/icon.icns', bundle_identifier='io.freep2p.minecraft',
                 info_plist={'CFBundleShortVersionString': '0.1.0',
                             'NSHighResolutionCapable': True,
                             'LSUIElement': True})

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for FibreLab Version 11.0 — onedir build
# Adapted from FibreLab Version 10.0\FibreLab10.spec: same collected
# packages / hidden imports / exclusions, just pointed at the v11.0 source
# files and renamed.

import os, re
from PyInstaller.utils.hooks import collect_all

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

# ── Collect non-PySide6 packages ───────────────────────────────────────────────
datas         = []
binaries      = []
hiddenimports = []

for pkg in ('matplotlib', 'pymeasure', 'pyvisa', 'scipy', 'pandas', 'numpy', 'openpyxl'):
    d, b, h = collect_all(pkg)
    datas         += d
    binaries      += b
    hiddenimports += h

# PySide6 — collect only what we use; skip QML/QtQuick (path-length killers)
_pyside6_d, _pyside6_b, _pyside6_h = collect_all('PySide6')

# Filter out QML/QtQuick assets — they add >200 MB and create paths >260 chars
_qml_pat = re.compile(r'[/\\]qml[/\\]', re.IGNORECASE)
datas    += [(s, d) for s, d in _pyside6_d if not _qml_pat.search(s)]
binaries += _pyside6_b
hiddenimports += _pyside6_h

# Core script travels as a plain source file (loaded via importlib at runtime)
# FiberLab.ico also travels as a data file -- the app looks for it at
# sys._MEIPASS/FiberLab.ico at runtime to set the window's title-bar icon.
# The icon= on EXE() below only embeds it into the exe's own file/taskbar
# icon; it does NOT make the raw .ico available inside the bundle for the
# app's own setWindowIcon() call, hence needing it listed here too.
datas += [
    (os.path.join(SPEC_DIR, 'core_script_version 11.0.py'), '.'),
    (os.path.join(SPEC_DIR, 'FiberLab.ico'), '.'),
]

# ── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports += [
    'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
    'PySide6.QtPrintSupport',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_pdf',
    'matplotlib.backends.backend_svg',
    'matplotlib.backends.backend_agg',
    'scipy.optimize', 'scipy.signal', 'scipy.special',
    'scipy.linalg', 'scipy.sparse', 'scipy.stats',
    'pandas', 'pandas.io.formats.excel',
    'numpy', 'numpy.core._multiarray_umath',
    'pyvisa', 'pyvisa.resources', 'pyvisa.adapters',
    'pyvisa.resources.serial', 'pyvisa.resources.gpib',
    'pyvisa.resources.tcpip', 'pyvisa.resources.usb',
    'pymeasure', 'pymeasure.instruments',
    'pymeasure.instruments.signalrecovery',
    'openpyxl',
    'ast', 'types', 'threading', 'json', 'math', 'csv',
    'importlib', 'importlib.util',
]

a = Analysis(
    [os.path.join(SPEC_DIR, 'Thermal conductivity measurement_version 11.0.py')],
    pathex=[SPEC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'PyQt5', 'PyQt6', 'wx', 'gi', 'IPython',
              'jupyter', 'notebook',
              'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtWebEngine',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore',
              'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtCharts',
              'PySide6.QtDataVisualization', 'PySide6.QtMultimedia',
              'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSensors',
              'PySide6.QtLocation', 'PySide6.QtPositioning'],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ── onedir build — exe + loose support files in a folder, no self-extraction
#    on every launch ──────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FibreLab 11.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPEC_DIR, 'FiberLab.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FibreLab 11.0',
)

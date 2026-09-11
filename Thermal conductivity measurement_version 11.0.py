# interface_code.py
"""Interface wrapper for 12042026_modified.py.

This file provides a dedicated interface layer and imports the measurement
functions from 12042026_modified.py without modifying that file.
"""

import ast
import os
import re
import sys
import threading
import types
import numpy as npyaya
import pyvisa
import formula_engine as fe   # MathFunctions: calculator + spreadsheet formula engine
os.environ["QT_API"] = "pyside6"
import matplotlib
matplotlib.use("QtAgg", force=True)
import matplotlib.pyplot as plt
# Apply dark theme + compact font sizes globally so every figure
# created by the core script inherits these settings automatically.
matplotlib.rcParams.update({
    'font.size':                        7,
    'axes.titlesize':                   8,
    'axes.labelsize':                   8,
    'xtick.labelsize':                  7,
    'ytick.labelsize':                  7,
    'figure.titlesize':                 11,
    'figure.facecolor':                 '#1e1e2f',
    'axes.facecolor':                   '#2b2b3d',
    'axes.edgecolor':                   '#555577',
    'text.color':                       'white',
    'axes.labelcolor':                  'white',
    'xtick.color':                      'white',
    'ytick.color':                      'white',
    'legend.facecolor':                 '#2b2b3d',
    'legend.edgecolor':                 '#555577',
    'legend.fontsize':                  7,
    'figure.subplot.hspace':            0.40,
    'figure.subplot.left':              0.16,
    'figure.subplot.bottom':            0.13,
    'figure.subplot.top':               0.88,
    'figure.subplot.right':             0.97,
    # Disable automatic layout engines so subplots_adjust is never overridden at draw time
    'figure.autolayout':                False,
    'figure.constrained_layout.use':    False,
})
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QGridLayout,
    QFrame,
    QFileDialog,
    QComboBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTableWidgetSelectionRange,
    QAbstractItemView,
    QHeaderView,
    QButtonGroup,
    QGroupBox,
    QCompleter,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QEvent
from PySide6.QtGui import QIcon, QColor, QKeySequence

def _get_settings_file():
    """
    When frozen (installed exe): store settings in %APPDATA%\FibreLab\
    so they persist across updates and work even when installed to
    Program Files (which is read-only for normal users).
    When running from source: store next to the script as before.
    """
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
        folder = os.path.join(appdata, 'FibreLab')
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, 'ui_settings.json')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui_settings.json')

SETTINGS_FILE = _get_settings_file()

# In-memory cache + debounced disk flush. Many UI controls (each of the 7265
# dialog's ~11 apply buttons, various checkboxes/dropdowns across the app)
# call save_settings() on every single change — writing the whole JSON file
# to disk synchronously on every call caused visible stutter when several
# fired in a row (e.g. one click of "Update All" triggered ~22 read+write
# cycles). Now writes coalesce into a single disk flush shortly after the
# last change in a burst; _flush_settings_now() is also called on app exit
# so a pending change is never lost.
_settings_cache = None
_settings_dirty = False
_settings_flush_timer = None

def load_settings():
    global _settings_cache
    if _settings_cache is None:
        import json
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    _settings_cache = json.load(f)
            except Exception:
                _settings_cache = {}
        else:
            _settings_cache = {}
    return dict(_settings_cache)  # copy — callers must not mutate the cache directly

def save_settings(s):
    global _settings_cache, _settings_dirty, _settings_flush_timer
    _settings_cache = dict(s)
    _settings_dirty = True
    if _settings_flush_timer is None:
        _settings_flush_timer = QTimer()
        _settings_flush_timer.setSingleShot(True)
        _settings_flush_timer.timeout.connect(_flush_settings_now)
    _settings_flush_timer.start(400)

def _flush_settings_now():
    global _settings_dirty
    if not _settings_dirty:
        return
    import json
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(_settings_cache, f, indent=2)
        _settings_dirty = False
    except Exception as _e:
        print(f"WARNING: Could not save settings to {SETTINGS_FILE}: {_e}", flush=True)


CORE_FILENAME = "core_script_version 11.0.py"
if getattr(sys, 'frozen', False):
    _BASE_DIR = sys._MEIPASS
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_PATH = os.path.join(_BASE_DIR, CORE_FILENAME)


class DummyInstrument:
    def write(self, *args, **kwargs):
        pass

    def query(self, *args, **kwargs):
        return "0,0,0,0"

    def close(self):
        pass


class DummyResourceManager:
    def open_resource(self, *args, **kwargs):
        return DummyInstrument()


def _lockin_human_readable(core):
    icpl = getattr(core, 'LOCKIN_ICPL', 1)
    rmod = getattr(core, 'LOCKIN_RMOD', 0)
    oflt = getattr(core, 'LOCKIN_OFLT', 8)
    ofsl = getattr(core, 'LOCKIN_OFSL', 2)
    ilin = getattr(core, 'LOCKIN_ILIN', 0)
    sync = getattr(core, 'LOCKIN_SYNC', 0)
    sens = getattr(core, 'LOCKIN_SENS', 16)
    ignd = getattr(core, 'LOCKIN_IGND', 0)
    isrc = getattr(core, 'LOCKIN_ISRC', 0)

    bi, mi, ui = LockinParamsDialog._OFLT_IDX_TO_COMBO.get(oflt, (0, 2, 2))
    tc_str = f"{LockinParamsDialog._TC_BASES[bi] * LockinParamsDialog._TC_MULTS[mi]} {LockinParamsDialog._TC_UNITS[ui]}"

    bi, mi, ui = LockinParamsDialog._SENS_IDX_TO_COMBO.get(sens, (2, 2, 2))
    sens_str = f"{LockinParamsDialog._SENS_BASES[bi] * LockinParamsDialog._SENS_MULTS[mi]} {LockinParamsDialog._SENS_UNITS[ui]}"

    return [
        f"  {'Coupling':<28}:  {'DC' if icpl == 1 else 'AC'}",
        f"  {'Dynamic Reserve':<28}:  {['High Reserve', 'Normal', 'Low Noise'][rmod]}",
        f"  {'Time Constant':<28}:  {tc_str}",
        f"  {'Filter Slope':<28}:  {['6 dB/oct', '12 dB/oct', '18 dB/oct', '24 dB/oct'][ofsl]}",
        f"  {'Line Filters':<28}:  {['No line filters', 'Line notch (50/60 Hz)', '2x line notch (100/120 Hz)', 'Both notch filters'][ilin]}",
        f"  {'Sync Filter':<28}:  {'ON (<200 Hz)' if sync == 1 else 'OFF (>200 Hz)'}",
        f"  {'Sensitivity':<28}:  {sens_str}",
        f"  {'Input Grounding':<28}:  {'Ground' if ignd == 1 else 'Float'}",
        f"  {'Input Type':<28}:  {'A-B differential' if isrc == 1 else 'A only'}",
    ]


def _write_params_file(params_path, title, sections):
    import datetime
    sep = "=" * 60
    lines = [
        sep,
        f"  {title}",
        f"  Date/Time : {datetime.datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}",
        sep,
    ]
    for section_name, entries in sections:
        lines.append("")
        lines.append(f"--- {section_name} ---")
        lines.extend(entries)
    lines.append("")
    lines.append(sep)
    with open(params_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _silent_backup(backup_folder, base_name, data, columns, completed, title, sections, suffix=None):
    """Silent auto-save to Backup_data folder. No popups — prints to console only.

    One file pair (`<base_name><suffix>.csv` + `_params.txt`) per measurement
    run, full stop. The number in `suffix` is picked once when a run starts
    (pass suffix=None the first time) and then reused for every subsequent
    call during that same run — periodic crash-safety snapshot, stop, or
    final completion all overwrite that same pair in place. Only the STATUS
    line inside the params file changes; no separate "_live" or "_completed"
    file is ever created.

    Returns (csv_path, suffix_used) — callers should hold onto suffix_used
    and pass it back in on the next call for the same run.
    """
    import re
    try:
        os.makedirs(backup_folder, exist_ok=True)
        if suffix is None:
            existing = os.listdir(backup_folder)
            indices = []
            pat = re.compile(rf'^{re.escape(base_name)}_(\d+)')
            for f in existing:
                m = pat.match(f)
                if m:
                    indices.append(int(m.group(1)))
            n = max(indices, default=0) + 1
            suffix = f'_{n}'
        csv_path    = os.path.join(backup_folder, base_name + suffix + '.csv')
        params_path = os.path.join(backup_folder, base_name + suffix + '_params.txt')
        import pandas as pd
        pd.DataFrame(data, columns=columns).to_csv(csv_path, index=False)
        _write_params_file(params_path, title, sections)
        return csv_path, suffix
    except Exception as e:
        print(f"Backup save failed: {e}")
        return None, suffix


def _backup_base_name(name_entry_text):
    """Return a clean base name: strip .csv/.txt extension only, or use today's date if empty."""
    import datetime
    raw = name_entry_text.strip()
    if raw:
        if raw.lower().endswith('.csv') or raw.lower().endswith('.txt'):
            return raw.rsplit('.', 1)[0]
        return raw
    return datetime.date.today().strftime('%Y%m%d') + '_measurement'


def _make_conversion_link_card():
    """Build the small 'fancy' card widget that visually represents the live
    bidirectional AC Current <-> AC Voltage relationship (I = V x k). Purely
    cosmetic chrome — callers own an inner rich-text QLabel they must keep
    up to date themselves; this function has no knowledge of the actual
    conversion logic. Shared between the main window's AC Current row and
    the IV dialog's Current sweep row so both look identical.

    Returns (frame, text_label).
    """
    frame = QFrame()
    frame.setObjectName("convLinkCard")
    frame.setStyleSheet("""
        QFrame#convLinkCard {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(0,198,167,55), stop:0.5 rgba(0,150,220,55),
                stop:1 rgba(0,119,255,55));
            border: 1px solid #00d4b0;
            border-radius: 8px;
        }
    """)
    row = QHBoxLayout(frame)
    row.setContentsMargins(9, 5, 9, 5)
    row.setSpacing(8)

    arrow = QLabel("⇌")
    arrow.setStyleSheet(
        "color:#00ffd5; font-size:20px; font-weight:bold;"
        " border:none; background:transparent;")
    row.addWidget(arrow)

    text = QLabel()
    text.setTextFormat(Qt.RichText)
    text.setStyleSheet(
        "color:#eafffa; font-size:9px; border:none; background:transparent;")
    row.addWidget(text)
    row.addStretch(1)

    glow = QGraphicsDropShadowEffect(frame)
    glow.setBlurRadius(18)
    glow.setOffset(0, 0)
    glow.setColor(QColor(0, 214, 181, 170))
    frame.setGraphicsEffect(glow)

    return frame, text


def load_core_module():
    """Load core_script.py without executing the bottom measurement block."""
    with open(CORE_PATH, "r", encoding="utf-8") as fh:
        source = fh.read()

    parsed = ast.parse(source, filename=CORE_PATH)
    safe_nodes = []

    for node in parsed.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            safe_nodes.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            safe_nodes.append(node)

    safe_module = ast.Module(body=safe_nodes, type_ignores=[])
    compiled = compile(safe_module, CORE_PATH, "exec")

    core = types.ModuleType("core")
    core.__file__ = CORE_PATH

    real_rmgr = pyvisa.ResourceManager
    real_show = plt.show
    plt.show = lambda *args, **kwargs: None
    pyvisa.ResourceManager = DummyResourceManager
    try:
        exec(compiled, core.__dict__)
    finally:
        pyvisa.ResourceManager = real_rmgr
        plt.show = real_show

    sys.modules["core"] = core
    return core


class FitDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fit range")
        self.setModal(True)

        self.min_entry = QLineEdit("10")
        self.max_entry = QLineEdit("30")

        form = QFormLayout(self)
        form.addRow("Fit min frequency (Hz):", self.min_entry)
        form.addRow("Fit max frequency (Hz):", self.max_entry)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addWidget(buttons)

    def get_range(self):
        return float(self.min_entry.text().strip()), float(self.max_entry.text().strip())




class LockinParamsDialog(QDialog):
    # OFLT lookup: value in µs → OFLT index
    _OFLT_US_TO_IDX = {
        10: 0, 30: 1, 100: 2, 300: 3,
        1_000: 4, 3_000: 5, 10_000: 6, 30_000: 7,
        100_000: 8, 300_000: 9, 1_000_000: 10, 3_000_000: 11,
        10_000_000: 12, 30_000_000: 13, 100_000_000: 14, 300_000_000: 15,
        1_000_000_000: 16, 3_000_000_000: 17, 10_000_000_000: 18, 30_000_000_000: 19,
    }
    # Reverse: OFLT index → (base_idx, mult_idx, unit_idx)
    # units order: ks(0), s(1), ms(2), µs(3)
    _OFLT_IDX_TO_COMBO = {
        0:  (0, 1, 3), 1:  (1, 1, 3), 2:  (0, 2, 3), 3:  (1, 2, 3),
        4:  (0, 0, 2), 5:  (1, 0, 2), 6:  (0, 1, 2), 7:  (1, 1, 2),
        8:  (0, 2, 2), 9:  (1, 2, 2), 10: (0, 0, 1), 11: (1, 0, 1),
        12: (0, 1, 1), 13: (1, 1, 1), 14: (0, 2, 1), 15: (1, 2, 1),
        16: (0, 0, 0), 17: (1, 0, 0), 18: (0, 1, 0), 19: (1, 1, 0),
    }
    _TC_BASES   = [1, 3]
    _TC_MULTS   = [1, 10, 100]
    _TC_UNITS   = ['ks', 's', 'ms', '\u00b5s']
    _TC_UNIT_US = [1_000_000_000, 1_000_000, 1_000, 1]

    # SENS lookup: value in nV → SENS index
    _SENS_NV_TO_IDX = {
        2: 0, 5: 1, 10: 2, 20: 3, 50: 4, 100: 5, 200: 6, 500: 7,
        1_000: 8, 2_000: 9, 5_000: 10, 10_000: 11, 20_000: 12, 50_000: 13,
        100_000: 14, 200_000: 15, 500_000: 16,
        1_000_000: 17, 2_000_000: 18, 5_000_000: 19, 10_000_000: 20,
        20_000_000: 21, 50_000_000: 22, 100_000_000: 23, 200_000_000: 24,
        500_000_000: 25, 1_000_000_000: 26,
    }
    # Reverse: SENS index → (base_idx, mult_idx, unit_idx)
    # units order: V/µA(0), mV/nA(1), µV/pA(2), nV/fA(3)
    _SENS_IDX_TO_COMBO = {
        0: (1,0,3), 1: (2,0,3), 2: (0,1,3), 3: (1,1,3), 4: (2,1,3),
        5: (0,2,3), 6: (1,2,3), 7: (2,2,3),
        8: (0,0,2), 9: (1,0,2), 10:(2,0,2), 11:(0,1,2), 12:(1,1,2),
        13:(2,1,2), 14:(0,2,2), 15:(1,2,2), 16:(2,2,2),
        17:(0,0,1), 18:(1,0,1), 19:(2,0,1), 20:(0,1,1), 21:(1,1,1),
        22:(2,1,1), 23:(0,2,1), 24:(1,2,1), 25:(2,2,1),
        26:(0,0,0),
    }
    _SENS_BASES   = [1, 2, 5]
    _SENS_MULTS   = [1, 10, 100]
    _SENS_UNITS   = ['V/\u00b5A', 'mV/nA', '\u00b5V/pA', 'nV/fA']
    _SENS_UNIT_NV = [1_000_000_000, 1_000_000, 1_000, 1]

    def __init__(self, parent, core):
        super().__init__(parent)
        self.setWindowTitle("Lock-in Parameters")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.core = core

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # --- Coupling ---
        self.coupling_box = QComboBox()
        self.coupling_box.addItems(["DC (ICPL 1)", "AC (ICPL 0)"])
        current_icpl = getattr(core, 'LOCKIN_ICPL', 1)
        self.coupling_box.setCurrentIndex(0 if current_icpl == 1 else 1)
        _coupling_row = QWidget(); _coupling_lay = QHBoxLayout(_coupling_row)
        _coupling_lay.setContentsMargins(0,0,0,0); _coupling_lay.setSpacing(4)
        _coupling_lay.addWidget(self.coupling_box)
        _btn_coupling = QPushButton("✓"); _btn_coupling.setFixedWidth(30)
        _btn_coupling.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_coupling.clicked.connect(self._apply_coupling)
        _coupling_lay.addWidget(_btn_coupling)
        form.addRow(QLabel("Coupling:"), _coupling_row)

        # --- Dynamic Reserve ---
        self.rmod_box = QComboBox()
        self.rmod_box.addItems(["High Reserve (RMOD 0)", "Normal (RMOD 1)", "Low Noise (RMOD 2)"])
        current_rmod = getattr(core, 'LOCKIN_RMOD', 0)
        self.rmod_box.setCurrentIndex(current_rmod)
        _rmod_row = QWidget(); _rmod_lay = QHBoxLayout(_rmod_row)
        _rmod_lay.setContentsMargins(0,0,0,0); _rmod_lay.setSpacing(4)
        _rmod_lay.addWidget(self.rmod_box)
        _btn_rmod = QPushButton("✓"); _btn_rmod.setFixedWidth(30)
        _btn_rmod.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_rmod.clicked.connect(self._apply_rmod)
        _rmod_lay.addWidget(_btn_rmod)
        form.addRow(QLabel("Dynamic Reserve:"), _rmod_row)

        # --- Time Constant ---
        current_oflt = getattr(core, 'LOCKIN_OFLT', 8)
        bi, mi, ui = self._OFLT_IDX_TO_COMBO.get(current_oflt, (0, 2, 2))  # default 100 ms

        tc_row = QWidget()
        tc_lay = QHBoxLayout(tc_row)
        tc_lay.setContentsMargins(0, 0, 0, 0)
        tc_lay.setSpacing(4)

        self.tc_base_box = QComboBox()
        self.tc_base_box.addItems(["1", "3"])
        self.tc_base_box.setCurrentIndex(bi)
        tc_lay.addWidget(self.tc_base_box)

        self.tc_mult_box = QComboBox()
        self.tc_mult_box.addItems(["x1", "x10", "x100"])
        self.tc_mult_box.setCurrentIndex(mi)
        tc_lay.addWidget(self.tc_mult_box)

        self.tc_unit_box = QComboBox()
        self.tc_unit_box.addItems(["ks", "s", "ms", "\u00b5s"])
        self.tc_unit_box.setCurrentIndex(ui)
        tc_lay.addWidget(self.tc_unit_box)
        _btn_tc = QPushButton("✓"); _btn_tc.setFixedWidth(30)
        _btn_tc.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_tc.clicked.connect(self._apply_tc)
        tc_lay.addWidget(_btn_tc)

        form.addRow(QLabel("Time Constant:"), tc_row)

        # --- Slope ---
        self.ofsl_box = QComboBox()
        self.ofsl_box.addItems(["6 dB/oct (OFSL 0)", "12 dB/oct (OFSL 1)", "18 dB/oct (OFSL 2)", "24 dB/oct (OFSL 3)"])
        current_ofsl = getattr(core, 'LOCKIN_OFSL', 2)
        self.ofsl_box.setCurrentIndex(current_ofsl)
        _ofsl_row = QWidget(); _ofsl_lay = QHBoxLayout(_ofsl_row)
        _ofsl_lay.setContentsMargins(0,0,0,0); _ofsl_lay.setSpacing(4)
        _ofsl_lay.addWidget(self.ofsl_box)
        _btn_ofsl = QPushButton("✓"); _btn_ofsl.setFixedWidth(30)
        _btn_ofsl.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_ofsl.clicked.connect(self._apply_ofsl)
        _ofsl_lay.addWidget(_btn_ofsl)
        form.addRow(QLabel("Slope:"), _ofsl_row)

        # --- Filters ---
        self.ilin_box = QComboBox()
        self.ilin_box.addItems([
            "No line filters (ILIN 0)",
            "Line notch ON – 50/60 Hz (ILIN 1)",
            "2\u00d7 line notch ON – 100/120 Hz (ILIN 2)",
            "Both notch filters ON (ILIN 3)",
        ])
        current_ilin = getattr(core, 'LOCKIN_ILIN', 0)
        self.ilin_box.setCurrentIndex(current_ilin)
        _ilin_row = QWidget(); _ilin_lay = QHBoxLayout(_ilin_row)
        _ilin_lay.setContentsMargins(0,0,0,0); _ilin_lay.setSpacing(4)
        _ilin_lay.addWidget(self.ilin_box)
        _btn_ilin = QPushButton("✓"); _btn_ilin.setFixedWidth(30)
        _btn_ilin.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_ilin.clicked.connect(self._apply_ilin)
        _ilin_lay.addWidget(_btn_ilin)
        form.addRow(QLabel("Filters:"), _ilin_row)

        # --- Synchronous Filter ---
        self.sync_box = QComboBox()
        self.sync_box.addItems([
            "OFF – use >200 Hz (SYNC 0)",
            "ON – use <200 Hz (SYNC 1)",
        ])
        current_sync = getattr(core, 'LOCKIN_SYNC', 0)
        self.sync_box.setCurrentIndex(current_sync)
        _sync_row = QWidget(); _sync_lay = QHBoxLayout(_sync_row)
        _sync_lay.setContentsMargins(0,0,0,0); _sync_lay.setSpacing(4)
        _sync_lay.addWidget(self.sync_box)
        _btn_sync = QPushButton("✓"); _btn_sync.setFixedWidth(30)
        _btn_sync.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_sync.clicked.connect(self._apply_sync)
        _sync_lay.addWidget(_btn_sync)
        form.addRow(QLabel("Sync Filter:"), _sync_row)

        # --- Sensitivity ---
        current_sens = getattr(core, 'LOCKIN_SENS', 16)
        sbi, smi, sui = self._SENS_IDX_TO_COMBO.get(current_sens, (2, 2, 2))

        sens_row = QWidget()
        sens_lay = QHBoxLayout(sens_row)
        sens_lay.setContentsMargins(0, 0, 0, 0)
        sens_lay.setSpacing(4)

        self.sens_base_box = QComboBox()
        self.sens_base_box.addItems(['1', '2', '5'])
        self.sens_base_box.setCurrentIndex(sbi)
        sens_lay.addWidget(self.sens_base_box)

        self.sens_mult_box = QComboBox()
        self.sens_mult_box.addItems(['x1', 'x10', 'x100'])
        self.sens_mult_box.setCurrentIndex(smi)
        sens_lay.addWidget(self.sens_mult_box)

        self.sens_unit_box = QComboBox()
        self.sens_unit_box.addItems(['V/\u00b5A', 'mV/nA', '\u00b5V/pA', 'nV/fA'])
        self.sens_unit_box.setCurrentIndex(sui)
        sens_lay.addWidget(self.sens_unit_box)
        _btn_sens = QPushButton("✓"); _btn_sens.setFixedWidth(30)
        _btn_sens.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_sens.clicked.connect(self._apply_sens)
        sens_lay.addWidget(_btn_sens)

        form.addRow(QLabel('Sensitivity:'), sens_row)

        # --- Input Grounding ---
        self.ignd_box = QComboBox()
        self.ignd_box.addItems(['Float (IGND 0)', 'Ground (IGND 1)'])
        current_ignd = getattr(core, 'LOCKIN_IGND', 0)
        self.ignd_box.setCurrentIndex(current_ignd)
        _ignd_row = QWidget(); _ignd_lay = QHBoxLayout(_ignd_row)
        _ignd_lay.setContentsMargins(0,0,0,0); _ignd_lay.setSpacing(4)
        _ignd_lay.addWidget(self.ignd_box)
        _btn_ignd = QPushButton("✓"); _btn_ignd.setFixedWidth(30)
        _btn_ignd.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_ignd.clicked.connect(self._apply_ignd)
        _ignd_lay.addWidget(_btn_ignd)
        form.addRow(QLabel('Input Grounding:'), _ignd_row)

        # --- Input Type (ISRC) ---
        self.isrc_box = QComboBox()
        self.isrc_box.addItems(['A only (ISRC 0)', 'A-B differential (ISRC 1)'])
        current_isrc = getattr(core, 'LOCKIN_ISRC', 0)
        self.isrc_box.setCurrentIndex(current_isrc)
        _isrc_row = QWidget(); _isrc_lay = QHBoxLayout(_isrc_row)
        _isrc_lay.setContentsMargins(0,0,0,0); _isrc_lay.setSpacing(4)
        _isrc_lay.addWidget(self.isrc_box)
        _btn_isrc = QPushButton("✓"); _btn_isrc.setFixedWidth(30)
        _btn_isrc.setStyleSheet("background:#28a745; color:white; border-radius:4px; font-weight:bold;")
        _btn_isrc.clicked.connect(self._apply_isrc)
        _isrc_lay.addWidget(_btn_isrc)
        form.addRow(QLabel('Input Type:'), _isrc_row)

        layout.addLayout(form)
        layout.addStretch(1)

        # Status label
        self._status = QLabel()
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#3be362; font-weight:bold;")
        current_isrc = getattr(core, 'LOCKIN_ISRC', 0)
        self._update_status_label(current_icpl, current_rmod, current_oflt, current_ofsl, current_ilin, current_sync, current_sens, current_ignd, current_isrc)
        layout.addWidget(self._status)

        self._load_sr830_settings()

        apply_btn = QPushButton("Apply All")
        apply_btn.setStyleSheet("background:#3a86ff; color:white; padding:6px; border-radius:5px;")
        apply_btn.clicked.connect(self._apply)
        layout.addWidget(apply_btn)

    def _refresh_status(self):
        self._update_status_label(
            getattr(self.core, 'LOCKIN_ICPL', 1),
            getattr(self.core, 'LOCKIN_RMOD', 0),
            getattr(self.core, 'LOCKIN_OFLT', 8),
            getattr(self.core, 'LOCKIN_OFSL', 2),
            getattr(self.core, 'LOCKIN_ILIN', 0),
            getattr(self.core, 'LOCKIN_SYNC', 0),
            getattr(self.core, 'LOCKIN_SENS', 16),
            getattr(self.core, 'LOCKIN_IGND', 0),
            getattr(self.core, 'LOCKIN_ISRC', 0),
        )

    def _lockin_write(self, cmd):
        lockin = getattr(self.core, 'lockin', None)
        if lockin is not None:
            lockin.write(cmd)

    def _apply_coupling(self):
        icpl = 1 if self.coupling_box.currentIndex() == 0 else 0
        self.core.LOCKIN_ICPL = icpl
        self._save_sr830_settings()
        self._lockin_write(f"ICPL {icpl}")
        self._refresh_status()

    def _apply_rmod(self):
        rmod = self.rmod_box.currentIndex()
        self.core.LOCKIN_RMOD = rmod
        self._save_sr830_settings()
        self._lockin_write(f"RMOD {rmod}")
        self._refresh_status()

    def _apply_tc(self):
        base     = self._TC_BASES[self.tc_base_box.currentIndex()]
        mult     = self._TC_MULTS[self.tc_mult_box.currentIndex()]
        unit_us  = self._TC_UNIT_US[self.tc_unit_box.currentIndex()]
        unit_str = self._TC_UNITS[self.tc_unit_box.currentIndex()]
        value_us = base * mult * unit_us
        oflt = self._OFLT_US_TO_IDX.get(value_us)
        if oflt is None:
            QMessageBox.warning(
                self, "Invalid Time Constant",
                f"{base * mult} {unit_str} is not a valid SR830 time constant.\n"
                "Please choose a different combination."
            )
            return
        self.core.LOCKIN_OFLT = oflt
        self.core.LOCKIN_OFLT_MANUAL = oflt
        self._lockin_write(f"OFLT {oflt}")
        self._refresh_status()
        self._save_sr830_settings()

    def _apply_ofsl(self):
        ofsl = self.ofsl_box.currentIndex()
        self.core.LOCKIN_OFSL = ofsl
        self._lockin_write(f"OFSL {ofsl}")
        self._refresh_status()
        self._save_sr830_settings()

    def _apply_ilin(self):
        ilin = self.ilin_box.currentIndex()
        self.core.LOCKIN_ILIN = ilin
        self._lockin_write(f"ILIN {ilin}")
        self._refresh_status()
        self._save_sr830_settings()

    def _apply_sync(self):
        sync = self.sync_box.currentIndex()
        self.core.LOCKIN_SYNC = sync
        self._lockin_write(f"SYNC {sync}")
        self._refresh_status()
        self._save_sr830_settings()

    def _apply_sens(self):
        sbase     = self._SENS_BASES[self.sens_base_box.currentIndex()]
        smult     = self._SENS_MULTS[self.sens_mult_box.currentIndex()]
        sunit_nv  = self._SENS_UNIT_NV[self.sens_unit_box.currentIndex()]
        sunit_str = self._SENS_UNITS[self.sens_unit_box.currentIndex()]
        value_nv  = sbase * smult * sunit_nv
        sens = self._SENS_NV_TO_IDX.get(value_nv)
        if sens is None:
            QMessageBox.warning(
                self, "Invalid Sensitivity",
                f"{sbase * smult} {sunit_str} is not a valid SR830 sensitivity.\n"
                "Please choose a different combination."
            )
            return
        self.core.LOCKIN_SENS = sens
        self.core.LOCKIN_SENS_MANUAL = sens
        self._lockin_write(f"SENS {sens}")
        self._refresh_status()
        self._save_sr830_settings()

    def _apply_ignd(self):
        ignd = self.ignd_box.currentIndex()
        self.core.LOCKIN_IGND = ignd
        self._lockin_write(f"IGND {ignd}")
        self._refresh_status()
        self._save_sr830_settings()

    def _apply_isrc(self):
        isrc = self.isrc_box.currentIndex()
        self.core.LOCKIN_ISRC = isrc
        self._lockin_write(f"ISRC {isrc}")
        self._refresh_status()
        self._save_sr830_settings()

    def _load_sr830_settings(self):
        try:
            s = load_settings()
            if 'sr830_icpl'      in s: self.coupling_box.setCurrentIndex(s['sr830_icpl'])
            if 'sr830_rmod'      in s: self.rmod_box.setCurrentIndex(s['sr830_rmod'])
            if 'sr830_tc_base'   in s: self.tc_base_box.setCurrentIndex(s['sr830_tc_base'])
            if 'sr830_tc_mult'   in s: self.tc_mult_box.setCurrentIndex(s['sr830_tc_mult'])
            if 'sr830_tc_unit'   in s: self.tc_unit_box.setCurrentIndex(s['sr830_tc_unit'])
            if 'sr830_ofsl'      in s: self.ofsl_box.setCurrentIndex(s['sr830_ofsl'])
            if 'sr830_ilin'      in s: self.ilin_box.setCurrentIndex(s['sr830_ilin'])
            if 'sr830_sync'      in s: self.sync_box.setCurrentIndex(s['sr830_sync'])
            if 'sr830_sens_base' in s: self.sens_base_box.setCurrentIndex(s['sr830_sens_base'])
            if 'sr830_sens_mult' in s: self.sens_mult_box.setCurrentIndex(s['sr830_sens_mult'])
            if 'sr830_sens_unit' in s: self.sens_unit_box.setCurrentIndex(s['sr830_sens_unit'])
            if 'sr830_ignd'      in s: self.ignd_box.setCurrentIndex(s['sr830_ignd'])
            if 'sr830_isrc'      in s: self.isrc_box.setCurrentIndex(s['sr830_isrc'])
        except Exception:
            pass

    def _save_sr830_settings(self):
        try:
            s = load_settings()
            s['sr830_icpl']      = self.coupling_box.currentIndex()
            s['sr830_rmod']      = self.rmod_box.currentIndex()
            s['sr830_tc_base']   = self.tc_base_box.currentIndex()
            s['sr830_tc_mult']   = self.tc_mult_box.currentIndex()
            s['sr830_tc_unit']   = self.tc_unit_box.currentIndex()
            s['sr830_ofsl']      = self.ofsl_box.currentIndex()
            s['sr830_ilin']      = self.ilin_box.currentIndex()
            s['sr830_sync']      = self.sync_box.currentIndex()
            s['sr830_sens_base'] = self.sens_base_box.currentIndex()
            s['sr830_sens_mult'] = self.sens_mult_box.currentIndex()
            s['sr830_sens_unit'] = self.sens_unit_box.currentIndex()
            s['sr830_ignd']      = self.ignd_box.currentIndex()
            s['sr830_isrc']      = self.isrc_box.currentIndex()
            save_settings(s)
        except Exception:
            pass

    def _oflt_str(self, oflt):
        bi, mi, ui = self._OFLT_IDX_TO_COMBO[oflt]
        return f"{self._TC_BASES[bi] * self._TC_MULTS[mi]} {self._TC_UNITS[ui]}"

    def _sens_str(self, sens):
        bi, mi, ui = self._SENS_IDX_TO_COMBO[sens]
        return f"{self._SENS_BASES[bi] * self._SENS_MULTS[mi]} {self._SENS_UNITS[ui]}"

    def _update_status_label(self, icpl, rmod, oflt, ofsl, ilin, sync, sens, ignd, isrc=0):
        coupling   = "DC" if icpl == 1 else "AC"
        reserve    = ["High Reserve", "Normal", "Low Noise"][rmod]
        tc_str     = self._oflt_str(oflt)
        slope_str  = ["6 dB", "12 dB", "18 dB", "24 dB"][ofsl]
        filter_str = ["No filters", "Line", "2\u00d7Line", "Both"][ilin]
        sync_str   = "Sync ON" if sync == 1 else "Sync OFF"
        sens_str   = self._sens_str(sens)
        ignd_str   = "Ground" if ignd == 1 else "Float"
        isrc_str   = "A-B" if isrc == 1 else "A only"
        self._status.setText(
            f"Active: {coupling} | {reserve} | TC {tc_str} | {slope_str}/oct\n"
            f"{filter_str} | {sync_str} | Sens {sens_str} | {ignd_str} | {isrc_str}"
        )

    def _apply(self):
        icpl     = 1 if self.coupling_box.currentIndex() == 0 else 0
        rmod     = self.rmod_box.currentIndex()
        ofsl     = self.ofsl_box.currentIndex()
        ilin     = self.ilin_box.currentIndex()
        sync     = self.sync_box.currentIndex()
        ignd     = self.ignd_box.currentIndex()
        isrc     = self.isrc_box.currentIndex()
        # --- time constant ---
        base     = self._TC_BASES[self.tc_base_box.currentIndex()]
        mult     = self._TC_MULTS[self.tc_mult_box.currentIndex()]
        unit_us  = self._TC_UNIT_US[self.tc_unit_box.currentIndex()]
        unit_str = self._TC_UNITS[self.tc_unit_box.currentIndex()]
        value_us = base * mult * unit_us
        oflt = self._OFLT_US_TO_IDX.get(value_us)
        if oflt is None:
            QMessageBox.warning(
                self, "Invalid Time Constant",
                f"{base * mult} {unit_str} is not a valid SR830 time constant.\n"
                "Please choose a different combination."
            )
            return
        # --- sensitivity ---
        sbase    = self._SENS_BASES[self.sens_base_box.currentIndex()]
        smult    = self._SENS_MULTS[self.sens_mult_box.currentIndex()]
        sunit_nv = self._SENS_UNIT_NV[self.sens_unit_box.currentIndex()]
        sunit_str= self._SENS_UNITS[self.sens_unit_box.currentIndex()]
        value_nv = sbase * smult * sunit_nv
        sens = self._SENS_NV_TO_IDX.get(value_nv)
        if sens is None:
            QMessageBox.warning(
                self, "Invalid Sensitivity",
                f"{sbase * smult} {sunit_str} is not a valid SR830 sensitivity.\n"
                "Please choose a different combination."
            )
            return
        self.core.LOCKIN_ICPL = icpl
        self.core.LOCKIN_RMOD = rmod
        self.core.LOCKIN_OFLT = oflt
        self.core.LOCKIN_OFLT_MANUAL = oflt
        self.core.LOCKIN_OFSL = ofsl
        self.core.LOCKIN_ILIN = ilin
        self.core.LOCKIN_SYNC = sync
        self.core.LOCKIN_SENS = sens
        self.core.LOCKIN_SENS_MANUAL = sens
        self.core.LOCKIN_IGND = ignd
        self.core.LOCKIN_ISRC = isrc
        self._lockin_write(f"ICPL {icpl}")
        self._lockin_write(f"RMOD {rmod}")
        self._lockin_write(f"OFLT {oflt}")
        self._lockin_write(f"OFSL {ofsl}")
        self._lockin_write(f"ILIN {ilin}")
        self._lockin_write(f"SYNC {sync}")
        self._lockin_write(f"SENS {sens}")
        self._lockin_write(f"IGND {ignd}")
        self._lockin_write(f"ISRC {isrc}")
        self._update_status_label(icpl, rmod, oflt, ofsl, ilin, sync, sens, ignd, isrc)
        coupling_str = "DC" if icpl == 1 else "AC"
        reserve_str  = ["High Reserve", "Normal", "Low Noise"][rmod]
        slope_str    = ["6 dB", "12 dB", "18 dB", "24 dB"][ofsl]
        filter_str   = ["No filters", "Line notch (50/60 Hz)", "2\u00d7 line notch (100/120 Hz)", "Both notch filters"][ilin]
        sync_str     = "ON (use <200 Hz)" if sync == 1 else "OFF (use >200 Hz)"
        ignd_str     = "Ground" if ignd == 1 else "Float"
        isrc_str     = "A-B differential" if isrc == 1 else "A only"
        QMessageBox.information(
            self, "Applied",
            f"Coupling: {coupling_str} (ICPL {icpl})\n"
            f"Dynamic Reserve: {reserve_str} (RMOD {rmod})\n"
            f"Time Constant: {base * mult} {unit_str} (OFLT {oflt})\n"
            f"Slope: {slope_str}/oct (OFSL {ofsl})\n"
            f"Filters: {filter_str} (ILIN {ilin})\n"
            f"Sync Filter: {sync_str} (SYNC {sync})\n"
            f"Sensitivity: {sbase * smult} {sunit_str} (SENS {sens})\n"
            f"Input Shield: {ignd_str} (IGND {ignd})\n"
            f"Input Type: {isrc_str} (ISRC {isrc})\n"
            "These settings will be used for all measurements until the software is closed."
        )
        self._save_sr830_settings()


class Lockin7265ParamsDialog(QDialog):

    _SEN_LABELS = [
        "1: 2 nV",   "2: 5 nV",   "3: 10 nV",  "4: 20 nV",  "5: 50 nV",
        "6: 100 nV", "7: 200 nV", "8: 500 nV",
        "9: 1 µV",   "10: 2 µV",  "11: 5 µV",  "12: 10 µV", "13: 20 µV",
        "14: 50 µV", "15: 100 µV","16: 200 µV","17: 500 µV",
        "18: 1 mV",  "19: 2 mV",  "20: 5 mV",  "21: 10 mV", "22: 20 mV",
        "23: 50 mV", "24: 100 mV","25: 200 mV","26: 500 mV","27: 1 V",
    ]
    _TC_LABELS = [
        "0: 10 µs",  "1: 20 µs",  "2: 40 µs",  "3: 80 µs",
        "4: 160 µs", "5: 320 µs", "6: 640 µs", "7: 5 ms",
        "8: 10 ms",  "9: 20 ms",  "10: 50 ms", "11: 100 ms",
        "12: 200 ms","13: 500 ms","14: 1 s",   "15: 2 s",
        "16: 5 s",   "17: 10 s",  "18: 20 s",  "19: 50 s",
        "20: 100 s", "21: 200 s", "22: 500 s", "23: 1 ks",
        "24: 2 ks",  "25: 5 ks",  "26: 10 ks", "27: 20 ks",
        "28: 50 ks", "29: 100 ks",
    ]

    def __init__(self, parent, core):
        super().__init__(parent)
        self.setWindowTitle("Lock-in 7265 Parameters")
        self.setModal(False)       # non-modal: stays open during measurement
        self.setMinimumWidth(420)
        self.core = core

        layout = QVBoxLayout(self)
        form = QFormLayout()

        def _row(widget, apply_fn):
            w = QWidget(); lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)
            lay.addWidget(widget)
            btn = QPushButton("✓"); btn.setFixedWidth(30)
            btn.setStyleSheet("background:#28a745;color:white;border-radius:4px;font-weight:bold;")
            btn.clicked.connect(apply_fn)
            lay.addWidget(btn)
            return w

        # ── Oscillator settings ────────────────────────────────────────────
        self.voltage_entry = QLineEdit(str(getattr(core, 'AC_VOLTAGE_7265', 0.0)))
        form.addRow(QLabel("AC Voltage (V):"), _row(self.voltage_entry, self._apply_voltage))

        self.freq_entry = QLineEdit(str(getattr(core, 'AC_FREQ_7265', 1.0)))
        form.addRow(QLabel("AC Freq (Hz):"), _row(self.freq_entry, self._apply_freq))

        # ── Input / filter settings ────────────────────────────────────────
        # IMODE
        self.imode_box = QComboBox()
        self.imode_box.addItems(["0: Voltage", "1: Current HI (10⁸ V/A)", "2: Current LO (10⁶ V/A)"])
        self.imode_box.setCurrentIndex(getattr(core, 'LOCKIN_7265_IMODE', 0))
        form.addRow(QLabel("Input Mode:"), _row(self.imode_box, self._apply_imode))

        # VMODE
        self.vmode_box = QComboBox()
        self.vmode_box.addItems(["1: A only", "2: −B only", "3: A−B diff"])
        self.vmode_box.setCurrentIndex(max(0, getattr(core, 'LOCKIN_7265_VMODE', 1) - 1))
        form.addRow(QLabel("Voltage Input:"), _row(self.vmode_box, self._apply_vmode))

        # FLOAT
        self.float_box = QComboBox()
        self.float_box.addItems(["0: Ground", "1: Float"])
        self.float_box.setCurrentIndex(getattr(core, 'LOCKIN_7265_FLOAT', 1))
        form.addRow(QLabel("Input Shield:"), _row(self.float_box, self._apply_float))

        # CP
        self.cp_box = QComboBox()
        self.cp_box.addItems(["0: AC", "1: DC"])
        self.cp_box.setCurrentIndex(getattr(core, 'LOCKIN_7265_CP', 1))
        form.addRow(QLabel("Coupling:"), _row(self.cp_box, self._apply_cp))

        # LF
        self.lf_box = QComboBox()
        self.lf_box.addItems(["0: Off", "1: Line notch (50/60 Hz)", "2: 2× Line notch", "3: Both"])
        self.lf_box.setCurrentIndex(getattr(core, 'LOCKIN_7265_LF', 0))
        form.addRow(QLabel("Line Rejection:"), _row(self.lf_box, self._apply_lf))

        # AUTOMATIC
        self.auto_box = QComboBox()
        self.auto_box.addItems(["0: Manual gain", "1: Auto gain"])
        self.auto_box.setCurrentIndex(1)
        form.addRow(QLabel("AC Gain:"), _row(self.auto_box, self._apply_auto))

        # SEN
        self.sen_box = QComboBox()
        self.sen_box.addItems(self._SEN_LABELS)
        sen_idx = getattr(core, 'LOCKIN_7265_SENS', 24)
        self.sen_box.setCurrentIndex(max(0, min(sen_idx - 1, len(self._SEN_LABELS) - 1)))
        form.addRow(QLabel("Sensitivity:"), _row(self.sen_box, self._apply_sen))

        # TC
        self.tc_box = QComboBox()
        self.tc_box.addItems(self._TC_LABELS)
        tc_idx = getattr(core, 'LOCKIN_7265_TC', 11)
        self.tc_box.setCurrentIndex(max(0, min(tc_idx, len(self._TC_LABELS) - 1)))
        form.addRow(QLabel("Time Constant:"), _row(self.tc_box, self._apply_tc))

        # SLOPE
        self.slope_box = QComboBox()
        self.slope_box.addItems(["0: 6 dB/oct", "1: 12 dB/oct", "2: 18 dB/oct", "3: 24 dB/oct"])
        self.slope_box.setCurrentIndex(getattr(core, 'LOCKIN_7265_SLOPE', 2))
        form.addRow(QLabel("Filter Slope:"), _row(self.slope_box, self._apply_slope))

        layout.addLayout(form)
        layout.addStretch(1)

        # ── Settings summary (green) ───────────────────────────────────────
        self._status = QLabel()
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#3be362; font-weight:bold; font-size:9px;")
        self._refresh_status()
        layout.addWidget(self._status)

        # ── Live frequency status bar (yellow) ─────────────────────────────
        self._freq_bar = QLabel("Current freq: -- Hz")
        self._freq_bar.setAlignment(Qt.AlignCenter)
        self._freq_bar.setStyleSheet(
            "color:#ffdd57; font-weight:bold; font-size:11px;"
            " background:#2b2b3d; border:1px solid #ffdd57;"
            " border-radius:4px; padding:4px;"
        )
        layout.addWidget(self._freq_bar)

        # Poll the instrument once per second so frequency updates live
        self._freq_timer = QTimer(self)
        self._freq_timer.setInterval(1000)
        self._freq_timer.timeout.connect(self._update_freq_bar)
        self._freq_timer.start()

        update_btn = QPushButton("Update All")
        update_btn.setStyleSheet("background:#3a86ff; color:white; padding:6px; border-radius:5px;")
        update_btn.clicked.connect(self._apply_all)
        layout.addWidget(update_btn)

        self._load_7265_settings()

    def _meas_running(self):
        """True while the measurement thread owns the instruments, OR a
        manual (standalone) 1w phase calibration is running synchronously
        on the GUI thread -- both cases mean a direct GPIB write from this
        dialog could race with/desynchronize an in-progress instrument
        sequence, so edits must be queued instead."""
        _main_win = self.parent()
        _meas_thread = getattr(_main_win, '_meas_thread', None)
        if _meas_thread is not None and _meas_thread.isRunning():
            return True
        return bool(getattr(_main_win, '_manual_1w_calib_running', False))

    def _write(self, cmd):
        # While a measurement is running, the worker thread owns GPIB access —
        # queue the command for it to apply at its next poll instead of
        # writing directly, which would race with its own instrument calls.
        if self._meas_running():
            try:
                self.core.LOCKIN7265_CMD_QUEUE.put(("write", cmd))
            except Exception as e:
                print(f"7265 queue error ({cmd}): {e}")
            return
        lockin7265 = getattr(self.core, 'lockin7265', None)
        if lockin7265 is not None:
            try:
                lockin7265.write(cmd)
            except Exception as e:
                print(f"7265 write error ({cmd}): {e}")

    def _apply_voltage(self):
        try:
            val = float(self.voltage_entry.text().strip())
        except ValueError:
            return
        self.core.AC_VOLTAGE_7265 = val
        if self._meas_running():
            try:
                self.core.LOCKIN7265_CMD_QUEUE.put(("voltage", val))
            except Exception as e:
                print(f"7265 queue error (voltage): {e}")
        else:
            lockin7265 = getattr(self.core, 'lockin7265', None)
            if lockin7265 is not None:
                try:
                    lockin7265.voltage = val
                except Exception as e:
                    print(f"7265 voltage set error: {e}")
        self._save_7265_settings()

    def _apply_freq(self):
        try:
            val = float(self.freq_entry.text().strip())
        except ValueError:
            return
        self.core.AC_FREQ_7265 = val
        if self._meas_running():
            try:
                self.core.LOCKIN7265_CMD_QUEUE.put(("frequency", val))
            except Exception as e:
                print(f"7265 queue error (frequency): {e}")
        else:
            lockin7265 = getattr(self.core, 'lockin7265', None)
            if lockin7265 is not None:
                try:
                    lockin7265.frequency = val
                except Exception as e:
                    print(f"7265 freq set error: {e}")
        self._save_7265_settings()

    def _update_freq_bar(self):
        lockin7265 = getattr(self.core, 'lockin7265', None)
        if lockin7265 is None:
            self._freq_bar.setText("Current freq: -- Hz  (not connected)")
            return
        # Skip the live GPIB query while a measurement is running — the worker
        # thread is talking to this same instrument concurrently, and issuing
        # a query from here too can corrupt both sides' reads and crash the run.
        if self._meas_running():
            self._freq_bar.setText("Current freq: -- Hz  (measurement running)")
            return
        try:
            freq = float(lockin7265.frequency)
            self._freq_bar.setText(f"Current freq:  {freq:.4f} Hz")
        except Exception:
            self._freq_bar.setText("Current freq: -- Hz  (read error)")

    def closeEvent(self, event):
        self._freq_timer.stop()
        super().closeEvent(event)

    def _load_7265_settings(self):
        try:
            s = load_settings()
            if '7265_voltage'  in s: self.voltage_entry.setText(str(s['7265_voltage']))
            if '7265_freq'     in s: self.freq_entry.setText(str(s['7265_freq']))
            if '7265_imode'    in s: self.imode_box.setCurrentIndex(s['7265_imode'])
            if '7265_vmode'    in s: self.vmode_box.setCurrentIndex(s['7265_vmode'])
            if '7265_float'    in s: self.float_box.setCurrentIndex(s['7265_float'])
            if '7265_cp'       in s: self.cp_box.setCurrentIndex(s['7265_cp'])
            if '7265_lf'       in s: self.lf_box.setCurrentIndex(s['7265_lf'])
            if '7265_auto'     in s: self.auto_box.setCurrentIndex(s['7265_auto'])
            if '7265_sen'      in s: self.sen_box.setCurrentIndex(s['7265_sen'])
            if '7265_tc'       in s: self.tc_box.setCurrentIndex(s['7265_tc'])
            if '7265_slope'    in s: self.slope_box.setCurrentIndex(s['7265_slope'])
        except Exception:
            pass

    def _save_7265_settings(self):
        try:
            s = load_settings()
            s['7265_voltage'] = self.voltage_entry.text().strip()
            s['7265_freq']    = self.freq_entry.text().strip()
            s['7265_imode']   = self.imode_box.currentIndex()
            s['7265_vmode']   = self.vmode_box.currentIndex()
            s['7265_float']   = self.float_box.currentIndex()
            s['7265_cp']      = self.cp_box.currentIndex()
            s['7265_lf']      = self.lf_box.currentIndex()
            s['7265_auto']    = self.auto_box.currentIndex()
            s['7265_sen']     = self.sen_box.currentIndex()
            s['7265_tc']      = self.tc_box.currentIndex()
            s['7265_slope']   = self.slope_box.currentIndex()
            save_settings(s)
        except Exception:
            pass

    def _apply_imode(self):
        val = self.imode_box.currentIndex()
        self.core.LOCKIN_7265_IMODE = val
        self._write(f"IMODE {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_vmode(self):
        val = self.vmode_box.currentIndex() + 1
        self.core.LOCKIN_7265_VMODE = val
        self._write(f"VMODE {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_float(self):
        val = self.float_box.currentIndex()
        self.core.LOCKIN_7265_FLOAT = val
        self._write(f"FLOAT {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_cp(self):
        val = self.cp_box.currentIndex()
        self.core.LOCKIN_7265_CP = val
        self._write(f"CP {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_lf(self):
        val = self.lf_box.currentIndex()
        self.core.LOCKIN_7265_LF = val
        self._write(f"LF {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_auto(self):
        val = self.auto_box.currentIndex()
        self._write(f"AUTOMATIC {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_sen(self):
        val = self.sen_box.currentIndex() + 1  # SEN is 1-indexed on the 7265
        self.core.LOCKIN_7265_SENS = val
        self.core.LOCKIN_7265_SENS_MANUAL = val
        self._write(f"SEN {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_tc(self):
        val = self.tc_box.currentIndex()
        self.core.LOCKIN_7265_TC = val
        self.core.LOCKIN_7265_TC_MANUAL = val
        self._write(f"TC {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_slope(self):
        val = self.slope_box.currentIndex()
        self.core.LOCKIN_7265_SLOPE = val
        self._write(f"SLOPE {val}")
        self._refresh_status()
        self._save_7265_settings()

    def _apply_all(self):
        self._apply_voltage()
        self._apply_freq()
        self._apply_imode()
        self._apply_vmode()
        self._apply_float()
        self._apply_cp()
        self._apply_lf()
        self._apply_auto()
        self._apply_sen()
        self._apply_tc()
        self._apply_slope()
        self._save_7265_settings()

    def _refresh_status(self):
        imode = getattr(self.core, 'LOCKIN_7265_IMODE', 0)
        cp    = getattr(self.core, 'LOCKIN_7265_CP', 1)
        sens  = getattr(self.core, 'LOCKIN_7265_SENS', 24)
        tc    = getattr(self.core, 'LOCKIN_7265_TC', 11)
        imode_str = ["Voltage", "Current HI", "Current LO"][imode]
        cp_str    = "DC" if cp == 1 else "AC"
        sen_str   = self._SEN_LABELS[sens - 1] if 1 <= sens <= len(self._SEN_LABELS) else str(sens)
        tc_str    = self._TC_LABELS[tc]    if 0 <= tc  < len(self._TC_LABELS)    else str(tc)
        self._status.setText(f"Mode: {imode_str} | {cp_str} | SEN {sen_str} | TC {tc_str}")


# ──────────────────────────────────────────────────────────────────────────────
# Frequency sweep helpers
# ──────────────────────────────────────────────────────────────────────────────

def _round_to_sig(x, sig=1):
    """Round x to `sig` significant figures."""
    import math
    if x <= 0:
        return x
    d = math.floor(math.log10(x))
    factor = 10 ** (d - sig + 1)
    return round(x / factor) * factor


def _build_freq_list(start, stop, n, spacing):
    """Return list of frequencies for one range (start/stop inclusive, n points)."""
    import math
    import numpy as np
    n = max(1, int(n))
    start, stop = float(start), float(stop)
    if n == 1:
        return [start]
    if spacing == "Logarithmic":
        return list(np.logspace(math.log10(max(start, 1e-9)),
                                math.log10(max(stop,  1e-9)), n))
    if spacing == "Rounded step":
        # Round ideal step to 1 sig fig, then fill with multiples of that step.
        # Start is kept exact; multiples of nice_step from the next round value
        # fill in up to stop (which is also kept exact).
        ideal_step = (stop - start) / (n - 1)
        nice_step = _round_to_sig(ideal_step, 1)
        if nice_step <= 0:
            return list(np.linspace(start, stop, n))
        first_mult = math.ceil(start / nice_step) * nice_step
        pts = []
        v = first_mult
        while v <= stop + nice_step * 0.01:
            pts.append(v)
            v = round(v + nice_step, 10)
        result = sorted(set([start] + [p for p in pts if start < p < stop + nice_step * 0.01] + [stop]))
        return result
    if spacing == "Equal space range":
        # Step from start by nice_step repeatedly. Stop at the last point
        # that does not exceed stop — stop itself is NOT appended.
        # All gaps are exactly nice_step; the list naturally ends at or
        # before the stop frequency.
        ideal_step = (stop - start) / (n - 1)
        nice_step = _round_to_sig(ideal_step, 1)
        if nice_step <= 0:
            return list(np.linspace(start, stop, n))
        pts = []
        v = start
        while v <= stop + nice_step * 1e-9:
            pts.append(round(v, 10))
            v = round(v + nice_step, 10)
        return pts
    return list(np.linspace(start, stop, n))


class FrequencyListDialog(QDialog):
    """Non-modal popup that shows the full sorted value list."""
    def __init__(self, frequencies, parent=None, unit="Hz"):
        super().__init__(parent)
        self.setWindowTitle(f"Value List ({unit})")
        self.setMinimumWidth(280)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout(self)

        header = QLabel(f"{len(frequencies)} values ({unit})")
        header.setStyleSheet("font-weight:bold; padding:4px;")
        layout.addWidget(header)

        tbl = QTableWidget(len(frequencies), 2, self)
        tbl.setHorizontalHeaderLabels(["#", f"Value ({unit})"])
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)
        tbl.setAlternatingRowColors(True)
        for i, f in enumerate(frequencies):
            tbl.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            tbl.setItem(i, 1, QTableWidgetItem(f"{f:.6g}"))
            tbl.setRowHeight(i, 18)
        layout.addWidget(tbl)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(
            "\n".join(f"{f:.6g}" for f in frequencies)))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


class _SubRangeRow(QWidget):
    """One row in the sub-ranges table."""
    removed = Signal(object)

    def __init__(self, start=1.0, stop=10.0, n=5, spacing="Linear", wait_time="",
                 show_wait=True, parent=None):
        super().__init__(parent)
        self._show_wait = show_wait
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(4)

        self.start_e  = QLineEdit(str(start));    self.start_e.setFixedWidth(55)
        self.stop_e   = QLineEdit(str(stop));     self.stop_e.setFixedWidth(55)
        self.n_e      = QLineEdit(str(n));        self.n_e.setFixedWidth(34)
        self.sp_box   = QComboBox();              self.sp_box.setFixedWidth(90)
        self.sp_box.addItems(["Linear", "Rounded step", "Equal space range", "Logarithmic"])
        self.sp_box.setCurrentText(spacing)

        rm = QPushButton("✕"); rm.setFixedWidth(22)
        rm.setStyleSheet("background:#e35f3b; color:white; border-radius:3px; font-size:9px;")
        rm.clicked.connect(lambda: self.removed.emit(self))

        widgets = [QLabel("Start:"), self.start_e,
                   QLabel("Stop:"),  self.stop_e,
                   QLabel("N:"),     self.n_e,
                   self.sp_box]

        if show_wait:
            self.wait_e = QLineEdit(str(wait_time)); self.wait_e.setFixedWidth(42)
            self.wait_e.setPlaceholderText("s")
            self.wait_e.setToolTip("Wait time (s) for this sub-range — required")
            self.wait_e.textChanged.connect(self._update_wait_style)
            self._update_wait_style(self.wait_e.text())
            widgets += [QLabel("Wait:"), self.wait_e]
        else:
            self.wait_e = None

        widgets.append(rm)
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)

    def _update_wait_style(self, text):
        if text.strip():
            self.wait_e.setStyleSheet("")
        else:
            self.wait_e.setStyleSheet("border: 1px solid #e35f3b; background: #3a1a1a;")

    def get_config(self):
        d = {
            "start":   float(self.start_e.text() or 1),
            "stop":    float(self.stop_e.text()  or 10),
            "n":       int(self.n_e.text()       or 5),
            "spacing": self.sp_box.currentText(),
        }
        if self._show_wait:
            d["wait_time"] = self.wait_e.text().strip()
        return d

    def set_config(self, d):
        self.start_e.setText(str(d.get("start", 1.0)))
        self.stop_e.setText(str(d.get("stop", 10.0)))
        self.n_e.setText(str(d.get("n", 5)))
        self.sp_box.setCurrentText(d.get("spacing", "Linear"))
        if self._show_wait and self.wait_e is not None:
            self.wait_e.setText(str(d.get("wait_time", "")))



class EditableListDialog(QDialog):
    """Floating panel for manually editing a frequency/voltage list.

    During a 3-omega measurement the dialog colour-codes rows:
      green  = already measured (locked, read-only)
      yellow = currently measuring (locked)
      white  = upcoming (fully editable; Apply patches the live list in-place)
    """

    _SS_TABLE = (
        "QTableWidget { background:#1a1a2e; gridline-color:#333355;"
        "  color:#e0e0f0; border:1px solid #333355; font-size:12px; }"
        "QTableWidget::item { padding:4px 8px; }"
        "QTableWidget::item:selected { background:#2d4a8a; color:white; }"
        "QHeaderView::section { background:#252540; color:#a0a0cc;"
        "  font-size:11px; padding:4px; border:none; border-bottom:1px solid #444466; }"
        "QScrollBar:vertical { background:#1a1a2e; width:10px; }"
        "QScrollBar::handle:vertical { background:#444466; border-radius:5px; }"
    )
    _SS_BTN = (
        "QPushButton { background:#252540; color:#c0c0e0; border:1px solid #444466;"
        "  border-radius:4px; padding:4px 12px; font-size:11px; }"
        "QPushButton:hover { background:#2d2d55; border-color:#6666aa; }"
        "QPushButton:pressed { background:#1a1a35; }"
        "QPushButton:disabled { background:#1e1e32; color:#555577; border-color:#333355; }"
    )
    _SS_BTN_PRIMARY = (
        "QPushButton { background:#2a5fd4; color:white; border:1px solid #3a6fe4;"
        "  border-radius:4px; padding:5px 18px; font-size:12px; font-weight:bold; }"
        "QPushButton:hover { background:#3a6fe4; }"
        "QPushButton:pressed { background:#1a4fc4; }"
    )
    _SS_BTN_DANGER = (
        "QPushButton { background:#5a1a1a; color:#ff9999; border:1px solid #8a3333;"
        "  border-radius:4px; padding:4px 12px; font-size:11px; }"
        "QPushButton:hover { background:#7a2222; }"
        "QPushButton:disabled { background:#1e1e32; color:#555577; border-color:#333355; }"
    )
    _SS_BTN_WARN = (
        "QPushButton { background:#4a3800; color:#ffcc44; border:1px solid #7a6000;"
        "  border-radius:4px; padding:5px 14px; font-size:11px; }"
        "QPushButton:hover { background:#5a4800; }"
    )

    def __init__(self, freq_widget, parent=None):
        super().__init__(parent)
        self._fw      = freq_widget
        self._unit    = freq_widget._unit
        self._loading = False
        self._loaded  = False

        self.setWindowTitle(f"Edit {self._unit} List")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.resize(480, 600)
        self.setStyleSheet(
            "QDialog { background:#12121f; }"
            "QLabel  { color:#c0c0e0; font-size:11px; }"
            "QLineEdit { background:#1e1e35; color:#e0e0f0; border:1px solid #444466;"
            "  border-radius:3px; padding:3px 6px; font-size:12px; }"
            "QLineEdit:focus { border-color:#6666cc; }"
        )

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # Measurement-mode banner (hidden when not measuring)
        self._meas_banner = QLabel()
        self._meas_banner.setStyleSheet(
            "background:#1a2a00; color:#aadd44; font-size:11px; font-weight:bold;"
            " border:1px solid #445500; border-radius:4px; padding:4px 10px;")
        self._meas_banner.setWordWrap(True)
        self._meas_banner.hide()
        root.addWidget(self._meas_banner)

        # Header
        hdr = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet("color:#9090cc; font-size:10px; font-style:italic;")
        hdr.addWidget(self._title_lbl)
        hdr.addStretch(1)
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(
            "color:#70c0ff; font-size:11px; font-weight:bold;"
            " background:#1a2540; border-radius:3px; padding:2px 8px;")
        hdr.addWidget(self._status_lbl)
        root.addLayout(hdr)

        # Toolbar
        tb = QHBoxLayout()
        tb.setSpacing(6)
        self._add_btn = QPushButton("+ Add Row")
        self._del_btn = QPushButton("Delete")
        self._up_btn  = QPushButton("Up")
        self._dn_btn  = QPushButton("Down")
        self._all_btn = QPushButton("All On")
        self._non_btn = QPushButton("All Off")
        self._up_btn.setFixedWidth(56)
        self._dn_btn.setFixedWidth(56)
        for b in (self._add_btn, self._del_btn, self._up_btn, self._dn_btn,
                  self._all_btn, self._non_btn):
            b.setStyleSheet(self._SS_BTN)
            b.setFixedHeight(28)
            tb.addWidget(b)
        self._del_btn.setStyleSheet(self._SS_BTN_DANGER)
        tb.addStretch(1)
        root.addLayout(tb)

        # Table
        self._tbl = QTableWidget(0, 3)
        self._tbl.setHorizontalHeaderLabels(["On", f"Value ({self._unit})", "Wait (s)"])
        self._tbl.setStyleSheet(self._SS_TABLE)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tbl.verticalHeader().setDefaultSectionSize(30)
        self._tbl.verticalHeader().hide()
        self._tbl.horizontalHeader().setStretchLastSection(False)
        self._tbl.setColumnWidth(0, 36)
        self._tbl.setColumnWidth(2, 90)
        self._tbl.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._tbl.itemChanged.connect(self._on_item_changed)
        self._tbl.itemSelectionChanged.connect(self._update_btn_states)
        root.addWidget(self._tbl)

        # Typed-value add row
        add_row_layout = QHBoxLayout()
        add_row_layout.setSpacing(6)
        add_row_layout.addWidget(QLabel("New value:"))
        self._new_val_edit = QLineEdit()
        self._new_val_edit.setPlaceholderText("e.g. 47.5")
        self._new_val_edit.setFixedWidth(120)
        self._new_val_edit.returnPressed.connect(self._add_typed_row)
        add_row_layout.addWidget(self._new_val_edit)
        _typed_add_btn = QPushButton("Add")
        _typed_add_btn.setFixedHeight(26)
        _typed_add_btn.setFixedWidth(50)
        _typed_add_btn.setStyleSheet(self._SS_BTN)
        _typed_add_btn.clicked.connect(self._add_typed_row)
        add_row_layout.addWidget(_typed_add_btn)
        add_row_layout.addStretch(1)
        root.addLayout(add_row_layout)

        # Bottom buttons
        bot = QHBoxLayout()
        self._reset_btn = QPushButton("Reset to Computed")
        self._apply_btn = QPushButton("Apply")
        self._close_btn = QPushButton("Close")
        self._reset_btn.setStyleSheet(self._SS_BTN_WARN)
        self._apply_btn.setStyleSheet(self._SS_BTN_PRIMARY)
        self._close_btn.setStyleSheet(self._SS_BTN)
        for b in (self._reset_btn, self._apply_btn, self._close_btn):
            b.setFixedHeight(32)
        bot.addWidget(self._reset_btn)
        bot.addStretch(1)
        bot.addWidget(self._close_btn)
        bot.addWidget(self._apply_btn)
        root.addLayout(bot)

        # Connections
        self._add_btn.clicked.connect(self._add_blank_row)
        self._del_btn.clicked.connect(self._delete_row)
        self._up_btn.clicked.connect(self._move_up)
        self._dn_btn.clicked.connect(self._move_dn)
        self._all_btn.clicked.connect(lambda: self._set_all(True))
        self._non_btn.clicked.connect(lambda: self._set_all(False))
        self._reset_btn.clicked.connect(self._reset_to_computed)
        self._apply_btn.clicked.connect(self._apply)
        self._close_btn.clicked.connect(self.close)

        # Refresh timer — updates colours every second while visible
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self.refresh_meas_colours)

        self._update_btn_states()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self._load_current()
            self._loaded = True
        self._refresh_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._refresh_timer.stop()

    def load_fresh(self):
        """Called by FrequencyRangeWidget._open_edit_dialog to always show current data."""
        self._load_current()
        self._loaded = True

    # ── Measurement mode helpers ───────────────────────────────────────────────

    def _is_meas_mode(self):
        return self._fw._meas_live_freqs is not None

    def _meas_locked_up_to(self):
        """Return inclusive row index up to which rows are locked (done + current).
        Returns -1 if not in meas mode or nothing started yet."""
        if not self._is_meas_mode():
            return -1
        done = self._fw._meas_done_count
        # done rows: 0..done-1; current row: done
        # Only lock "current" if cur_freq is actually set
        if self._fw._meas_cur_freq is not None:
            return done  # lock done + current
        return done - 1  # nothing started yet or between freqs

    def refresh_meas_colours(self):
        """Recolour rows to reflect current measurement progress (called from timer/signal)."""
        if not self._is_meas_mode():
            self._meas_banner.hide()
            self._reset_btn.setEnabled(True)
            return
        lock_up_to = self._meas_locked_up_to()
        n = self._tbl.rowCount()
        done = self._fw._meas_done_count
        prev = self._loading
        self._loading = True
        for r in range(n):
            if r < done:
                self._colour_row_meas(r, "done")
            elif r == done and self._fw._meas_cur_freq is not None:
                self._colour_row_meas(r, "current")
            else:
                cb = self._tbl.item(r, 0)
                en = cb.checkState() == Qt.CheckState.Checked if cb else True
                self._colour_row_meas(r, "upcoming" if en else "upcoming-off")
        self._loading = prev
        self._update_btn_states()
        # Update banner
        live = self._fw._meas_live_freqs
        total = len(live) if live else 0
        self._meas_banner.setText(
            f"Measurement active: {done}/{total} done   "
            f"| Green=done  Yellow=current  White=upcoming"
        )
        self._meas_banner.show()
        self._reset_btn.setEnabled(False)  # cannot reset to computed during run

    def _colour_row_meas(self, r, status):
        """Apply measurement-state colour to row r (does NOT touch self._loading)."""
        if status == "done":
            bg = QColor("#0d2214"); fg = QColor("#5cb85c")
        elif status == "current":
            bg = QColor("#2a1e00"); fg = QColor("#ffc107")
        elif status == "upcoming-off":
            bg = QColor("#1a1a26"); fg = QColor("#555577")
        else:  # upcoming (enabled)
            bg = QColor("#1e2840"); fg = QColor("#e0e0f0")
        for c in range(3):
            item = self._tbl.item(r, c)
            if item:
                item.setBackground(bg)
                if c > 0:
                    item.setForeground(fg)

    # ── Table population ───────────────────────────────────────────────────────

    def _load_current(self):
        """Populate table from custom list / live freqs / computed range."""
        self._loading = True
        self._tbl.setRowCount(0)
        if self._is_meas_mode():
            # During measurement: show the live freq list with done/current/upcoming colours
            live = self._fw._meas_live_freqs
            wait_map = self._fw._meas_wait_map or {}
            rows = [{"value": f, "enabled": True,
                     "wait": wait_map.get(round(f, 9), 0.0)} for f in live]
            self._title_lbl.setText("Live measurement list — edit upcoming rows then Apply")
        elif self._fw._custom_list is not None:
            rows = self._fw._custom_list
            self._title_lbl.setText("Showing: custom edited list")
        else:
            try:
                freqs = self._fw.get_frequencies()
            except Exception:
                freqs = []
            rows = [{"value": f, "enabled": True, "wait": self._wait_for(f)} for f in freqs]
            self._title_lbl.setText("Showing: computed from range settings")
        for r in rows:
            self._append_row_locked(r["value"], r["enabled"], r["wait"])
        self._loading = False
        if self._is_meas_mode():
            self.refresh_meas_colours()
        self._refresh_status()
        self._update_btn_states()

    def _wait_for(self, value):
        try:
            if self._fw._sub_rows:
                for row in self._fw._sub_rows:
                    c  = row.get_config()
                    lo, hi = sorted([float(c["start"]), float(c["stop"])])
                    if lo <= value <= hi:
                        wt = c.get("wait_time", "")
                        return float(wt) if wt else 0.0
                c  = self._fw._sub_rows[0].get_config()
                wt = c.get("wait_time", "")
                return float(wt) if wt else 0.0
            elif self._fw._show_wait and hasattr(self._fw, "wait_e"):
                return float(self._fw.wait_e.text() or 0)
        except Exception:
            pass
        return 0.0

    def _make_items(self, value, enabled, wait):
        cb = QTableWidgetItem()
        cb.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable |
            Qt.ItemFlag.ItemIsEnabled       |
            Qt.ItemFlag.ItemIsSelectable)
        cb.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        cb.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        val_text = f"{value:.6g}" if value is not None else ""
        vi = QTableWidgetItem(val_text)
        vi.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        wt_text = f"{wait:.4g}" if (wait is not None and wait != 0) else "0"
        wi = QTableWidgetItem(wt_text)
        wi.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        return cb, vi, wi

    def _apply_row_colour(self, r, enabled):
        """Normal (non-meas) row colouring."""
        clr = QColor("#1e2840") if enabled else QColor("#1a1a26")
        txt = QColor("#e0e0f0") if enabled else QColor("#666688")
        prev = self._loading
        self._loading = True
        for c in range(3):
            item = self._tbl.item(r, c)
            if item:
                item.setBackground(clr)
                if c > 0:
                    item.setForeground(txt)
        self._loading = prev

    def _append_row_locked(self, value, enabled, wait):
        """Append row while _loading is already True."""
        r = self._tbl.rowCount()
        self._tbl.insertRow(r)
        cb, vi, wi = self._make_items(value, enabled, wait)
        self._tbl.setItem(r, 0, cb)
        self._tbl.setItem(r, 1, vi)
        self._tbl.setItem(r, 2, wi)
        self._apply_row_colour(r, enabled)

    def _insert_at(self, ins, value=None, enabled=True, wait=None):
        if wait is None:
            wait = self._wait_for(value) if value is not None else 0.0
        prev = self._loading
        self._loading = True
        self._tbl.insertRow(ins)
        cb, vi, wi = self._make_items(value, enabled, wait)
        self._tbl.setItem(ins, 0, cb)
        self._tbl.setItem(ins, 1, vi)
        self._tbl.setItem(ins, 2, wi)
        self._loading = prev
        self._apply_row_colour(ins, enabled)
        self._tbl.selectRow(ins)
        self._refresh_status()
        self._update_btn_states()
        if value is None:
            self._tbl.editItem(self._tbl.item(ins, 1))

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _on_item_changed(self, item):
        if self._loading:
            return
        r = item.row()
        if item.column() == 0:
            en = (item.checkState() == Qt.CheckState.Checked)
            if self._is_meas_mode():
                lock = self._meas_locked_up_to()
                status = "done" if r < self._fw._meas_done_count else \
                         "current" if r == self._fw._meas_done_count and self._fw._meas_cur_freq is not None else \
                         ("upcoming" if en else "upcoming-off")
                prev = self._loading; self._loading = True
                self._colour_row_meas(r, status)
                self._loading = prev
            else:
                self._apply_row_colour(r, en)
        self._refresh_status()

    def _refresh_status(self):
        n = self._tbl.rowCount()
        enabled = sum(
            1 for r in range(n)
            if self._tbl.item(r, 0) and
               self._tbl.item(r, 0).checkState() == Qt.CheckState.Checked
        )
        self._status_lbl.setText(f"{n} pts  |  {enabled} enabled")

    def _update_btn_states(self):
        sel = self._tbl.currentRow()
        n   = self._tbl.rowCount()
        lock = self._meas_locked_up_to()  # -1 if not measuring
        in_upcoming = sel > lock  # True if selected row is editable
        self._del_btn.setEnabled(sel >= 0 and in_upcoming)
        self._up_btn.setEnabled(sel > max(lock + 1, 0) and in_upcoming)
        self._dn_btn.setEnabled(in_upcoming and 0 <= sel < n - 1)
        self._all_btn.setEnabled(not self._is_meas_mode())
        self._non_btn.setEnabled(not self._is_meas_mode())

    # ── Row operations ────────────────────────────────────────────────────────

    def _upcoming_insert_pos(self, sel):
        """Safe insert position: always after locked rows."""
        lock = self._meas_locked_up_to()
        if sel > lock:
            return sel + 1
        return max(lock + 1, self._tbl.rowCount())  # append at end of upcoming

    def _add_blank_row(self):
        sel = self._tbl.currentRow()
        ins = self._upcoming_insert_pos(sel)
        self._insert_at(ins, value=None)

    def _add_typed_row(self):
        raw = self._new_val_edit.text().strip()
        try:
            value = float(raw)
        except ValueError:
            self._new_val_edit.setStyleSheet(
                "background:#3a1010; color:#ff9999; border:1px solid #cc3333;"
                " border-radius:3px; padding:3px 6px; font-size:12px;")
            return
        self._new_val_edit.setStyleSheet("")
        sel = self._tbl.currentRow()
        ins = self._upcoming_insert_pos(sel)
        self._insert_at(ins, value=value)
        self._new_val_edit.clear()
        self._new_val_edit.setFocus()

    def _delete_row(self):
        sel = self._tbl.currentRow()
        if sel < 0 or sel <= self._meas_locked_up_to():
            return
        self._tbl.removeRow(sel)
        new_sel = min(sel, self._tbl.rowCount() - 1)
        if new_sel >= 0:
            self._tbl.selectRow(new_sel)
        self._refresh_status()
        self._update_btn_states()

    def _move_up(self):
        r = self._tbl.currentRow()
        lock = self._meas_locked_up_to()
        if r <= max(lock + 1, 0):
            return
        self._swap_rows(r, r - 1)
        self._tbl.selectRow(r - 1)
        self._update_btn_states()

    def _move_dn(self):
        r = self._tbl.currentRow()
        if r < 0 or r >= self._tbl.rowCount() - 1 or r <= self._meas_locked_up_to():
            return
        self._swap_rows(r, r + 1)
        self._tbl.selectRow(r + 1)
        self._update_btn_states()

    def _swap_rows(self, a, b):
        prev = self._loading
        self._loading = True
        for col in range(3):
            ia = self._tbl.item(a, col)
            ib = self._tbl.item(b, col)
            if not (ia and ib):
                continue
            ta, tb_ = ia.text(), ib.text()
            ia.setText(tb_)
            ib.setText(ta)
            if col == 0:
                ca = ia.checkState()
                cb_ = ib.checkState()
                ia.setCheckState(cb_)
                ib.setCheckState(ca)
        self._loading = prev
        en_a = (self._tbl.item(a, 0).checkState() == Qt.CheckState.Checked)
        en_b = (self._tbl.item(b, 0).checkState() == Qt.CheckState.Checked)
        self._apply_row_colour(a, en_a)
        self._apply_row_colour(b, en_b)

    def _set_all(self, state):
        if self._is_meas_mode():
            return  # not allowed during measurement
        cs = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
        prev = self._loading
        self._loading = True
        for r in range(self._tbl.rowCount()):
            item = self._tbl.item(r, 0)
            if item:
                item.setCheckState(cs)
            self._apply_row_colour(r, state)
        self._loading = prev
        self._refresh_status()

    def _read_table(self):
        rows = []
        for r in range(self._tbl.rowCount()):
            try:
                cb = self._tbl.item(r, 0)
                vi = self._tbl.item(r, 1)
                wi = self._tbl.item(r, 2)
                enabled = (cb.checkState() == Qt.CheckState.Checked)
                value   = float(vi.text())
                wait    = float(wi.text() or 0)
                rows.append({"value": value, "enabled": enabled, "wait": wait})
            except Exception:
                pass
        return rows

    # ── Apply / Reset ──────────────────────────────────────────────────────────

    def _apply(self):
        if self._is_meas_mode():
            self._apply_during_meas()
        else:
            rows = self._read_table()
            if not rows:
                QMessageBox.warning(self, "Empty List",
                                    "No valid rows found. Add some values first.")
                return
            self._fw._custom_list = rows
            self._fw._refresh_indicator()
            self._title_lbl.setText("Showing: custom edited list  (applied)")

    def _apply_during_meas(self):
        """Update the live frequency list from the upcoming (editable) rows."""
        done = self._fw._meas_done_count
        n = self._tbl.rowCount()
        # Rows > done are "upcoming" and editable
        # Row == done is "current" and must not be touched
        new_upcoming = []
        new_waits    = {}
        for r in range(done + 1, n):
            try:
                cb = self._tbl.item(r, 0)
                vi = self._tbl.item(r, 1)
                wi = self._tbl.item(r, 2)
                enabled = (cb.checkState() == Qt.CheckState.Checked)
                value   = float(vi.text())
                wait    = float(wi.text() or 0)
                if enabled:
                    new_upcoming.append(value)
                    new_waits[round(value, 9)] = wait
            except Exception:
                pass
        # Atomic in-place slice replacement (GIL-safe in CPython)
        live = self._fw._meas_live_freqs
        live[done + 1:] = new_upcoming
        # Patch wait map for any newly added frequencies
        if self._fw._meas_wait_map is not None:
            self._fw._meas_wait_map.update(new_waits)
        # Also persist as custom_list so it survives the run
        all_rows = []
        for r in range(n):
            try:
                cb = self._tbl.item(r, 0)
                vi = self._tbl.item(r, 1)
                wi = self._tbl.item(r, 2)
                all_rows.append({"value": float(vi.text()),
                                 "enabled": cb.checkState() == Qt.CheckState.Checked,
                                 "wait":    float(wi.text() or 0)})
            except Exception:
                pass
        self._fw._custom_list = all_rows if all_rows else None
        self._fw._refresh_indicator()
        self._title_lbl.setText(
            f"Live edit applied — {len(new_upcoming)} upcoming frequencies")
        self.refresh_meas_colours()

    def _reset_to_computed(self):
        if self._is_meas_mode():
            return  # not allowed during measurement
        reply = QMessageBox.question(
            self, "Reset to Computed",
            "Discard the custom list and go back to the computed range?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._fw._custom_list = None
            self._fw._refresh_indicator()
            self._load_current()


class FrequencyRangeWidget(QWidget):
    """Compact widget for defining a swept frequency list.

    Global row: start / stop / N / spacing — used when no sub-ranges exist.
    Sub-ranges: optional list of (start, stop, N, spacing) rows whose union
                replaces the global sweep.
    """

    def __init__(self, unit="Hz", show_wait=True, parent=None):
        super().__init__(parent)
        self._sub_rows = []
        self._show_wait = show_wait
        self._custom_list    = None  # list of {value, enabled, wait} or None
        self._last_used_list = None  # saved after each completed/stopped run for repeat use
        self._edit_dialog    = None  # created lazily
        # Live measurement state — set by MainWindow while a sweep is running
        self._meas_live_freqs = None   # shared list with core thread; modify upcoming slice in-place
        self._meas_done_count = 0      # number of completed frequencies
        self._meas_cur_freq   = None   # frequency currently being measured
        self._meas_wait_map   = None   # freq→wait_time dict shared with core
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ── Global row ────────────────────────────────────────────────────────
        global_row = QHBoxLayout()
        global_row.setSpacing(4)

        self._unit = unit
        self.start_e   = QLineEdit("1.0");   self.start_e.setFixedWidth(55)
        self.stop_e    = QLineEdit("100.0"); self.stop_e.setFixedWidth(55)
        self.n_e       = QLineEdit("20");    self.n_e.setFixedWidth(38)
        self.sp_box    = QComboBox();        self.sp_box.setFixedWidth(100)
        self.sp_box.addItems(["Linear", "Rounded step", "Equal space range", "Logarithmic"])

        list_btn = QPushButton("View List")
        list_btn.setFixedWidth(70)
        list_btn.setStyleSheet(
            "background:#3a86ff; color:white; border-radius:3px;"
            " font-size:9px; padding:2px 4px;"
        )
        list_btn.setToolTip(f"Click to preview the full {unit} list")
        list_btn.clicked.connect(self._show_list)

        edit_list_btn = QPushButton("Edit List")
        edit_list_btn.setFixedWidth(60)
        edit_list_btn.setStyleSheet(
            "background:#2a5040; color:#70d0a0; border:1px solid #3a7060;"
            " border-radius:3px; font-size:9px; padding:2px 4px;"
        )
        edit_list_btn.setToolTip(f"Manually edit the {unit} list — add, delete, reorder, enable/disable")
        edit_list_btn.clicked.connect(self._open_edit_dialog)

        self._last_btn = QPushButton("Last")
        self._last_btn.setFixedWidth(36)
        self._last_btn.setStyleSheet(
            "QPushButton { background:#2a2a40; color:#9090cc; border:1px solid #444466;"
            "  border-radius:3px; font-size:9px; padding:2px 4px; }"
            "QPushButton:hover { background:#35356a; color:#c0c0ff; }"
            "QPushButton:disabled { color:#3a3a55; border-color:#2a2a3a; }"
        )
        self._last_btn.setToolTip("Load the frequency list from the last completed measurement run")
        self._last_btn.setEnabled(False)
        self._last_btn.clicked.connect(self._load_last_used)

        for w in (QLabel(f"Start ({unit}):"), self.start_e,
                  QLabel(f"Stop ({unit}):"),  self.stop_e,
                  QLabel("N:"),               self.n_e,
                  self.sp_box,                list_btn, edit_list_btn, self._last_btn):
            global_row.addWidget(w)
        global_row.addStretch(1)
        outer.addLayout(global_row)

        # ── Active-mode indicator ─────────────────────────────────────────────
        self._mode_label = QLabel()
        self._mode_label.setStyleSheet(
            "font-size:9px; padding:2px 6px; border-radius:3px;"
        )
        outer.addWidget(self._mode_label)

        # ── Sub-ranges header ─────────────────────────────────────────────────
        sub_hdr = QHBoxLayout()
        _hdr_text = ("Sub-ranges (each needs its own wait time):"
                     if show_wait else "Sub-ranges:")
        sub_hdr.addWidget(QLabel(_hdr_text))
        sub_hdr.addStretch(1)
        add_btn = QPushButton("+ Add Range")
        add_btn.setFixedWidth(80)
        add_btn.setStyleSheet(
            "background:#2b2b3d; color:white; border:1px solid #555577;"
            " border-radius:3px; font-size:9px; padding:2px 4px;"
        )
        add_btn.clicked.connect(self._add_sub_range)
        sub_hdr.addWidget(add_btn)
        outer.addLayout(sub_hdr)

        # ── Sub-ranges container ──────────────────────────────────────────────
        self._sub_container = QWidget()
        self._sub_layout    = QVBoxLayout(self._sub_container)
        self._sub_layout.setContentsMargins(0, 0, 0, 0)
        self._sub_layout.setSpacing(2)
        outer.addWidget(self._sub_container)

        self._refresh_indicator()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_ranges(self, global_wait_time=None):
        """Return list of dicts: [{"frequencies": [...], "wait_time": float}, ...]

        global_wait_time: fallback used for the global range (float, seconds).
        Raises ValueError if any sub-range has an empty wait_time field.
        """
        if getattr(self, '_custom_list', None) is not None:
            # Group enabled rows by wait time
            from collections import defaultdict as _dd
            groups = _dd(list)
            for r in self._custom_list:
                if r['enabled']:
                    groups[r['wait']].append(r['value'])
            if not groups:
                return [{"frequencies": [], "wait_time": global_wait_time or 0.0}]
            # Return one entry per unique wait time, preserving order
            seen_wt = []
            result = []
            for r in self._custom_list:
                if r['enabled'] and r['wait'] not in seen_wt:
                    seen_wt.append(r['wait'])
                    result.append({"frequencies": groups[r['wait']], "wait_time": r['wait']})
            return result
        if self._sub_rows:
            missing = [i + 1 for i, r in enumerate(self._sub_rows)
                       if not r.get_config()["wait_time"]]
            if missing:
                raise ValueError(
                    f"Sub-range{'s' if len(missing) > 1 else ''} "
                    f"{', '.join(str(i) for i in missing)} "
                    f"{'have' if len(missing) > 1 else 'has'} no wait time. "
                    f"Please fill in the Wait field for every sub-range."
                )
            result = []
            for row in self._sub_rows:
                c = row.get_config()
                freqs = _build_freq_list(c["start"], c["stop"], c["n"], c["spacing"])
                result.append({"frequencies": freqs, "wait_time": float(c["wait_time"])})
            return result
        else:
            freqs = self.get_frequencies()
            wt = global_wait_time if global_wait_time is not None else 0.0
            return [{"frequencies": freqs, "wait_time": wt}]

    def get_frequencies(self):
        """Return sorted, deduplicated list of measurement frequencies (Hz)."""
        if getattr(self, '_custom_list', None) is not None:
            return [r['value'] for r in self._custom_list if r['enabled']]
        if self._sub_rows:
            pts = []
            for row in self._sub_rows:
                c = row.get_config()
                pts.extend(_build_freq_list(c["start"], c["stop"], c["n"], c["spacing"]))
        else:
            try:
                start = float(self.start_e.text())
                stop  = float(self.stop_e.text())
                n     = int(self.n_e.text())
                sp    = self.sp_box.currentText()
            except ValueError:
                return [1.0]
            pts = _build_freq_list(start, stop, n, sp)
        # deduplicate (round to 6 sig figs), sort
        seen = set()
        result = []
        for f in sorted(pts):
            key = round(f, 6)
            if key not in seen:
                seen.add(key)
                result.append(f)
        return result

    def get_config(self):
        return {
            "start":          self.start_e.text(),
            "stop":           self.stop_e.text(),
            "n":              self.n_e.text(),
            "spacing":        self.sp_box.currentText(),
            "sub_ranges":     [r.get_config() for r in self._sub_rows],
            "custom_list":    getattr(self, '_custom_list', None),
            "last_used_list": getattr(self, '_last_used_list', None),
        }

    def set_config(self, d):
        if not d:
            return
        self.start_e.setText(str(d.get("start", "1.0")))
        self.stop_e.setText(str(d.get("stop", "100.0")))
        self.n_e.setText(str(d.get("n", "20")))
        self.sp_box.setCurrentText(d.get("spacing", "Linear"))
        for row in list(self._sub_rows):
            self._remove_sub_range(row)
        for sr in d.get("sub_ranges", []):
            self._add_sub_range(sr)
        self._custom_list    = d.get("custom_list", None)
        self._last_used_list = d.get("last_used_list", None)
        self._refresh_indicator()

    def _refresh_indicator(self):
        n = len(self._sub_rows)
        cl = getattr(self, '_custom_list', None)
        if cl is not None:
            enabled = sum(1 for r in cl if r['enabled'])
            self._mode_label.setText(
                f"✎ Custom list — {len(cl)} pts, {enabled} enabled")
            self._mode_label.setStyleSheet(
                "font-size:9px; padding:2px 6px; border-radius:3px;"
                " background:#1a2a3a; color:#70d0ff; border:1px solid #2a5a7a;"
            )
            tip = "Custom list active — click '✎ Edit List' to modify"
            for w in (self.start_e, self.stop_e, self.n_e, self.sp_box):
                w.setEnabled(False)
                w.setToolTip(tip)
        elif n == 0:
            self._mode_label.setText("● Using global range")
            self._mode_label.setStyleSheet(
                "font-size:9px; padding:2px 6px; border-radius:3px;"
                " background:#1a3a1a; color:#6fcf6f; border:1px solid #3a6a3a;"
            )
            # re-enable global row fields
            for w in (self.start_e, self.stop_e, self.n_e, self.sp_box):
                w.setEnabled(True)
                w.setToolTip("")
        else:
            self._mode_label.setText(f"● Using {n} sub-range{'s' if n > 1 else ''} — global range ignored")
            self._mode_label.setStyleSheet(
                "font-size:9px; padding:2px 6px; border-radius:3px;"
                " background:#3a2a00; color:#ffcc44; border:1px solid #7a6000;"
            )
            # grey-out global row fields
            tip = "Overridden by sub-ranges — remove all sub-ranges to use this"
            for w in (self.start_e, self.stop_e, self.n_e, self.sp_box):
                w.setEnabled(False)
                w.setToolTip(tip)
        # Enable "Last" button whenever a last-used list is saved
        if hasattr(self, '_last_btn'):
            self._last_btn.setEnabled(
                getattr(self, '_last_used_list', None) is not None)

    # ── Private ────────────────────────────────────────────────────────────────

    def _load_last_used(self):
        """Load the last-used measurement list as the active custom list."""
        ll = getattr(self, '_last_used_list', None)
        if not ll:
            return
        self._custom_list = [dict(r) for r in ll]  # shallow copy
        self._refresh_indicator()
        if self._edit_dialog is not None and self._edit_dialog.isVisible():
            self._edit_dialog.load_fresh()

    def get_values(self):
        """Generic alias for get_frequencies() — use when widget is not Hz-based."""
        return self.get_frequencies()

    def _open_edit_dialog(self):
        """Open (or raise) the EditableListDialog for this widget."""
        if self._edit_dialog is None:
            self._edit_dialog = EditableListDialog(self, self.window())
        self._edit_dialog.load_fresh()  # always refresh on open
        self._edit_dialog.show()
        self._edit_dialog.raise_()
        self._edit_dialog.activateWindow()

    def _add_sub_range(self, config=None):
        row = _SubRangeRow(show_wait=self._show_wait, parent=self._sub_container)
        if isinstance(config, dict):
            row.set_config(config)
        row.removed.connect(self._remove_sub_range)
        self._sub_rows.append(row)
        self._sub_layout.addWidget(row)
        row.show()
        self._refresh_indicator()

    def _remove_sub_range(self, row):
        if row in self._sub_rows:
            self._sub_rows.remove(row)
        self._sub_layout.removeWidget(row)
        row.deleteLater()
        self._refresh_indicator()

    def _show_list(self):
        try:
            freqs = self.get_frequencies()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return
        dlg = FrequencyListDialog(freqs, self, unit=self._unit)
        dlg.exec()


class IVLivePlotWindow(QWidget):
    """Live plot window for IV measurement: V₃ω vs Time.
    Parented to IVDialog (same modal group) so it stays movable and in front
    while the modal exec() loop is running. Qt.Window flag gives it its own
    title bar and taskbar entry so it can be freely moved/closed independently.
    White lines = wait phase, colored = averaging phase.
    """
    def __init__(self, iv_dialog, main_win):
        # Parent = iv_dialog keeps us inside the modal group (critical on Windows)
        # Qt.Window gives us an independent title bar and movability
        super().__init__(iv_dialog)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowTitle("IV Live Plot — V₃ω vs Time")
        self.resize(900, 580)
        self._main_win = main_win

        layout = QVBoxLayout(self)

        self.fig = Figure(figsize=(9, 5), dpi=100)
        self.ax  = self.fig.add_subplot(111)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("V₃ω (V)")
        self.fig.suptitle("V₃ω vs Time (all voltage steps)")

        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Hidden toolbar drives zoom/home — canvas sits directly in layout
        # so mouse events reach it properly
        self._toolbar = NavigationToolbar(self.canvas, self)
        self._toolbar.hide()

        layout.addWidget(self.canvas)

        # Simple control row — same style as the main window zoom button
        ctrl = QHBoxLayout()
        self._zoom_btn = QPushButton("🔍 Zoom")
        self._zoom_btn.setCheckable(True)
        self._zoom_btn.setToolTip(
            "Enable: click and drag on the plot to zoom in.\n"
            "Click again to disable and restore full view."
        )
        self._zoom_btn.setStyleSheet(
            "QPushButton { background:#2b2b3d; color:white; border:1px solid #555577;"
            "  padding:3px 12px; border-radius:4px; }"
            "QPushButton:checked { background:#3a86ff; color:white; }"
        )
        self._zoom_btn.toggled.connect(self._toggle_zoom)

        reset_btn = QPushButton("🏠 Reset View")
        reset_btn.setStyleSheet(
            "QPushButton { background:#2b2b3d; color:white; border:1px solid #555577;"
            "  padding:3px 12px; border-radius:4px; }"
            "QPushButton:hover { background:#3d3d5c; }"
        )
        reset_btn.clicked.connect(self._reset_view)

        self._force_avg_btn = QPushButton("▶ Start Average")
        self._force_avg_btn.setEnabled(False)
        self._force_avg_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._force_avg_btn.setToolTip(
            "Skip remaining wait time and start averaging immediately for the current voltage step.")
        self._force_avg_btn.setStyleSheet(
            "QPushButton { background:#e8a020; color:black; font-weight:bold;"
            "  padding:4px 12px; border-radius:4px; border:1px solid #c07010; }"
            "QPushButton:hover { background:#f0b030; }"
            "QPushButton:disabled { background:#555; color:#999; border-color:#444; }"
        )
        self._force_avg_btn.clicked.connect(self._force_averaging_now)

        ctrl.addStretch(1)
        ctrl.addWidget(reset_btn)
        ctrl.addWidget(self._zoom_btn)
        ctrl.addWidget(self._force_avg_btn)
        layout.addLayout(ctrl)

        self._wait_lines   = {}
        self._avg_lines    = {}
        self._last_v_start = -1

        main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
        self.canvas.draw()

    def _toggle_zoom(self, checked):
        if checked:
            if self._toolbar.mode.name != 'ZOOM':
                self._toolbar.zoom()
        else:
            if self._toolbar.mode.name == 'ZOOM':
                self._toolbar.zoom()
            self._toolbar.home()

    def _reset_view(self):
        if self._zoom_btn.isChecked():
            self._zoom_btn.setChecked(False)  # triggers _toggle_zoom → home
        else:
            self._toolbar.home()

    def _force_averaging_now(self):
        try:
            self._main_win.core.force_averaging = True
            self._main_win.set_status("Force averaging requested — will start averaging at next poll.")
        except Exception:
            self._main_win.set_status("Force averaging: no measurement running.")

    def set_measuring(self, active):
        self._force_avg_btn.setEnabled(active)

    def reset(self):
        self.ax.clear()
        for leg in self.fig.legends[:]:
            leg.remove()
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("V₃ω (V)")
        self.fig.suptitle("V₃ω vs Time (all voltage steps)")
        self._wait_lines.clear()
        self._avg_lines.clear()
        self._last_v_start = -1
        if self._zoom_btn.isChecked():
            self._zoom_btn.setChecked(False)
        self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
        self.canvas.draw()

    def update_live(self, t_data, v3w_data, v_start_idx, wait_n, label):
        try:
            if v_start_idx != self._last_v_start:
                self._last_v_start = v_start_idx
                lw, = self.ax.plot([], [], color='white', alpha=1.0)
                la, = self.ax.plot([], [], label=label)
                self._wait_lines[label] = lw
                self._avg_lines[label]  = la

            wl = self._wait_lines.get(label)
            al = self._avg_lines.get(label)

            if wl:
                if wait_n is None:
                    wl.set_data(t_data[v_start_idx:], v3w_data[v_start_idx:])
                else:
                    wl.set_data(t_data[v_start_idx:wait_n], v3w_data[v_start_idx:wait_n])
                    if al:
                        al.set_data(t_data[wait_n:], v3w_data[wait_n:])

            if not self._zoom_btn.isChecked():
                self.ax.relim()
                self.ax.autoscale_view()

            if wait_n is not None:
                for leg in self.fig.legends[:]:
                    leg.remove()
                handles, labels_leg = self.ax.get_legend_handles_labels()
                if handles:
                    _ncol = max(1, -(-len(handles) // 3))
                    self.fig.legend(handles, labels_leg,
                                    loc='upper right',
                                    bbox_to_anchor=(0.99, 1.005),
                                    fontsize=6, ncol=_ncol,
                                    framealpha=0.8, borderpad=0.3,
                                    handlelength=1.0, handletextpad=0.4,
                                    labelspacing=0.2)

            # Only render when visible — data is always updated in the background
            if self.isVisible():
                # Throttle: re-styling the whole figure is real CPU work that
                # doesn't need doing every ~0.2s poll tick — once a second is
                # visually indistinguishable.
                import time as _time
                _now = _time.monotonic()
                if not hasattr(self, '_last_iv_style_draw') or _now - self._last_iv_style_draw >= 1.0:
                    self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
                    self._last_iv_style_draw = _now
                self.canvas.draw()
                QApplication.processEvents()
        except Exception:
            pass


class PhaseCalibrationWindow(QWidget):
    """1ω phase calibration window.
    Measures R and θ at 1ω, waits for stability, averages, then writes PHAS to SR830.
    White lines = wait phase, cyan = averaging phase.
    """
    _CALIB_COLOR = '#00c6a7'

    def __init__(self, main_win):
        super().__init__(main_win)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowTitle("1ω Phase Calibration")
        self.resize(860, 920)
        self._main_win = main_win

        # Crash-safety: periodically re-write the same backup file pair
        # while calibration is running (see _silent_backup's suffix=).
        self._calib_autosave_timer = QTimer(self)
        self._calib_autosave_timer.setInterval(60_000)  # 60 s
        self._calib_autosave_timer.timeout.connect(self._periodic_autosave_calibration)

        layout = QVBoxLayout(self)

        # ── Input row ────────────────────────────────────────────────────────
        inp_row = QHBoxLayout()
        inp_row.addWidget(QLabel("Frequency (Hz):"))
        self.freq_entry = QLineEdit("5.0")
        self.freq_entry.setFixedWidth(70)
        inp_row.addWidget(self.freq_entry)
        inp_row.addSpacing(16)
        inp_row.addWidget(QLabel("Wait time (s):"))
        self.wait_entry = QLineEdit("300")
        self.wait_entry.setFixedWidth(70)
        inp_row.addWidget(self.wait_entry)
        inp_row.addSpacing(16)
        inp_row.addWidget(QLabel("Average time (s):"))
        self.avg_entry = QLineEdit("60")
        self.avg_entry.setFixedWidth(70)
        inp_row.addWidget(self.avg_entry)
        inp_row.addStretch(1)
        layout.addLayout(inp_row)

        # ── Activity LEDs ─────────────────────────────────────────────────────
        _led_row = QHBoxLayout()
        _LED_OFF = "background:#444; border-radius:7px; min-width:14px; max-width:14px; min-height:14px; max-height:14px;"
        _LED_ON  = "background:#3be362; border-radius:7px; min-width:14px; max-width:14px; min-height:14px; max-height:14px; border:1px solid #1a9e40;"
        self._led_1w = QLabel(); self._led_1w.setStyleSheet(_LED_OFF)
        self._led_3w = QLabel(); self._led_3w.setStyleSheet(_LED_OFF)
        self._LED_OFF_SS = _LED_OFF; self._LED_ON_SS = _LED_ON
        _led_row.addWidget(self._led_1w)
        _led_row.addWidget(QLabel("1ω Calibration"))
        _led_row.addSpacing(24)
        _led_row.addWidget(self._led_3w)
        _led_row.addWidget(QLabel("3ω Measurement"))
        _led_row.addStretch(1)
        layout.addLayout(_led_row)

        # ── Plot ─────────────────────────────────────────────────────────────
        self.fig = Figure(figsize=(8, 8), dpi=100)
        # Top→bottom: V₁ω (time), θ (time), I_AC (time), R₁ω (frequency)
        self.ax_r, self.ax_theta, self.ax_i, self.ax_res = self.fig.subplots(4, 1, sharex=False)
        self.ax_r.set_ylabel(r"$V_{1\omega}$ (V)")
        self.ax_theta.set_ylabel(r"$\theta$ (°)")
        self.ax_i.set_ylabel(r"$I_{AC}$")
        self.ax_i.set_xlabel("Time (s)")
        self.ax_res.set_ylabel(r"$R_{1\omega}$ (Ω)")
        self.ax_res.set_xlabel("Frequency (Hz)")
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._toolbar = NavigationToolbar(self.canvas, self)
        self._toolbar.hide()
        layout.addWidget(self.canvas)

        # ── Zoom / Reset ─────────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        self._zoom_btn = QPushButton("\U0001f50d Zoom")
        self._zoom_btn.setCheckable(True)
        self._zoom_btn.setStyleSheet(
            "QPushButton { background:#2b2b3d; color:white; border:1px solid #555577;"
            "  padding:3px 12px; border-radius:4px; }"
            "QPushButton:checked { background:#3a86ff; color:white; }"
        )
        self._zoom_btn.toggled.connect(self._toggle_zoom)
        reset_btn = QPushButton("\U0001f3e0 Reset View")
        reset_btn.setStyleSheet(
            "QPushButton { background:#2b2b3d; color:white; border:1px solid #555577;"
            "  padding:3px 12px; border-radius:4px; }"
            "QPushButton:hover { background:#3d3d5c; }"
        )
        reset_btn.clicked.connect(self._reset_view)
        ctrl.addStretch(1)
        ctrl.addWidget(reset_btn)
        ctrl.addWidget(self._zoom_btn)
        layout.addLayout(ctrl)

        # ── Force averaging ───────────────────────────────────────────────────
        self._force_avg_btn = QPushButton("▶ Start Average")
        self._force_avg_btn.setEnabled(False)
        self._force_avg_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._force_avg_btn.setToolTip(
            "Skip remaining wait time and start averaging immediately.")
        self._force_avg_btn.setStyleSheet(
            "QPushButton { background:#e8a020; color:black; font-weight:bold;"
            "  padding:4px 12px; border-radius:4px; border:1px solid #c07010; }"
            "QPushButton:hover { background:#f0b030; }"
            "QPushButton:disabled { background:#555; color:#999; border-color:#444; }"
        )
        self._force_avg_btn.clicked.connect(self._force_averaging_now)

        self._skip_cur_btn = QPushButton("⏩ Skip Current")
        self._skip_cur_btn.setEnabled(False)
        self._skip_cur_btn.setToolTip(
            "Abort this frequency's 1ω calibration now and proceed to 3ω.\n"
            "Last measured PHAS is kept.")
        self._skip_cur_btn.setStyleSheet(
            "QPushButton { background:#7a4000; color:white; font-weight:bold;"
            "  padding:4px 12px; border-radius:4px; border:1px solid #a05000; }"
            "QPushButton:hover { background:#a05800; }"
            "QPushButton:disabled { background:#555; color:#999; border-color:#444; }")
        self._skip_cur_btn.clicked.connect(self._skip_current_now)

        self._skip_next_btn = QPushButton("⏭ Skip Next Freq")
        self._skip_next_btn.setEnabled(False)
        self._skip_next_btn.setToolTip(
            "Add the next frequency to the skip list so its 1ω calibration is skipped.")
        self._skip_next_btn.setStyleSheet(
            "QPushButton { background:#4a3080; color:white; font-weight:bold;"
            "  padding:4px 12px; border-radius:4px; border:1px solid #6040a0; }"
            "QPushButton:hover { background:#5a40a0; }"
            "QPushButton:disabled { background:#555; color:#999; border-color:#444; }")
        self._skip_next_btn.clicked.connect(self._skip_next_freq)

        _fa_row = QHBoxLayout()
        _fa_row.addWidget(self._force_avg_btn)
        _fa_row.addSpacing(12)
        _fa_row.addWidget(self._skip_cur_btn)
        _fa_row.addWidget(self._skip_next_btn)
        _fa_row.addStretch(1)
        layout.addLayout(_fa_row)

        # ── Start / Stop ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Calibration")
        self.start_btn.setStyleSheet(
            "background:#3be362; color:black; font-weight:bold; padding:5px;")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet(
            "background:#e35f3b; color:white; font-weight:bold; padding:5px;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        # ── Status ───────────────────────────────────────────────────────────
        self._status_lbl = QLabel(
            "Ready — enter parameters and click Start Calibration")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(
            "color:#ffdd57; font-weight:bold; padding:4px;")
        layout.addWidget(self._status_lbl)

        # ── Proceed / Repeat (hidden until calibration completes) ────────────
        self._action_widget = QWidget()
        action_row = QHBoxLayout(self._action_widget)
        self._proceed_btn = QPushButton("Proceed to 3ω Measurement  ✓")
        self._proceed_btn.setStyleSheet(
            "background:#3a86ff; color:white; font-weight:bold;"
            " padding:6px; border-radius:5px;")
        self._proceed_btn.clicked.connect(self._proceed)
        self._repeat_btn = QPushButton("Repeat Calibration  ↺")
        self._repeat_btn.setStyleSheet(
            "background:#6c4f9e; color:white; font-weight:bold;"
            " padding:6px; border-radius:5px;")
        self._repeat_btn.clicked.connect(self._repeat)
        action_row.addWidget(self._proceed_btn)
        action_row.addWidget(self._repeat_btn)
        self._action_widget.hide()
        layout.addWidget(self._action_widget)

        # ── Save Data — explicit save to the main window's chosen folder,
        # separate from the automatic Backup_data crash-safety copy. Shown
        # whenever there's calibration data to save, whether the run
        # completed, was stopped, or failed partway through.
        self._save_calib_btn = QPushButton("💾 Save Data")
        self._save_calib_btn.setStyleSheet(
            "background:#2d6a2d; color:white; font-weight:bold;"
            " padding:6px; border-radius:5px;")
        self._save_calib_btn.clicked.connect(self._save_calibration_data)
        self._save_calib_btn.hide()
        layout.addWidget(self._save_calib_btn)

        # Line objects for live update (manual mode)
        self._r_wait_line   = None
        self._r_avg_line    = None
        self._th_wait_line  = None
        self._th_avg_line   = None
        self._res_wait_line = None
        self._res_avg_line  = None
        self._i_wait_line   = None
        self._i_avg_line    = None

        # ── Auto 1ω mode state ───────────────────────────────────────────────
        self._auto_mode        = False
        self._auto_color_cycle = [
            '#3be362','#818cf8','#ff9f43','#ff6b6b','#4a9eff',
            '#a55eea','#26de81','#fd9644','#45aaf2','#fc5c65',
            '#ffdd59','#00b894','#e17055','#74b9ff','#fd79a8',
        ]
        self._auto_color_idx   = 0
        self._auto_t_offset    = 0.0   # cumulative time offset for continuous x-axis
        self._auto_last_t_max  = 0.0
        self._auto_cur_freq    = None
        self._auto_wait_lines  = {}    # freq → (r_w, th_w, i_w)
        self._auto_avg_lines   = {}    # freq → (r_a, th_a, i_a)
        self._auto_freq_xs     = []    # x (Hz) for R₁ω vs freq plot
        self._auto_freq_ys     = []    # y (Ω)
        self._auto_freq_ths    = []    # theta (°)
        self._auto_scatter     = None
        self._ax_res_twin      = None  # twin y-axis for theta on the freq plot
        self._auto_status_txt  = None
        self._auto_freq_queue  = []   # full list of freqs in this run
        self._auto_cur_idx     = -1   # index of currently calibrating freq

        main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
        self.canvas.draw()

        # ── Last-measurement results bar ──────────────────────────────────────
        self._results_bar = QLabel("—")
        self._results_bar.setAlignment(Qt.AlignCenter)
        self._results_bar.setWordWrap(False)
        self._results_bar.setStyleSheet(
            "color:#a0d0ff; font-family:monospace; font-size:11px;"
            " background:#1a1a2e; border:1px solid #333355;"
            " border-radius:4px; padding:3px 8px;")
        layout.addWidget(self._results_bar)

        self._load_calib_settings()

    def _load_calib_settings(self):
        try:
            s = load_settings()
            if "calib_freq"      in s: self.freq_entry.setText(str(s["calib_freq"]))
            if "calib_wait_time" in s: self.wait_entry.setText(str(s["calib_wait_time"]))
            if "calib_avg_time"  in s: self.avg_entry.setText(str(s["calib_avg_time"]))
        except Exception:
            pass

    def _save_calib_settings(self):
        try:
            s = load_settings()
            s["calib_freq"]      = self.freq_entry.text()
            s["calib_wait_time"] = self.wait_entry.text()
            s["calib_avg_time"]  = self.avg_entry.text()
            save_settings(s)
        except Exception:
            pass

    def _toggle_zoom(self, checked):
        if checked:
            if self._toolbar.mode.name != 'ZOOM':
                self._toolbar.zoom()
        else:
            if self._toolbar.mode.name == 'ZOOM':
                self._toolbar.zoom()
            self._toolbar.home()

    def _reset_view(self):
        if self._zoom_btn.isChecked():
            self._zoom_btn.setChecked(False)
        else:
            self._toolbar.home()

    def reset(self):
        # Clear only time-series axes; ax_res keeps accumulated freq points
        for ax in (self.ax_r, self.ax_theta, self.ax_i):
            ax.clear()
        self.ax_r.set_ylabel(r"$V_{1\omega}$ (V)")
        self.ax_theta.set_ylabel(r"$\theta$ (°)")
        self.ax_i.set_ylabel(r"$I_{AC}$")
        self.ax_i.set_xlabel("Time (s)")
        self._r_wait_line = self._r_avg_line = None
        self._th_wait_line = self._th_avg_line = None
        self._i_wait_line = self._i_avg_line = None
        if self._zoom_btn.isChecked():
            self._zoom_btn.setChecked(False)
        self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
        self.canvas.draw()

    def update_live(self, t_data, r_data, theta_data, wait_n, i_data=None):
        try:
            if self._r_wait_line is None:
                self._r_wait_line,   = self.ax_r.plot([], [], color='white', alpha=1.0)
                self._r_avg_line,    = self.ax_r.plot([], [], color=self._CALIB_COLOR)
                self._th_wait_line,  = self.ax_theta.plot([], [], color='white', alpha=1.0)
                self._th_avg_line,   = self.ax_theta.plot([], [], color=self._CALIB_COLOR)
                self._i_wait_line,   = self.ax_i.plot([], [], color='white', alpha=1.0)
                self._i_avg_line,    = self.ax_i.plot([], [], color=self._CALIB_COLOR)

            # Auto-scale current unit based on peak magnitude
            peak = max(abs(v) for v in i_data) if i_data else 0
            if peak >= 0.5e-3:
                _i_scale, _i_unit = 1e3,  "mA"
            elif peak >= 0.5e-6:
                _i_scale, _i_unit = 1e6,  "µA"
            else:
                _i_scale, _i_unit = 1e9,  "nA"
            self.ax_i.set_ylabel(fr"$I_{{AC}}$ ({_i_unit})")
            i_scaled = [v * _i_scale for v in i_data] if i_data else []

            if wait_n is None:
                self._r_wait_line.set_data(t_data, r_data)
                self._th_wait_line.set_data(t_data, theta_data)
                self._i_wait_line.set_data(t_data, i_scaled)
            else:
                self._r_wait_line.set_data(t_data[:wait_n], r_data[:wait_n])
                self._r_avg_line.set_data(t_data[wait_n:], r_data[wait_n:])
                self._th_wait_line.set_data(t_data[:wait_n], theta_data[:wait_n])
                self._th_avg_line.set_data(t_data[wait_n:], theta_data[wait_n:])
                self._i_wait_line.set_data(t_data[:wait_n], i_scaled[:wait_n])
                self._i_avg_line.set_data(t_data[wait_n:], i_scaled[wait_n:])

            if not self._zoom_btn.isChecked():
                for ax in (self.ax_r, self.ax_theta, self.ax_i):
                    ax.relim()
                    ax.autoscale_view()

            if self.isVisible():
                # Throttle: re-styling the whole figure is real CPU work that
                # doesn't need doing every ~0.2s poll tick — once a second is
                # visually indistinguishable.
                import time as _time
                _now = _time.monotonic()
                if not hasattr(self, '_last_manual_style_draw') or _now - self._last_manual_style_draw >= 1.0:
                    self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
                    self._last_manual_style_draw = _now
                self.canvas.draw()
                QApplication.processEvents()
        except Exception:
            pass

    def add_freq_point(self, freq, r1w):
        """Add one (freq, R1w) point to the bottom frequency plot after manual calibration."""
        try:
            if not hasattr(self, '_manual_freq_xs'):
                self._manual_freq_xs = []
                self._manual_freq_ys = []
            if r1w is None or r1w != r1w:
                return
            self._manual_freq_xs.append(freq)
            self._manual_freq_ys.append(r1w)
            _peak = max(abs(v) for v in self._manual_freq_ys)
            if _peak >= 1e6:
                _r_scale, _r_unit = 1e-6, "MΩ"
            elif _peak >= 1e3:
                _r_scale, _r_unit = 1e-3, "kΩ"
            elif _peak >= 1.0:
                _r_scale, _r_unit = 1.0,  "Ω"
            elif _peak >= 1e-3:
                _r_scale, _r_unit = 1e3,  "mΩ"
            else:
                _r_scale, _r_unit = 1e6,  "µΩ"
            _r_scaled = [v * _r_scale for v in self._manual_freq_ys]
            # Save the current view before cla() wipes it — cla() plus the
            # replot below auto-scales the view regardless of the zoom guard
            # further down, so restoring the saved limits explicitly is the
            # only way to actually keep a zoom.
            _res_zoomed = self._zoom_btn.isChecked()
            _res_xlim = self.ax_res.get_xlim() if _res_zoomed else None
            _res_ylim = self.ax_res.get_ylim() if _res_zoomed else None
            self.ax_res.cla()
            self.ax_res.set_ylabel(f"$R_{{1\\omega}}$ ({_r_unit})")
            self.ax_res.set_xlabel("Frequency (Hz)")
            self.ax_res.scatter(self._manual_freq_xs, _r_scaled,
                                color='#ff9f43', s=60, zorder=3)
            if not _res_zoomed:
                self.ax_res.relim()
                self.ax_res.autoscale_view()
            else:
                if _res_xlim is not None:
                    self.ax_res.set_xlim(_res_xlim)
                if _res_ylim is not None:
                    self.ax_res.set_ylim(_res_ylim)
            self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
            self.canvas.draw()
        except Exception:
            pass

    # ── Auto 1ω mode ──────────────────────────────────────────────────────────

    def enter_auto_mode(self):
        """Switch to auto-1ω layout: ax_res becomes R₁ω vs frequency."""
        self._auto_mode       = True
        self._auto_color_idx  = 0
        self._auto_t_offset   = 0.0
        self._auto_last_t_max = 0.0
        self._auto_cur_freq   = None
        self._auto_wait_lines = {}
        self._auto_avg_lines  = {}
        self._auto_freq_xs    = []
        self._auto_freq_ys    = []
        self._auto_freq_ths   = []
        self._auto_scatter    = None
        self._ax_res_twin     = None
        self._auto_status_txt = None
        self._auto_freq_queue = []
        self._auto_cur_idx    = -1
        for ax in (self.ax_r, self.ax_theta, self.ax_res, self.ax_i):
            ax.cla()
        self.ax_r.set_ylabel(r"$V_{1\omega}$ (V)")
        self.ax_theta.set_ylabel(r"$\theta$ (°)")
        self.ax_i.set_ylabel(r"$I_{AC}$")
        self.ax_i.set_xlabel("Time (s)")
        self.ax_res.set_ylabel(r"$R_{1\omega}$ (Ω)")
        self.ax_res.set_xlabel("Frequency (Hz)")
        self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
        self._skip_cur_btn.setEnabled(True)
        self._skip_next_btn.setEnabled(False)  # enabled after first freq arrives
        self._force_avg_btn.setEnabled(True)
        self.canvas.draw()
        self.show()
        self.raise_()

    def exit_auto_mode(self):
        """Restore manual 1ω layout (leave accumulated plots visible)."""
        self._set_led('1w', False); self._set_led('3w', False)
        self._skip_cur_btn.setEnabled(False)
        self._skip_next_btn.setEnabled(False)
        self._force_avg_btn.setEnabled(False)
        self._auto_mode = False
        self._auto_status_txt = None
        self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
        self.canvas.draw()

    def handle_auto_update(self, phase, args):
        """Process auto-1ω signals from the measurement thread."""
        try:
            if phase == '1w_auto_start':
                # New frequency's 1ω calibration starting
                f = args[0]
                if f not in self._auto_freq_queue:
                    self._auto_freq_queue.append(f)
                self._auto_cur_idx = self._auto_freq_queue.index(f)
                self._auto_cur_freq = f
                # Enable skip-next only once we know there could be a next frequency
                self._skip_next_btn.setEnabled(True)

                # Skipped frequencies never get a '1w_auto_time'/'1w_auto_done'
                # update — creating line objects/a legend entry for them here
                # would just leave an empty, unused legend row for the rest
                # of the run. Still track queue/index bookkeeping above (the
                # skip dialog needs it), just skip the plot artifacts.
                if round(f, 9) in self._main_win._1w_skip_freqs:
                    return

                self._set_led('1w', True); self._set_led('3w', False)
                color = self._auto_color_cycle[self._auto_color_idx % len(self._auto_color_cycle)]
                self._auto_color_idx += 1
                label = f"{f:.4g} Hz"

                # Remove status overlay if present
                if self._auto_status_txt is not None:
                    try:
                        self._auto_status_txt.remove()
                    except Exception:
                        pass
                    self._auto_status_txt = None

                # Create new line pairs for this frequency (wait=white, avg=color)
                rw,  = self.ax_r.plot([], [], color='white', alpha=1.0)
                thw, = self.ax_theta.plot([], [], color='white', alpha=1.0)
                iw,  = self.ax_i.plot([], [], color='white', alpha=1.0)
                self._auto_wait_lines[f] = (rw, thw, iw)

                ra,  = self.ax_r.plot([], [], color=color, label=label)
                tha, = self.ax_theta.plot([], [], color=color, label=label)
                ia,  = self.ax_i.plot([], [], color=color, label=label)
                self._auto_avg_lines[f] = (ra, tha, ia)

                # Update title to show current frequency

                self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
                self.canvas.draw_idle()

            elif phase == '1w_auto_time':
                # Live time-series update during 1ω calibration at current frequency
                f, t_data, r_data, theta_data, wait_n, i_data = args
                if f not in self._auto_wait_lines:
                    return

                # Compute display time = local t + cumulative offset
                t_disp = [t + self._auto_t_offset for t in t_data]
                if t_disp:
                    self._auto_last_t_max = t_disp[-1]

                # Auto-scale current
                peak = max(abs(v) for v in i_data) if i_data else 0
                if peak >= 0.5e-3:
                    _i_scale, _i_unit = 1e3,  "mA"
                elif peak >= 0.5e-6:
                    _i_scale, _i_unit = 1e6,  "µA"
                else:
                    _i_scale, _i_unit = 1e9,  "nA"
                self.ax_i.set_ylabel(fr"$I_{{AC}}$ ({_i_unit})")
                i_sc = [v * _i_scale for v in i_data] if i_data else []

                wl = self._auto_wait_lines[f]
                al = self._auto_avg_lines[f]
                if wait_n is None:
                    wl[0].set_data(t_disp, r_data)
                    wl[1].set_data(t_disp, theta_data)
                    wl[2].set_data(t_disp, i_sc)
                else:
                    wl[0].set_data(t_disp[:wait_n], r_data[:wait_n])
                    wl[1].set_data(t_disp[:wait_n], theta_data[:wait_n])
                    wl[2].set_data(t_disp[:wait_n], i_sc[:wait_n])
                    al[0].set_data(t_disp[wait_n:], r_data[wait_n:])
                    al[1].set_data(t_disp[wait_n:], theta_data[wait_n:])
                    al[2].set_data(t_disp[wait_n:], i_sc[wait_n:])

                if not self._zoom_btn.isChecked():
                    for ax in (self.ax_r, self.ax_theta, self.ax_i):
                        ax.relim(); ax.autoscale_view()

                # Throttle: re-styling the whole figure is real CPU work that
                # doesn't need doing every ~0.2s poll tick — once a second is
                # visually indistinguishable and matches the main window's
                # own time-plot throttling.
                if self.isVisible():
                    import time as _time
                    _now = _time.monotonic()
                    if not hasattr(self, '_last_time_style_draw') or _now - self._last_time_style_draw >= 1.0:
                        self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
                        self._last_time_style_draw = _now
                    self.canvas.draw_idle()

            elif phase == '1w_auto_done':
                # Frequency completed — add point to R₁ω and θ vs freq plots
                f, _avg_r_v, _avg_i_v, avg_res, avg_th = args
                self._set_led('1w', False)
                self._set_results_bar(f, _avg_r_v, avg_res, avg_th)
                # Advance time offset for next frequency (gap = 5 s)
                self._auto_t_offset = self._auto_last_t_max + 5.0

                if not (avg_res != avg_res):  # skip NaN R
                    self._auto_freq_xs.append(f)
                    self._auto_freq_ys.append(avg_res)
                    self._auto_freq_ths.append(avg_th)

                # Save the current view before cla() wipes it — cla() plus the
                # replot below auto-scales the view regardless of the zoom
                # guard further down, so the only way to actually keep a zoom
                # is to restore the saved limits explicitly afterward.
                _res_zoomed = self._zoom_btn.isChecked()
                _res_xlim = self.ax_res.get_xlim() if _res_zoomed else None
                _res_ylim = self.ax_res.get_ylim() if _res_zoomed else None
                _res_twin_ylim = (self._ax_res_twin.get_ylim()
                                  if _res_zoomed and self._ax_res_twin is not None else None)

                # Remove old twin axis and redraw both series
                if self._ax_res_twin is not None:
                    try:
                        self._ax_res_twin.remove()
                    except Exception:
                        pass
                    self._ax_res_twin = None

                self.ax_res.cla()
                self.ax_res.set_xlabel("Frequency (Hz)")

                if self._auto_freq_xs:
                    # Auto-scale R1w to best unit
                    _peak_r = max(abs(v) for v in self._auto_freq_ys)
                    if _peak_r >= 1e6:
                        _r_scale, _r_unit = 1e-6, "MΩ"
                    elif _peak_r >= 1e3:
                        _r_scale, _r_unit = 1e-3, "kΩ"
                    elif _peak_r >= 1.0:
                        _r_scale, _r_unit = 1.0,  "Ω"
                    elif _peak_r >= 1e-3:
                        _r_scale, _r_unit = 1e3,  "mΩ"
                    else:
                        _r_scale, _r_unit = 1e6,  "µΩ"
                    _r_scaled = [v * _r_scale for v in self._auto_freq_ys]

                    self.ax_res.set_ylabel(f"$R_{{1\\omega}}$ ({_r_unit})", color='#4a9eff')
                    self.ax_res.tick_params(axis='y', colors='#4a9eff', labelcolor='#4a9eff')
                    self.ax_res.plot(self._auto_freq_xs, _r_scaled,
                                     'o-', color='#4a9eff', linewidth=1.5,
                                     markersize=6, label=f"$R_{{1\\omega}}$")

                    self._ax_res_twin = self.ax_res.twinx()
                    self._ax_res_twin.set_ylabel(r"$\theta$ (°)", color='#ff9f43')
                    self._ax_res_twin.tick_params(axis='y', colors='#ff9f43',
                                                  labelcolor='#ff9f43')
                    self._ax_res_twin.spines['right'].set_edgecolor('#ff9f43')
                    self._ax_res_twin.set_facecolor('#2b2b3d')
                    self._ax_res_twin.plot(self._auto_freq_xs, self._auto_freq_ths,
                                           's--', color='#ff9f43', linewidth=1.5,
                                           markersize=6, label=r"$\theta$")

                    lines1, labels1 = self.ax_res.get_legend_handles_labels()
                    lines2, labels2 = self._ax_res_twin.get_legend_handles_labels()
                    self.ax_res.legend(lines1 + lines2, labels1 + labels2,
                                       loc='best', fontsize=9)
                else:
                    self.ax_res.set_ylabel(r"$R_{1\omega}$ (Ω)", color='#4a9eff')
                    self.ax_res.tick_params(axis='y', colors='#4a9eff', labelcolor='#4a9eff')

                if not _res_zoomed:
                    self.ax_res.relim(); self.ax_res.autoscale_view()
                    if self._ax_res_twin:
                        self._ax_res_twin.relim(); self._ax_res_twin.autoscale_view()
                else:
                    if _res_xlim is not None:
                        self.ax_res.set_xlim(_res_xlim)
                    if _res_ylim is not None:
                        self.ax_res.set_ylim(_res_ylim)
                    if self._ax_res_twin is not None and _res_twin_ylim is not None:
                        self._ax_res_twin.set_ylim(_res_twin_ylim)
                if self.isVisible():
                    self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
                    if self._ax_res_twin:
                        self._ax_res_twin.yaxis.label.set_color('#ff9f43')
                        self._ax_res_twin.yaxis.label.set_fontsize(12)
                        for tl in self._ax_res_twin.get_yticklabels():
                            tl.set_color('#ff9f43')
                            tl.set_fontsize(11)
                    self.canvas.draw_idle()

            elif phase == '1w_auto_3w':
                self._set_led('3w', True); self._set_led('1w', False)
                # 3ω measurement running — show status overlay
                f = args[0]

                # Add text overlay on the time-series area
                if self._auto_status_txt is None:
                    self._auto_status_txt = self.ax_r.text(
                        0.5, 0.5, "3ω measurement\nin progress",
                        transform=self.ax_r.transAxes,
                        ha='center', va='center',
                        fontsize=14, color='#ffaa00', alpha=0.8,
                        bbox=dict(boxstyle='round,pad=0.4', facecolor='#1e1e2f', edgecolor='#ffaa00')
                    )
                if self.isVisible():
                    self._main_win._apply_embedded_style_to_fig(self.fig, hspace=0.65)
                    self.canvas.draw_idle()

        except Exception:
            pass

    def _start(self):
        if not self._main_win.instruments_connected:
            QMessageBox.warning(self, "Not Connected",
                                "Connect instruments before calibrating.")
            return
        if not self._main_win._ensure_float_before_measurement():
            return

        try:
            freq      = float(self.freq_entry.text())
            wait_time = float(self.wait_entry.text())
            avg_time  = float(self.avg_entry.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid parameter values.")
            return
        # Auto average time override
        _auto_at = self._main_win._calc_auto_avg_time(freq)
        if _auto_at is not None:
            avg_time = _auto_at

        self._save_calib_settings()

        try:
            params = self._main_win.read_parameters()
        except Exception as exc:
            QMessageBox.critical(self, "Parameter Error", str(exc))
            return

        self.reset()
        self._action_widget.hide()
        self._save_calib_btn.hide()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._force_avg_btn.setEnabled(True)
        self._set_led('1w', True)
        self._status_lbl.setText("Waiting for 1ω signal to stabilise...")
        self._status_lbl.setStyleSheet(
            "color:#ffdd57; font-weight:bold; padding:4px;")

        self._main_win.assign_parameters_to_core(params)
        self._main_win.core.stop_requested = False
        self._main_win.core.force_averaging = False
        # New calibration run → forget the previous run's backup file slot.
        self._main_win._backup_suffix_calib = None

        _auto_on  = self._main_win.auto_params_cb.isChecked()
        _dlg      = self._main_win._auto_params_dialog
        _adaptive = _auto_on and _dlg.cb_adaptive_calib.isChecked()

        _auto_fn         = self._main_win._auto_params_fn       if _adaptive else None
        _auto_sens_sr830 = _adaptive and _dlg.cb_sens_sr830.isChecked()
        _auto_sens_7265  = _adaptive and _dlg.cb_sens_7265.isChecked()
        _any             = _auto_sens_sr830 or _auto_sens_7265
        _stab_fn         = self._main_win._stability_check_fn   if _any else None
        _sr830_thresh    = self._main_win._sr830_thresholds_fn  if _auto_sens_sr830 else None
        _dsp_thresh      = self._main_win._dsp7265_thresholds_fn if _auto_sens_7265  else None

        self._main_win._patch_core_stop_support()
        self._calib_autosave_timer.start()

        avg_r = avg_theta = avg_res = None
        self._main_win._manual_1w_calib_running = True
        try:
            avg_r, avg_theta, avg_res = self._main_win.core.calibrate_1w_phase(
                callback=self._calib_callback,
                freq=freq,
                wait_time=wait_time,
                average_time=avg_time,
                auto_params_fn=_auto_fn,
                auto_sens_sr830=_auto_sens_sr830,
                auto_sens_7265=_auto_sens_7265,
                stability_check_fn=_stab_fn,
                sr830_thresholds_fn=_sr830_thresh,
                dsp7265_thresholds_fn=_dsp_thresh,
            )
        except RuntimeError as exc:
            if "stopped" not in str(exc).lower():
                QMessageBox.critical(self, "Calibration Error", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Calibration Error", str(exc))
        finally:
            self._main_win._manual_1w_calib_running = False
            self._calib_autosave_timer.stop()
            self._main_win._restore_core_stop_support()
            self._main_win._ground_lockins_after_measurement()
            threading.Thread(
                target=lambda: (self._main_win.core.shutdown()
                                if not self._main_win.stop_requested else None),
                daemon=True,
            ).start()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._force_avg_btn.setEnabled(False)

        if avg_r is not None:
            self._main_win._phase_calibrated     = True
            self._main_win._calibrated_phase_deg = avg_theta
            self._main_win._auto_backup_calibration(completed=True)
            self._status_lbl.setText(
                f"Calibrated — R₁ω = {avg_r * 1e3:.4f} mV  |  "
                f"PHAS applied = {avg_theta:.4f}°"
            )
            self._status_lbl.setStyleSheet(
                "color:#3be362; font-weight:bold; padding:4px;")
            self._set_led('1w', False)
            try:
                _freq_val = float(self.freq_entry.text())
            except ValueError:
                _freq_val = 0.0
            self._set_results_bar(_freq_val, avg_r, avg_res, avg_theta)
            self._action_widget.show()
            self._save_calib_btn.show()
        else:
            # Stopped or failed before averaging finished — still back up
            # whatever calibration time series was captured, instead of
            # silently discarding it.
            self._main_win._auto_backup_calibration(completed=False)
            self._status_lbl.setText("Calibration stopped or failed.")
            self._status_lbl.setStyleSheet(
                "color:#e35f3b; font-weight:bold; padding:4px;")
            self._set_led('1w', False)
            if self._main_win._calib_t_data:
                self._save_calib_btn.show()

    def _periodic_autosave_calibration(self):
        """Crash-safety snapshot, called by self._calib_autosave_timer every
        interval while calibration is running."""
        try:
            self._main_win._auto_backup_calibration(completed=False, live=True)
        except Exception as e:
            print(f"Calibration periodic autosave failed: {e}")

    def _save_calibration_data(self):
        """Explicit save to the main window's chosen folder — separate from
        the automatic Backup_data crash-safety copy, same pattern as the 3ω
        and IV save_data() methods (overwrite confirmation + a clear error
        dialog if the write itself fails)."""
        df = self._main_win._calib_dataframe()
        if df is None:
            QMessageBox.warning(self, "No Data", "No calibration data available to save.")
            return

        folder = self._main_win.save_dir_entry.text().strip() or "."
        base = self._main_win.save_name_entry.text().strip() or "calibration"
        try:
            filetype = self._main_win.filetype_box.currentText()  # ".csv" or ".txt"
        except Exception:
            filetype = ".csv"
        filename = f"{base}_1w_calib{filetype}"

        os.makedirs(folder, exist_ok=True)
        full_path = os.path.join(folder, filename)

        if os.path.exists(full_path):
            reply = QMessageBox.question(
                self, "File Already Exists",
                f"{filename} already exists in this folder:\n{folder}\n\n"
                "Overwrite it with this calibration's data?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        try:
            sep = "," if filetype == ".csv" else "\t"
            df.to_csv(full_path, index=False, sep=sep)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed",
                f"Could not save calibration data to:\n{full_path}\n\n{exc}\n\n"
                "The file may be open in another program (e.g. Excel) — "
                "close it and try again.")
            return

        try:
            params_path = os.path.join(folder, filename.rsplit(".", 1)[0] + "_params.txt")
            p_entries = []
            try:
                p_entries.append(f"  {'Frequency (Hz)':<28}:  {float(self.freq_entry.text()):.4g}")
            except ValueError:
                pass
            if self._main_win._calibrated_phase_deg is not None:
                p_entries.append(
                    f"  {'Calibrated PHAS (°)':<28}:  {self._main_win._calibrated_phase_deg:.4f}")
            # Include R/r/L/S like the 3w and IV params files do -- the
            # Analysis window's _load_params_txt() requires all four to be
            # present before it treats a params.txt as usable, otherwise it
            # (correctly, but confusingly) reports "No _params.txt found"
            # even though the file exists.
            meas_entries = []
            try:
                p = self._main_win.read_parameters()
                meas_entries = [
                    f"  {'Resistance (R)':<28}:  {p['R']:.4f} Ohm",
                    f"  {'dR/dT (r)':<28}:  {p['r']:.4f} Ohm/K",
                    f"  {'Length (L)':<28}:  {p['L']:.4e} m",
                    f"  {'Cross Section (S)':<28}:  {p['S']:.4e} m^2",
                ]
            except Exception:
                pass
            _write_params_file(params_path, "1ω PHASE CALIBRATION PARAMETERS", [
                ("Calibration Result",   p_entries),
                ("Measurement Settings", meas_entries),
                ("Lock-in Parameters",   _lockin_human_readable(self._main_win.core)),
            ])
        except Exception as e:
            print(f"Could not save calibration params file: {e}")

        QMessageBox.information(self, "Saved", f"Saved to {full_path}")

    def _skip_current_now(self):
        """Abort the current 1ω calibration mid-run. 3ω proceeds with last PHAS."""
        try:
            self._main_win.core.skip_1w_calib = True
        except Exception as e:
            print(f'skip_current error: {e}')

    def _skip_next_freq(self):
        """Add the next frequency in the queue to the skip set."""
        next_idx = self._auto_cur_idx + 1
        if next_idx < len(self._auto_freq_queue):
            # Next freq already known from the queue
            nf = self._auto_freq_queue[next_idx]
            self._main_win._1w_skip_freqs.add(round(nf, 9))
            self._main_win._skip_freq_dialog._refresh_list()
        else:
            # Queue not fully built yet — find next freq from widget list
            try:
                freqs = self._main_win.freq_range_widget.get_frequencies()
                _cur = self._auto_freq_queue[-1] if self._auto_freq_queue else None
                if _cur is None:
                    return  # no current freq known yet — nothing safe to do
                past = False
                for f in freqs:
                    if past:
                        self._main_win._1w_skip_freqs.add(round(f, 9))
                        self._main_win._skip_freq_dialog._refresh_list()
                        break
                    if abs(f - _cur) < 1e-9:
                        past = True
            except Exception:
                pass

    def _refresh_skip_display(self):
        """Called by SkipFreqDialog after Apply to keep skip display in sync."""
        pass  # placeholder — no separate display needed

    def _set_led(self, which, on):
        """which: '1w' or '3w'. on: True=green, False=grey."""
        ss = self._LED_ON_SS if on else self._LED_OFF_SS
        if which == '1w':
            self._led_1w.setStyleSheet(ss)
        elif which == '3w':
            self._led_3w.setStyleSheet(ss)

    def _set_results_bar(self, freq, v1w, r1w, theta):
        """Update the bottom results bar with latest measured values. r1w may be None."""
        if r1w is not None and not self._auto_mode:
            self.add_freq_point(freq, r1w)
        av = abs(v1w)
        if av >= 1.0:
            v_str = f"{v1w:.5f} V"
        elif av >= 1e-3:
            v_str = f"{v1w*1e3:.5f} mV"
        else:
            v_str = f"{v1w*1e6:.5f} µV"
        if r1w is None or r1w != r1w:  # None or NaN
            r_str = "—"
        else:
            ar = abs(r1w)
            if ar >= 1e6:
                r_str = f"{r1w*1e-6:.4f} MΩ"
            elif ar >= 1e3:
                r_str = f"{r1w*1e-3:.4f} kΩ"
            elif ar >= 1.0:
                r_str = f"{r1w:.4f} Ω"
            else:
                r_str = f"{r1w*1e3:.4f} mΩ"
        self._results_bar.setText(
            f"Last:   f = {freq:.4g} Hz   |   V₁ω = {v_str}"
            f"   |   R₁ω = {r_str}   |   θ = {theta:.4f}°"
        )

    def _calib_callback(self, phase, *args):
        if phase == '1w_time':
            t_data, r_data, theta_data, wait_n, i_data = args
            self._main_win._calib_t_data     = t_data
            self._main_win._calib_r_data     = r_data
            self._main_win._calib_theta_data = theta_data
            self._main_win._calib_i_data     = i_data
            self.update_live(t_data, r_data, theta_data, wait_n, i_data)

    def _force_averaging_now(self):
        try:
            self._main_win.core.force_averaging = True
            self._main_win.set_status("Force averaging requested — will start averaging at next poll.")
        except Exception:
            self._main_win.set_status("Force averaging: no measurement running.")

    def _stop(self):
        self._main_win.core.stop_requested = True
        threading.Thread(
            target=lambda: (self._main_win.core.shutdown()
                            if hasattr(self._main_win.core, 'shutdown') else None),
            daemon=True,
        ).start()

    def _proceed(self):
        self._action_widget.hide()
        self.hide()

    def _repeat(self):
        self._action_widget.hide()
        self._start()


class IVDialog(QDialog):
    def __init__(self, parent, core):
        super().__init__(parent)
        self.setWindowTitle("IV Measurement")
        self.core = core
        self.parent = parent
        self.iv_data = None
        self._iv_ts_t_data = None
        self._iv_ts_v3w_data = None

        # Crash-safety: periodically re-write the same backup file pair
        # while an IV measurement is running (see _silent_backup's suffix=).
        self._iv_autosave_timer = QTimer(self)
        self._iv_autosave_timer.setInterval(60_000)  # 60 s
        self._iv_autosave_timer.timeout.connect(self._periodic_autosave_iv)
        # Reserved backup filename suffix for the run in progress — reset to
        # None at the start of each new run (see start_iv).
        self._backup_suffix_iv    = None
        self._backup_suffix_iv_ts = None

        layout = QVBoxLayout(self)

        # Build the underlying voltage-sweep widget first (object only — not
        # yet added to the layout) so the Current sweep section below, which
        # is what you actually type first, can be laid out above it while
        # still referencing its start_e/stop_e fields for the live link.
        self.volt_range_widget = FrequencyRangeWidget(unit="V", show_wait=False)
        self.volt_range_widget.start_e.setText("0.004")
        self.volt_range_widget.stop_e.setText("0.1")
        self.volt_range_widget.n_e.setText("10")

        # ── Current sweep — linked convenience fields for Start/Stop (V) ───
        # Same purpose as the main window's AC Current field: only the
        # Voltage sweep's Start/Stop values below are ever used to build the
        # actual IV sweep list. These two fields let you type the desired
        # start/stop CURRENT instead and have the corresponding voltage
        # back-computed via the live Safety Control conversion factor.
        self._iv_cur_link_updating = False
        cur_sweep_row = QHBoxLayout()
        cur_sweep_row.setSpacing(4)
        cur_sweep_row.addWidget(QLabel("Current sweep (A):"))
        self.cur_start_e = QLineEdit(); self.cur_start_e.setFixedWidth(65)
        self.cur_stop_e  = QLineEdit(); self.cur_stop_e.setFixedWidth(65)
        cur_sweep_row.addWidget(QLabel("Start:"))
        cur_sweep_row.addWidget(self.cur_start_e)
        cur_sweep_row.addWidget(QLabel("Stop:"))
        cur_sweep_row.addWidget(self.cur_stop_e)
        cur_sweep_row.addStretch(1)
        layout.addLayout(cur_sweep_row)

        self.iv_link_frame, self.iv_link_text = _make_conversion_link_card()
        self.iv_link_frame.setToolTip(
            "Current sweep and Voltage sweep are linked live through the "
            "active Safety Control conversion factor k. The experiment "
            "always uses the Voltage sweep values below.")
        layout.addWidget(self.iv_link_frame)

        layout.addWidget(QLabel("Voltage sweep (V):"))
        layout.addWidget(self.volt_range_widget)

        self.volt_range_widget.start_e.textChanged.connect(
            lambda _t: self._sync_iv_current_from_voltage('start'))
        self.volt_range_widget.stop_e.textChanged.connect(
            lambda _t: self._sync_iv_current_from_voltage('stop'))
        self.cur_start_e.textChanged.connect(
            lambda _t: self._sync_iv_voltage_from_current('start'))
        self.cur_stop_e.textChanged.connect(
            lambda _t: self._sync_iv_voltage_from_current('stop'))
        self._sync_iv_current_from_voltage('start')   # initial populate
        self._sync_iv_current_from_voltage('stop')
        self._refresh_iv_link_label()

        # Live-refresh if Safety Control mode/range is changed in the main
        # window while this dialog stays open — otherwise the Voltage sweep
        # silently goes stale relative to the Current sweep values shown.
        # Re-derives Voltage from Current (same direction as the main
        # window's own safety-toggle handlers), then updates the link label.
        try:
            for _btn in (self.parent.safety_low_src_btn, self.parent.safety_high_src_btn,
                         self.parent.safety_low_range_btn, self.parent.safety_high_range_btn):
                _btn.toggled.connect(self._on_safety_changed_externally)
        except Exception:
            pass

        form = QFormLayout()
        self.freq_e = QLineEdit("5")
        self.wait_time = QLineEdit("30")
        self.avg_time  = QLineEdit("10")
        form.addRow("Frequency (Hz):", self.freq_e)
        form.addRow("Wait time (s):", self.wait_time)
        form.addRow("Average time (s):", self.avg_time)
        layout.addLayout(form)

        self.fig = Figure(figsize=(5, 4))
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel(r"$I^3\ (\mathrm{A}^3)$")
        self.ax.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$")
        self.ax.grid(True, linestyle='--', color='white', alpha=0.3)
        layout.addWidget(self.canvas)

        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start IV")
        self.start_btn.setStyleSheet("background:#3be362; color:black;")
        self.start_btn.clicked.connect(self.start_iv)
        btn_layout.addWidget(self.start_btn)

        self.proceed_btn = QPushButton("Proceed")
        self.proceed_btn.setEnabled(False)
        self.proceed_btn.clicked.connect(self.proceed)
        btn_layout.addWidget(self.proceed_btn)

        self.redo_btn = QPushButton("Redo IV")
        self.redo_btn.setEnabled(False)
        self.redo_btn.clicked.connect(self.start_iv)
        btn_layout.addWidget(self.redo_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet("background:#e35f3b; color:white;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_iv)
        btn_layout.addWidget(self.stop_btn)

        self.live_plot_btn = QPushButton("📈 Live Plot")
        self.live_plot_btn.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #6a0dad, stop:1 #0077ff);"
            "color:white; font-weight:bold; border-radius:5px; padding:4px 8px;"
        )
        self.live_plot_btn.clicked.connect(self._open_live_plot)
        btn_layout.addWidget(self.live_plot_btn)

        layout.addLayout(btn_layout)

        save_form = QFormLayout()
        self.save_dir = QLineEdit("")
        self.save_name = QLineEdit("sample_IV")
        save_form.addRow("Save folder:", self.save_dir)
        save_form.addRow("File name:", self.save_name)
        layout.addLayout(save_form)

        self.save_btn = QPushButton("Save Data")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_data)
        layout.addWidget(self.save_btn)

        # Create live plot window now (hidden) so it captures all data from step 1
        self._live_plot_window = IVLivePlotWindow(self, self.parent)

        self._load_iv_settings()

    def _load_iv_settings(self):
        s = load_settings()
        if "volt_range_iv" in s:
            try:
                self.volt_range_widget.set_config(s["volt_range_iv"])
            except Exception:
                pass
        if "iv_freq"      in s: self.freq_e.setText(s["iv_freq"])
        if "iv_wait_time" in s: self.wait_time.setText(s["iv_wait_time"])
        if "iv_avg_time"  in s: self.avg_time.setText(s["iv_avg_time"])
        if "iv_save_dir"  in s: self.save_dir.setText(s["iv_save_dir"])
        if "iv_save_name" in s: self.save_name.setText(s["iv_save_name"])

    def _save_iv_settings(self):
        s = load_settings()
        s["volt_range_iv"] = self.volt_range_widget.get_config()
        s["iv_freq"]       = self.freq_e.text()
        s["iv_wait_time"] = self.wait_time.text()
        s["iv_avg_time"]  = self.avg_time.text()
        s["iv_save_dir"]  = self.save_dir.text()
        s["iv_save_name"] = self.save_name.text()
        save_settings(s)

    def closeEvent(self, event):
        self._save_iv_settings()
        try:
            for _btn in (self.parent.safety_low_src_btn, self.parent.safety_high_src_btn,
                         self.parent.safety_low_range_btn, self.parent.safety_high_range_btn):
                _btn.toggled.disconnect(self._on_safety_changed_externally)
        except Exception:
            pass
        event.accept()

    def _open_live_plot(self):
        self._live_plot_window.show()
        self._live_plot_window.raise_()
        self._live_plot_window.activateWindow()

    def _on_safety_changed_externally(self, checked=None):
        """Safety Control mode/range changed in the main window while this
        IV dialog is open. Re-derive the Voltage sweep from the Current
        sweep fields using the new conversion factor (same direction as the
        main window's own safety-toggle handlers), then refresh the link
        label. Never touches the sweep logic itself."""
        self._sync_iv_voltage_from_current('start')
        self._sync_iv_voltage_from_current('stop')
        self._refresh_iv_link_label()

    def _iv_current_conversion_factor(self):
        return getattr(self.core, 'CURRENT_CONVERSION_FACTOR', 1e-3) or 1e-3

    def _iv_safety_mode_display_text(self):
        src = getattr(self.core, 'SAFETY_CURRENT_SOURCE', 'low')
        if src != 'high':
            return "Low current source"
        rng = getattr(self.core, 'SAFETY_CURRENT_RANGE', 'low_range')
        return "High source · High range" if rng == 'high_range' else "High source · Low range"

    def _refresh_iv_link_label(self):
        """Purely cosmetic: refresh the fancy link card's live k display.
        Never affects the actual Current/Voltage sweep values."""
        if not hasattr(self, 'iv_link_text'):
            return
        k = self._iv_current_conversion_factor()
        k_txt = f"{k * 1e3:g} mA/V" if k < 1.0 else f"{k:g} A/V"
        self.iv_link_text.setText(
            "<b>I&nbsp;=&nbsp;V&nbsp;&times;&nbsp;k</b>"
            "&nbsp;&nbsp;|&nbsp;&nbsp;"
            f"<b style='color:#7CFFEA;'>k&nbsp;=&nbsp;{k_txt}</b>"
            f"&nbsp;&nbsp;<span style='color:#c8d6e0;'>({self._iv_safety_mode_display_text()})</span>"
            "&nbsp;&nbsp;<span style='color:#8a97a5;'>— voltage sweep drives the experiment</span>"
        )

    def _sync_iv_current_from_voltage(self, which):
        """Recompute the linked Current Start/Stop field from its Voltage
        Start/Stop counterpart."""
        if self._iv_cur_link_updating:
            return
        v_entry = self.volt_range_widget.start_e if which == 'start' else self.volt_range_widget.stop_e
        c_entry = self.cur_start_e if which == 'start' else self.cur_stop_e
        try:
            voltage = float(v_entry.text())
        except ValueError:
            return
        self._iv_cur_link_updating = True
        try:
            c_entry.setText(f"{voltage * self._iv_current_conversion_factor():.6g}")
        finally:
            self._iv_cur_link_updating = False

    def _sync_iv_voltage_from_current(self, which):
        """Reverse direction — the calculation this feature exists for: type
        a desired start/stop current, get the driving voltage that would
        produce it."""
        if self._iv_cur_link_updating:
            return
        v_entry = self.volt_range_widget.start_e if which == 'start' else self.volt_range_widget.stop_e
        c_entry = self.cur_start_e if which == 'start' else self.cur_stop_e
        try:
            current = float(c_entry.text())
        except ValueError:
            return
        factor = self._iv_current_conversion_factor()
        if factor == 0:
            return
        self._iv_cur_link_updating = True
        try:
            v_entry.setText(f"{current / factor:.6g}")
        finally:
            self._iv_cur_link_updating = False

    def start_iv(self):
        if not getattr(self.parent,"instruments_connected",False):
            QMessageBox.warning(self,"Not Connected","Connect instruments before starting IV.")
            return
        if not self.parent._ensure_float_before_measurement():
            return
        # Reset live plot for a fresh run (always, so all steps are captured)
        self._live_plot_window.reset()
        self._iv_ts_t_data = None
        self._iv_ts_v3w_data = None
        # New run → forget the previous run's backup file slot.
        self._backup_suffix_iv    = None
        self._backup_suffix_iv_ts = None
        _original_iv_sleep = None   # defined before try so finally can always reference it
        try:
            _global_iv_wt = float(self.wait_time.text())
            _iv_freq = float(self.freq_e.text())
            _iv_voltages = self.volt_range_widget.get_values()
            if not _iv_voltages:
                QMessageBox.warning(self, "No Voltages", "Voltage sweep range produced no points. Check Start/Stop/N.")
                return
            params = {"freq_IV": _iv_freq}
            for k, v in params.items():
                setattr(self.core, k, v)
            self.core.__dict__.update(params)

            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)

            QApplication.processEvents()
            self.core.stop_requested = False

            # Patch time.sleep so Qt events are processed during IV loops,
            # allowing the Stop button click to reach stop_iv()
            import time as _time_module
            _original_iv_sleep = self.core.time.sleep

            def _iv_patched_sleep(seconds):
                interval = 0.05
                elapsed = 0.0
                while elapsed < seconds:
                    if getattr(self.core, 'stop_requested', False):
                        return
                    QApplication.processEvents()
                    _original_iv_sleep(min(interval, seconds - elapsed))
                    elapsed += interval

            self.core.time.sleep = _iv_patched_sleep

            self._iv_autosave_timer.start()
            self._live_plot_window.set_measuring(True)

            def update_plot(phase, *args):
                if phase == 'iv_time':
                    t_data, v3w_data, v_start_idx, wait_n, label = args
                    # Capture references once — IV_measurement() only ever
                    # appends to these lists, so the reference stays valid
                    # (and keeps growing) even after the function returns.
                    if self._iv_ts_t_data is None:
                        self._iv_ts_t_data = t_data
                        self._iv_ts_v3w_data = v3w_data
                    self._live_plot_window.update_live(
                        t_data, v3w_data, v_start_idx, wait_n, label)
                    return
                if phase != 'iv_summary':
                    return
                I3, V3w = args
                try:
                    self.ax.clear()
                    self.ax.set_xlabel(r"$I^3\ (\mathrm{A}^3)$")
                    self.ax.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$")
                    self.ax.grid(True, linestyle='--', color='white', alpha=0.3)

                    self.ax.plot(I3, V3w, 'o-', label="Data")

                    if len(I3) >= 3:
                        import numpy as np

                        try:
                            coeffs, cov = np.polyfit(I3, V3w, 1, cov=True)
                            fit_y = np.polyval(coeffs, I3)

                            self.ax.plot(I3, fit_y, '-', label="Fit")

                            slope = coeffs[0]
                            slope_err = np.sqrt(cov[0, 0])

                            residuals = np.array(V3w) - fit_y
                            ss_res = np.sum(residuals**2)
                            ss_tot = np.sum((np.array(V3w) - np.mean(V3w))**2)
                            r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else float('nan')

                            # Find the emptiest corner to place the annotation
                            corners = [
                                (0.03, 0.97, 'left',  'top'),
                                (0.97, 0.97, 'right', 'top'),
                                (0.03, 0.05, 'left',  'bottom'),
                                (0.97, 0.05, 'right', 'bottom'),
                            ]
                            ax_xlim = self.ax.get_xlim()
                            ax_ylim = self.ax.get_ylim()
                            xrange = ax_xlim[1] - ax_xlim[0] or 1
                            yrange = ax_ylim[1] - ax_ylim[0] or 1
                            best_corner = corners[0]
                            min_pts = float('inf')
                            for cx, cy, ha, va in corners:
                                # Convert axes fraction to data coords
                                cx_data = ax_xlim[0] + cx * xrange
                                cy_data = ax_ylim[0] + cy * yrange
                                # Count points within 25% of range from this corner
                                count = sum(
                                    1 for px, py in zip(I3, V3w)
                                    if abs(px - cx_data) < 0.25 * xrange
                                    and abs(py - cy_data) < 0.25 * yrange
                                )
                                if count < min_pts:
                                    min_pts = count
                                    best_corner = (cx, cy, ha, va)
                            bx, by, bha, bva = best_corner

                            self.ax.text(
                                bx, by,
                                f"Slope = {slope:.3e} ± {slope_err:.3e}\nR² = {r_squared:.5f}",
                                transform=self.ax.transAxes,
                                verticalalignment=bva,
                                horizontalalignment=bha,
                                fontsize=8,
                                color='white',
                                bbox=dict(
                                    boxstyle='round,pad=0.4',
                                    facecolor='#3a86ff',
                                    edgecolor='white',
                                    alpha=0.85,
                                    linewidth=1.2,
                                )
                            )
                        except Exception:
                            pass  # fit failed — keep raw data plot

                    self.ax.legend()
                    self.canvas.draw()
                    QApplication.processEvents()
                except Exception:
                    pass  # never let a plot error abort the measurement
             
             
            # 🔴 THIS is the correct call
            _p        = self.parent
            _auto_on  = (getattr(_p, 'auto_params_cb', None) is not None
                         and _p.auto_params_cb.isChecked())
            _dlg      = _p._auto_params_dialog
            _auto_fn  = _p._auto_params_fn if _auto_on else None
            _auto_sens_sr830 = _auto_on and _dlg.cb_sens_sr830.isChecked()
            _auto_sens_7265  = _auto_on and _dlg.cb_sens_7265.isChecked()
            _any_auto_sens   = _auto_sens_sr830 or _auto_sens_7265
            _stab_fn         = _p._stability_check_fn if _any_auto_sens else None
            _sr830_thresh    = _p._sr830_thresholds_fn  if _auto_sens_sr830 else None
            _dsp_thresh      = _p._dsp7265_thresholds_fn if _auto_sens_7265  else None
            _iv_auto_at = _p._calc_auto_avg_time(_iv_freq)
            self.iv_data = self.core.IV_measurement(
                callback=update_plot,
                iv_wait_time=_global_iv_wt,
                iv_average_time=_iv_auto_at if _iv_auto_at is not None else float(self.avg_time.text()),
                frequencies=[_iv_freq],
                voltages=_iv_voltages,
                auto_params_fn=_auto_fn,
                auto_sens_sr830=_auto_sens_sr830,
                auto_sens_7265=_auto_sens_7265,
                stability_check_fn=_stab_fn,
                sr830_thresholds_fn=_sr830_thresh,
                dsp7265_thresholds_fn=_dsp_thresh,
            )

            # core.IV_measurement() returns *normally* whether it ran to
            # completion or was cut short by stop_iv() — both share the
            # same return path. Use the stop flag to tell them apart so we
            # don't mislabel an interrupted run as completed.
            was_stopped = bool(getattr(self.core, 'stop_requested', False))
            self._auto_backup_iv(self.iv_data, completed=not was_stopped)
            # Store IV data in main window for pairing with next 3ω measurement
            self.parent._latest_iv_data = self.iv_data
            # Also add to measurement history for Results window
            import datetime
            iv_name = self.parent.save_name_entry.text().strip() or f"{datetime.date.today().strftime('%Y%m%d')}_measurement"
            existing = [m['name'] for m in self.parent._measurement_history if m.get('status') in ('iv', 'iv_interrupted')]
            if iv_name in existing:
                base = iv_name.rsplit('_', 1)[0] if '_' in iv_name else iv_name
                n = 1
                while f"{base}_{n}" in existing:
                    n += 1
                iv_name = f"{base}_{n}"
            iv_entry = {
                'name': iv_name,
                'status': 'iv' if not was_stopped else 'iv_interrupted',
                'data_3w': [],
                'data_iv': list(self.iv_data) if self.iv_data else [],
                'fit_results': None,
                'params': self.parent.read_parameters(),
                'timestamp': datetime.datetime.now(),
                'ts_data': {}
            }
            self.parent._measurement_history.append(iv_entry)
            if self.parent._results_window is not None:
                self.parent._results_window._refresh_sidebar()

            if was_stopped:
                n_pts = len(self.iv_data) if self.iv_data else 0
                self.parent.set_status(f"IV measurement stopped — {n_pts} point(s) captured.")
                QMessageBox.information(self, "IV Measurement",
                    f"IV measurement stopped.\n{n_pts} voltage point(s) captured and backed up.")
            else:
                QMessageBox.information(self, "IV Measurement", "Measurement finished.")

            self.proceed_btn.setEnabled(True)
            self.save_btn.setEnabled(bool(self.iv_data))
            self.redo_btn.setEnabled(True)

        except Exception as e:
            partial = getattr(self.core, 'partial_IV_results', [])
            self._auto_backup_iv(partial, completed=False)
            QMessageBox.critical(self, "IV Error", str(e))
        finally:
            self._iv_autosave_timer.stop()
            self._live_plot_window.set_measuring(False)
            try:
                self.core.shutdown()
            except Exception as e:
                print(f"Shutdown error after IV measurement: {e}")
            if _original_iv_sleep is not None:
                self.core.time.sleep = _original_iv_sleep
            self.parent._ground_lockins_after_measurement()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def stop_iv(self):
        self.core.stop_requested = True
        try:
            self.core.shutdown()
        except Exception as e:
            print(f"Shutdown error after stop: {e}")

    def _iv_ts_dataframe(self):
        """Build raw V3w-vs-time DataFrame from the live-plot callback buffers.

        Exists independently of the per-voltage-step averages, so a stop
        during the very first voltage step's wait/average phase still has
        something to back up.
        """
        if self._iv_ts_t_data is None or self._iv_ts_v3w_data is None:
            return None
        min_len = min(len(self._iv_ts_t_data), len(self._iv_ts_v3w_data))
        if min_len == 0:
            return None
        import pandas as pd
        return pd.DataFrame({
            'Time (s)': list(self._iv_ts_t_data[:min_len]),
            'V3w (V)':  list(self._iv_ts_v3w_data[:min_len]),
        })

    def _periodic_autosave_iv(self):
        """Crash-safety snapshot, called by self._iv_autosave_timer every
        interval while an IV measurement is running."""
        try:
            partial = getattr(self.core, 'partial_IV_results', [])
            self._auto_backup_iv(partial, completed=False, live=True)
        except Exception as e:
            print(f"IV periodic autosave failed: {e}")

    def _auto_backup_iv(self, data, completed, live=False):
        """Silently back up IV data to Backup_data folder.

        Exactly one file pair per run: self._backup_suffix_iv / _ts is
        reserved on the first write of a run (reset in start_iv) and reused
        on every later call, so periodic ticks/stop/completion overwrite the
        same pair in place. live=True marks a periodic crash-safety tick.
        """
        df_ts = self._iv_ts_dataframe()
        if not data and df_ts is None:
            return
        save_dir = self.save_dir.text().strip() or os.getcwd()
        backup_folder = os.path.join(save_dir, 'Backup_data')
        base_name = _backup_base_name(self.save_name.text())
        status = "IN PROGRESS" if live else ("COMPLETED" if completed else "INTERRUPTED")
        try:
            p = self.parent.read_parameters()
            iv_entries = [
                f"  {'Status':<28}:  {status}",
                f"  {'V_start':<28}:  {float(self.volt_range_widget.start_e.text()):.4f} V",
                f"  {'V_end':<28}:  {float(self.volt_range_widget.stop_e.text()):.4f} V",
                f"  {'I_start':<28}:  {float(self.cur_start_e.text()):.6g} A",
                f"  {'I_end':<28}:  {float(self.cur_stop_e.text()):.6g} A",
                f"  {'N points':<28}:  {self.volt_range_widget.n_e.text()}",
                f"  {'Spacing':<28}:  {self.volt_range_widget.sp_box.currentText()}",
                f"  {'Frequency (Hz)':<28}:  {self.freq_e.text()}",
            ]
            meas_entries = [
                f"  {'Global IV Wait Time':<28}:  {float(self.wait_time.text()):.1f} s",
                f"  {'IV Averaging Time':<28}:  {float(self.avg_time.text()):.1f} s",
                f"  {'Resistance (R)':<28}:  {p['R']:.4f} Ohm",
                f"  {'dR/dT (r)':<28}:  {p['r']:.4f} Ohm/K",
                f"  {'Length (L)':<28}:  {p['L']:.4e} m",
                f"  {'Cross Section (S)':<28}:  {p['S']:.4e} m^2",
            ]
        except Exception:
            iv_entries = [f"  {'Status':<28}:  {status}"]
            meas_entries = []

        path = None
        if data:
            path, self._backup_suffix_iv = _silent_backup(
                backup_folder, base_name, data,
                columns=["Voltage (V)", "Current (A)", "I^3 (A^3)", "V3w (V)"],
                completed=completed,
                title=f"IV MEASUREMENT PARAMETERS ({status})",
                sections=[("IV Settings", iv_entries),
                          ("Measurement Settings", meas_entries),
                          ("Lock-in Parameters", _lockin_human_readable(self.core))],
                suffix=self._backup_suffix_iv,
            )

        if df_ts is not None:
            _, self._backup_suffix_iv_ts = _silent_backup(
                backup_folder, 'Time series_' + base_name,
                df_ts.values.tolist(), list(df_ts.columns),
                completed=completed,
                title=f"IV TIME SERIES ({status})",
                sections=[],
                suffix=self._backup_suffix_iv_ts,
            )

        if live:
            return
        if path:
            self.parent.set_status(f"IV Backup: {os.path.basename(path)}")
        elif df_ts is not None:
            self.parent.set_status(f"IV Backup: Time series_{base_name} ({status.lower()})")

    def save_data(self):
        if self.iv_data is None:
            return

        import os
        folder = self.save_dir.text().strip() or "."
        name = self.save_name.text().strip()

        try:
            filetype = self.parent.filetype_box.currentText()  # ".csv" or ".txt"
        except Exception:
            filetype = ".csv"

        if not name.lower().endswith(".csv") and not name.lower().endswith(".txt"):
            name += filetype

        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)

        if os.path.exists(path):
            reply = QMessageBox.question(
                self, "File Already Exists",
                f"{name} already exists in this folder:\n{folder}\n\n"
                "Overwrite it with this IV measurement's data?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        df = self.core.pd.DataFrame(
            self.iv_data,
            columns=["Voltage (V)", "Current (A)", "I^3 (A^3)", "V3w (V)"]
        )
        try:
            df.to_csv(path, index=False, sep="," if filetype == ".csv" else "\t")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed",
                f"Could not save data to:\n{path}\n\n{exc}\n\n"
                "The file may be open in another program (e.g. Excel) — "
                "close it and try again.")
            return

        try:
            params_path = os.path.join(folder, name.rsplit(".", 1)[0] + "_params.txt")
            p = self.parent.read_parameters()
            iv_entries = [
                f"  {'V_start':<28}:  {float(self.volt_range_widget.start_e.text()):.4f} V",
                f"  {'V_end':<28}:  {float(self.volt_range_widget.stop_e.text()):.4f} V",
                f"  {'I_start':<28}:  {float(self.cur_start_e.text()):.6g} A",
                f"  {'I_end':<28}:  {float(self.cur_stop_e.text()):.6g} A",
                f"  {'N points':<28}:  {self.volt_range_widget.n_e.text()}",
                f"  {'Spacing':<28}:  {self.volt_range_widget.sp_box.currentText()}",
                f"  {'Frequency (Hz)':<28}:  {self.freq_e.text()}",
            ]
            meas_entries = [
                f"  {'Global IV Wait Time':<28}:  {float(self.wait_time.text()):.1f} s",
                f"  {'IV Averaging Time':<28}:  {float(self.avg_time.text()):.1f} s",
                f"  {'Resistance (R)':<28}:  {p['R']:.4f} Ohm",
                f"  {'dR/dT (r)':<28}:  {p['r']:.4f} Ohm/K",
                f"  {'Length (L)':<28}:  {p['L']:.4e} m",
                f"  {'Cross Section (S)':<28}:  {p['S']:.4e} m^2",
            ]
            _write_params_file(params_path, "IV MEASUREMENT PARAMETERS", [
                ("IV Settings",         iv_entries),
                ("Measurement Settings", meas_entries),
                ("Lock-in Parameters",  _lockin_human_readable(self.core)),
            ])
        except Exception as e:
            print(f"Could not save params file: {e}")

        # Save the raw V3w-vs-time series alongside the main IV data,
        # same as the main window's manual save_data() does for 3ω.
        df_ts = self._iv_ts_dataframe()
        if df_ts is not None:
            try:
                ts_base = name.rsplit(".", 1)[0]
                ts_sep  = "," if filetype == ".csv" else "\t"
                ts_path = os.path.join(folder, "Time series_" + ts_base + filetype)
                df_ts.to_csv(ts_path, index=False, sep=ts_sep)
            except Exception as e:
                print(f"IV time series save failed: {e}")

        QMessageBox.information(self, "Saved", f"Saved to {path}")

        self.close()
        self.parent.run_button.setEnabled(True)

    def proceed(self):
        self.parent.run_button.setEnabled(True)
        self.close()

# ── TC lookup tables (seconds) ────────────────────────────────────────────────
_SR830_TC_VALUES = [
    10e-6, 30e-6, 100e-6, 300e-6,
    1e-3,  3e-3,  10e-3,  30e-3,  100e-3, 300e-3,
    1,     3,     10,     30,     100,    300,
    1000,  3000,  10000,  30000,
]
_DSP7265_TC_VALUES = [
    10e-6, 20e-6, 40e-6, 80e-6, 160e-6, 320e-6, 640e-6,
    5e-3,  10e-3, 20e-3, 50e-3, 100e-3, 200e-3, 500e-3,
    1,  2,  5,  10,  20,  50,  100,  200,  500,
    1000, 2000, 5000, 10000, 20000, 50000, 100000,
]


class AutoParamsButton(QPushButton):
    """Full-width checkable toggle button; emits settingsRequested on double-click."""
    settingsRequested = Signal()

    _STYLE_ON = """
        QPushButton {
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #00c6a7, stop:1 #0077ff);
            color: #ffffff;
            font-weight: bold;
            font-size: 11px;
            border-radius: 6px;
            padding: 6px 4px;
            letter-spacing: 1px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #00e0be, stop:1 #3399ff);
        }
    """
    _STYLE_OFF = """
        QPushButton {
            background: #2e2e40;
            color: #888899;
            font-weight: bold;
            font-size: 11px;
            border-radius: 6px;
            border: 1px solid #444466;
            padding: 6px 4px;
            letter-spacing: 1px;
        }
        QPushButton:hover {
            background: #3a3a55;
            color: #aaaacc;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self._refresh(False)
        self.toggled.connect(self._refresh)
        # Timer distinguishes single click (toggle) from double click (settings)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._do_toggle)

    def _refresh(self, checked):
        self.setText("⚡ AUTO PARAMS  ●  ON" if checked else "⚡ AUTO PARAMS  ○  OFF")
        self.setStyleSheet(self._STYLE_ON if checked else self._STYLE_OFF)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setDown(True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setDown(False)
            if self.rect().contains(event.pos()):
                if self._click_timer.isActive():
                    # Second click arrived before timer → double-click: open settings
                    self._click_timer.stop()
                    self.settingsRequested.emit()
                else:
                    # Start timer; if no second click arrives, treat as single click
                    self._click_timer.start(QApplication.doubleClickInterval())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Fully handled by mouseReleaseEvent timer logic above
        event.accept()

    def _do_toggle(self):
        self.setChecked(not self.isChecked())



class SkipFreqDialog(QDialog):
    """Small panel listing all planned 3omega frequencies with checkboxes.
    Unchecked = skip 1omega calibration for that frequency (use last PHAS).
    Reads the frequency list live from freq_range_widget each time it opens."""

    def __init__(self, main_win):
        super().__init__(main_win)
        self.setWindowTitle("Skip 1omega Calibration — Frequency Selection")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self.resize(320, 420)
        self._main_win = main_win

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Checked = run 1omega calibration.  Uncheck to skip (last PHAS kept)."))

        # Scroll area for checkboxes
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._cb_layout = QVBoxLayout(self._inner)
        self._cb_layout.setSpacing(4)
        self._scroll.setWidget(self._inner)
        layout.addWidget(self._scroll)

        # Select-all / none shortcuts
        _sel_row = QHBoxLayout()
        _all_btn = QPushButton("All")
        _none_btn = QPushButton("None")
        for b in (_all_btn, _none_btn):
            b.setFixedHeight(22)
            b.setStyleSheet("background:#2b2b3d; color:white; border:1px solid #555577;"
                            " padding:2px 10px; border-radius:3px;")
        _all_btn.clicked.connect(lambda: self._set_all(True))
        _none_btn.clicked.connect(lambda: self._set_all(False))
        _sel_row.addWidget(QLabel("Select:"))
        _sel_row.addWidget(_all_btn)
        _sel_row.addWidget(_none_btn)
        _sel_row.addStretch(1)
        layout.addLayout(_sel_row)

        _upd_btn = QPushButton("Update")
        _upd_btn.setStyleSheet(
            "background:#3a86ff; color:white; font-weight:bold;"
            " padding:5px; border-radius:4px;")
        _upd_btn.clicked.connect(self._apply)
        layout.addWidget(_upd_btn)

        self._checkboxes = []  # list of (freq, QCheckBox)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_list()

    def _refresh_list(self):
        # Clear old checkboxes
        while self._cb_layout.count():
            item = self._cb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

        try:
            if hasattr(self._main_win, 'freq_range_widget') and self._main_win.freq_range_widget is not None:
                freqs = self._main_win.freq_range_widget.get_frequencies()
            else:
                freqs = []
        except Exception:
            freqs = []

        skip_set = self._main_win._1w_skip_freqs
        for f in freqs:
            cb = QCheckBox(f"{f:.6g} Hz")
            cb.setChecked(round(f, 9) not in skip_set)  # checked = will calibrate
            self._cb_layout.addWidget(cb)
            self._checkboxes.append((f, cb))
        self._cb_layout.addStretch(1)

    def _set_all(self, state):
        for _, cb in self._checkboxes:
            cb.setChecked(state)

    def _apply(self):
        skip_set = self._main_win._1w_skip_freqs
        skip_set.clear()
        for f, cb in self._checkboxes:
            if not cb.isChecked():
                skip_set.add(round(f, 9))
        # Update the "skip next" index on the calib window if open
        try:
            self._main_win._phase_calib_window._refresh_skip_display()
        except Exception:
            pass


class AutoParamsSettingsDialog(QDialog):
    """Non-modal dialog — each checkbox is fully independent."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto Params Settings")
        self.setFixedWidth(320)
        layout = QVBoxLayout(self)

        # ── Auto 1ω Calibration per frequency ────────────────────────────
        layout.addWidget(QLabel("Auto 1ω Calibration:"))
        self.cb_auto_1w = QCheckBox("Run 1ω phase calibration before each 3ω frequency step")
        self.cb_auto_1w.setChecked(False)
        self.cb_auto_1w.setToolTip(
            "Before each 3ω frequency step, automatically run a 1ω calibration:\n"
            "measure V₁ω and θ, write PHAS to SR830, then switch to 3ω.\n"
            "Uses WAIT_TIME and AVERAGE_TIME from the main panel.\n"
            "Can be enabled/disabled while a measurement is running.")
        self._skip_btn = QPushButton("Skip…")
        self._skip_btn.setFixedHeight(22)
        self._skip_btn.setEnabled(False)
        self._skip_btn.setToolTip("Choose which frequencies to skip 1ω calibration for.")
        self._skip_btn.setStyleSheet(
            "QPushButton { background:#444466; color:white; border:1px solid #666688;"
            "  padding:2px 8px; border-radius:3px; }"
            "QPushButton:enabled { background:#3a4a7a; }"
            "QPushButton:hover:enabled { background:#4a5a9a; }")
        self.cb_auto_1w.toggled.connect(self._skip_btn.setEnabled)
        _1w_row = QHBoxLayout()
        _1w_row.addWidget(self.cb_auto_1w)
        _1w_row.addWidget(self._skip_btn)
        layout.addLayout(_1w_row)

        layout.addSpacing(8)
        _sep_a1w = QFrame()
        _sep_a1w.setFrameShape(QFrame.HLine)
        _sep_a1w.setStyleSheet("color: #555577;")
        layout.addWidget(_sep_a1w)
        layout.addSpacing(4)

        # ── 1ω Phase Calibration ──────────────────────────────────────────
        layout.addWidget(QLabel("1ω Phase Calibration:"))
        self.cb_adaptive_calib = QCheckBox("Adaptive calibration (auto TC + sensitivity)")
        self.cb_adaptive_calib.setChecked(True)
        layout.addWidget(self.cb_adaptive_calib)

        layout.addSpacing(8)
        sep0 = QFrame()
        sep0.setFrameShape(QFrame.HLine)
        sep0.setStyleSheet("color: #555577;")
        layout.addWidget(sep0)
        layout.addSpacing(4)

        # ── Time constant (independent per instrument) ────────────────────
        layout.addWidget(QLabel("Time constant (auto):"))
        self.cb_sr830 = QCheckBox("SR830 — auto time constant")
        self.cb_7265  = QCheckBox("DSP 7265 — auto time constant")
        self.cb_sr830.setChecked(True)
        self.cb_7265.setChecked(True)
        layout.addWidget(self.cb_sr830)
        layout.addWidget(self.cb_7265)

        layout.addSpacing(8)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #555577;")
        layout.addWidget(sep)
        layout.addSpacing(4)

        # ── Sensitivity — SR830 ───────────────────────────────────────────
        layout.addWidget(QLabel("Sensitivity (auto) — SR830:"))
        self.cb_sens_sr830 = QCheckBox("SR830 — auto sensitivity")
        self.cb_sens_sr830.setChecked(False)
        layout.addWidget(self.cb_sens_sr830)

        layout.addSpacing(4)
        def _thresh_row(label_text, default):
            row = QHBoxLayout()
            row.addWidget(QLabel(label_text))
            edit = QLineEdit(default)
            edit.setFixedWidth(55)
            row.addWidget(edit)
            row.addStretch()
            layout.addLayout(row)
            return edit

        self.sr830_overload_pct  = _thresh_row("  Overload threshold (%):", "90")
        self.sr830_lower_pct     = _thresh_row("  Lower threshold (%):", "10")
        self.sr830_stability_pct = _thresh_row("  Stability criterion (%):", "0.5")
        self.sr830_overload_pct.setToolTip(
            "Increase SENS when R > this % of full-scale. Default: 90.")
        self.sr830_lower_pct.setToolTip(
            "Decrease SENS when R < this % of full-scale. Keep well below overload to avoid oscillation. Default: 10.")
        self.sr830_stability_pct.setToolTip(
            "Stable when (max-min)/mean < this % over last 20% of wait time. Default: 0.5.")

        layout.addSpacing(6)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #555577;")
        layout.addWidget(sep2)
        layout.addSpacing(4)

        # ── Sensitivity — DSP7265 ─────────────────────────────────────────
        layout.addWidget(QLabel("Sensitivity (auto) — DSP7265:"))
        self.cb_sens_7265 = QCheckBox("DSP7265 — auto sensitivity")
        self.cb_sens_7265.setChecked(False)
        layout.addWidget(self.cb_sens_7265)

        layout.addSpacing(4)
        self.dsp_overload_pct  = _thresh_row("  Overload threshold (%):", "90")
        self.dsp_lower_pct     = _thresh_row("  Lower threshold (%):", "10")
        self.dsp_stability_pct = _thresh_row("  Stability criterion (%):", "0.5")
        self.dsp_overload_pct.setToolTip(
            "Increase SEN when MAG > this % of full-scale. Default: 90.")
        self.dsp_lower_pct.setToolTip(
            "Decrease SEN when MAG < this % of full-scale. Keep well below overload to avoid oscillation. Default: 10.")
        self.dsp_stability_pct.setToolTip(
            "Stable when (max-min)/mean < this % over last 20% of wait time. Default: 0.5.")

        layout.addSpacing(8)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setStyleSheet("color: #555577;")
        layout.addWidget(sep3)
        layout.addSpacing(4)

        self.cb_auto_proceed = QCheckBox("Auto-proceed if max wait reached")
        self.cb_auto_proceed.setChecked(True)
        self.cb_auto_proceed.setToolTip(
            "If the signal does not stabilise within 3× wait time, proceed to averaging\n"
            "automatically instead of showing a dialog. Useful for overnight runs.\n"
            "Can be toggled at any time during measurement.")
        layout.addWidget(self.cb_auto_proceed)

        layout.addSpacing(8)
        sep4 = QFrame()
        sep4.setFrameShape(QFrame.HLine)
        sep4.setStyleSheet("color: #555577;")
        layout.addWidget(sep4)
        layout.addSpacing(4)

        # ── Auto Average Time ─────────────────────────────────────────────
        layout.addWidget(QLabel("Average Time (auto):"))
        _avg_row = QHBoxLayout()
        self.cb_auto_avg_time = QCheckBox("Auto average time  —  threshold:")
        self.cb_auto_avg_time.setChecked(False)
        self.cb_auto_avg_time.setToolTip(
            "Automatically set average time based on the measurement frequency.\n"
            "  avg_time = max(threshold, ceil(1/f))\n"
            "  If 1/f > threshold  →  uses ceil(1/f)  (long period, low frequency)\n"
            "  If 1/f < threshold  →  uses threshold   (short period, high frequency)\n"
            "Applies to: IV, 1ω calibration (manual + auto), and 3ω measurement.\n"
            "Can be toggled and threshold changed at any time during measurement.")
        self.auto_avg_threshold_e = QLineEdit("60")
        self.auto_avg_threshold_e.setFixedWidth(48)
        self.auto_avg_threshold_e.setToolTip("Threshold time (s): if ceil(1/f) is below this, this value is used as avg time.")
        _avg_row.addWidget(self.cb_auto_avg_time)
        _avg_row.addWidget(self.auto_avg_threshold_e)
        _avg_row.addWidget(QLabel("s"))
        _avg_row.addStretch()
        layout.addLayout(_avg_row)

        layout.addSpacing(8)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)



# ── Background measurement thread ────────────────────────────────────────────
class MeasurementThread(QThread):
    """Runs core.measure() on a worker thread.

    Emits:
      plot_update(phase, args)   – raw callback data for the GUI to plot
      finished_ok(data)          – measurement completed normally
      finished_stop(partial)     – user pressed Stop
      finished_err(msg, partial) – unexpected exception
    """
    plot_update   = Signal(str, object)   # (phase, tuple-of-args)
    finished_ok   = Signal(object)        # completed results list
    finished_stop = Signal(object)        # partial results list
    finished_err  = Signal(str, object)   # (error message, partial results)

    def __init__(self, core, measure_kwargs):
        super().__init__()
        self._core   = core
        self._kwargs = measure_kwargs

    def _callback(self, phase, *args):
        self.plot_update.emit(phase, args)

    def run(self):
        try:
            data = self._core.measure(callback=self._callback, **self._kwargs)
            self.finished_ok.emit(data)
        except RuntimeError as exc:
            partial = getattr(self._core, 'partial_measurement_results', [])
            if str(exc) == "Measurement stopped":
                self.finished_stop.emit(partial)
            else:
                self.finished_err.emit(str(exc), partial)
        except Exception as exc:
            import traceback
            partial = getattr(self._core, 'partial_measurement_results', [])
            self.finished_err.emit(f"{exc}\n{traceback.format_exc()}", partial)

class MeasurementInterface(QMainWindow):
    # Cross-thread signal: fires on main thread to show stability dialog
    _stability_signal = Signal(float, str)   # (elapsed_s, freq_label)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FibreLab")
        _icon_path = os.path.join(
            getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))),
            'FiberLab.ico'
        )
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        self.setMinimumSize(700, 480)

        self.core = load_core_module()
        self.lockin = None
        self.lockin7265 = None
        # self.multimeter = None  # replaced by lockin7265 current measurement
        self.rm = None
        self.current_data = None
        # Created once — never recreated, so checkbox states persist across opens
        self._auto_params_dialog = AutoParamsSettingsDialog(self)
        self._1w_skip_freqs = set()  # set of round(f,9) to skip 1w calib
        self._skip_freq_dialog = SkipFreqDialog(self)
        self._auto_params_dialog._skip_btn.clicked.connect(self._open_skip_dialog)
        self._stability_check_event  = threading.Event()
        self._stability_check_result = None
        self._stability_signal.connect(self._show_stability_dialog)
        self.fit_results = None
        self.stop_requested  = False
        self.original_sleep  = None
        self._meas_thread    = None
        # True only while PhaseCalibrationWindow's manual (standalone) 1w
        # calibration is running synchronously on the GUI thread -- unlike
        # _meas_thread (the automatic sweep's QThread), there's no thread
        # object to check isRunning() on, so _meas_running() below needs
        # this explicit flag to also treat a manual calibration run as
        # "instruments busy" and route DSP7265 dialog edits through the
        # command queue instead of writing directly.
        self._manual_1w_calib_running = False
        self._last_time_draw = 0.0
        self._original_pause = None
        self._original_show = None
        self._captured_figures = []
        # Line-object tracking for real-time time-plot updates via callback
        self._time_wait_lines = {}
        self._time_avg_lines = {}
        self._last_freq_start_idx = -1
        self.instrument_status = {
            "lockin":     False,
            "lockin7265": False,
            # "multimeter": False,  # replaced by lockin7265 current measurement
        }
        self.instruments_connected = False
        self._lockin7265_params_dialog = None   # keep reference for non-modal dialog

        # Crash-safety: periodically re-write the same backup file pair
        # while a 3ω measurement is running, so a crash (not a clean stop)
        # during a long wait doesn't lose data since the last completed
        # frequency. See _silent_backup's suffix= param.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60_000)  # 60 s
        self._autosave_timer.timeout.connect(self._periodic_autosave_3w)
        # Reserved backup filename suffix for the run in progress — set once,
        # reused by every backup call (periodic/stop/complete) so there is
        # only ever one file pair per run. Reset to None at the start of
        # each new run (see on_run).
        self._backup_suffix_3w     = None
        self._backup_suffix_3w_ts  = None
        self._backup_suffix_calib  = None
        # 🔌 Load saved GPIB addresses or use defaults

        settings = load_settings()

        self.lockin_address       = settings.get("lockin_address",       self.core.LOCKIN_ADDRESS)
        self.lockin7265_address   = settings.get("lockin7265_address",   self.core.LOCKIN_7265_ADDRESS)
        # self.multimeter_address = settings.get("multimeter_address", self.core.MULTIMETER_ADDRESS)
 
        # connection state preserved

        self._build_ui()
        self._phase_calibrated = False
        self._calibrated_phase_deg = None
        # PhaseCalibrationWindow owns a matplotlib Figure/toolbar — build it
        # lazily on first use (see the _phase_calib_window property below)
        # instead of paying that cost on every app startup.
        self._phase_calib_window_impl = None

        # Time series storage (built during measurement callback)
        self._ts_t_data     = None
        self._ts_I_data     = None
        self._ts_r_data     = None
        self._ts_theta_data = None
        self._ts_freq_col   = []
        self._ts_last_len   = 0
        # Calibration time series storage
        self._calib_t_data     = None
        self._calib_r_data     = None
        self._calib_theta_data = None
        self._calib_i_data     = None

        # Measurement history for Results window (session-based)
        self._measurement_history = []  # list of dicts: {name, status, data_3w, data_iv, fit_results, params, timestamp}
        self._results_window  = None
        self._analysis_window = None
        self._math_functions_window = None
        self._latest_iv_data  = None  # track most recent IV data for pairing with 3w measurements

        self.setStyleSheet("""
        QWidget {background:#1e1e2f; color:white;}
        QPushButton {background:#3a86ff; padding:5px; border-radius:6px;}
        QPushButton:hover {background:#5aa0ff;}
        QLineEdit {background:#2b2b3d;}
        """)



    def update_indicator(self,label,state):
        if state:
            label.setText("● Connected")
            label.setStyleSheet("color:green;font-weight:bold;")
        else:
            label.setText("● Disconnected")
            label.setStyleSheet("color:red;font-weight:bold;")
            
    def edit_gpib_address(self, instrument):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Set {instrument} GPIB Address")
     
        layout = QVBoxLayout(dialog)
     
        entry = QLineEdit()
        if instrument == "Lock-in":
            entry.setText(self.lockin_address)
        elif instrument == "Lock-in 7265":
            entry.setText(self.lockin7265_address)
        # else:  # Multimeter removed
        #     entry.setText(self.multimeter_address)
     
        layout.addWidget(QLabel("Enter GPIB address:"))
        layout.addWidget(entry)
     
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
     
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
     
        if dialog.exec() == QDialog.Accepted:
            addr = entry.text().strip()

            settings = load_settings()

            if instrument == "Lock-in":
                self.lockin_address = addr
                settings["lockin_address"] = addr
            elif instrument == "Lock-in 7265":
                self.lockin7265_address = addr
                settings["lockin7265_address"] = addr
            # else:  # Multimeter removed
            #     self.multimeter_address = addr
            #     settings["multimeter_address"] = addr

            save_settings(settings)

            QMessageBox.information(self, "Saved", f"{instrument} address saved:\n{addr}")
            
    def connect_lockin(self):
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
     
            # 🔴 ALWAYS close old connection
            if self.lockin is not None:
                try:
                    self.lockin.close()
                except:
                    pass
     
            # 🔴 create new connection
            self.lockin = self.rm.open_resource(self.lockin_address)
     
            # 🔴 VERIFY connection (THIS IS KEY)
            idn = self.lockin.query("*IDN?")
     
            self.core.lockin = self.lockin
            self.instrument_status["lockin"] = True
            self.update_indicator(self.lockin_indicator, True)
            self.set_status(f"Lock-in connected: {idn.strip()}")
            if all(self.instrument_status.values()):
                self.instruments_connected = True
            self._phase_calibrated = False
            self._calibrated_phase_deg = None

        except Exception as e:
            self.instrument_status["lockin"] = False
            self.update_indicator(self.lockin_indicator, False)
            QMessageBox.critical(self, "Connection Error", str(e))

    # def connect_multimeter(self):  # replaced by lockin7265 current measurement
    #     try:
    #         if self.rm is None:
    #             self.rm = pyvisa.ResourceManager()
    #         if self.multimeter is not None:
    #             try:
    #                 self.multimeter.close()
    #             except:
    #                 pass
    #         self.multimeter = self.rm.open_resource(self.multimeter_address)
    #         idn = self.multimeter.query("*IDN?")
    #         self.core.multimeter = self.multimeter
    #         self.instrument_status["multimeter"] = True
    #         self.update_indicator(self.meter_indicator, True)
    #         self.set_status(f"Multimeter connected: {idn.strip()}")
    #         if all(self.instrument_status.values()):
    #             self.instruments_connected = True
    #     except Exception as e:
    #         self.instrument_status["multimeter"] = False
    #         self.update_indicator(self.meter_indicator, False)
    #         QMessageBox.critical(self, "Connection Error", str(e))

    def connect_lockin7265(self):
        from pymeasure.instruments.signalrecovery import DSP7265
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            if self.lockin7265 is not None:
                try:
                    self.lockin7265.adapter.close()
                except Exception:
                    pass
            self.lockin7265 = DSP7265(self.lockin7265_address)
            idn = self.lockin7265.ask("ID?")
            self.core.lockin7265 = self.lockin7265
            self.instrument_status["lockin7265"] = True
            self.update_indicator(self.lockin7265_indicator, True)
            self.set_status(f"Lock-in 7265 connected: {idn.strip()}")
            if all(self.instrument_status.values()):
                self.instruments_connected = True
        except Exception as e:
            self.instrument_status["lockin7265"] = False
            self.update_indicator(self.lockin7265_indicator, False)
            QMessageBox.critical(self, "Connection Error", str(e))

    def _load_main_settings(self):
        s = load_settings()
        for key, entry in self.entries.items():
            sk = f"main_{key}"
            if sk in s:
                entry.setText(str(s[sk]))
        if "main_save_dir" in s:
            self.save_dir_entry.setText(s["main_save_dir"])
        if "main_save_name" in s:
            self.save_name_entry.setText(s["main_save_name"])
        if "main_filetype" in s:
            idx = self.filetype_box.findText(s["main_filetype"])
            if idx >= 0:
                self.filetype_box.setCurrentIndex(idx)
        if "freq_range_3w" in s:
            try:
                self.freq_range_widget.set_config(s["freq_range_3w"])
            except Exception:
                pass

    def _save_main_settings(self):
        s = load_settings()
        for key, entry in self.entries.items():
            s[f"main_{key}"] = entry.text()
        s["main_save_dir"]   = self.save_dir_entry.text()
        s["main_save_name"]  = self.save_name_entry.text()
        s["main_filetype"]   = self.filetype_box.currentText()
        s["freq_range_3w"]   = self.freq_range_widget.get_config()
        save_settings(s)

    def closeEvent(self, event):
        self._save_main_settings()
        event.accept()

    def connect_all_instruments(self):
        self.connect_lockin()
        # self.connect_multimeter()  # replaced by lockin7265 current measurement
        self.connect_lockin7265()
        if all(self.instrument_status.values()):
            self.instruments_connected=True
            self.set_status("All instruments connected")

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        left_panel = QWidget()
        right_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        right_layout = QVBoxLayout(right_panel)

        # Parameters panel doesn't grow on its own when the window is
        # resized/maximized (stretch factor 0, below) but stays manually
        # draggable via the splitter handle — Minimum (not Fixed) lets the
        # splitter widen/narrow it on demand.
        left_panel.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # The params panel content has a fixed natural height; if the window
        # gets shorter than that, scroll it instead of squashing/overlapping
        # the buttons and entry fields.
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_panel)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)

        self.entries = {}
        self._committed_params = {}
        params = [
            ("AC_VOLTAGE (V)", 0.006),
            ("test_freq (Hz)", 1.0),
            ("STABILIZATION_TIME (s)", 2.0),
            ("WAIT_TIME (s) [global]", 5 * 60),
            ("AVERAGE_TIME (s)", 1 * 60),
            ("dt (s)", 0.2),
            ("R (Ohm)", 60.0),
            ("r (Ohm/K)", 1.0),
            ("L (m)", 2.2e-3),
            ("S (m²)", 250e-12),
        ]

        form = QFormLayout()

        # ── AC Current — linked convenience field for AC_VOLTAGE ───────────
        # Purely a UI convenience: only AC_VOLTAGE is ever sent to the
        # hardware/core, and read_parameters() below never reads this field.
        # Typing a desired AC Current here back-computes the AC_VOLTAGE that
        # would produce it, via the live Safety Control CURRENT_CONVERSION_FACTOR,
        # so the user never has to do that division by hand. Editing AC_VOLTAGE
        # keeps this field in sync too (see _sync_ac_current_from_voltage /
        # _sync_ac_voltage_from_current).
        self._ac_link_updating = False
        self.ac_current_entry = QLineEdit()

        ac_cur_tick = QPushButton("✓")
        ac_cur_tick.setFixedSize(22, 22)
        ac_cur_tick.setToolTip("Apply the corresponding AC Voltage to the running measurement")
        ac_cur_tick.setStyleSheet(
            "background:#2d6a2d; color:white; border-radius:3px;"
            " font-size:11px; font-weight:bold; padding:0px;"
        )
        ac_cur_tick.clicked.connect(
            lambda: self._commit_param('AC_VOLTAGE', self.entries['AC_VOLTAGE']))

        ac_cur_row_w = QWidget()
        ac_cur_row_l = QHBoxLayout(ac_cur_row_w)
        ac_cur_row_l.setContentsMargins(0, 0, 0, 0)
        ac_cur_row_l.setSpacing(3)
        ac_cur_row_l.addWidget(self.ac_current_entry)
        ac_cur_row_l.addWidget(ac_cur_tick)
        form.addRow(QLabel("AC Current (A)"), ac_cur_row_w)

        self.ac_link_frame, self.ac_link_text = _make_conversion_link_card()
        self.ac_link_frame.setToolTip(
            "AC Current and AC Voltage are linked live through the active "
            "Safety Control conversion factor k. Edit either field — the "
            "experiment always runs at the AC Voltage value shown below.")
        form.addRow(QLabel(""), self.ac_link_frame)

        for name, default in params:
            key = name.split(' ')[0]
            entry = QLineEdit(str(default))
            self._committed_params[key] = float(default)

            tick_btn = QPushButton("✓")
            tick_btn.setFixedSize(22, 22)
            tick_btn.setToolTip("Apply this value to the running measurement")
            tick_btn.setStyleSheet(
                "background:#2d6a2d; color:white; border-radius:3px;"
                " font-size:11px; font-weight:bold; padding:0px;"
            )
            tick_btn.clicked.connect(lambda checked, k=key, e=entry: self._commit_param(k, e))
            entry.textChanged.connect(lambda text, k=key, e=entry: self._mark_param_pending(k, e, text))

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(3)
            row_l.addWidget(entry)
            row_l.addWidget(tick_btn)

            form.addRow(QLabel(name), row_w)
            self.entries[key] = entry

            if key == "AC_VOLTAGE":
                entry.textChanged.connect(lambda _t: self._sync_ac_current_from_voltage())
                self.ac_current_entry.textChanged.connect(lambda _t: self._sync_ac_voltage_from_current())
                self._sync_ac_current_from_voltage()   # initial populate
                self._refresh_ac_link_label()

        # Frequency sweep widget — replaces START_FREQ/END_FREQ/FREQ_STEP
        form.addRow(QLabel("Frequencies:"), QLabel(""))  # spacer row label
        left_layout.addLayout(form)

        self.freq_range_widget = FrequencyRangeWidget()
        left_layout.addWidget(self.freq_range_widget)

        # ── Safety Control ──────────────────────────────────────────────
        safety_box = QGroupBox("Safety Control")
        safety_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #555577;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 12px;
                color: #e0e0f0;
                font-weight: bold;
                font-size: 11px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
            }
        """)
        safety_layout = QVBoxLayout(safety_box)
        safety_layout.setSpacing(6)

        _safety_toggle_style = """
            QPushButton {
                background: #2e2e40;
                color: #aaaacc;
                border: 1px solid #444466;
                border-radius: 5px;
                padding: 7px 6px;
                font-weight: bold;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #3a3a55;
                color: #ffffff;
            }
            QPushButton:checked {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #00c6a7, stop:1 #0077ff);
                color: #ffffff;
                border: 1px solid #00e0be;
            }
        """

        src_row = QHBoxLayout()
        src_row.setSpacing(6)
        self.safety_low_src_btn  = QPushButton("Low current source")
        self.safety_high_src_btn = QPushButton("High current source")
        for _b in (self.safety_low_src_btn, self.safety_high_src_btn):
            _b.setCheckable(True)
            _b.setStyleSheet(_safety_toggle_style)
            src_row.addWidget(_b)
        safety_layout.addLayout(src_row)

        self._safety_src_group = QButtonGroup(self)
        self._safety_src_group.setExclusive(True)
        self._safety_src_group.addButton(self.safety_low_src_btn)
        self._safety_src_group.addButton(self.safety_high_src_btn)

        # Sub-range choice — visually nested under "High current source"
        # (indented, captioned, distinct amber accent) since it's a
        # second-tier choice only meaningful when that option is selected.
        _safety_subrange_style = """
            QPushButton {
                background: #26263a;
                color: #999ab0;
                border: 1px solid #3a3a55;
                border-radius: 4px;
                padding: 5px 6px;
                font-weight: 600;
                font-size: 9px;
            }
            QPushButton:hover {
                background: #33334a;
                color: #ffffff;
            }
            QPushButton:checked {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #ff9f43, stop:1 #ffcd56);
                color: #1e1e2f;
                border: 1px solid #ffcd56;
            }
        """

        self.safety_range_widget = QWidget()
        range_outer = QVBoxLayout(self.safety_range_widget)
        range_outer.setContentsMargins(18, 2, 0, 0)  # indent = nested under High current source
        range_outer.setSpacing(3)

        range_caption = QLabel("↳ High current source range:")
        range_caption.setStyleSheet("color:#888899; font-size:9px; font-weight:normal; border:none;")
        range_outer.addWidget(range_caption)

        range_row = QHBoxLayout()
        range_row.setContentsMargins(0, 0, 0, 0)
        range_row.setSpacing(6)
        self.safety_low_range_btn  = QPushButton("Low range (0–0.5 mA)")
        self.safety_high_range_btn = QPushButton("High range (0–1 A)")
        for _b in (self.safety_low_range_btn, self.safety_high_range_btn):
            _b.setCheckable(True)
            _b.setStyleSheet(_safety_subrange_style)
            range_row.addWidget(_b)
        range_outer.addLayout(range_row)
        safety_layout.addWidget(self.safety_range_widget)

        self._safety_range_group = QButtonGroup(self)
        self._safety_range_group.setExclusive(True)
        self._safety_range_group.addButton(self.safety_low_range_btn)
        self._safety_range_group.addButton(self.safety_high_range_btn)

        left_layout.addWidget(safety_box)

        # Resistance-safety state — the R value (if any) already confirmed
        # via the double-confirm dialog; persists until R is edited again.
        self._safety_r_confirmed_value = None

        # Restore last-used selection — persists across measurements and app
        # restarts until explicitly switched, same pattern as other params.
        def _save_safety_settings():
            _s = load_settings()
            _s["safety_current_source"] = "high" if self.safety_high_src_btn.isChecked() else "low"
            _s["safety_current_range"]  = "high_range" if self.safety_high_range_btn.isChecked() else "low_range"
            save_settings(_s)

        def _apply_safety_mode_to_core():
            """Push the selected source+range to core — safety_check() reads
            these live every poll. CURRENT_LIMIT/CURRENT_CONVERSION_FACTOR
            are set per the exact combination selected; VOLTAGE_LIMIT (low
            source) / VOLTAGE_LIMIT_HIGH_SOURCE (high source) are fixed
            constants already defined in core.py."""
            _mode  = "high" if self.safety_high_src_btn.isChecked() else "low"
            _range = "high_range" if self.safety_high_range_btn.isChecked() else "low_range"
            try:
                self.core.SAFETY_CURRENT_SOURCE = _mode
                self.core.SAFETY_CURRENT_RANGE  = _range
                if _mode == "low":
                    self.core.CURRENT_LIMIT = 0.01                # 10 mA
                    self.core.CURRENT_CONVERSION_FACTOR = 1e-3    # 1 V = 1 mA
                elif _range == "high_range":
                    self.core.CURRENT_LIMIT = 1.0                 # 1 A
                    self.core.CURRENT_CONVERSION_FACTOR = 1.0     # 1 V = 1 A
                else:  # high source, low range
                    self.core.CURRENT_LIMIT = 0.5e-3              # 0.5 mA
                    self.core.CURRENT_CONVERSION_FACTOR = 1e-3    # 1 V = 1 mA
            except Exception:
                pass

        def _on_safety_source_toggled(checked):
            self.safety_range_widget.setVisible(self.safety_high_src_btn.isChecked())
            _apply_safety_mode_to_core()
            # Conversion factor just changed — re-derive AC_VOLTAGE from the
            # AC Current field so the pair stays consistent with the new mode.
            self._sync_ac_voltage_from_current()
            self._refresh_ac_link_label()
            _save_safety_settings()
            self._revalidate_resistance_safety()

        def _on_safety_range_toggled(checked):
            _apply_safety_mode_to_core()
            self._sync_ac_voltage_from_current()
            self._refresh_ac_link_label()
            _save_safety_settings()
            self._revalidate_resistance_safety()

        _safety_settings = load_settings()
        if _safety_settings.get("safety_current_source", "low") == "high":
            self.safety_high_src_btn.setChecked(True)
        else:
            self.safety_low_src_btn.setChecked(True)
        if _safety_settings.get("safety_current_range", "low_range") == "high_range":
            self.safety_high_range_btn.setChecked(True)
        else:
            self.safety_low_range_btn.setChecked(True)
        self.safety_range_widget.setVisible(self.safety_high_src_btn.isChecked())
        _apply_safety_mode_to_core()
        # A saved non-default safety mode may have just changed the
        # conversion factor away from what the params form assumed at
        # construction — re-derive AC_VOLTAGE from AC Current to match.
        self._sync_ac_voltage_from_current()
        self._refresh_ac_link_label()

        self.safety_high_src_btn.toggled.connect(_on_safety_source_toggled)
        self.safety_low_src_btn.toggled.connect(_on_safety_source_toggled)
        self.safety_low_range_btn.toggled.connect(_on_safety_range_toggled)
        self.safety_high_range_btn.toggled.connect(_on_safety_range_toggled)

        # Small 7265 params button — placed prominently above Connect All
        self.lockin7265_params_button = QPushButton("lockin7265 Params")
        self.lockin7265_params_button.setStyleSheet(
            "background:#6c4f9e; color:white; padding:3px 8px;"
            " border-radius:4px; font-size:10px; font-weight:bold;"
        )
        self.lockin7265_params_button.clicked.connect(self.open_lockin7265_params_dialog)
        left_layout.addWidget(self.lockin7265_params_button)

        self.connect_all_button=QPushButton("Connect All Instruments")
        self.connect_all_button.clicked.connect(self.connect_all_instruments)
        left_layout.addWidget(self.connect_all_button)

        self.run_button = QPushButton("Run Measurement")

        self.lockin_params_button = QPushButton("Lockin params")
        self.lockin_params_button.clicked.connect(self.open_lockin_params_dialog)
        left_layout.addWidget(self.lockin_params_button)

        self.auto_params_cb = AutoParamsButton()
        self.auto_params_cb.setToolTip(
            "Auto time constant based on frequency.\n"
            "Double-click to select which instruments are controlled."
        )
        self.auto_params_cb.settingsRequested.connect(self._open_auto_params_settings)
        left_layout.addWidget(self.auto_params_cb)

        self.iv_button = QPushButton("Check IV")
        self.iv_button.clicked.connect(self.open_iv_dialog)
        left_layout.addWidget(self.iv_button)

        self.phase_calib_btn = QPushButton("1ω Phase Calibration")
        self.phase_calib_btn.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #00c6a7, stop:1 #0077ff);"
            "color:white; font-weight:bold; border-radius:5px; padding:5px 4px;")
        self.phase_calib_btn.clicked.connect(self.open_phase_calibration)
        left_layout.addWidget(self.phase_calib_btn)

        self.run_button.clicked.connect(self.on_run)
        left_layout.addWidget(self.run_button)

        self.stop_button = QPushButton("Stop Measurement")
        self.stop_button.clicked.connect(self.on_stop)
        self.stop_button.setEnabled(False)
        left_layout.addWidget(self.stop_button)

        self.fit_button = QPushButton("Fit Data")
        self.fit_button.clicked.connect(self.open_fit_dialog)
        self.fit_button.setEnabled(False)
        left_layout.addWidget(self.fit_button)

        self.results_button = QPushButton("📋  Results")
        self.results_button.clicked.connect(self.open_results)
        left_layout.addWidget(self.results_button)

        self.analysis_button = QPushButton("📈  Analysis")
        self.analysis_button.clicked.connect(self.open_analysis)
        left_layout.addWidget(self.analysis_button)

        self.run_button.setStyleSheet("background:#3be362; color:black; padding:5px 8px;")
        self.fit_button.setStyleSheet("background:#3be362; color:black; padding:5px 8px;")
        self.stop_button.setStyleSheet("background:#e35f3b; color:white; padding:5px 8px;")
        _data_btn_style = (
            "QPushButton {"
            "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "    stop:0 #818cf8, stop:1 #4f46e5);"
            "  color: white;"
            "  font-weight: bold;"
            "  padding: 5px 8px;"
            "  text-align: center;"
            "}"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "    stop:0 #a5b4fc, stop:1 #6366f1);"
            "}"
        )
        self.results_button.setStyleSheet(_data_btn_style)
        self.analysis_button.setStyleSheet(_data_btn_style)

        self.save_dir_entry = QLineEdit("")
        self.save_dir_entry.setEnabled(True)
        self.save_name_entry = QLineEdit("Sample_Thermal_conductivity")
        self.save_name_entry.setEnabled(True)

        row = QHBoxLayout()
        self.browse_btn = QPushButton("Browse")
        def browse_folder():
            _s = load_settings()
            _start = _s.get("last_browse_dir", "")
            folder = QFileDialog.getExistingDirectory(self, "Select Folder", _start)
            if folder:
                self.save_dir_entry.setText(folder)
                _s["last_browse_dir"] = folder
                save_settings(_s)
        self.browse_btn.clicked.connect(browse_folder)
        row.addWidget(self.save_dir_entry)
        row.addWidget(self.browse_btn)

        save_form = QFormLayout()
        save_form.addRow(QLabel("Save folder:"), row)
        save_form.addRow(QLabel("Save file name:"), self.save_name_entry)

        self.filetype_box = QComboBox()
        self.filetype_box.addItems([".csv",".txt"])

        settings = load_settings()
        last = settings.get("filetype",".csv")
        idx = self.filetype_box.findText(last)
        if idx>=0: self.filetype_box.setCurrentIndex(idx)

        save_form.addRow(QLabel("File type:"), self.filetype_box)
        left_layout.addLayout(save_form)

        self.save_button = QPushButton("Save Data")
        self.save_button.clicked.connect(self.save_data)
        self.save_button.setEnabled(False)
        left_layout.addWidget(self.save_button)

        # ===== Equal button widths =====
        def _set_equal_button_widths():
            buttons = [
                self.connect_all_button,
                self.lockin_params_button,
                self.phase_calib_btn,
                self.iv_button,
                self.run_button,
                self.stop_button,
                self.fit_button,
                self.results_button,
                self.analysis_button,
                self.save_button
            ]
            max_w = max(b.sizeHint().width() for b in buttons)
            for b in buttons:
                b.setMinimumWidth(max_w)

        QTimer.singleShot(0, _set_equal_button_widths)


        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        box=QFrame()
        g=QGridLayout(box)
        g.addWidget(QLabel("Lock-in"),0,0)
        self.lockin_indicator=QLabel("● Disconnected")
        self.lockin_indicator.setStyleSheet("color:red;")
        g.addWidget(self.lockin_indicator,0,1)
        b1 = QPushButton("Connect")
        b1.clicked.connect(self.connect_lockin)
         
        plug1 = QPushButton("🔌")
        plug1.setFixedWidth(30)
        plug1.clicked.connect(lambda: self.edit_gpib_address("Lock-in"))
         
        g.addWidget(b1, 0, 2)
        g.addWidget(plug1, 0, 3)

        # Multimeter row removed — current measured via lockin7265 (1 V = 1 mA)
        # g.addWidget(QLabel("Multimeter"),1,0)
        # self.meter_indicator=QLabel("● Disconnected")
        # self.meter_indicator.setStyleSheet("color:red;")
        # g.addWidget(self.meter_indicator,1,1)
        # b2 = QPushButton("Connect")
        # b2.clicked.connect(self.connect_multimeter)
        # plug2 = QPushButton("🔌")
        # plug2.setFixedWidth(30)
        # plug2.clicked.connect(lambda: self.edit_gpib_address("Multimeter"))
        # g.addWidget(b2, 1, 2)
        # g.addWidget(plug2, 1, 3)

        g.addWidget(QLabel("Lock-in 7265"), 2, 0)
        self.lockin7265_indicator = QLabel("● Disconnected")
        self.lockin7265_indicator.setStyleSheet("color:red;")
        g.addWidget(self.lockin7265_indicator, 2, 1)
        b3 = QPushButton("Connect")
        b3.clicked.connect(self.connect_lockin7265)
        plug3 = QPushButton("🔌")
        plug3.setFixedWidth(30)
        plug3.clicked.connect(lambda: self.edit_gpib_address("Lock-in 7265"))
        g.addWidget(b3, 2, 2)
        g.addWidget(plug3, 2, 3)

        left_layout.addWidget(box)

        self.math_functions_btn = QPushButton("🧮  MathFunctions")
        self.math_functions_btn.setStyleSheet(_data_btn_style)
        self.math_functions_btn.clicked.connect(self.open_math_functions)
        left_layout.addWidget(self.math_functions_btn)

        # ===== SR830 active params status box =====
        lockin_status_frame = QFrame()
        lockin_status_frame.setFrameShape(QFrame.StyledPanel)
        lockin_status_frame.setStyleSheet("QFrame { border:1px solid #444; border-radius:4px; }")
        lsf_layout = QVBoxLayout(lockin_status_frame)
        lsf_layout.setContentsMargins(5, 3, 5, 3)
        lsf_layout.setSpacing(1)
        lsf_title = QLabel("SR830 settings (active):")
        lsf_title.setStyleSheet("color:gray; font-size:11px; border:none;")
        lsf_layout.addWidget(lsf_title)
        self.lockin_status_box_label = QLabel()
        self.lockin_status_box_label.setWordWrap(True)
        self.lockin_status_box_label.setStyleSheet("color:#3be362; font-size:11px; border:none;")
        lsf_layout.addWidget(self.lockin_status_box_label)
        left_layout.addWidget(lockin_status_frame)

        # ===== DSP7265 active params status box =====
        dsp_status_frame = QFrame()
        dsp_status_frame.setFrameShape(QFrame.StyledPanel)
        dsp_status_frame.setStyleSheet("QFrame { border:1px solid #444; border-radius:4px; }")
        dsf_layout = QVBoxLayout(dsp_status_frame)
        dsf_layout.setContentsMargins(5, 3, 5, 3)
        dsf_layout.setSpacing(1)
        dsf_title = QLabel("DSP7265 settings (active):")
        dsf_title.setStyleSheet("color:gray; font-size:11px; border:none;")
        dsf_layout.addWidget(dsf_title)
        self.dsp7265_status_box_label = QLabel()
        self.dsp7265_status_box_label.setWordWrap(True)
        self.dsp7265_status_box_label.setStyleSheet("color:#5bc8f5; font-size:11px; border:none;")
        dsf_layout.addWidget(self.dsp7265_status_box_label)
        left_layout.addWidget(dsp_status_frame)

        # Live refresh timer — updates both status boxes every second during measurement
        self._lockin_refresh_timer = QTimer(self)
        self._lockin_refresh_timer.setInterval(1000)
        self._lockin_refresh_timer.timeout.connect(self._refresh_all_lockin_status)
        self._lockin_refresh_timer.start()
        QTimer.singleShot(0, self._refresh_all_lockin_status)

        left_layout.addStretch(1)

        QTimer.singleShot(0, self._load_main_settings)

        footer = QLabel("© 2026 Vigneswaran Ravi")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color:white; margin-top:10px;")
        left_layout.addWidget(footer)

        self.time_frame = QWidget()
        self.time_frame.setLayout(QVBoxLayout())

        # ── Start Averaging button ────────────────────────────────────────────
        self.force_avg_btn = QPushButton("▶ Start Average")
        self.force_avg_btn.setEnabled(False)
        self.force_avg_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.force_avg_btn.setToolTip(
            "Skip remaining wait time and start averaging immediately for the current frequency.")
        self.force_avg_btn.setStyleSheet(
            "QPushButton { background:#e8a020; color:black; font-weight:bold;"
            "  padding:4px 12px; border-radius:4px; border:1px solid #c07010; }"
            "QPushButton:hover { background:#f0b030; }"
            "QPushButton:disabled { background:#555; color:#999; border-color:#444; }"
        )
        self.force_avg_btn.clicked.connect(self._force_averaging_now)
        _fa_row = QHBoxLayout()
        _fa_row.addWidget(self.force_avg_btn)
        _fa_row.addStretch(1)
        self.time_frame.layout().addLayout(_fa_row)

        self.fig_time = Figure(figsize=(7, 14.0), dpi=100)
        (self.ax_time_x, self.ax_time_y, self.ax_time_r,
         self.ax_time_I, self.ax_time_theta) = self.fig_time.subplots(5, 1, sharex=True)
        self.fig_time.suptitle("X, Y, V₃ω, I, θ vs Time (all frequencies)")
        self.ax_time_x.set_ylabel("X (V)")
        self.ax_time_y.set_ylabel("Y (V)")
        self.ax_time_r.set_ylabel(r"$V_{3\omega}$ (V)")
        self.ax_time_I.set_ylabel("I (µA)")
        self.ax_time_theta.set_ylabel("θ (°)")
        self.ax_time_theta.set_xlabel("Time (s)")
        self.canvas_time = FigureCanvas(self.fig_time)
        self.canvas_time.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._toolbar_time = NavigationToolbar(self.canvas_time, self)
        self._toolbar_time.hide()
        scroll_time = QScrollArea()
        scroll_time.setWidget(self.canvas_time)
        scroll_time.setWidgetResizable(True)
        scroll_time.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_time.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.time_frame.layout().addWidget(scroll_time)
        self._apply_embedded_style_to_fig(self.fig_time)

        self.summary_frame = QWidget()
        self.summary_frame.setLayout(QVBoxLayout())
        self.fig_summary = Figure(figsize=(7, 18.0), dpi=100)
        (self.ax_summary_x, self.ax_summary_y, self.ax_summary_r,
         self.ax_summary_theta) = self.fig_summary.subplots(4, 1, sharex=True)
        self.fig_summary.suptitle("X, Y, V₃ω, θ vs Frequency")
        self.ax_summary_x.set_ylabel("X (V)")
        self.ax_summary_y.set_ylabel("Y (V)")
        self.ax_summary_r.set_ylabel(r"$V_{3\omega}$ (V)")
        self.ax_summary_theta.set_ylabel("θ (°)")
        self.ax_summary_theta.set_xlabel("Frequency (Hz)")
        self.canvas_summary = FigureCanvas(self.fig_summary)
        self.canvas_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._toolbar_summary = NavigationToolbar(self.canvas_summary, self)
        self._toolbar_summary.hide()
        scroll_summary = QScrollArea()
        scroll_summary.setWidget(self.canvas_summary)
        scroll_summary.setWidgetResizable(True)
        scroll_summary.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_summary.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.summary_frame.layout().addWidget(scroll_summary)
        self._apply_embedded_style_to_fig(self.fig_summary)

        right_layout.addWidget(self.time_frame, 1)
        right_layout.addWidget(self.summary_frame, 1)

        # ── Zoom toggle button ────────────────────────────────────────────────
        self.zoom_button = QPushButton("🔍 Zoom")
        self.zoom_button.setCheckable(True)
        self.zoom_button.setToolTip(
            "Enable: click and drag on a plot to zoom in.\n"
            "Click again to disable zoom and reset view."
        )
        self.zoom_button.setStyleSheet(
            "QPushButton { background:#2b2b3d; color:white; border:1px solid #555577;"
            "  padding:3px 10px; border-radius:4px; }"
            "QPushButton:checked { background:#3a86ff; color:white; }"
        )
        self.zoom_button.toggled.connect(self._toggle_zoom)
        zoom_row = QHBoxLayout()
        zoom_row.addStretch(1)
        zoom_row.addWidget(self.zoom_button)
        right_layout.addLayout(zoom_row)

        # Lock the parameters panel to its natural content width so resizing
        # or maximizing the window only grows/shrinks the plot area.
        def _set_left_panel_min_width():
            # Floor only — prevents auto-shrinking when the main window is
            # resized/maximized, but the splitter handle can still be
            # dragged wider since this is a minimum, not a fixed width.
            w = left_panel.sizeHint().width() + 2
            left_panel.setMinimumWidth(w)
            left_scroll.setMinimumWidth(w + left_scroll.frameWidth() * 2)
        QTimer.singleShot(0, _set_left_panel_min_width)

    def _toggle_zoom(self, checked: bool):
        for toolbar in (self._toolbar_time, self._toolbar_summary):
            if checked:
                # Enable rectangle zoom mode (first call activates it)
                if toolbar.mode.name != 'ZOOM':
                    toolbar.zoom()
            else:
                # Disable zoom mode if active, then reset to full view
                if toolbar.mode.name == 'ZOOM':
                    toolbar.zoom()   # toggles zoom off
                toolbar.home()       # restore default view

    def set_status(self, message: str):
        self.status_label.setText(message)
        QApplication.processEvents()

    def get_param(self, name: str, dtype=float):
        return dtype(self.entries[name].text().strip())

    def read_parameters(self):
        _freqs = self.freq_range_widget.get_frequencies()
        _start = _freqs[0]  if _freqs else 1.0
        _end   = _freqs[-1] if _freqs else 1.0
        _step  = (_end - _start) / max(len(_freqs) - 1, 1) if len(_freqs) > 1 else 1.0
        return {
            "AC_VOLTAGE": float(self.entries["AC_VOLTAGE"].text()),
            # Snapshotted here (not recomputed later) so every saved/historical
            # record reflects the conversion factor that was actually active
            # for this run, even if Safety Control mode is changed afterward.
            "AC_CURRENT": float(self.entries["AC_VOLTAGE"].text()) * self._ac_current_conversion_factor(),
            # Keep legacy keys so assign_parameters_to_core sets them on core
            "START_FREQ": _start,
            "END_FREQ":   _end,
            "FREQ_STEP":  _step,
            "FREQUENCIES": _freqs,
            "test_freq": float(self.entries["test_freq"].text()),
            "STABILIZATION_TIME": float(self.entries["STABILIZATION_TIME"].text()),
            "WAIT_TIME": float(self.entries["WAIT_TIME"].text()),
            "AVERAGE_TIME": float(self.entries["AVERAGE_TIME"].text()),
            "dt": float(self.entries["dt"].text()),
            "R": float(self.entries["R"].text()),
            "r": float(self.entries["r"].text()),
            "L": float(self.entries["L"].text()),
            "S": float(self.entries["S"].text()),
        }

    def _ac_current_conversion_factor(self):
        """The live Safety-Control conversion factor (A per V of AC_VOLTAGE),
        kept up to date by _apply_safety_mode_to_core() as the source/range
        toggles change."""
        return getattr(self.core, 'CURRENT_CONVERSION_FACTOR', 1e-3) or 1e-3

    def _safety_mode_display_text(self):
        """Human-readable label for whichever Safety Control mode currently
        determines the conversion factor k. Reads core state directly
        (rather than the toggle-button widgets) so it's safe to call before
        the Safety Control box has been built."""
        src = getattr(self.core, 'SAFETY_CURRENT_SOURCE', 'low')
        if src != 'high':
            return "Low current source"
        rng = getattr(self.core, 'SAFETY_CURRENT_RANGE', 'low_range')
        return "High source · High range" if rng == 'high_range' else "High source · Low range"

    def _refresh_ac_link_label(self):
        """Purely cosmetic: refresh the fancy link card's live k display.
        Called wherever the conversion factor itself may have changed —
        never affects the actual AC Current/AC_VOLTAGE values."""
        if not hasattr(self, 'ac_link_text'):
            return
        k = self._ac_current_conversion_factor()
        k_txt = f"{k * 1e3:g} mA/V" if k < 1.0 else f"{k:g} A/V"
        self.ac_link_text.setText(
            "<b>I&nbsp;=&nbsp;V&nbsp;&times;&nbsp;k</b>"
            "&nbsp;&nbsp;|&nbsp;&nbsp;"
            f"<b style='color:#7CFFEA;'>k&nbsp;=&nbsp;{k_txt}</b>"
            f"&nbsp;&nbsp;<span style='color:#c8d6e0;'>({self._safety_mode_display_text()})</span>"
        )

    def _sync_ac_current_from_voltage(self):
        """Recompute the AC Current display from the AC_VOLTAGE field."""
        if self._ac_link_updating:
            return
        try:
            voltage = float(self.entries['AC_VOLTAGE'].text())
        except (ValueError, KeyError):
            return
        self._ac_link_updating = True
        try:
            current = voltage * self._ac_current_conversion_factor()
            self.ac_current_entry.setText(f"{current:.6g}")
        finally:
            self._ac_link_updating = False

    def _sync_ac_voltage_from_current(self):
        """Recompute AC_VOLTAGE from the AC Current field (reverse direction —
        this is the calculation the user is asking for: type a desired
        current, get the driving voltage that would produce it)."""
        if self._ac_link_updating:
            return
        try:
            current = float(self.ac_current_entry.text())
        except (ValueError, AttributeError):
            return
        factor = self._ac_current_conversion_factor()
        if factor == 0:
            return
        self._ac_link_updating = True
        try:
            voltage = current / factor
            self.entries['AC_VOLTAGE'].setText(f"{voltage:.6g}")
        finally:
            self._ac_link_updating = False

    def _mark_param_pending(self, key, entry, text):
        """Yellow border when the field value differs from the last committed value."""
        try:
            current = float(text)
            committed = self._committed_params.get(key)
            pending = committed is None or abs(current - committed) > 1e-15
        except (ValueError, TypeError):
            pending = True
        entry.setStyleSheet(
            "border:1px solid #ffaa00; background:#2a2000;" if pending else ""
        )

    def _commit_param(self, key, entry):
        """Apply the field value immediately and clear the pending indicator."""
        try:
            value = float(entry.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Value",
                                f"'{entry.text()}' is not a valid number for {key}.")
            return
        self._committed_params[key] = value
        entry.setStyleSheet("")
        setattr(self.core, key, value)
        if key == "R":
            self._revalidate_resistance_safety()

    # ── High current source resistance safety ───────────────────────────────
    # Only meaningful when High current source is selected: Low range's safe
    # R ceiling is 1800 Ohm, High range's is 9 Ohm. Checked whenever R is
    # committed (tick clicked — never on every keystroke), whenever the
    # source/range toggles change, and as a final gate right before Run.

    def _current_range_resistance_limit(self):
        """(limit_ohm, range_label) for the selected High-source range, or
        None if Low current source is selected (check doesn't apply)."""
        if not self.safety_high_src_btn.isChecked():
            return None
        if self.safety_high_range_btn.isChecked():
            return (9.0, "High range (0–1 A)")
        return (1800.0, "Low range (0–0.5 mA)")

    def _show_resistance_warning(self, r_val, limit, range_name):
        """Warn -> Proceed -> double-confirm flow. Returns True only if the
        user explicitly confirmed proceeding at this resistance."""
        while True:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Resistance Safety Warning")
            box.setText(
                f"Entered resistance (R = {r_val:.4g} Ω) exceeds the safe limit "
                f"for {range_name}: {limit:.4g} Ω.\n\n"
                "Proceeding at this resistance in this current range can damage the instrument."
            )
            ok_btn = box.addButton("OK — Re-enter value", QMessageBox.RejectRole)
            proceed_btn = box.addButton("Proceed", QMessageBox.AcceptRole)
            box.setDefaultButton(ok_btn)
            box.exec()
            if box.clickedButton() is not proceed_btn:
                return False
            confirm = QMessageBox.warning(
                self, "Confirm — Risk of Instrument Damage",
                f"Are you SURE you want to proceed with R = {r_val:.4g} Ω on {range_name}?\n\n"
                "This exceeds the safe resistance limit and may damage the instrument.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if confirm == QMessageBox.Yes:
                self._safety_r_confirmed_value = r_val
                return True
            # No -> loop back to the first warning dialog

    def _check_safety_resistance(self, r_val, interactive=True):
        """True if r_val is safe (or already confirmed for this exact value
        — persists until R changes). If interactive and unsafe, runs the
        warn/proceed/double-confirm flow."""
        _info = self._current_range_resistance_limit()
        if _info is None:
            return True  # Low current source — this check doesn't apply
        limit, range_name = _info
        if r_val <= limit:
            self._safety_r_confirmed_value = None
            return True
        if (self._safety_r_confirmed_value is not None
                and abs(self._safety_r_confirmed_value - r_val) < 1e-12):
            return True
        if not interactive:
            return False
        return self._show_resistance_warning(r_val, limit, range_name)

    def _revalidate_resistance_safety(self):
        """Re-check the last-committed R against whichever range is now
        selected. Called after R is committed and after the source/range
        toggles change. Mid-run: auto-stops immediately, no prompt (current
        may already be flowing through a now-unsafe resistance). Otherwise:
        interactive warn/confirm flow."""
        try:
            r_val = float(self._committed_params.get("R", 60.0))
        except (TypeError, ValueError):
            return
        _info = self._current_range_resistance_limit()
        if _info is None:
            return
        limit, range_name = _info
        _running = self._meas_thread is not None and self._meas_thread.isRunning()
        if r_val <= limit:
            self._safety_r_confirmed_value = None
            return
        if _running:
            self.on_stop()
            QMessageBox.critical(
                self, "Measurement Stopped — Resistance Safety",
                f"R = {r_val:.4g} Ω exceeds the safe limit for {range_name}: "
                f"{limit:.4g} Ω.\n\nThe measurement has been stopped automatically.")
            return
        self._check_safety_resistance(r_val, interactive=True)

    def _check_safety_resistance_before_run(self):
        """Final gate in on_run() — validates the value about to actually be
        used (current field text, same as read_parameters() uses), not just
        the last-ticked value, so an uncommitted edit can't bypass the
        check. Returns True if safe to start."""
        try:
            r_val = float(self.entries["R"].text())
        except (ValueError, KeyError):
            return True  # invalid text — existing parameter validation catches this
        return self._check_safety_resistance(r_val, interactive=True)

    def _set_lockins_float(self, to_float):
        """Set both connected lock-ins' input grounding to Float
        (to_float=True) or Ground (to_float=False): writes the hardware
        command, updates core state, and refreshes any open params-dialog
        combobox so the UI never shows a stale value. Only touches
        instruments that are actually connected.

        SR830 IGND: 0 = Float, 1 = Ground.
        DSP7265 FLOAT: 0 = Ground, 1 = Float — note the numbering is
        flipped relative to the SR830, by the instruments' own convention.
        """
        if self.instrument_status.get('lockin') and self.lockin is not None:
            ignd = 0 if to_float else 1
            try:
                self.lockin.write(f"IGND {ignd}")
            except Exception:
                pass
            self.core.LOCKIN_IGND = ignd
            dlg = getattr(self, '_lockin_params_dialog', None)
            if dlg is not None:
                try:
                    dlg.ignd_box.setCurrentIndex(ignd)
                except Exception:
                    pass
        if self.instrument_status.get('lockin7265') and self.lockin7265 is not None:
            flt = 1 if to_float else 0
            try:
                self.lockin7265.write(f"FLOAT {flt}")
            except Exception:
                pass
            self.core.LOCKIN_7265_FLOAT = flt
            dlg7265 = getattr(self, '_lockin7265_params_dialog', None)
            if dlg7265 is not None:
                try:
                    dlg7265.float_box.setCurrentIndex(flt)
                except Exception:
                    pass

    def _ensure_float_before_measurement(self):
        """Pre-flight gate for every measurement start (3ω sweep, IV, manual
        1ω calibration): the input should always be Float while actively
        measuring — Ground is the safe idle state _ground_lockins_after_measurement
        restores once a run ends. Only checks instruments that are
        connected. Returns True if safe to start (already Float, or the
        user chose to switch now); False if the user cancelled."""
        not_float = []
        if self.instrument_status.get('lockin') and getattr(self.core, 'LOCKIN_IGND', 0) != 0:
            not_float.append("SR830")
        if self.instrument_status.get('lockin7265') and getattr(self.core, 'LOCKIN_7265_FLOAT', 1) != 1:
            not_float.append("DSP7265")
        if not not_float:
            return True
        reply = QMessageBox.question(
            self, "Input Not Set to Float",
            "The following lock-in input(s) are set to Ground, not Float:\n\n"
            + "\n".join(f"  •  {n}" for n in not_float)
            + "\n\nMeasurements should run with Float input.\n"
              "Switch to Float and start?",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return False
        self._set_lockins_float(True)
        return True

    def _ground_lockins_after_measurement(self):
        """Called whenever a measurement (3ω sweep, IV, or manual 1ω
        calibration) finishes, for any reason — completed, stopped, or
        errored. Restores both connected lock-ins' input to Ground, the
        safe idle state; Float is only ever asserted right before a
        measurement starts (see _ensure_float_before_measurement)."""
        try:
            self._set_lockins_float(False)
        except Exception:
            pass

    def _sync_committed_params(self):
        """Sync committed values from UI before a new measurement starts."""
        for key, entry in self.entries.items():
            try:
                self._committed_params[key] = float(entry.text())
                entry.setStyleSheet("")
            except (ValueError, TypeError):
                pass

    def _calc_auto_avg_time(self, f):
        """Return ceil(1/f) floored by threshold if Auto Average Time is enabled, else None."""
        import math
        try:
            dlg = self._auto_params_dialog
            if not dlg.cb_auto_avg_time.isChecked():
                return None
            threshold = float(dlg.auto_avg_threshold_e.text())
        except Exception:
            return None
        if f <= 0:
            return threshold
        period = math.ceil(1.0 / f)
        return float(max(threshold, period))

    def _live_params_fn(self):
        """Return only the last *committed* values so mid-edit typos in the
        main panel do not affect a running measurement until ✓ is clicked.
        If Auto Average Time is enabled, overrides AVERAGE_TIME with ceil(1/f)."""
        _live_keys = {"AC_VOLTAGE", "STABILIZATION_TIME", "WAIT_TIME", "AVERAGE_TIME", "dt"}
        try:
            params = {k: v for k, v in self._committed_params.items() if k in _live_keys}
            # Auto average time: use current freq tracked from freq_start signal
            fw = getattr(self, 'freq_range_widget', None)
            cur_f = fw._meas_cur_freq if fw is not None else None
            if cur_f is not None:
                _auto_at = self._calc_auto_avg_time(cur_f)
                if _auto_at is not None:
                    params['AVERAGE_TIME'] = _auto_at
            return params
        except Exception:
            return {}

    def connect_instruments(self):
        from pymeasure.instruments.signalrecovery import DSP7265
        self.set_status("Connecting instruments...")
        self.rm = pyvisa.ResourceManager()
        self.lockin = self.rm.open_resource(self.core.LOCKIN_ADDRESS)
        # self.multimeter = self.rm.open_resource(self.core.MULTIMETER_ADDRESS)  # replaced by lockin7265
        self.lockin7265 = DSP7265(self.core.LOCKIN_7265_ADDRESS)
        self.core.rm = self.rm
        self.core.lockin = self.lockin
        # self.core.multimeter = self.multimeter
        self.core.lockin7265 = self.lockin7265
        identity = self.lockin.query("*IDN?").strip()
        self.set_status(f"Connected to {identity}")

    def disconnect_instruments(self):
        if self.lockin is not None:
            try:
                self.lockin.close()
            except Exception:
                pass
        # if self.multimeter is not None:  # replaced by lockin7265
        #     try:
        #         self.multimeter.close()
        #     except Exception:
        #         pass
        if self.lockin7265 is not None:
            try:
                self.lockin7265.adapter.close()
            except Exception:
                pass
        if self.rm is not None:
            try:
                self.rm.close()
            except Exception:
                pass
        self.set_status("Disconnected")

        self.instrument_status = {
            "lockin":     False,
            "lockin7265": False,
            # "multimeter": False,  # replaced by lockin7265
        }
        self.instruments_connected = False
        self.update_indicator(self.lockin_indicator, False)
        # self.update_indicator(self.meter_indicator, False)  # meter_indicator removed
        self.update_indicator(self.lockin7265_indicator, False)
        self._phase_calibrated = False
        self._calibrated_phase_deg = None
        
    def assign_parameters_to_core(self, params):
        for name, value in params.items():
            setattr(self.core, name, value)

        self.core.__dict__.update(params)

        # Capture the manually-configured TC/sensitivity baseline at the start
        # of a run, mirroring the params dialogs' "Apply" handlers. This is
        # what auto-calibration "reassert manual value" logic reads back from
        # once 1w/3w auto-calibration has overwritten the plain LOCKIN_* globals.
        if 'LOCKIN_OFLT' in params:
            self.core.LOCKIN_OFLT_MANUAL = params['LOCKIN_OFLT']
        if 'LOCKIN_SENS' in params:
            self.core.LOCKIN_SENS_MANUAL = params['LOCKIN_SENS']
        if 'LOCKIN_7265_TC' in params:
            self.core.LOCKIN_7265_TC_MANUAL = params['LOCKIN_7265_TC']
        if 'LOCKIN_7265_SENS' in params:
            self.core.LOCKIN_7265_SENS_MANUAL = params['LOCKIN_7265_SENS']

        self.core.File_directory = self.save_dir_entry.text().strip()
        self.core.path = os.path.join(self.core.File_directory, self.core.DATA_FILE)

    def _patched_sleep(self, seconds: float):
        # core.time is the process-wide `time` module, so this patch applies
        # regardless of which thread calls time.sleep() — both the manual
        # 1w-calibration path (blocks the GUI thread, needs processEvents()
        # to stay responsive) and the QThread-driven measurement path (must
        # NOT call a main-thread-only Qt API from a worker thread) go through
        # here. Only pump the Qt event loop when actually on the GUI thread.
        interval = 0.05
        elapsed = 0.0
        _on_gui_thread = QThread.currentThread() is QApplication.instance().thread()
        while elapsed < seconds:
            if self.stop_requested or getattr(self.core, 'stop_requested', False):
                raise RuntimeError("Measurement stopped")
            if _on_gui_thread:
                QApplication.processEvents()
            if self.original_sleep is not None:
                self.original_sleep(min(interval, seconds - elapsed))
            else:
                import time
                time.sleep(min(interval, seconds - elapsed))
            elapsed += interval

    def _apply_embedded_style_to_fig(self, fig, hspace=0.45):
        """Apply dark theme, compact fonts, and fixed margins to an embedded figure.

        Called before every canvas render via the fig.draw hook so styles are
        guaranteed to be consistent regardless of what matplotlib resets internally
        (autoscale, tick reformatting, etc.).

        hspace is overridable per-figure — e.g. the Phase Calibration window's
        4th subplot (R1w vs frequency) sits directly under the 3rd time-series
        subplot's "Time (s)" x-label and needs more vertical clearance than the
        other embedded figures do.
        """
        _bg    = '#1e1e2f'
        _ax_bg = '#2b2b3d'
        _fg    = 'white'
        _spine = '#555577'

        # ── Disable ALL automatic layout engines ──────────────────────────────
        # Both set_layout_engine(None) and set_tight_layout(False) must be set;
        # one or the other is sufficient depending on matplotlib version.
        try:
            fig.set_layout_engine(None)
        except Exception:
            pass
        try:
            fig.set_tight_layout(False)
        except Exception:
            pass

        # ── Figure background ─────────────────────────────────────────────────
        fig.patch.set_facecolor(_bg)

        # ── Figure-level texts (suptitle, etc.) ───────────────────────────────
        for txt in fig.texts:
            txt.set_color(_fg)
            txt.set_fontsize(13)
            txt.set_ha('center')
            txt.set_position((0.5, txt.get_position()[1]))

        # ── Subplot margins — FIXED, full width (legend is inside the plot) ────
        fig.subplots_adjust(top=0.88, bottom=0.13, hspace=hspace, left=0.20, right=0.97)

        # ── Per-axes styling ──────────────────────────────────────────────────
        import matplotlib.ticker as _ticker
        for ax in fig.get_axes():
            ax.set_facecolor(_ax_bg)
            # Small y margin so data points/markers are never clipped at edges.
            # Scales automatically with the data range — no fixed pixel size.
            ax.margins(y=0.12)
            # Dashed white grid — professional and unobtrusive
            ax.grid(True, linestyle='--', color='white', alpha=0.2, linewidth=0.6)

            for spine in ax.spines.values():
                spine.set_edgecolor(_spine)

            # tick_params updates _major_tick_kw (used for new ticks) AND
            # calls _apply_params on every existing tick object.
            ax.tick_params(axis='both', which='both',
                           colors=_fg, labelsize=11, labelcolor=_fg)

            # Explicitly iterate every tick label Text object — some matplotlib
            # versions create new tick objects inside Axis.draw() that bypass
            # tick_params if the axis limits changed since the last draw.
            for axis_obj in (ax.xaxis, ax.yaxis):
                for tick in (axis_obj.get_major_ticks() +
                             axis_obj.get_minor_ticks()):
                    tick.label1.set_color(_fg)
                    tick.label1.set_fontsize(11)
                    tick.label2.set_color(_fg)
                    tick.label2.set_fontsize(11)
                    tick.tick1line.set_color(_fg)
                    tick.tick2line.set_color(_fg)

                # ── Disable the separate "1eN" offset-text multiplier ─────────
                # ScalarFormatter positions offsetText ABOVE the top subplot's
                # Y-axis, placing it level with the suptitle on high-DPI screens.
                # Setting useOffset=False folds the exponent into each tick label
                # (e.g. "-7.5e-05") so the offsetText is never rendered at all.
                fmt = axis_obj.get_major_formatter()
                if isinstance(fmt, _ticker.ScalarFormatter):
                    fmt.set_useOffset(False)
                    fmt.set_powerlimits((-3, 3))  # use sci notation beyond ±999

                # Keep colour/size styling in case a formatter does use it.
                axis_obj.offsetText.set_color(_fg)
                axis_obj.offsetText.set_fontsize(11)

            # Axis title and axis labels
            ax.title.set_color(_fg)
            ax.title.set_fontsize(12)
            ax.xaxis.label.set_color(_fg)
            ax.xaxis.label.set_fontsize(12)
            ax.yaxis.label.set_color(_fg)
            ax.yaxis.label.set_fontsize(12)

            # Axes-level legend (if any)
            legend = ax.get_legend()
            if legend is not None:
                legend.get_frame().set_facecolor(_ax_bg)
                legend.get_frame().set_edgecolor(_spine)
                for text in legend.get_texts():
                    text.set_color(_fg)
                    text.set_fontsize(10)

        # ── Figure-level legends ──────────────────────────────────────────────
        for fig_legend in fig.legends:
            fig_legend.get_frame().set_facecolor(_ax_bg)
            fig_legend.get_frame().set_edgecolor(_spine)
            for text in fig_legend.get_texts():
                text.set_color(_fg)
                text.set_fontsize(7)
            for handle in fig_legend.legend_handles:
                try:
                    handle.set_linewidth(1.5)
                except Exception:
                    pass

    def _patched_pause(self, interval=0.05):
        QApplication.processEvents()

    def _patched_show(self, *args, **kwargs):
        QApplication.processEvents()

    def _patch_core_stop_support(self):
        if hasattr(self.core, "time") and self.original_sleep is None:
            self.original_sleep = self.core.time.sleep
            self.core.time.sleep = self._patched_sleep
        import matplotlib.pyplot as _plt
        self._original_pause = _plt.pause
        self._original_show = _plt.show
        _plt.pause = self._patched_pause
        _plt.show = self._patched_show

    def _restore_core_stop_support(self):
        if hasattr(self.core, "time") and self.original_sleep is not None:
            self.core.time.sleep = self.original_sleep
            self.original_sleep = None
        import matplotlib.pyplot as _plt
        if hasattr(self, "_original_pause") and self._original_pause is not None:
            _plt.pause = self._original_pause
            self._original_pause = None
        if hasattr(self, "_original_show") and self._original_show is not None:
            _plt.show = self._original_show
            self._original_show = None

    def _clear_core_figures(self):
        for num in plt.get_fignums():
            plt.close(num)

    def _replace_canvas(self, old_canvas, new_figure, container):
        old_canvas.setParent(None)
        old_canvas.deleteLater()
        canvas = FigureCanvas(new_figure)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        container.layout().addWidget(canvas)
        return canvas

    def _capture_figure_context(self):
        original_figure = plt.figure
        original_subplots = plt.subplots
        original_ion = plt.ion

        def _hook_fig_draw(fig):
            """Override fig.draw(renderer) so styles are applied inside every render."""
            import matplotlib.figure as _mpl_fig
            _orig_fig_draw = _mpl_fig.Figure.draw  # always the stable class-level method

            def _styled_draw(self_fig, renderer):
                try:
                    self._apply_embedded_style_to_fig(self_fig)
                except Exception:
                    pass
                _orig_fig_draw(self_fig, renderer)

            import types as _types
            fig.draw = _types.MethodType(_styled_draw, fig)

        def capture_figure(fig):
            if len(self._captured_figures) < 2:
                self._captured_figures.append(fig)
                # Close the auto-created popup window; the Figure object itself survives.
                plt.close(fig)
                self._apply_embedded_style_to_fig(fig)
                _hook_fig_draw(fig)   # ← install the per-render style hook
                if len(self._captured_figures) == 1:
                    self.canvas_time = self._replace_canvas(self.canvas_time, fig, self.time_frame)
                    self.fig_time = fig
                    _axes = fig.get_axes()
                    if len(_axes) >= 5:
                        (self.ax_time_x, self.ax_time_y, self.ax_time_r,
                         self.ax_time_I, self.ax_time_theta) = _axes[0], _axes[1], _axes[2], _axes[3], _axes[4]
                    elif len(_axes) >= 3:
                        self.ax_time_x, self.ax_time_y, self.ax_time_r = _axes[0], _axes[1], _axes[2]
                    self.canvas_time.draw()
                elif len(self._captured_figures) == 2:
                    self.canvas_summary = self._replace_canvas(self.canvas_summary, fig, self.summary_frame)
                    self.fig_summary = fig
                    _axes = fig.get_axes()
                    if len(_axes) >= 4:
                        (self.ax_summary_x, self.ax_summary_y, self.ax_summary_r,
                         self.ax_summary_theta) = _axes[0], _axes[1], _axes[2], _axes[3]
                    elif len(_axes) >= 3:
                        self.ax_summary_x, self.ax_summary_y, self.ax_summary_r = _axes[0], _axes[1], _axes[2]
                    self.canvas_summary.draw()

        def patched_subplots(*args, **kwargs):
            # Temporarily restore plt.figure so the internal plt.figure() call
            # inside plt.subplots() is NOT intercepted — avoids double-capture.
            plt.figure = original_figure
            try:
                result = original_subplots(*args, **kwargs)
            finally:
                plt.figure = original_figure  # leave unpatched; subplots is enough
            fig = result[0] if isinstance(result, tuple) else result
            capture_figure(fig)
            return result

        class FigureContext:
            def __enter__(inner_self):
                plt.subplots = patched_subplots
                plt.ion = lambda: None  # prevent interactive mode from auto-showing figures
                return None

            def __exit__(inner_self, exc_type, exc_val, exc_tb):
                plt.subplots = original_subplots
                plt.ion = original_ion
                return False

        return FigureContext()

    

    def _refresh_lockin_status_box(self):
        icpl = getattr(self.core, 'LOCKIN_ICPL', 1)
        rmod = getattr(self.core, 'LOCKIN_RMOD', 0)
        oflt = getattr(self.core, 'LOCKIN_OFLT', 8)
        ofsl = getattr(self.core, 'LOCKIN_OFSL', 2)
        ilin = getattr(self.core, 'LOCKIN_ILIN', 0)
        sync = getattr(self.core, 'LOCKIN_SYNC', 0)
        sens = getattr(self.core, 'LOCKIN_SENS', 16)
        ignd = getattr(self.core, 'LOCKIN_IGND', 0)
        bi, mi, ui = LockinParamsDialog._OFLT_IDX_TO_COMBO.get(oflt, (0, 2, 2))
        tc_str = (f"{LockinParamsDialog._TC_BASES[bi] * LockinParamsDialog._TC_MULTS[mi]}"
                  f" {LockinParamsDialog._TC_UNITS[ui]}")
        sbi, smi, sui = LockinParamsDialog._SENS_IDX_TO_COMBO.get(sens, (2, 2, 2))
        sens_str = (f"{LockinParamsDialog._SENS_BASES[sbi] * LockinParamsDialog._SENS_MULTS[smi]}"
                    f" {LockinParamsDialog._SENS_UNITS[sui]}")
        coupling_str = "DC" if icpl == 1 else "AC"
        reserve_str  = ["High Res", "Normal", "Low Noise"][rmod]
        slope_str    = ["6dB", "12dB", "18dB", "24dB"][ofsl]
        filter_str   = ["No filt", "Line", "2×Line", "Both"][ilin]
        sync_str     = "Sync ON" if sync == 1 else "Sync OFF"
        ignd_str     = "Ground" if ignd == 1 else "Float"
        self.lockin_status_box_label.setText(
            f"{coupling_str} | {reserve_str} | TC {tc_str} | {slope_str}/oct\n"
            f"{filter_str} | {sync_str} | Sens {sens_str} | {ignd_str}"
        )

    def _refresh_dsp7265_status_box(self):
        imode = getattr(self.core, 'LOCKIN_7265_IMODE', 0)
        vmode = getattr(self.core, 'LOCKIN_7265_VMODE', 1)
        flt   = getattr(self.core, 'LOCKIN_7265_FLOAT', 1)
        cp    = getattr(self.core, 'LOCKIN_7265_CP',    1)
        lf    = getattr(self.core, 'LOCKIN_7265_LF',    0)
        sens  = getattr(self.core, 'LOCKIN_7265_SENS',  25)
        tc    = getattr(self.core, 'LOCKIN_7265_TC',    11)
        slope = getattr(self.core, 'LOCKIN_7265_SLOPE', 2)
        dsp_sens_vals = getattr(self.core, '_DSP7265_SENS_VALUES', [])
        dsp_tc_vals   = getattr(self.core, '_DSP7265_TC_VALUES',   [])
        try:
            sv = dsp_sens_vals[sens]
            if sv >= 1:
                sens_str = f"{sv:.4g} V"
            elif sv >= 1e-3:
                sens_str = f"{sv*1e3:.4g} mV"
            else:
                sens_str = f"{sv*1e6:.4g} µV"
        except (IndexError, TypeError):
            sens_str = f"idx {sens}"
        try:
            tv = dsp_tc_vals[tc]
            if tv >= 1:
                tc_str = f"{tv:.4g} s"
            elif tv >= 1e-3:
                tc_str = f"{tv*1e3:.4g} ms"
            else:
                tc_str = f"{tv*1e6:.4g} µs"
        except (IndexError, TypeError):
            tc_str = f"idx {tc}"
        imode_str = ["Voltage", "Current HI", "Current LO"][min(imode, 2)]
        vmode_str = ["", "A", "-B", "A-B"][min(vmode, 3)]
        cp_str    = "DC" if cp == 1 else "AC"
        flt_str   = "Float" if flt == 1 else "Gnd"
        lf_str    = ["No rej", "Line", "2×Line", "Both"][min(lf, 3)]
        slope_str = ["6dB", "12dB", "18dB", "24dB"][min(slope, 3)]
        self.dsp7265_status_box_label.setText(
            f"{imode_str} ({vmode_str}) | {cp_str} | {flt_str} | TC {tc_str} | {slope_str}/oct\n"
            f"{lf_str} | Sens {sens_str}"
        )

    def _refresh_all_lockin_status(self):
        self._refresh_lockin_status_box()
        self._refresh_dsp7265_status_box()

    def open_lockin_params_dialog(self):
        dialog = LockinParamsDialog(self, self.core)
        dialog.exec()
        self._refresh_all_lockin_status()

    def open_lockin7265_params_dialog(self):
        # Re-use existing window if already open
        if self._lockin7265_params_dialog is not None and self._lockin7265_params_dialog.isVisible():
            self._lockin7265_params_dialog.raise_()
            self._lockin7265_params_dialog.activateWindow()
            return
        self._lockin7265_params_dialog = Lockin7265ParamsDialog(self, self.core)
        self._lockin7265_params_dialog.show()

    @property
    def _phase_calib_window(self):
        """Built on first access rather than at startup — it owns a real
        matplotlib Figure/toolbar, which is real construction cost most
        sessions never need paid before the main window even appears."""
        if self._phase_calib_window_impl is None:
            self._phase_calib_window_impl = PhaseCalibrationWindow(self)
        return self._phase_calib_window_impl

    def open_phase_calibration(self):
        self._phase_calib_window.show()
        self._phase_calib_window.raise_()
        self._phase_calib_window.activateWindow()

    def open_iv_dialog(self):
        dialog = IVDialog(self, self.core)
        try:
            dialog.save_dir.setText(self.save_dir_entry.text())
            dialog.save_name.setText(self.save_name_entry.text() + "_IV")
        except Exception:
            pass
        dialog.setModal(False)
        dialog.show()

    def on_run(self):
        if not self._check_safety_resistance_before_run():
            return
        if not self._ensure_float_before_measurement():
            return
        self._sync_committed_params()
        try:
            params = self.read_parameters()
            _global_wt = params.get("WAIT_TIME", 0.0)
            _ranges = self.freq_range_widget.get_ranges(global_wait_time=_global_wt)
        except ValueError as exc:
            QMessageBox.warning(self, "Sub-range Wait Time Missing", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Parameter error", f"Invalid parameter: {exc}")
            return
        # Build freq→wait_time map for the core
        _freq_wait_map = {}
        for rng in _ranges:
            for f in rng["frequencies"]:
                _freq_wait_map[round(f, 9)] = rng["wait_time"]

        if not self._phase_calibrated:
            reply = QMessageBox.question(self, "Phase Not Calibrated",
                "1ω phase calibration has not been performed.\n"
                "Proceed without calibration? (PHAS will be set to 0)",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
            else:
                try:
                    if self.lockin is not None:
                        self.lockin.write("PHAS 0")
                except Exception:
                    pass

        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.force_avg_btn.setEnabled(True)
        self.fit_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.save_dir_entry.setEnabled(False)
        self.save_name_entry.setEnabled(False)
        self.fit_results = None
        self.stop_requested = False
        try:
            self.core.stop_requested = False
        except Exception:
            pass

        for ax in (self.ax_time_x, self.ax_time_y, self.ax_time_r,
                   self.ax_time_I, self.ax_time_theta):
            ax.clear()
        # Remove figure-level legends from the previous run immediately
        for leg in self.fig_time.legends[:]:
            leg.remove()
        self.fig_time.suptitle("X, Y, V₃ω, I, θ vs Time (all frequencies)")
        self.ax_time_x.set_ylabel("X (V)")
        self.ax_time_y.set_ylabel("Y (V)")
        self.ax_time_r.set_ylabel(r"$V_{3\omega}$ (V)")
        self.ax_time_I.set_ylabel("I (µA)")
        self.ax_time_theta.set_ylabel("θ (°)")
        self.ax_time_theta.set_xlabel("Time (s)")
        self._apply_embedded_style_to_fig(self.fig_time)
        self.canvas_time.draw()

        for ax in (self.ax_summary_x, self.ax_summary_y, self.ax_summary_r,
                   self.ax_summary_theta):
            ax.clear()
        self.fig_summary.suptitle("X, Y, V₃ω, θ vs Frequency")
        self.ax_summary_x.set_ylabel("X (V)")
        self.ax_summary_y.set_ylabel("Y (V)")
        self.ax_summary_r.set_ylabel(r"$V_{3\omega}$ (V)")
        self.ax_summary_theta.set_ylabel("θ (°)")
        self.ax_summary_theta.set_xlabel("Frequency (Hz)")
        self._apply_embedded_style_to_fig(self.fig_summary)
        self.canvas_summary.draw()

        self._clear_core_figures()
        self._captured_figures = []
        # Reset per-run line-object tracking for the time plot callback
        self._time_wait_lines = {}
        self._time_avg_lines = {}
        self._last_freq_start_idx = -1
        # connection state preserved

        try:
            if not self.instruments_connected:
                raise RuntimeError("Connect instruments first")
            self.assign_parameters_to_core(params)
            self.core.setup_lockin_3w()
            self.core.setup_lockin_7265_3w()
            # self.core.setup_multimeter()  # replaced by lockin7265
            self._patch_core_stop_support()
            self.set_status("Measuring...")

            # Reset time series for this new run
            self._ts_t_data     = None
            self._ts_I_data     = None
            self._ts_r_data     = None
            self._ts_theta_data = None
            self._ts_freq_col   = []
            self._ts_last_len   = 0

            # New run → forget the previous run's backup file slot so this
            # run gets a fresh number instead of overwriting the last run's.
            self._backup_suffix_3w    = None
            self._backup_suffix_3w_ts = None

            self._autosave_timer.start()

            # Build kwargs (no callback — thread provides it)
            _auto_on        = self.auto_params_cb.isChecked()
            _dlg            = self._auto_params_dialog
            _auto_fn        = self._auto_params_fn  if _auto_on else None
            _auto_s_sr830   = _auto_on and _dlg.cb_sens_sr830.isChecked()
            _auto_s_7265    = _auto_on and _dlg.cb_sens_7265.isChecked()
            _any_auto_sens  = _auto_s_sr830 or _auto_s_7265
            _stab_fn        = self._stability_check_fn if _any_auto_sens else None
            _sr830_thresh   = self._sr830_thresholds_fn  if _auto_s_sr830 else None
            _dsp_thresh     = self._dsp7265_thresholds_fn if _auto_s_7265  else None

            # Auto 1ω calibration — build fn if checkbox enabled (readable live during run)
            _auto_1w_enabled = _auto_on and _dlg.cb_auto_1w.isChecked()
            # Thread is created below; fn is built after so it can capture the thread ref
            self._meas_thread = MeasurementThread(self.core, {})  # placeholder, updated below

            _auto_1w_fn = self._make_auto_1w_fn(self._meas_thread, _freq_wait_map) \
                          if _auto_1w_enabled else None

            if _auto_1w_enabled:
                self._phase_calib_window.enter_auto_mode()

            # Shared mutable list — core iterates it by index so GUI can patch upcoming items live
            self._live_freqs_list = list(params.get("FREQUENCIES") or [])
            self.freq_range_widget._meas_live_freqs = self._live_freqs_list
            self.freq_range_widget._meas_done_count = 0
            self.freq_range_widget._meas_cur_freq   = None
            self.freq_range_widget._meas_wait_map   = _freq_wait_map

            _meas_kwargs = dict(
                frequencies           = self._live_freqs_list,
                freq_wait_map         = _freq_wait_map,
                auto_params_fn        = _auto_fn,
                auto_sens_sr830       = _auto_s_sr830,
                auto_sens_7265        = _auto_s_7265,
                stability_check_fn    = _stab_fn,
                sr830_thresholds_fn   = _sr830_thresh,
                dsp7265_thresholds_fn = _dsp_thresh,
                live_params_fn        = self._live_params_fn,
                auto_1w_calib_fn      = _auto_1w_fn,
            )
            self._meas_thread._kwargs = _meas_kwargs  # update placeholder
            self._meas_thread.plot_update.connect(self._meas_plot_callback)
            self._meas_thread.finished_ok.connect(self._on_meas_finished_ok)
            self._meas_thread.finished_stop.connect(self._on_meas_finished_stop)
            self._meas_thread.finished_err.connect(self._on_meas_finished_err)
            self._meas_thread.finished.connect(self._on_meas_thread_done)
            self._meas_thread.start()
            # on_run() returns immediately — GUI stays live
            return

        except Exception as exc:
            QMessageBox.critical(self, "Measurement error", str(exc))
            self.set_status(f"Error: {exc}")
            self._autosave_timer.stop()
            self._restore_core_stop_support()
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.force_avg_btn.setEnabled(False)
            # Always re-enable the save path fields so the user can
            # change them even if the run failed or was stopped.
            self.save_dir_entry.setEnabled(True)
            self.save_name_entry.setEnabled(True)
            if self.current_data is not None:
                self.fit_button.setEnabled(True)

    def _on_meas_thread_done(self):
        """Called when MeasurementThread finishes (after result signal),
        regardless of whether it completed, was stopped, or errored."""
        self._autosave_timer.stop()
        self._restore_core_stop_support()
        self._ground_lockins_after_measurement()
        def _bg_shutdown():
            try:
                self.core.shutdown()
            except Exception:
                pass
        threading.Thread(target=_bg_shutdown, daemon=True).start()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.force_avg_btn.setEnabled(False)
        self.save_dir_entry.setEnabled(True)
        self.save_name_entry.setEnabled(True)

    def _finish_auto_1w(self, completed=True):
        """Called on measurement end — final backup, user-dir save, restore window."""
        if hasattr(self, '_auto_1w_state') and self._auto_1w_state is not None:
            self._auto_1w_backup(completed=completed)   # final backup with correct status
            self._save_auto_1w_data()                   # copy to user save directory
            self._phase_calib_window.exit_auto_mode()
            self._auto_1w_state = None

    def _clear_meas_freq_state(self):
        """Clear live-frequency state from freq_range_widget after any run finishes."""
        if hasattr(self, 'freq_range_widget') and self.freq_range_widget is not None:
            fw = self.freq_range_widget
            # Save the actual list that was measured for the "Last" button
            live = getattr(self, '_live_freqs_list', None)
            if live:
                wm = fw._meas_wait_map or {}
                fw._last_used_list = [
                    {'value': f, 'enabled': True,
                     'wait': wm.get(round(f, 9), 0.0)}
                    for f in live
                ]
            fw._meas_live_freqs = None
            fw._meas_done_count = 0
            fw._meas_cur_freq   = None
            fw._meas_wait_map   = None
            fw._refresh_indicator()  # enables _last_btn
            if fw._edit_dialog is not None and fw._edit_dialog.isVisible():
                fw._edit_dialog.refresh_meas_colours()
        self._live_freqs_list = None

    def _on_meas_finished_ok(self, data):
        self.current_data = data
        self._add_to_measurement_history(data, status='completed', fit_results=None)
        self._auto_backup_3w(data, completed=True)
        self._finish_auto_1w(completed=True)
        self._clear_meas_freq_state()
        self.set_status("Measurement complete")
        self.save_button.setEnabled(True)
        QMessageBox.information(self, "Measurement", "Measurement finished.")

    def _on_meas_finished_stop(self, partial):
        if partial:
            self.current_data = partial
            self._add_to_measurement_history(partial, status='interrupted', fit_results=None)
            self.save_button.setEnabled(True)
        self._auto_backup_3w(partial, completed=False)
        self._finish_auto_1w(completed=False)
        self._clear_meas_freq_state()
        self.set_status("Measurement stopped")

    def _on_meas_finished_err(self, msg, partial):
        if partial:
            self.current_data = partial
            self._add_to_measurement_history(partial, status='interrupted', fit_results=None)
            self.save_button.setEnabled(True)
        self._auto_backup_3w(partial, completed=False)
        self._finish_auto_1w(completed=False)
        self._clear_meas_freq_state()
        QMessageBox.critical(self, "Measurement error", msg)
        self.set_status(f"Error: {msg.splitlines()[0]}")

    def _meas_plot_callback(self, phase, args):
        """Slot — receives (phase, args-tuple) from MeasurementThread.plot_update.
        Throttled: time-panel redraws at most once every 2 s to keep GUI fast
        during 24-72 h measurements."""
        import time as _time
        import numpy as np
        try:
            if phase == 'time':
                t_data, x_data, y_data, r_data, I_data, theta_data, freq_start_idx, wait_n, label = args

                # Store references and build parallel frequency column
                if self._ts_t_data is None:
                    self._ts_t_data     = t_data
                    self._ts_I_data     = I_data
                    self._ts_r_data     = r_data
                    self._ts_theta_data = theta_data
                try:
                    _freq_val = float(label.split()[0])
                except Exception:
                    _freq_val = float('nan')
                new_len = len(t_data)
                if new_len > self._ts_last_len:
                    self._ts_freq_col.extend([_freq_val] * (new_len - self._ts_last_len))
                    self._ts_last_len = new_len

                # Create new line objects when a new frequency starts
                if freq_start_idx != self._last_freq_start_idx:
                    self._last_freq_start_idx = freq_start_idx
                    lxw, = self.ax_time_x.plot([], [], color='white', alpha=1.0)
                    lyw, = self.ax_time_y.plot([], [], color='white', alpha=1.0)
                    lrw, = self.ax_time_r.plot([], [], color='white', alpha=1.0)
                    liw, = self.ax_time_I.plot([], [], color='white', alpha=1.0)
                    ltw, = self.ax_time_theta.plot([], [], color='white', alpha=1.0)
                    self._time_wait_lines[label] = (lxw, lyw, lrw, liw, ltw)
                    lxa, = self.ax_time_x.plot([], [], label=label)
                    lya, = self.ax_time_y.plot([], [], label=label)
                    lra, = self.ax_time_r.plot([], [], label=label)
                    lia, = self.ax_time_I.plot([], [], label=label)
                    lta, = self.ax_time_theta.plot([], [], label=label)
                    self._time_avg_lines[label] = (lxa, lya, lra, lia, lta)

                wl = self._time_wait_lines.get(label)
                al = self._time_avg_lines.get(label)

                if wl:
                    if wait_n is None:  # still in wait phase
                        wl[0].set_data(t_data[freq_start_idx:], x_data[freq_start_idx:])
                        wl[1].set_data(t_data[freq_start_idx:], y_data[freq_start_idx:])
                        wl[2].set_data(t_data[freq_start_idx:], r_data[freq_start_idx:])
                        wl[3].set_data(t_data[freq_start_idx:], np.array(I_data[freq_start_idx:]) * 1e6)
                        wl[4].set_data(t_data[freq_start_idx:], theta_data[freq_start_idx:])
                    else:              # averaging phase
                        wl[0].set_data(t_data[freq_start_idx:wait_n], x_data[freq_start_idx:wait_n])
                        wl[1].set_data(t_data[freq_start_idx:wait_n], y_data[freq_start_idx:wait_n])
                        wl[2].set_data(t_data[freq_start_idx:wait_n], r_data[freq_start_idx:wait_n])
                        wl[3].set_data(t_data[freq_start_idx:wait_n], np.array(I_data[freq_start_idx:wait_n]) * 1e6)
                        wl[4].set_data(t_data[freq_start_idx:wait_n], theta_data[freq_start_idx:wait_n])
                        if al:
                            al[0].set_data(t_data[wait_n:], x_data[wait_n:])
                            al[1].set_data(t_data[wait_n:], y_data[wait_n:])
                            al[2].set_data(t_data[wait_n:], r_data[wait_n:])
                            al[3].set_data(t_data[wait_n:], np.array(I_data[wait_n:]) * 1e6)
                            al[4].set_data(t_data[wait_n:], theta_data[wait_n:])

                # Throttle: relim + redraw at most once every 2 seconds
                _now = _time.monotonic()
                if not hasattr(self, '_last_time_draw') or _now - self._last_time_draw >= 1.0:
                    if not self.zoom_button.isChecked():
                        for ax in (self.ax_time_x, self.ax_time_y, self.ax_time_r,
                                   self.ax_time_I, self.ax_time_theta):
                            ax.relim()
                            ax.autoscale_view()
                    self._apply_embedded_style_to_fig(self.fig_time)
                    self.canvas_time.draw_idle()
                    self._last_time_draw = _now

            elif phase == 'freq_start':
                _f, = args
                fw = getattr(self, 'freq_range_widget', None)
                if fw is not None and fw._meas_live_freqs is not None:
                    fw._meas_cur_freq = _f
                    _ed = fw._edit_dialog
                    if _ed is not None and _ed.isVisible():
                        _ed.refresh_meas_colours()

            elif phase == 'summary':
                summary_freqs, summary_x, summary_y, summary_r, summary_theta = args

                # Update live-freq done count so Edit List dialog can colour rows
                fw = getattr(self, 'freq_range_widget', None)
                if fw is not None and fw._meas_live_freqs is not None:
                    fw._meas_done_count = len(summary_freqs)
                    _ed = fw._edit_dialog
                    if _ed is not None and _ed.isVisible():
                        _ed.refresh_meas_colours()

                # Update legend on time plot after each frequency completes
                for leg in self.fig_time.legends[:]:
                    leg.remove()
                handles, labels_leg = self.ax_time_x.get_legend_handles_labels()
                if handles:
                    # Max 3 rows; grow columns as frequency count increases
                    _max_rows = 3
                    _ncol = max(1, -(-len(handles) // _max_rows))  # ceiling division
                    self.fig_time.legend(handles, labels_leg,
                                         loc='upper right',
                                         bbox_to_anchor=(0.99, 1.005),
                                         fontsize=6, ncol=_ncol,
                                         framealpha=0.8, borderpad=0.3,
                                         handlelength=1.0, handletextpad=0.4,
                                         labelspacing=0.2)
                self._apply_embedded_style_to_fig(self.fig_time)
                self.canvas_time.draw_idle()

                _summary_axes = (self.ax_summary_x, self.ax_summary_y,
                                 self.ax_summary_r, self.ax_summary_theta)
                _zoomed = self.zoom_button.isChecked()
                _saved_lims = [(ax.get_xlim(), ax.get_ylim()) for ax in _summary_axes] if _zoomed else None
                for ax, data, ylabel in zip(
                    _summary_axes,
                    (summary_x, summary_y, summary_r, summary_theta),
                    ("X (V)", "Y (V)", r"$V_{3\omega}$ (V)", "θ (°)")
                ):
                    ax.cla()
                    ax.margins(y=0.15)
                    ax.plot(summary_freqs, data, 'o-')
                    ax.set_ylabel(ylabel)
                    ax.relim()
                    ax.autoscale_view()
                if _zoomed and _saved_lims:
                    for ax, (xlim, ylim) in zip(_summary_axes, _saved_lims):
                        ax.set_xlim(xlim)
                        ax.set_ylim(ylim)
                self.ax_summary_theta.set_xlabel("Frequency (Hz)")
                self._apply_embedded_style_to_fig(self.fig_summary)
                self.canvas_summary.draw_idle()

            elif phase in ('1w_auto_start', '1w_auto_time', '1w_auto_done', '1w_auto_3w'):
                self._phase_calib_window.handle_auto_update(phase, args)

        except Exception:
            pass  # never let a plot error abort the measurement

    def _open_auto_params_settings(self):
        self._auto_params_dialog.show()
        self._auto_params_dialog.raise_()
        self._auto_params_dialog.activateWindow()

    def _sr830_thresholds_fn(self):
        """Returns (overload_pct, lower_pct, stability_pct) for SR830, read live from dialog."""
        dlg = self._auto_params_dialog
        try:
            overload = float(dlg.sr830_overload_pct.text()) / 100.0
        except ValueError:
            overload = 0.90
        try:
            lower = float(dlg.sr830_lower_pct.text()) / 100.0
        except ValueError:
            lower = 0.10
        try:
            stab = float(dlg.sr830_stability_pct.text()) / 100.0
        except ValueError:
            stab = 0.005
        return (overload, lower, stab)

    def _dsp7265_thresholds_fn(self):
        """Returns (overload_pct, lower_pct, stability_pct) for DSP7265, read live from dialog."""
        dlg = self._auto_params_dialog
        try:
            overload = float(dlg.dsp_overload_pct.text()) / 100.0
        except ValueError:
            overload = 0.90
        try:
            lower = float(dlg.dsp_lower_pct.text()) / 100.0
        except ValueError:
            lower = 0.10
        try:
            stab = float(dlg.dsp_stability_pct.text()) / 100.0
        except ValueError:
            stab = 0.005
        return (overload, lower, stab)

    def _auto_params_fn(self, freq):
        """Called by core before each 3ω frequency step (after the 1ω step, if
        any). Sets TC/sensitivity on enabled instruments to the ideal 3ω
        value, or re-asserts the manually configured value when the
        corresponding auto option is disabled -- so 3ω's own TC/sensitivity
        condition always wins over whatever the 1ω step left the instrument
        at. The manually-configured value is read from the dedicated
        LOCKIN_*_MANUAL globals (set only by the params dialogs'
        "Apply"/measurement-start assignment), never from the plain
        LOCKIN_OFLT/LOCKIN_SENS/LOCKIN_7265_TC/LOCKIN_7265_SENS globals --
        those are freely overwritten by 1ω's own adaptive-calibration hunt,
        so reading them back here would silently re-assert 1ω's leftover
        value instead of the user's."""
        if not self.auto_params_cb.isChecked():
            return
        dlg = self._auto_params_dialog
        sr830_enabled = dlg.cb_sr830.isChecked()
        dsp_enabled   = dlg.cb_7265.isChecked()
        sr830_sens_enabled = dlg.cb_sens_sr830.isChecked()
        dsp_sens_enabled   = dlg.cb_sens_7265.isChecked()
        ideal_tc = 1.0 / freq
        if self.lockin is not None:
            if sr830_enabled:
                idx = next((i for i, v in enumerate(_SR830_TC_VALUES) if v >= ideal_tc),
                           len(_SR830_TC_VALUES) - 1)
                idx = min(idx + 1, len(_SR830_TC_VALUES) - 1)  # one step above borderline
            else:
                idx = int(self.core.LOCKIN_OFLT_MANUAL)  # re-assert manually configured value
            try:
                self.lockin.write(f"OFLT {idx}")
                self.core.LOCKIN_OFLT = idx  # keep global in sync for status display
            except Exception:
                pass
            if not sr830_sens_enabled:
                # 3ω's own auto-sensitivity is off for SR830: re-assert the
                # manually configured sensitivity so a preceding 1ω
                # auto-sensitivity hunt can never leave 3ω at the wrong,
                # un-recoverable SENS. When sr830_sens_enabled is True, 3ω's
                # own wait-phase logic (measure()) already resets SENS from
                # its own tracked history every step -- left untouched here.
                sens_idx = int(self.core.LOCKIN_SENS_MANUAL)
                try:
                    self.lockin.write(f"SENS {sens_idx}")
                    self.core.LOCKIN_SENS = sens_idx  # keep global in sync for status display
                except Exception:
                    pass
        if self.lockin7265 is not None:
            if dsp_enabled:
                idx = next((i for i, v in enumerate(_DSP7265_TC_VALUES) if v >= ideal_tc),
                           len(_DSP7265_TC_VALUES) - 1)
                idx = min(idx + 1, len(_DSP7265_TC_VALUES) - 1)  # one step above borderline
            else:
                idx = int(self.core.LOCKIN_7265_TC_MANUAL)  # re-assert manually configured value
            try:
                self.lockin7265.write(f"TC {idx}")
                self.core.LOCKIN_7265_TC = idx  # keep global in sync for status display
            except Exception:
                pass
            if not dsp_sens_enabled:
                # Same reasoning as the SR830 branch above, for the DSP7265.
                sens_idx = int(self.core.LOCKIN_7265_SENS_MANUAL)
                try:
                    self.lockin7265.write(f"SEN {sens_idx}")
                    self.core.LOCKIN_7265_SENS = sens_idx  # keep global in sync for status display
                except Exception:
                    pass

    def _auto_params_fn_1w(self, freq):
        """Called before the 1ω calibration step when cb_adaptive_calib is
        checked (live). Sets TC on BOTH instruments unconditionally — a
        single switch for the 1ω step, independent of the 3ω TC checkboxes."""
        ideal_tc = 1.0 / freq
        if self.lockin is not None:
            idx = next((i for i, v in enumerate(_SR830_TC_VALUES) if v >= ideal_tc),
                       len(_SR830_TC_VALUES) - 1)
            idx = min(idx + 1, len(_SR830_TC_VALUES) - 1)  # one step above borderline
            try:
                self.lockin.write(f"OFLT {idx}")
                self.core.LOCKIN_OFLT = idx
            except Exception:
                pass
        if self.lockin7265 is not None:
            idx = next((i for i, v in enumerate(_DSP7265_TC_VALUES) if v >= ideal_tc),
                       len(_DSP7265_TC_VALUES) - 1)
            idx = min(idx + 1, len(_DSP7265_TC_VALUES) - 1)  # one step above borderline
            try:
                self.lockin7265.write(f"TC {idx}")
                self.core.LOCKIN_7265_TC = idx
            except Exception:
                pass

    def _stability_check_fn(self, elapsed, freq):
        """Called from measurement thread when max wait is exceeded.
        Emits a signal so the main thread shows a dialog, then blocks until
        the user clicks Wait or Proceed.  Returns 'proceed' or 'wait:<seconds>'.
        """
        # Always reset event/result first to clear any stale state from a previous call.
        self._stability_check_event.clear()
        self._stability_check_result = None
        freq_label = f"{freq:.2f} Hz" if freq != int(freq) else f"{int(freq)} Hz"
        try:
            if self._auto_params_dialog.cb_auto_proceed.isChecked():
                print(f"  Auto-proceed: max wait reached at {freq_label} after {elapsed:.0f}s",
                      flush=True)
                return 'proceed'
        except Exception:
            pass
        self._stability_signal.emit(elapsed, freq_label)
        timed_out = not self._stability_check_event.wait(timeout=600)   # 10-min safety timeout
        if timed_out:
            print(f"  WARNING: stability dialog timed out after 10 min at {freq_label} — "
                  f"proceeding with potentially unstabilised data", flush=True)
        return self._stability_check_result or 'proceed'

    # ── Auto 1ω calibration helpers ───────────────────────────────────────────

    def _open_skip_dialog(self):
        """Refresh and show the skip-frequency dialog."""
        self._skip_freq_dialog._refresh_list()
        self._skip_freq_dialog.show()
        self._skip_freq_dialog.raise_()

    def _make_auto_1w_fn(self, thread, freq_wait_map):
        """Build the auto_1w_calib_fn closure to pass to core.measure().

        Whether this 1ω step is adaptive (auto TC + auto sensitivity, both
        lock-ins together) is governed solely by cb_adaptive_calib, read
        fresh on every call — independent of the 3ω auto-sens/TC checkboxes,
        and toggleable live while a measurement is running.
        """
        import numpy as _np
        _core = self.core
        state = {
            'ts_t': [], 'ts_freq': [], 'ts_r': [], 'ts_theta': [], 'ts_i': [],
            'freq_rows': [],
            'backup_sfx_ts': None,
            'backup_sfx_fd': None,
        }
        self._auto_1w_state = state

        _skip_freqs = self._1w_skip_freqs  # live reference — changes mid-meas take effect

        def _fn(f):
            # Check if this frequency is in the skip set
            if round(f, 9) in _skip_freqs:
                thread.plot_update.emit('1w_auto_start', (f,))  # keep queue in sync
                thread.plot_update.emit('1w_auto_3w', (f,))
                return

            _wt = freq_wait_map.get(round(f, 9)) or self._committed_params.get('WAIT_TIME', 300)
            _at = self._calc_auto_avg_time(f) or self._committed_params.get('AVERAGE_TIME', 60)

            thread.plot_update.emit('1w_auto_start', (f,))

            _cb_r = []; _cb_th = []; _cb_i = []; _cb_wn = [None]

            def _cb(phase, *a):
                if phase == '1w_time':
                    t_, r_, th_, wn_, i_ = a
                    _cb_r.clear();  _cb_r.extend(r_)
                    _cb_th.clear(); _cb_th.extend(th_)
                    _cb_i.clear();  _cb_i.extend(i_)
                    _cb_wn[0] = wn_
                    thread.plot_update.emit('1w_auto_time', (f, t_, r_, th_, wn_, i_))

            # Read live — independent of the 3ω auto-sens/TC checkboxes, and
            # toggleable mid-measurement since this closure runs fresh per frequency.
            _calib_adaptive = self._auto_params_dialog.cb_adaptive_calib.isChecked()
            if _calib_adaptive:
                _apfn        = self._auto_params_fn_1w
                _asens_sr830 = True
                _asens_7265  = True
                _stabfn      = self._stability_check_fn
                _sr830_th    = self._sr830_thresholds_fn
                _dsp_th      = self._dsp7265_thresholds_fn
            else:
                _apfn        = None
                _asens_sr830 = False
                _asens_7265  = False
                _stabfn      = None
                _sr830_th    = None
                _dsp_th      = None

            avg_r, avg_theta, _ = _core.calibrate_1w_phase(
                callback=_cb, freq=f, wait_time=_wt, average_time=_at,
                auto_params_fn=_apfn,
                auto_sens_sr830=_asens_sr830, auto_sens_7265=_asens_7265,
                stability_check_fn=_stabfn,
                sr830_thresholds_fn=_sr830_th,
                dsp7265_thresholds_fn=_dsp_th)

            if avg_r is None:
                # Check if this was a user skip (not a full stop)
                if not getattr(_core, 'stop_requested', False):
                    # Skipped mid-calibration — proceed to 3w with last PHAS
                    thread.plot_update.emit('1w_auto_3w', (f,))
                return  # either skipped or stopped — don't calibrate

            wn = _cb_wn[0]
            _r_avg  = _cb_r[wn:]  if wn is not None else _cb_r
            _th_avg = _cb_th[wn:] if wn is not None else _cb_th
            _i_avg  = _cb_i[wn:]  if wn is not None else _cb_i
            avg_r_v  = float(_np.mean(_r_avg))  if _r_avg  else avg_r
            avg_th_v = float(_np.mean(_th_avg)) if _th_avg else avg_theta
            avg_i_v  = float(_np.mean(_i_avg))  if _i_avg  else 0.0
            avg_res  = avg_r_v / avg_i_v if abs(avg_i_v) > 1e-15 else float('nan')

            # Append continuous time-series data
            t_now = (state['ts_t'][-1] + 5.0) if state['ts_t'] else 0.0
            for idx, (r, th, i) in enumerate(zip(_cb_r, _cb_th, _cb_i)):
                state['ts_t'].append(t_now + idx * self._committed_params.get('dt', 0.2))
                state['ts_freq'].append(f)
                state['ts_r'].append(r)
                state['ts_theta'].append(th)
                state['ts_i'].append(i)

            state['freq_rows'].append({
                'Frequency (Hz)':    f,
                'V_1w_avg (V)':      avg_r_v,
                'I_AC_avg (A)':      avg_i_v,
                'R_1w_avg (Ohm)':    avg_res,
                'theta_avg (deg)':   avg_th_v,
                'PHAS_written (deg)': avg_theta,
            })

            self._auto_1w_backup()
            thread.plot_update.emit('1w_auto_done', (f, avg_r_v, avg_i_v, avg_res, avg_th_v))
            thread.plot_update.emit('1w_auto_3w', (f,))

        return _fn

    def _auto_1w_backup(self, completed=False):
        """Auto-save 1ω calibration data to Backup_data folder.
        completed=True marks the final write after a clean finish;
        False marks an in-progress or interrupted save."""
        state = getattr(self, '_auto_1w_state', None)
        if not state:
            return
        save_dir = self.save_dir_entry.text().strip() or os.getcwd()
        backup   = os.path.join(save_dir, 'Backup_data')
        base     = _backup_base_name(self.save_name_entry.text())

        if state['ts_t']:
            rows = list(zip(state['ts_t'], state['ts_freq'],
                            state['ts_r'], state['ts_theta'], state['ts_i']))
            _, state['backup_sfx_ts'] = _silent_backup(
                backup, 'Time_series_' + base + '_1w', rows,
                columns=['time_s', 'Frequency (Hz)', 'V_1w (V)', 'theta (deg)', 'I_AC (A)'],
                completed=completed, title='1ω AUTO CALIBRATION — TIME SERIES',
                sections=[], suffix=state['backup_sfx_ts'])

        if state['freq_rows']:
            cols = ['Frequency (Hz)', 'V_1w_avg (V)', 'I_AC_avg (A)',
                    'R_1w_avg (Ohm)', 'theta_avg (deg)', 'PHAS_written (deg)']
            rows_fd = [[r[c] for c in cols] for r in state['freq_rows']]
            _, state['backup_sfx_fd'] = _silent_backup(
                backup, base + '_1w_frequency_dependent', rows_fd,
                columns=cols,
                completed=completed, title='1ω AUTO CALIBRATION — FREQUENCY DEPENDENT',
                sections=[], suffix=state['backup_sfx_fd'])

    def _save_auto_1w_data(self):
        """Save final 1ω auto-cal files to the user's save directory."""
        import pandas as _pd
        state = getattr(self, '_auto_1w_state', None)
        if not state:
            return
        save_dir = self.save_dir_entry.text().strip() or os.getcwd()
        base     = _backup_base_name(self.save_name_entry.text())

        try:
            if state['ts_t']:
                path = os.path.join(save_dir, base + '_1w_frequency_dependent_time_series.csv')
                _pd.DataFrame({
                    'time_s':        state['ts_t'],
                    'Frequency (Hz)':state['ts_freq'],
                    'V_1w (V)':      state['ts_r'],
                    'theta (deg)':   state['ts_theta'],
                    'I_AC (A)':      state['ts_i'],
                }).to_csv(path, index=False)
                print(f"  1ω time-series saved: {path}")

            if state['freq_rows']:
                path = os.path.join(save_dir, base + '_1w_frequency_dependent.csv')
                _pd.DataFrame(state['freq_rows']).to_csv(path, index=False)
                print(f"  1ω frequency-dependent saved: {path}")
        except Exception as e:
            print(f"  1ω save failed: {e}")

    def _show_stability_dialog(self, elapsed, freq_label):
        """Runs on main thread. Shows dialog; unblocks the measurement thread."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Signal Not Stable")
        dlg.setFixedWidth(360)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"Signal at {freq_label} has not stabilised after {elapsed:.0f} s.\n"
            "Choose an action:"
        ))
        extra_edit = QLineEdit("60")
        extra_edit.setPlaceholderText("Extra seconds to wait")
        row = QHBoxLayout()
        row.addWidget(QLabel("Wait extra (s):"))
        row.addWidget(extra_edit)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        wait_btn    = QPushButton("Wait longer")
        proceed_btn = QPushButton("Proceed anyway")
        proceed_btn.setStyleSheet("background:#e35f3b; color:white;")
        btn_row.addWidget(wait_btn)
        btn_row.addWidget(proceed_btn)
        layout.addLayout(btn_row)

        def _on_wait():
            try:
                extra = float(extra_edit.text())
            except ValueError:
                extra = 60.0
            self._stability_check_result = f'wait:{extra}'
            self._stability_check_event.set()
            dlg.accept()

        def _on_proceed():
            self._stability_check_result = 'proceed'
            self._stability_check_event.set()
            dlg.accept()

        wait_btn.clicked.connect(_on_wait)
        proceed_btn.clicked.connect(_on_proceed)
        dlg.exec()

    def _force_averaging_now(self):
        try:
            self.core.force_averaging = True
            self.set_status("Force averaging requested — will start averaging at next poll.")
        except Exception:
            self.set_status("Force averaging: no measurement running.")

    def on_stop(self):
        if self.stop_requested:
            return
        self.stop_requested = True
        try:
            self.core.stop_requested = True
        except Exception:
            pass
        self.stop_button.setEnabled(False)
        self.set_status("Stop requested. Waiting for current step to finish...")

    def open_fit_dialog(self):
        if self.current_data is None:
            QMessageBox.warning(self, "No data", "Run and complete the measurement before fitting.")
            return

        dialog = FitDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        try:
            min_freq, max_freq = dialog.get_range()
        except ValueError:
            QMessageBox.critical(self, "Invalid input", "Please enter valid numeric frequencies.")
            return

        if min_freq >= max_freq:
            QMessageBox.critical(self, "Invalid range", "Minimum frequency must be smaller than maximum frequency.")
            return

        self.perform_fit(min_freq, max_freq)

    def perform_fit(self, min_freq: float, max_freq: float):
        A = (4 * self.get_param('L') * self.get_param('R') * self.get_param('r')) / (np.pi**4 * self.get_param('S'))
        freqs_all = np.array(self.current_data)[:, 0]
        v3w_all   = np.array(self.current_data)[:, 5]

        self.fit_range = (min_freq, max_freq)

        # ---- Run Global Fit (must succeed) ----
        try:
            k_fit, gamma_fit, k_err, gamma_fit_err, freqs_fit_g, v3w_fit_g, v_fit_g = \
                self.core.fit_3omega_fixed_A(self.current_data, A, f_min=min_freq, f_max=max_freq)
            self.fit_results = {
                'global':        (k_fit, gamma_fit, k_err, gamma_fit_err),
                'global_curve':  (list(freqs_fit_g), list(v_fit_g)),
                'phase':         None,
                'phase_curve':   None,
                'phase_data':    None,
                'accurate':      None,
                'accurate_curve': None,
                'fit_range':     (min_freq, max_freq),
            }
            self.set_status(f"Fit complete: k = {k_fit:.4f} ± {k_err:.4f} W/mK,  γ = {gamma_fit:.4e}")
            self.save_dir_entry.setEnabled(True)
            self.save_name_entry.setEnabled(True)
            self.save_button.setEnabled(True)
        except Exception as exc:
            QMessageBox.critical(self, "Fit error", str(exc))
            self.set_status(f"Fit error: {exc}")
            return

        # ---- Run Phase Fit ----
        phase_ok = False
        try:
            gamma_p, gamma_p_err, freqs_sel, tan_phi, slope, intercept = \
                self.core.phase_fit(self.current_data, f_min=min_freq, f_max=max_freq)
            phase_ok = True
            self.fit_results['phase'] = (gamma_p, gamma_p_err)
            fit_line = slope * np.array(freqs_sel) + intercept
            self.fit_results['phase_curve'] = (list(freqs_sel), list(fit_line))
            self.fit_results['phase_data']  = (list(freqs_sel), list(tan_phi))
        except Exception as phase_exc:
            phase_err_msg = str(phase_exc)

        # ---- Run Accurate Fit (needs gamma from phase fit) ----
        accurate_ok = False
        if phase_ok:
            try:
                k_acc, k_acc_err, freqs_fit_a, v3w_fit_a, v_fit_a = \
                    self.core.fit_3omega_fixed_A_gamma(
                        self.current_data, A, f_min=min_freq, f_max=max_freq, gamma=gamma_p)
                accurate_ok = True
                self.fit_results['accurate']       = (k_acc, k_acc_err)
                self.fit_results['accurate_curve'] = (list(freqs_fit_a), list(v_fit_a))
            except Exception as acc_exc:
                acc_err_msg = str(acc_exc)
        else:
            acc_err_msg = f"Phase fit failed: {phase_err_msg}"

        # ---- Build tabbed result dialog ----
        fit_dialog = QDialog(self)
        fit_dialog.setWindowTitle(f"Fit Results  —  Range: {min_freq}–{max_freq} Hz")
        fit_dialog.setMinimumSize(800, 700)
        fit_dialog.resize(960, 800)
        dlg_layout = QVBoxLayout(fit_dialog)
        dlg_layout.setSpacing(6)
        dlg_layout.setContentsMargins(10, 10, 10, 10)

        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabBar::tab {
                background: #1a2535;
                color: #7a9ab5;
                padding: 8px 22px;
                font-size: 12px;
                border: 1px solid #2d3f52;
                border-bottom: none;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #1f6fbf;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #4a90d9;
                border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                background: #243447;
                color: #c0d8f0;
            }
            QTabWidget::pane {
                border: 1px solid #2d3f52;
                background: #141e2b;
            }
        """)
        dlg_layout.addWidget(tabs)

        fit_toolbars = []

        def _styled_ax(ax, title, xlabel, ylabel):
            ax.set_title(title, fontsize=13, pad=10)
            ax.set_xlabel(xlabel, fontsize=11, labelpad=8)
            ax.set_ylabel(ylabel, fontsize=11, labelpad=8)
            ax.tick_params(labelsize=10)
            ax.legend(fontsize=10)
            ax.grid(True)

        def _make_error_tab(msg):
            w = QWidget()
            l = QVBoxLayout(w)
            lbl = QLabel(f"Could not compute this fit:\n\n{msg}")
            lbl.setStyleSheet("color:#e35f3b; font-size:11px; padding:20px;")
            lbl.setAlignment(Qt.AlignCenter)
            l.addWidget(lbl)
            return w

        def _make_fit_tab(param_text, fig_fn):
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(8, 8, 8, 4)
            l.setSpacing(6)
            lbl = QLabel(param_text)
            lbl.setStyleSheet(
                "font-size:11px; font-weight:bold; font-family:monospace;"
                " color:#3be362; padding:6px 12px;"
                " background:#0e1620; border-radius:4px;"
            )
            lbl.setAlignment(Qt.AlignCenter)
            l.addWidget(lbl)
            fig = fig_fn()
            canvas = FigureCanvas(fig)
            canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            canvas.setMinimumSize(600, 400)
            toolbar = NavigationToolbar(canvas, fit_dialog)
            toolbar.hide()
            fit_toolbars.append(toolbar)
            l.addWidget(canvas)
            return w, fig

        figs_to_close = []

        # --- Global Fit tab ---
        def _global_fig():
            fig = Figure(figsize=(7.5, 5))
            ax = fig.add_subplot(111)
            ax.scatter(freqs_all, v3w_all, label="All data")
            ax.scatter(freqs_fit_g, v3w_fit_g, color='red', label="Fit region")
            ax.plot(freqs_fit_g, v_fit_g, linewidth=2, label="Fit")
            ax.axvspan(min_freq, max_freq, alpha=0.2, label="Fit window")
            _styled_ax(ax, "3ω Fit (STRICT RANGE)", "Frequency (Hz)", "V3ω (V)")
            fig.set_tight_layout({'pad': 2.0})
            return fig

        global_tab, fig_g = _make_fit_tab(
            f"k  =  {k_fit:.4f} ± {k_err:.4f} W/mK        "
            f"γ  =  {gamma_fit:.4e} ± {gamma_fit_err:.4e}        "
            f"Range: {min_freq} – {max_freq} Hz",
            _global_fig
        )
        figs_to_close.append(fig_g)
        tabs.addTab(global_tab, "Global Fit")

        # --- Phase Fit tab ---
        if phase_ok:
            def _phase_fig():
                fig = Figure(figsize=(7.5, 5))
                ax = fig.add_subplot(111)
                ax.scatter(freqs_sel, tan_phi, label="Data")
                ax.plot(freqs_sel, slope * freqs_sel + intercept, label="Linear fit")
                _styled_ax(ax, "Phase Fit", "Frequency (Hz)", "tan(φ)")
                fig.set_tight_layout({'pad': 2.0})
                return fig

            phase_tab, fig_p = _make_fit_tab(
                f"γ  =  {gamma_p:.4e} ± {gamma_p_err:.4e}        "
                f"Range: {min_freq} – {max_freq} Hz",
                _phase_fig
            )
            figs_to_close.append(fig_p)
            tabs.addTab(phase_tab, "Phase Fit")
        else:
            tabs.addTab(_make_error_tab(phase_err_msg), "Phase Fit")

        # --- Accurate Fit tab ---
        if accurate_ok:
            def _accurate_fig():
                fig = Figure(figsize=(7.5, 5))
                ax = fig.add_subplot(111)
                ax.scatter(freqs_all, v3w_all, label="All data")
                ax.scatter(freqs_fit_a, v3w_fit_a, color='red', label="Fit region")
                ax.plot(freqs_fit_a, v_fit_a, linewidth=2, label="Fit (fixed γ)")
                ax.axvspan(min_freq, max_freq, alpha=0.2, label="Fit window")
                _styled_ax(ax, "3ω Fit (fixed A and γ)", "Frequency (Hz)", "V3ω (V)")
                fig.set_tight_layout({'pad': 2.0})
                return fig

            accurate_tab, fig_a = _make_fit_tab(
                f"k  =  {k_acc:.4f} ± {k_acc_err:.4f} W/mK        "
                f"γ  =  {gamma_p:.4e}  (fixed from phase fit)        "
                f"Range: {min_freq} – {max_freq} Hz",
                _accurate_fig
            )
            figs_to_close.append(fig_a)
            tabs.addTab(accurate_tab, "Accurate Fit")
        else:
            tabs.addTab(_make_error_tab(acc_err_msg), "Accurate Fit")

        # ---- Bottom row: zoom button + close ----
        def _toggle_fit_zoom(checked):
            for tb in fit_toolbars:
                if checked:
                    if tb.mode.name != 'ZOOM':
                        tb.zoom()
                else:
                    if tb.mode.name == 'ZOOM':
                        tb.zoom()
                    tb.home()

        zoom_btn = QPushButton("🔍 Zoom")
        zoom_btn.setCheckable(True)
        zoom_btn.setToolTip(
            "Enable: click and drag on a plot to zoom in.\n"
            "Click again to disable zoom and reset view."
        )
        zoom_btn.setStyleSheet(
            "QPushButton { background:#2b2b3d; color:white; border:1px solid #555577;"
            "  padding:4px 14px; border-radius:4px; }"
            "QPushButton:checked { background:#3a86ff; color:white; }"
        )
        zoom_btn.toggled.connect(_toggle_fit_zoom)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(fit_dialog.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(zoom_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        dlg_layout.addLayout(btn_row)

        fit_dialog.exec()
        for fig in figs_to_close:
            fig.clf()

        # Store fit results in measurement history if this data is in the current session
        if self.fit_results is not None and self.current_data is not None:
            for meas in self._measurement_history:
                if meas['data_3w'] == self.current_data or (
                    len(meas['data_3w']) == len(self.current_data) and
                    all(a == b for a, b in zip(meas['data_3w'], self.current_data))
                ):
                    meas['fit_results'] = self.fit_results
                    break

    def _ts_dataframe(self):
        """Build time series DataFrame from stored callback arrays."""
        if self._ts_t_data is None:
            return None
        min_len = min(len(self._ts_t_data), len(self._ts_freq_col),
                      len(self._ts_I_data), len(self._ts_r_data), len(self._ts_theta_data))
        if min_len == 0:
            return None
        import pandas as pd
        return pd.DataFrame({
            'Time (s)':       list(self._ts_t_data[:min_len]),
            'Frequency (Hz)': self._ts_freq_col[:min_len],
            'Current (A)':    list(self._ts_I_data[:min_len]),
            'V_3ω (V)':       list(self._ts_r_data[:min_len]),
            'θ (°)':          list(self._ts_theta_data[:min_len]),
        })

    def _calib_dataframe(self):
        """Build calibration time series DataFrame from stored callback arrays."""
        if self._calib_t_data is None:
            return None
        arrays = [self._calib_t_data, self._calib_r_data, self._calib_theta_data]
        if self._calib_i_data is not None:
            arrays.append(self._calib_i_data)
        min_len = min(len(a) for a in arrays)
        if min_len == 0:
            return None
        import pandas as pd
        df = pd.DataFrame({
            'Time (s)': list(self._calib_t_data[:min_len]),
            'R₁ω (V)':  list(self._calib_r_data[:min_len]),
            'θ (°)':    list(self._calib_theta_data[:min_len]),
        })
        if self._calib_i_data is not None:
            df['I_AC (A)'] = list(self._calib_i_data[:min_len])
        return df

    def _add_to_measurement_history(self, data, status, fit_results=None):
        """Add a measurement to the session history."""
        import datetime
        name = self.save_name_entry.text().strip() or f"{datetime.date.today().strftime('%Y%m%d')}_measurement"
        # Handle duplicate names by adding suffix
        existing = [m['name'] for m in self._measurement_history]
        if name in existing:
            base = name.rsplit('_', 1)[0] if '_' in name else name
            n = 1
            while f"{base}_{n}" in existing:
                n += 1
            name = f"{base}_{n}"

        _1w_st = getattr(self, '_auto_1w_state', None)
        _1w_rows = _1w_st['freq_rows'] if _1w_st else []
        entry = {
            'name': name,
            'status': status,  # 'completed' or 'interrupted'
            'data_3w': list(data) if data else [],
            'data_iv': list(self._latest_iv_data) if self._latest_iv_data else [],
            'data_1w': [[r['Frequency (Hz)'], r['R_1w_avg (Ohm)'], r['theta_avg (deg)']]
                         for r in _1w_rows],
            'fit_results': fit_results,
            'params': self.read_parameters(),
            'calibrated': self._phase_calibrated,
            'calib_phase_deg': self._calibrated_phase_deg,
            'timestamp': datetime.datetime.now(),
            'ts_data': {  # time series data
                't': list(self._ts_t_data) if self._ts_t_data else [],
                'freq': list(self._ts_freq_col) if self._ts_freq_col else [],
                'I': list(self._ts_I_data) if self._ts_I_data else [],
                'r': list(self._ts_r_data) if self._ts_r_data else [],
                'theta': list(self._ts_theta_data) if self._ts_theta_data else [],
            }
        }
        self._measurement_history.append(entry)
        if self._results_window is not None:
            self._results_window._refresh_sidebar()

    def open_results(self):
        """Open Results panel."""
        try:
            if self._results_window is None:
                self._results_window = ResultsWindow(self)
            self._results_window.show()
            self._results_window.raise_()
            self._results_window.activateWindow()
        except Exception as e:
            QMessageBox.critical(self, "Results Error", f"Could not open Results window:\n{e}")
            self._results_window = None

    def open_analysis(self):
        """Open Analysis window."""
        try:
            if not hasattr(self, '_analysis_window') or self._analysis_window is None:
                self._analysis_window = AnalysisWindow(self)
            self._analysis_window.show()
            self._analysis_window.raise_()
            self._analysis_window.activateWindow()
        except Exception as e:
            QMessageBox.critical(self, "Analysis Error", f"Could not open Analysis window:\n{e}")
            self._analysis_window = None

    def open_math_functions(self):
        """Open the MathFunctions window (Calculator + Excel tabs)."""
        try:
            if self._math_functions_window is None:
                self._math_functions_window = MathFunctionsWindow(self)
            self._math_functions_window.show()
            self._math_functions_window.raise_()
            self._math_functions_window.activateWindow()
        except Exception as e:
            QMessageBox.critical(self, "MathFunctions Error", f"Could not open MathFunctions window:\n{e}")
            self._math_functions_window = None

    def _auto_backup_calibration(self, completed=True, live=False):
        """Silently back up calibration time series to Backup_data folder.

        Exactly one file pair per calibration run: self._backup_suffix_calib
        is reserved on the first write (reset to None when a new calibration
        starts — see PhaseCalibrationWindow._start) and reused on every later
        call, so periodic ticks/stop/completion overwrite the same pair.
        """
        df = self._calib_dataframe()
        if df is None:
            return
        save_dir = self.save_dir_entry.text().strip() or os.getcwd()
        backup_folder = os.path.join(save_dir, 'Backup_data')
        status = "IN PROGRESS" if live else ("COMPLETED" if completed else "INTERRUPTED")
        p_entries = [f"  {'Status':<28}:  {status}"]
        if self._calibrated_phase_deg is not None:
            p_entries.append(
                f"  {'Calibrated PHAS (°)':<28}:  {self._calibrated_phase_deg:.4f}")
        _, self._backup_suffix_calib = _silent_backup(
            backup_folder, 'data_calibration',
            df.values.tolist(), list(df.columns),
            completed=completed,
            title=f"CALIBRATION TIME SERIES ({status})",
            sections=[("Calibration Result", p_entries)],
            suffix=self._backup_suffix_calib,
        )

    def _periodic_autosave_3w(self):
        """Crash-safety snapshot, called by self._autosave_timer every interval
        while a 3ω measurement is running. Always overwrites the same '_live'
        file — see _silent_backup's live= flag."""
        try:
            partial = getattr(self.core, 'partial_measurement_results', [])
            self._auto_backup_3w(partial, completed=False, live=True)
        except Exception as e:
            print(f"Periodic autosave failed: {e}")

    def _auto_backup_3w(self, data, completed, live=False):
        """Silently back up 3ω data to Backup_data folder.

        `data` (the per-frequency averaged rows) and the raw time series are
        backed up independently: a stop during the very first frequency's
        wait/average phase means `data` is still empty, but the time series
        already has samples — that must still be saved.

        Exactly one file pair per run: self._backup_suffix_3w / _ts is
        reserved on the first write of a run (reset to None in on_run) and
        reused on every later call — periodic crash-safety tick, stop, or
        final completion all overwrite that same pair in place.
        live=True marks a periodic crash-safety tick (no status-bar spam).
        """
        df_ts = self._ts_dataframe()
        if not data and df_ts is None:
            return
        save_dir = self.save_dir_entry.text().strip() or os.getcwd()
        backup_folder = os.path.join(save_dir, 'Backup_data')
        base_name = _backup_base_name(self.save_name_entry.text())
        status = "IN PROGRESS" if live else ("COMPLETED" if completed else "INTERRUPTED")
        try:
            p = self.read_parameters()
            meas_entries = [
                f"  {'Status':<28}:  {status}",
                f"  {'AC Voltage':<28}:  {p['AC_VOLTAGE']:.4f} V",
                f"  {'AC Current':<28}:  {p['AC_CURRENT']:.6g} A",
                f"  {'Frequencies (Hz)':<28}:  {', '.join(f'{f:.4g}' for f in p.get('FREQUENCIES', [p['START_FREQ']]))}",
                f"  {'Global Wait Time':<28}:  {p['WAIT_TIME']:.1f} s",
                f"  {'Averaging Time':<28}:  {p['AVERAGE_TIME']:.1f} s",
                f"  {'Stabilisation Time':<28}:  {p['STABILIZATION_TIME']:.1f} s",
                f"  {'Polling Interval (dt)':<28}:  {p['dt']:.3f} s",
                f"  {'Resistance (R)':<28}:  {p['R']:.4f} Ohm",
                f"  {'dR/dT (r)':<28}:  {p['r']:.4f} Ohm/K",
                f"  {'Length (L)':<28}:  {p['L']:.4e} m",
                f"  {'Cross Section (S)':<28}:  {p['S']:.4e} m^2",
                f"  {'1ω Phase Calibration':<28}:  {'Yes' if self._phase_calibrated else 'No'}",
            ] + ([f"  {'Calibrated PHAS (°)':<28}:  {self._calibrated_phase_deg:.4f}"]
                 if self._phase_calibrated else [])
        except Exception:
            meas_entries = [f"  {'Status':<28}:  {status}"]

        path = None
        if data:
            path, self._backup_suffix_3w = _silent_backup(
                backup_folder, base_name, data,
                columns=["Frequency (Hz)", "Current (A)", "in phase voltage (V)",
                         "out of phase voltage (V)", "V3w_measured (V)",
                         "V_3omega_calculated (V)", "Theta (degree)"],
                completed=completed,
                title=f"RUN MEASUREMENT PARAMETERS ({status})",
                sections=[("Measurement Settings", meas_entries),
                          ("Lock-in Parameters", _lockin_human_readable(self.core))],
                suffix=self._backup_suffix_3w,
            )

        # Also backup the time series — independent of whether any
        # frequency fully completed its wait+average phase yet.
        if df_ts is not None:
            _, self._backup_suffix_3w_ts = _silent_backup(
                backup_folder, 'Time series_' + base_name,
                df_ts.values.tolist(), list(df_ts.columns),
                completed=completed,
                title=f"MEASUREMENT TIME SERIES ({status})",
                sections=[],
                suffix=self._backup_suffix_3w_ts,
            )

        if live:
            return
        if path:
            self.set_status(f"Backup: {os.path.basename(path)}")
        elif df_ts is not None:
            self.set_status(f"Backup: Time series_{base_name} ({status.lower()})")

    def save_data(self):
        if self.current_data is None:
            QMessageBox.warning(self, "No data", "No measurement data available to save.")
            return

        folder = self.save_dir_entry.text().strip() or "."
        filename = self.save_name_entry.text().strip()

        if not filename:
            QMessageBox.critical(self, "Invalid filename", "Enter a file name before saving.")
            return

        filetype = self.filetype_box.currentText()  # ".csv" or ".txt"
        if not filename.lower().endswith(".csv") and not filename.lower().endswith(".txt"):
            filename += filetype

        os.makedirs(folder, exist_ok=True)
        full_path = os.path.join(folder, filename)

        if os.path.exists(full_path):
            reply = QMessageBox.question(
                self, "File Already Exists",
                f"{filename} already exists in this folder:\n{folder}\n\n"
                "Overwrite it with this measurement's data?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        df = self.core.pd.DataFrame(
            self.current_data,
            columns=[
                "Frequency (Hz)",
                "Current (A)",
                "in phase voltage (V)",
                "out of phase voltage (V)",
                "V3w_measured (V)",
                "V_3omega_calculated (V)",
                "Theta (degree)",
            ],
        )

        # ---- Add fit result columns (all NaN in data rows, filled in summary row) ----
        import numpy as np
        fit_cols = [
            "k_fit (Global Fit)",
            "k_fit_error (Global Fit)",
            "gamma_fit (Global Fit)",
            "gamma_fit_err (Global Fit)",
            "k_low_freq (Global Fit)",
            "gamma (Phase Fit)",
            "gamma_err (Phase Fit)",
            "k_fit (Accurate Fit)",
            "k_fit_error (Accurate Fit)",
        ]
        for col in fit_cols:
            df[col] = np.nan

        try:
            A = (4 * self.get_param('L') * self.get_param('R') * self.get_param('r')) / (np.pi**4 * self.get_param('S'))
            summary = {col: np.nan for col in df.columns}

            if self.fit_results is not None:
                global_res = self.fit_results.get('global')
                phase_res  = self.fit_results.get('phase')
                acc_res    = self.fit_results.get('accurate')

                if global_res is not None:
                    k_fit, gamma_fit, k_err, gamma_fit_err = global_res
                    summary["k_fit (Global Fit)"]      = k_fit
                    summary["k_fit_error (Global Fit)"] = k_err
                    summary["gamma_fit (Global Fit)"]   = gamma_fit
                    summary["gamma_fit_err (Global Fit)"] = gamma_fit_err
                    try:
                        fit_min, fit_max = getattr(self, 'fit_range', (None, None))
                        summary["k_low_freq (Global Fit)"] = \
                            self.core.compute_k_lowfreq(self.current_data, A, fit_min, fit_max)
                    except Exception as klf_exc:
                        summary["k_low_freq (Global Fit)"] = np.nan
                        self.set_status(f"k_low_freq skipped: {klf_exc}")

                if phase_res is not None:
                    gamma_p, gamma_p_err = phase_res
                    summary["gamma (Phase Fit)"]   = gamma_p
                    summary["gamma_err (Phase Fit)"] = gamma_p_err

                if acc_res is not None:
                    k_acc, k_acc_err = acc_res
                    summary["k_fit (Accurate Fit)"]      = k_acc
                    summary["k_fit_error (Accurate Fit)"] = k_acc_err

            df.loc[len(df)] = summary

        except Exception:
            pass

        try:
            if filetype == ".csv":
                df.to_csv(full_path, index=False)
            else:
                df.to_csv(full_path, index=False, sep="\t")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed",
                f"Could not save data to:\n{full_path}\n\n{exc}\n\n"
                "The file may be open in another program (e.g. Excel) — "
                "close it and try again.")
            return

        settings = load_settings()
        settings["filetype"] = filetype
        save_settings(settings)

        try:
            params_path = os.path.join(folder, filename.rsplit(".", 1)[0] + "_params.txt")
            p = self.read_parameters()
            meas_entries = [
                f"  {'AC Voltage':<28}:  {p['AC_VOLTAGE']:.4f} V",
                f"  {'AC Current':<28}:  {p['AC_CURRENT']:.6g} A",
                f"  {'Frequencies (Hz)':<28}:  {', '.join(f'{f:.4g}' for f in p.get('FREQUENCIES', [p['START_FREQ']]))}",
                f"  {'Global Wait Time':<28}:  {p['WAIT_TIME']:.1f} s",
                f"  {'Averaging Time':<28}:  {p['AVERAGE_TIME']:.1f} s",
                f"  {'Stabilisation Time':<28}:  {p['STABILIZATION_TIME']:.1f} s",
                f"  {'Polling Interval (dt)':<28}:  {p['dt']:.3f} s",
                f"  {'Resistance (R)':<28}:  {p['R']:.4f} Ohm",
                f"  {'dR/dT (r)':<28}:  {p['r']:.4f} Ohm/K",
                f"  {'Length (L)':<28}:  {p['L']:.4e} m",
                f"  {'Cross Section (S)':<28}:  {p['S']:.4e} m^2",
                f"  {'1ω Phase Calibration':<28}:  {'Yes' if self._phase_calibrated else 'No'}",
            ] + ([f"  {'Calibrated PHAS (°)':<28}:  {self._calibrated_phase_deg:.4f}"]
                 if self._phase_calibrated else [])
            _write_params_file(params_path, "RUN MEASUREMENT PARAMETERS", [
                ("Measurement Settings", meas_entries),
                ("Lock-in Parameters",  _lockin_human_readable(self.core)),
            ])
        except Exception as e:
            print(f"Could not save params file: {e}")

        reply = QMessageBox.question(self, "Save Plots",
            "Would you like to save the plots?",
            QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            try:
                base = filename.rsplit(".", 1)[0]
                self.fig_time.savefig(os.path.join(folder, "all frequencies_" + base + ".png"))
                self.fig_summary.savefig(os.path.join(folder, "frequency_" + base + ".png"))
            except Exception:
                pass

        # Save time series alongside main data
        df_ts = self._ts_dataframe()
        if df_ts is not None:
            try:
                ts_base = filename.rsplit(".", 1)[0]
                ts_path = os.path.join(folder, "Time series_" + ts_base + ".csv")
                df_ts.to_csv(ts_path, index=False)
            except Exception as e:
                print(f"Time series save failed: {e}")

        # Save calibration time series if available
        df_calib = self._calib_dataframe()
        if df_calib is not None:
            try:
                calib_base = filename.rsplit(".", 1)[0]
                calib_path = os.path.join(folder, "calibration_" + calib_base + ".csv")
                df_calib.to_csv(calib_path, index=False)
            except Exception as e:
                print(f"Calibration save failed: {e}")

        QMessageBox.information(self, "Saved", f"Data saved to:\n{full_path}")
        self.set_status(f"Saved to {full_path}")


class CalculatorWidget(QWidget):
    """Scientific calculator — reuses formula_engine's tokenizer/parser/AST
    directly (same grammar as the spreadsheet), with its own function
    registry so SIN/COS/TAN/ASIN/ACOS/ATAN respect a live Deg/Rad toggle
    (spreadsheet formulas stay radians-only, matching Excel convention)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle_mode = "deg"
        self._memory = 0.0
        self._funcs = fe.make_calculator_functions(lambda: self._angle_mode)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._history_lbl = QLabel("")
        self._history_lbl.setStyleSheet(
            "color:#888899; font-size:11px; font-family:Consolas,'Courier New',monospace;")
        self._history_lbl.setAlignment(Qt.AlignRight)
        layout.addWidget(self._history_lbl)

        self.display = QLineEdit()
        self.display.setAlignment(Qt.AlignRight)
        self.display.setStyleSheet(
            "background:#12121c; color:#4af4a8; font-size:24px; font-weight:bold;"
            " font-family:Consolas,'Courier New',monospace; padding:10px;"
            " border:1px solid #444466; border-radius:6px;")
        self.display.returnPressed.connect(self.evaluate)
        layout.addWidget(self.display)

        top_row = QHBoxLayout()
        self.mode_btn = QPushButton("DEG")
        self.mode_btn.setCheckable(True)
        self.mode_btn.setStyleSheet(
            "QPushButton { background:#2e2e40; color:#aaaacc; border:1px solid #444466;"
            "  border-radius:5px; padding:5px 10px; font-weight:bold; font-size:10px; }"
            "QPushButton:checked { background:#3a4a7a; color:white; }")
        self.mode_btn.toggled.connect(self._toggle_mode)
        self.mem_lbl = QLabel("M: 0")
        self.mem_lbl.setStyleSheet("color:#888899; font-size:11px;")
        top_row.addWidget(self.mode_btn)
        top_row.addStretch(1)
        top_row.addWidget(self.mem_lbl)
        layout.addLayout(top_row)

        grid = QGridLayout()
        grid.setSpacing(5)
        layout.addLayout(grid)

        _num_style = (
            "QPushButton { background:#2b2b3d; color:white; font-size:15px; font-weight:bold;"
            "  border-radius:6px; padding:10px; }"
            "QPushButton:hover { background:#3a3a55; }")
        _fn_style = (
            "QPushButton { background:#22283a; color:#a0c4ff; font-size:12px; font-weight:bold;"
            "  border-radius:6px; padding:9px; }"
            "QPushButton:hover { background:#2e3650; }")
        _op_style = (
            "QPushButton { background:#3a4a7a; color:white; font-size:16px; font-weight:bold;"
            "  border-radius:6px; padding:10px; }"
            "QPushButton:hover { background:#4a5a9a; }")
        _eq_style = (
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "    stop:0 #00c6a7, stop:1 #0077ff); color:white; font-size:16px; font-weight:bold;"
            "  border-radius:6px; padding:10px; }")
        _clr_style = (
            "QPushButton { background:#a83244; color:white; font-size:13px; font-weight:bold;"
            "  border-radius:6px; padding:10px; }"
            "QPushButton:hover { background:#c23f54; }")
        _mem_style = (
            "QPushButton { background:#2e2e40; color:#d0d0e0; font-size:11px; font-weight:bold;"
            "  border-radius:5px; padding:6px; }"
            "QPushButton:hover { background:#3a3a55; }")

        def _insert(text):
            self.display.insert(text)
            self.display.setFocus()

        def _insert_fn(fname):
            self.display.insert(fname + "()")
            self.display.setCursorPosition(self.display.cursorPosition() - 1)
            self.display.setFocus()

        rows = [
            [("sin", lambda: _insert_fn("SIN")), ("cos", lambda: _insert_fn("COS")),
             ("tan", lambda: _insert_fn("TAN")), ("ln", lambda: _insert_fn("LN")),
             ("log", lambda: _insert_fn("LOG"))],
            [("asin", lambda: _insert_fn("ASIN")), ("acos", lambda: _insert_fn("ACOS")),
             ("atan", lambda: _insert_fn("ATAN")), ("√x", lambda: _insert_fn("SQRT")),
             ("x²", lambda: _insert("^2"))],
            [("(", lambda: _insert("(")), (")", lambda: _insert(")")),
             ("π", lambda: _insert("PI()")), ("e", lambda: _insert("E()")),
             ("x^y", lambda: _insert("^"))],
            [("7", lambda: _insert("7")), ("8", lambda: _insert("8")),
             ("9", lambda: _insert("9")), ("÷", lambda: _insert("/")),
             ("C", self.clear_all)],
            [("4", lambda: _insert("4")), ("5", lambda: _insert("5")),
             ("6", lambda: _insert("6")), ("×", lambda: _insert("*")),
             ("⌫", self.backspace)],
            [("1", lambda: _insert("1")), ("2", lambda: _insert("2")),
             ("3", lambda: _insert("3")), ("-", lambda: _insert("-")),
             ("x!", lambda: _insert_fn("FACT"))],
            [("0", lambda: _insert("0")), (".", lambda: _insert(".")),
             ("%", lambda: _insert("%")), ("+", lambda: _insert("+")),
             ("=", self.evaluate)],
        ]
        for r, row_defs in enumerate(rows):
            for c, (label, slot) in enumerate(row_defs):
                btn = QPushButton(label)
                if label == "C":
                    btn.setStyleSheet(_clr_style)
                elif label == "=":
                    btn.setStyleSheet(_eq_style)
                elif label in ("÷", "×", "-", "+", "x^y"):
                    btn.setStyleSheet(_op_style)
                elif label.isdigit() or label == ".":
                    btn.setStyleSheet(_num_style)
                else:
                    btn.setStyleSheet(_fn_style)
                btn.clicked.connect(slot)
                grid.addWidget(btn, r, c)

        mem_row = QHBoxLayout()
        for label, slot in [("MC", self.mem_clear), ("MR", self.mem_recall),
                             ("M+", self.mem_add), ("M-", self.mem_sub), ("MS", self.mem_store)]:
            b = QPushButton(label)
            b.setStyleSheet(_mem_style)
            b.clicked.connect(slot)
            mem_row.addWidget(b)
        layout.addLayout(mem_row)

        # ── History — every evaluated expression this session, most recent
        # first. Click an entry to load its expression back into the
        # display for editing/re-evaluation (not persisted across restarts;
        # a fresh calculator tab starts with an empty history, matching
        # every other in-app "session" list like the Excel undo stack).
        hist_hdr = QHBoxLayout()
        hist_hdr.addWidget(QLabel("History"))
        hist_hdr.addStretch(1)
        clear_hist_btn = QPushButton("Clear")
        clear_hist_btn.setStyleSheet(
            "QPushButton { background:#2e2e40; color:#aaaacc; border:1px solid #444466;"
            "  border-radius:4px; padding:3px 8px; font-size:10px; }"
            "QPushButton:hover { background:#3a3a55; color:white; }")
        clear_hist_btn.clicked.connect(self.clear_history)
        hist_hdr.addWidget(clear_hist_btn)
        layout.addLayout(hist_hdr)

        self._history_list = QListWidget()
        self._history_list.setStyleSheet(
            "QListWidget { background:#12121c; color:#c8d0e0; border:1px solid #444466;"
            "  border-radius:6px; font-family:Consolas,'Courier New',monospace; font-size:11px; }"
            "QListWidget::item { padding:4px 6px; }"
            "QListWidget::item:selected { background:#3a4a7a; color:white; }"
            "QListWidget::item:hover { background:#22283a; }")
        self._history_list.setMaximumHeight(120)
        self._history_list.itemClicked.connect(self._recall_history_item)
        layout.addWidget(self._history_list)

    def _toggle_mode(self, checked):
        self._angle_mode = "rad" if checked else "deg"
        self.mode_btn.setText("RAD" if checked else "DEG")

    def clear_all(self):
        self.display.clear()
        self.display.setFocus()

    def backspace(self):
        self.display.backspace()
        self.display.setFocus()

    def _current_value(self):
        text = self.display.text().strip()
        if not text:
            return None
        try:
            ast_node = fe.parse_formula(text)
        except fe.FormulaSyntaxError:
            return None
        result = fe.eval_formula(ast_node, functions=self._funcs)
        if isinstance(result, fe.ErrorValue) or not isinstance(result, (int, float)):
            return None
        return float(result)

    def evaluate(self):
        text = self.display.text().strip()
        if not text:
            return
        try:
            ast_node = fe.parse_formula(text)
        except fe.FormulaSyntaxError:
            self._history_lbl.setText(text)
            self.display.setText("Syntax error")
            return
        result = fe.eval_formula(ast_node, functions=self._funcs)
        self._history_lbl.setText("%s =" % text)
        if isinstance(result, fe.ErrorValue):
            result_text = result.token
        elif isinstance(result, float):
            result_text = "%.10g" % result
        else:
            result_text = str(result)
        self.display.setText(result_text)
        self._add_history_entry(text, result_text)

    def _add_history_entry(self, expr, result_text):
        """Prepend one entry to the History list (most recent first)."""
        item = QListWidgetItem("%s = %s" % (expr, result_text))
        item.setData(Qt.ItemDataRole.UserRole, expr)
        self._history_list.insertItem(0, item)

    def _recall_history_item(self, item):
        """Clicking a history entry loads its original expression back into
        the display, ready to edit or re-evaluate — never auto-evaluates,
        since the point is usually to tweak a past calculation."""
        expr = item.data(Qt.ItemDataRole.UserRole)
        if expr is not None:
            self.display.setText(expr)
            self.display.setFocus()

    def clear_history(self):
        self._history_list.clear()

    def mem_clear(self):
        self._memory = 0.0
        self.mem_lbl.setText("M: 0")

    def _update_mem_label(self):
        self.mem_lbl.setText("M: %.6g" % self._memory)

    def mem_recall(self):
        self.display.setText("%.10g" % self._memory)

    def mem_add(self):
        v = self._current_value()
        if v is not None:
            self._memory += v
            self._update_mem_label()

    def mem_sub(self):
        v = self._current_value()
        if v is not None:
            self._memory -= v
            self._update_mem_label()

    def mem_store(self):
        v = self._current_value()
        if v is not None:
            self._memory = v
            self._update_mem_label()


class _SpreadsheetTable(QTableWidget):
    """QTableWidget with Excel-style Ctrl+C / Ctrl+V / Delete-to-clear and
    edit-routing support. QTableWidget provides none of these out of the
    box, and their absence makes a spreadsheet feel fundamentally broken.

    Native in-cell editing is disabled (see SpreadsheetGrid.__init__,
    setEditTriggers(NoEditTriggers)) -- ALL cell editing is routed through
    the formula bar instead (via self._grid, set by SpreadsheetGrid right
    after construction), so that clicking/dragging cells while composing a
    formula can insert their reference into it, exactly like Excel. This
    class only decides *when* an edit session should start (typing a
    character, F2, double-click); SpreadsheetGrid owns the actual editing
    state and reference-insertion logic."""

    _grid = None

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_at_current()
            return
        if (event.key() == Qt.Key.Key_Delete
                and self.state() != QAbstractItemView.State.EditingState):
            self._clear_selection()
            return
        if self._grid is not None:
            row, col = self.currentRow(), self.currentColumn()
            if row >= 0 and col >= 0:
                key = event.key()
                if key == Qt.Key.Key_F2:
                    self._grid.begin_edit_existing(row, col)
                    return
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._grid.move_current(1, 0)
                    return
                if key == Qt.Key.Key_Backspace:
                    self._clear_selection()
                    return
                text = event.text()
                if (text and text.isprintable()
                        and not (event.modifiers() & (
                            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))):
                    self._grid.begin_edit_new(row, col, text)
                    return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        if index.isValid() and self._grid is not None:
            self._grid.begin_edit_existing(index.row(), index.column())
            return
        super().mouseDoubleClickEvent(event)

    def _selected_block(self):
        ranges = self.selectedRanges()
        if not ranges:
            return None
        return max(ranges, key=lambda r: r.rowCount() * r.columnCount())

    def _copy_selection(self):
        rng = self._selected_block()
        if rng is None:
            return
        lines = []
        for r in range(rng.topRow(), rng.bottomRow() + 1):
            cells = []
            for c in range(rng.leftColumn(), rng.rightColumn() + 1):
                item = self.item(r, c)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def _paste_at_current(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        rng = self._selected_block()
        if rng is not None:
            start_row, start_col = rng.topRow(), rng.leftColumn()
        else:
            start_row, start_col = max(self.currentRow(), 0), max(self.currentColumn(), 0)
        rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if rows and rows[-1] == "":
            rows = rows[:-1]
        for i, row_text in enumerate(rows):
            r = start_row + i
            if r >= self.rowCount():
                break
            for j, cell_text in enumerate(row_text.split("\t")):
                c = start_col + j
                if c >= self.columnCount():
                    break
                item = self.item(r, c)
                if item is None:
                    item = QTableWidgetItem("")
                    self.setItem(r, c, item)
                item.setText(cell_text)

    def _clear_selection(self):
        for item in self.selectedItems():
            item.setText("")


class _FillHandle(QLabel):
    """The small square at the bottom-right corner of the current cell
    that, when dragged, copies that cell's content into the cells passed
    over -- Excel's fill handle. Relative references in a formula shift
    accordingly (formula_engine.translate_formula); $-anchored ones stay
    put. Lives as a small overlay widget on the table's viewport, always
    repositioned to track the current cell (see SpreadsheetGrid)."""

    def __init__(self, grid):
        super().__init__(grid.table.viewport())
        self._grid = grid
        self.setFixedSize(7, 7)
        self.setStyleSheet("background:#217346; border:1px solid #ffffff;")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._dragging = False
        self._anchor = None
        self.hide()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        row, col = self._grid.table.currentRow(), self._grid.table.currentColumn()
        if row < 0 or col < 0:
            return
        self._anchor = (row, col)
        self._dragging = True
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        vp = self._grid.table.viewport()
        pos = vp.mapFromGlobal(self.mapToGlobal(event.position().toPoint()
                                                  if hasattr(event, "position") else event.pos()))
        index = self._grid.table.indexAt(pos)
        if index.isValid():
            self._grid._preview_fill(self._anchor, index.row(), index.column())

    def mouseReleaseEvent(self, event):
        if not self._dragging:
            return
        self._dragging = False
        vp = self._grid.table.viewport()
        pos = vp.mapFromGlobal(self.mapToGlobal(event.position().toPoint()
                                                  if hasattr(event, "position") else event.pos()))
        index = self._grid.table.indexAt(pos)
        anchor = self._anchor
        self._anchor = None
        if index.isValid() and anchor is not None:
            self._grid._apply_fill(anchor, index.row(), index.column())
        else:
            self._grid._clear_fill_preview()


class SpreadsheetGrid(QWidget):
    """One spreadsheet tab's content: formula bar + QTableWidget grid, backed
    by a formula_engine.Sheet. One instance lives per inner Excel tab (one
    per opened/new file) inside ExcelTabContainer."""

    # Authentic Excel colors: white sheet, light gray headers, Excel-blue
    # selection fill, Office-green accents where a border/emphasis is needed.
    _SS_TABLE = (
        "QTableWidget { background:#ffffff; gridline-color:#d4d4d4;"
        "  color:#000000; border:1px solid #b0b0b0; font-size:12px;"
        "  selection-background-color:#c9dfef; selection-color:#000000; }"
        "QTableWidget::item { padding:2px 6px; border:none; }"
        "QTableWidget::item:selected { background:#c9dfef; color:#000000; }"
        "QHeaderView::section { background:#f3f2f1; color:#3a3a3a;"
        "  font-size:11px; padding:4px; border:none;"
        "  border-right:1px solid #d4d4d4; border-bottom:1px solid #d4d4d4; }"
        "QHeaderView::section:hover { background:#e5f1fb; color:#217346; }"
        "QTableCornerButton::section { background:#f3f2f1;"
        "  border-right:1px solid #d4d4d4; border-bottom:1px solid #d4d4d4; }"
        "QScrollBar:vertical { background:#f3f2f1; width:14px; }"
        "QScrollBar::handle:vertical { background:#c1c1c1; border-radius:6px; min-height:24px; }"
        "QScrollBar::handle:vertical:hover { background:#a0a0a0; }"
        "QScrollBar:horizontal { background:#f3f2f1; height:14px; }"
        "QScrollBar::handle:horizontal { background:#c1c1c1; border-radius:6px; min-width:24px; }"
        "QScrollBar::handle:horizontal:hover { background:#a0a0a0; }")

    N_ROWS = 200
    N_COLS = 26

    def __init__(self, parent=None, sheet=None, file_path=None):
        super().__init__(parent)
        self.sheet = sheet if sheet is not None else fe.Sheet()
        self.file_path = file_path
        self._loading = False

        # Excel-style click/drag-to-insert-reference state: while
        # _ref_target is set, the formula bar is the active edit surface
        # for that (row, col), and clicking/dragging grid cells or column
        # /row headers inserts their address into the formula bar instead
        # of performing normal navigation.
        self._ref_target = None
        self._ref_insert_start = None
        self._ref_insert_end = None
        self._ref_drag_anchor = None
        self._last_header_col = None
        self._last_header_row = None
        self._header_col_anchor = None
        self._header_row_anchor = None
        self._autoscroll_timer = None
        self._autoscroll_kind = None
        self._drag_last_pos = None

        self.setStyleSheet("background:#ffffff;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 5, 6, 5)
        bar.setSpacing(6)
        bar_frame = QFrame()
        bar_frame.setLayout(bar)
        bar_frame.setStyleSheet("background:#f8f8f8; border-bottom:1px solid #d4d4d4;")
        # Name Box -- Excel's bordered cell-reference box at the far left
        self._addr_label = QLabel("A1")
        self._addr_label.setFixedWidth(56)
        self._addr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._addr_label.setStyleSheet(
            "color:#000000; font-weight:bold; font-family:Consolas,'Courier New',monospace;"
            " background:#ffffff; border:1px solid #b0b0b0; border-radius:2px; padding:3px;")
        # Cancel (X) / Confirm (check) -- Excel shows these only while
        # actively editing a cell, giving an obvious, always-visible way
        # to abandon a botched formula instead of relying on Escape,
        # which is easy to not know about (a stuck/garbled in-progress
        # formula is otherwise hard to recover from cleanly).
        _edit_btn_style = (
            "QPushButton { background:#ffffff; border:1px solid #b0b0b0; border-radius:2px;"
            "  font-weight:bold; font-size:13px; padding:2px; }"
            "QPushButton:hover { background:#f0f0f0; }")
        self._cancel_edit_btn = QPushButton("✕")
        self._cancel_edit_btn.setFixedSize(26, 26)
        self._cancel_edit_btn.setStyleSheet(_edit_btn_style + "QPushButton { color:#c00000; }")
        self._cancel_edit_btn.setToolTip("Cancel (Esc)")
        self._cancel_edit_btn.clicked.connect(self._cancel_edit)
        self._confirm_edit_btn = QPushButton("✓")
        self._confirm_edit_btn.setFixedSize(26, 26)
        self._confirm_edit_btn.setStyleSheet(_edit_btn_style + "QPushButton { color:#217346; }")
        self._confirm_edit_btn.setToolTip("Confirm (Enter)")
        self._confirm_edit_btn.clicked.connect(lambda: self._commit_formula_bar())
        self._cancel_edit_btn.hide()
        self._confirm_edit_btn.hide()
        # fx -- Excel's function/formula indicator between the Name Box and the bar
        fx_label = QLabel("𝑓x")
        fx_label.setStyleSheet("color:#217346; font-weight:bold; font-size:13px; padding:0 2px;")
        self._formula_bar = QLineEdit()
        self._formula_bar.setStyleSheet(
            "background:#ffffff; color:#000000; font-family:Consolas,'Courier New',monospace;"
            " padding:4px; border:1px solid #b0b0b0; border-radius:2px;")
        self._formula_bar.returnPressed.connect(self._commit_formula_bar)
        self._formula_bar.textChanged.connect(self._on_formula_bar_text_changed)
        # Function-name autocomplete (Excel's formula IntelliSense) --
        # sorted() keeps it in sync with formula_engine.FUNCTIONS
        # automatically, no separate list to fall out of date.
        self._completer_span = None
        self._completer = QCompleter(sorted(fe.FUNCTIONS.keys()), self._formula_bar)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setWidget(self._formula_bar)
        self._completer.activated.connect(self._on_function_completed)
        bar.addWidget(self._addr_label)
        bar.addWidget(self._cancel_edit_btn)
        bar.addWidget(self._confirm_edit_btn)
        bar.addWidget(fx_label)
        bar.addWidget(self._formula_bar)
        layout.addWidget(bar_frame)

        self.table = _SpreadsheetTable(self.N_ROWS, self.N_COLS)
        self.table._grid = self
        self.table.setStyleSheet(self._SS_TABLE)
        self.table.setHorizontalHeaderLabels([fe.index_to_col(c) for c in range(self.N_COLS)])
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setDefaultSectionSize(80)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Native in-cell editing is disabled -- all editing goes through
        # the formula bar (see class docstring on _SpreadsheetTable) so
        # that reference-click-insertion works uniformly everywhere.
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)
        self.table.horizontalHeader().sectionClicked.connect(self._on_column_header_clicked)
        self.table.verticalHeader().sectionClicked.connect(self._on_row_header_clicked)
        self.table.horizontalHeader().sectionPressed.connect(self._on_column_header_pressed)
        self.table.horizontalHeader().sectionEntered.connect(self._on_column_header_entered)
        self.table.verticalHeader().sectionPressed.connect(self._on_row_header_pressed)
        self.table.verticalHeader().sectionEntered.connect(self._on_row_header_entered)
        layout.addWidget(self.table)

        self._error_brush = QColor("#c00000")
        self._normal_brush = QColor("#000000")

        # Installed last, once self.table (referenced inside eventFilter)
        # fully exists -- installing earlier risks Qt synchronously
        # delivering an event to a filtered widget during construction,
        # before self.table is assigned, crashing the eventFilter callback.
        self._formula_bar.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
        self.table.horizontalHeader().viewport().installEventFilter(self)
        self.table.verticalHeader().viewport().installEventFilter(self)
        self.table.setFocus()

        # Fill handle (Excel's drag-to-copy square) -- created last, once
        # the table/viewport it's parented to and tracks already exist.
        self._fill_handle = _FillHandle(self)
        self.table.verticalScrollBar().valueChanged.connect(self._reposition_fill_handle)
        self.table.horizontalScrollBar().valueChanged.connect(self._reposition_fill_handle)
        self._reposition_fill_handle()

    def _cell_item(self, row, col):
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem("")
            self.table.setItem(row, col, item)
        return item

    def _on_current_cell_changed(self, row, col, prev_row, prev_col):
        if row < 0 or col < 0:
            return
        self._addr_label.setText(fe.format_address(row, col))
        self._reposition_fill_handle()
        if self._ref_target is not None:
            return  # composing a formula elsewhere -- don't clobber the bar
        cell = self.sheet.get_cell(row, col)
        self._formula_bar.setText(cell.raw if cell else "")

    # ---- Fill handle (Excel's drag-to-copy square) ----------------------

    def _reposition_fill_handle(self):
        """Keep the fill handle glued to the bottom-right corner of the
        current cell; hidden while composing a formula, since a stray
        click there would otherwise be misread as inserting a reference."""
        if self._ref_target is not None:
            self._fill_handle.hide()
            return
        row, col = self.table.currentRow(), self.table.currentColumn()
        if row < 0 or col < 0:
            self._fill_handle.hide()
            return
        rect = self.table.visualRect(self.table.model().index(row, col))
        if rect.isEmpty():
            self._fill_handle.hide()
            return
        hs = self._fill_handle.width()
        self._fill_handle.move(rect.right() - hs // 2, rect.bottom() - hs // 2)
        self._fill_handle.raise_()
        self._fill_handle.show()

    def _fill_range_for(self, anchor, target_row, target_col):
        """(top, left, bottom, right) of the fill-preview/target rect for
        a drag from `anchor` to (target_row, target_col) -- vertical if
        the drag is primarily vertical, horizontal otherwise, matching
        Excel's own single-axis fill-handle behavior (no diagonal fill)."""
        ar, ac = anchor
        if abs(target_row - ar) >= abs(target_col - ac):
            top, bottom = min(ar, target_row), max(ar, target_row)
            return (top, ac, bottom, ac)
        left, right = min(ac, target_col), max(ac, target_col)
        return (ar, left, ar, right)

    def _preview_fill(self, anchor, target_row, target_col):
        top, left, bottom, right = self._fill_range_for(anchor, target_row, target_col)
        prev = self._loading
        self._loading = True
        try:
            self.table.clearSelection()
            self.table.setRangeSelected(QTableWidgetSelectionRange(top, left, bottom, right), True)
        finally:
            self._loading = prev

    def _clear_fill_preview(self):
        prev = self._loading
        self._loading = True
        try:
            self.table.clearSelection()
        finally:
            self._loading = prev

    def _apply_fill(self, anchor, target_row, target_col):
        ar, ac = anchor
        top, left, bottom, right = self._fill_range_for(anchor, target_row, target_col)
        source_cell = self.sheet.get_cell(ar, ac)
        source_raw = source_cell.raw if source_cell else ""
        prev = self._loading
        self._loading = True
        try:
            for r in range(top, bottom + 1):
                for c in range(left, right + 1):
                    if (r, c) == (ar, ac):
                        continue
                    if not source_raw:
                        fe.set_cell_raw(self.sheet, r, c, "")
                        continue
                    try:
                        translated = fe.translate_formula(source_raw, r - ar, c - ac)
                    except fe.FormulaSyntaxError:
                        translated = source_raw
                    fe.set_cell_raw(self.sheet, r, c, translated)
            self.table.clearSelection()
        finally:
            self._loading = prev
        fe.recalculate(self.sheet)
        self._writeback_all()

    def _on_item_changed(self, item):
        if self._loading:
            return
        row, col = item.row(), item.column()
        text = item.text()
        try:
            fe.set_cell_raw(self.sheet, row, col, text)
        except fe.FormulaSyntaxError as ex:
            self._revert_cell(row, col, str(ex))
            return
        fe.recalculate(self.sheet)
        self._writeback_all()
        if row == self.table.currentRow() and col == self.table.currentColumn():
            cell = self.sheet.get_cell(row, col)
            self._formula_bar.setText(cell.raw if cell else "")

    def _revert_cell(self, row, col, err_msg):
        cell = self.sheet.get_cell(row, col)
        prev_text = cell.raw if cell else ""
        prev = self._loading
        self._loading = True
        try:
            self._cell_item(row, col).setText(prev_text)
        finally:
            self._loading = prev
        QMessageBox.warning(self, "Formula Error", "Could not parse formula:\n%s" % err_msg)

    # ---- Excel-style formula editing: begin / cancel / commit ----------

    def begin_edit_new(self, row, col, first_char):
        """Start editing (row,col), replacing its content -- triggered by
        typing a character while the cell is merely selected."""
        self._begin_edit(row, col, first_char)

    def begin_edit_existing(self, row, col):
        """Start editing (row,col), keeping its current content -- F2 or
        double-click."""
        cell = self.sheet.get_cell(row, col)
        self._begin_edit(row, col, cell.raw if cell else "")

    def _begin_edit(self, row, col, initial_text):
        self._ref_target = (row, col)
        self._ref_insert_start = None
        self._ref_insert_end = None
        self._ref_drag_anchor = None
        self.table.setCurrentCell(row, col)
        self._formula_bar.setText(initial_text)  # also mirrors live into the cell, see below
        self._formula_bar.setFocus()
        self._formula_bar.setCursorPosition(len(initial_text))
        self._cancel_edit_btn.show()
        self._confirm_edit_btn.show()
        self._fill_handle.hide()

    def _on_formula_bar_text_changed(self, text):
        """Mirror the formula bar's in-progress text directly into the
        cell being edited, live -- Excel shows what you're typing (or the
        formula being built by clicking cell references) right in the
        cell itself, not only in the bar above it. Fires for both real
        typing (textChanged, not textEdited -- deliberately, so a
        click-inserted reference is ALSO mirrored, not just keystrokes)
        and programmatic edits. Guarded by _loading so this preview write
        never re-triggers engine recalculation -- only committing
        (Enter/Tab) does that."""
        self._update_function_completer()
        if self._ref_target is None:
            return
        self._highlight_all_formula_refs(text)
        row, col = self._ref_target
        prev = self._loading
        self._loading = True
        try:
            self._cell_item(row, col).setText(text)
        finally:
            self._loading = prev

    def _highlight_all_formula_refs(self, text):
        """Highlight EVERY cell/range reference currently in the formula
        bar simultaneously, not just the most recently inserted one --
        Excel keeps every referenced range visibly highlighted while you
        build a formula (click B1, then C1, for "=B1+C1": both B1 and C1
        stay highlighted, not just C1). Re-derives the full highlight set
        from the formula's own text on every change (typed or
        click-inserted) rather than tracking it incrementally, so it can
        never drift out of sync with what the formula actually contains."""
        if not text.startswith("="):
            return
        try:
            tokens = fe.tokenize(text[1:])
        except fe.FormulaSyntaxError:
            return  # formula mid-edit and momentarily unparseable -- leave the last valid highlight
        ranges = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == "REF_SHAPED":
                is_range = (i + 2 < len(tokens) and tokens[i + 1].type == "COLON"
                            and tokens[i + 2].type == "REF_SHAPED")
                try:
                    r0, c0 = fe.parse_address(tok.text.replace("$", ""))
                    if is_range:
                        r1, c1 = fe.parse_address(tokens[i + 2].text.replace("$", ""))
                    else:
                        r1, c1 = r0, c0
                except ValueError:
                    i += 1
                    continue
                top, bottom = sorted((r0, r1))
                left, right = sorted((c0, c1))
                if top < self.N_ROWS and left < self.N_COLS:
                    ranges.append((top, left, min(bottom, self.N_ROWS - 1), min(right, self.N_COLS - 1)))
                i += 3 if is_range else 1
                continue
            i += 1
        prev = self._loading
        self._loading = True
        try:
            self.table.clearSelection()
            for (top, left, bottom, right) in ranges:
                self.table.setRangeSelected(QTableWidgetSelectionRange(top, left, bottom, right), True)
        finally:
            self._loading = prev

    # ---- Function-name autocomplete (Excel's formula IntelliSense) -----

    def _current_word_span(self):
        """(start, end) span of the identifier-like fragment immediately
        before the cursor, e.g. "SL" from "=SL|" or "=SUM(A1,SL|" --
        the candidate function-name-in-progress for autocomplete."""
        text = self._formula_bar.text()
        pos = self._formula_bar.cursorPosition()
        start = pos
        while start > 0 and (text[start - 1].isalpha() or text[start - 1] == "_"):
            start -= 1
        return start, pos

    def _update_function_completer(self):
        if self._ref_target is None or not self._formula_bar.text().startswith("="):
            self._completer.popup().hide()
            return
        start, end = self._current_word_span()
        word = self._formula_bar.text()[start:end]
        if len(word) < 1:
            self._completer.popup().hide()
            return
        text = self._formula_bar.text()
        if end < len(text) and text[end] == "(":
            # already a complete, already-typed function call -- nothing to suggest
            self._completer.popup().hide()
            return
        self._completer_span = (start, end)
        self._completer.setCompletionPrefix(word.upper())
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        rect = self._formula_bar.cursorRect()
        rect.setWidth(self._completer.popup().sizeHintForColumn(0)
                       + self._completer.popup().verticalScrollBar().sizeHint().width())
        self._completer.complete(rect)

    def _on_function_completed(self, name):
        if self._completer_span is None:
            return
        start, end = self._completer_span
        self._completer_span = None
        text = self._formula_bar.text()
        new_text = text[:start] + name + "(" + text[end:]
        self._formula_bar.setText(new_text)
        self._formula_bar.setCursorPosition(start + len(name) + 1)
        self._formula_bar.setFocus()

    def move_current(self, drow, dcol):
        row = min(max(self.table.currentRow() + drow, 0), self.N_ROWS - 1)
        col = min(max(self.table.currentColumn() + dcol, 0), self.N_COLS - 1)
        self.table.setCurrentCell(row, col)

    def insert_function_call(self, func_name):
        """Insert 'FUNCNAME(' from the Insert Function (fx) picker: starts
        a new formula edit on the current cell if nothing is being
        composed yet, otherwise inserts at the formula bar's cursor."""
        text_to_insert = func_name + "("
        if self._ref_target is None:
            row, col = self.table.currentRow(), self.table.currentColumn()
            if row < 0 or col < 0:
                return
            self._begin_edit(row, col, "=" + text_to_insert)
            return
        bar = self._formula_bar
        text = bar.text()
        pos = bar.cursorPosition()
        if not text.startswith("="):
            text = "=" + text
            pos += 1
        new_text = text[:pos] + text_to_insert + text[pos:]
        bar.setText(new_text)
        bar.setCursorPosition(pos + len(text_to_insert))
        bar.setFocus()

    def _focus_table_deferred(self):
        """Defer the focus change to the next event-loop iteration.
        Calling table.setFocus() synchronously from inside a signal
        handler triggered by the formula bar's OWN key event (e.g.
        returnPressed) is unreliable -- Qt's still-in-progress handling
        of that key event for the currently-focused widget can silently
        win, leaving focus on the formula bar and breaking arrow-key
        navigation right after committing an edit."""
        QTimer.singleShot(0, self.table.setFocus)

    def _cancel_edit(self):
        if self._ref_target is None:
            return
        row, col = self._ref_target
        self._ref_target = None
        self._ref_insert_start = None
        self._ref_insert_end = None
        self._ref_drag_anchor = None
        cell = self.sheet.get_cell(row, col)
        prev = self._loading
        self._loading = True
        try:
            # undo the live in-cell preview -- restore the cell's actual
            # last-committed display text, not whatever was being typed
            self._cell_item(row, col).setText(cell.display if cell else "")
        finally:
            self._loading = prev
        self._formula_bar.setText(cell.raw if cell else "")
        self._cancel_edit_btn.hide()
        self._confirm_edit_btn.hide()
        self._reposition_fill_handle()
        self._focus_table_deferred()

    def _commit_formula_bar(self, advance=(1, 0)):
        if self._ref_target is not None:
            row, col = self._ref_target
        else:
            row, col = self.table.currentRow(), self.table.currentColumn()
        if row < 0 or col < 0:
            return
        text = self._formula_bar.text()
        try:
            fe.set_cell_raw(self.sheet, row, col, text)
        except fe.FormulaSyntaxError as ex:
            QMessageBox.warning(self, "Formula Error", "Could not parse formula:\n%s" % str(ex))
            return
        self._ref_target = None
        self._ref_insert_start = None
        self._ref_insert_end = None
        self._ref_drag_anchor = None
        self._cancel_edit_btn.hide()
        self._confirm_edit_btn.hide()
        prev = self._loading
        self._loading = True
        try:
            self._cell_item(row, col).setText(text)
        finally:
            self._loading = prev
        fe.recalculate(self.sheet)
        self._writeback_all()
        next_row = min(max(row + advance[0], 0), self.N_ROWS - 1)
        next_col = min(max(col + advance[1], 0), self.N_COLS - 1)
        self.table.setCurrentCell(next_row, next_col)
        self._reposition_fill_handle()
        self._focus_table_deferred()

    # ---- Click/drag-to-insert-reference while composing a formula ------

    # Matches a complete cell/range reference sitting at the very end of
    # a string, e.g. "B1" or "B1:B200" -- used to detect "the user just
    # finished one reference and is now starting another with no
    # separator typed in between" (see _insert_ref_text).
    _REF_TAIL_RE = re.compile(r'[A-Za-z]\d+(:[A-Za-z]\d+)?$')

    def _insert_ref_text(self, addr):
        text = self._formula_bar.text()
        if self._ref_insert_start is None:
            start = self._formula_bar.selectionStart()
            if start < 0:
                start = self._formula_bar.cursorPosition()
            sel_len = len(self._formula_bar.selectedText())
            # If the cursor sits immediately after a complete reference
            # with nothing selected (e.g. a drag for one SLOPE argument
            # just finished) and the user is now starting ANOTHER
            # reference without typing a separator first, insert a comma
            # automatically. Without this, two perfectly clean
            # selections silently glue together into invalid syntax --
            # "=SLOPE(B1:B200D1:D200)" -- which looks like nothing went
            # wrong until the formula is committed and rejected.
            if sel_len == 0 and self._REF_TAIL_RE.search(text[:start]):
                text = text[:start] + "," + text[start:]
                start += 1
                self._formula_bar.setText(text)
            end = start + sel_len
            self._ref_insert_start = start
        else:
            end = self._ref_insert_end
        new_text = text[:self._ref_insert_start] + addr + text[end:]
        self._ref_insert_end = self._ref_insert_start + len(addr)
        self._formula_bar.setText(new_text)
        self._formula_bar.setCursorPosition(self._ref_insert_end)

    def _apply_ref_selection(self, r0, c0, r1, c1):
        top, bottom = min(r0, r1), max(r0, r1)
        left, right = min(c0, c1), max(c0, c1)
        if (top, left) == (bottom, right):
            addr = fe.format_address(top, left)
        else:
            addr = "%s:%s" % (fe.format_address(top, left), fe.format_address(bottom, right))
        self._insert_ref_text(addr)  # highlighting itself is driven by _highlight_all_formula_refs,
                                      # via the textChanged this setText() triggers -- see that method

    def _ref_editing_active(self):
        return self._ref_target is not None and self._formula_bar.text().startswith("=")

    def _grid_mouse_press(self, event):
        if self._ref_target is not None and not self._ref_editing_active():
            self._commit_formula_bar()  # clicking elsewhere commits a plain (non-formula) edit
            self.table.setFocus()
            return False
        if not self._ref_editing_active():
            # Not composing a formula -- this is a normal navigation
            # click. Explicitly (re)claim keyboard focus for the table so
            # arrow-key navigation works right after: Qt's usual
            # click-grabs-focus behavior on the outer QTableWidget can't
            # be relied on here (the viewport itself -- which is what
            # physically receives the click -- has focus policy NoFocus
            # by design, and any prior formula-bar edit or header click
            # may have left focus elsewhere).
            self.table.setFocus()
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.table.indexAt(pos)
        if not index.isValid():
            return False
        row, col = index.row(), index.column()
        self._ref_drag_anchor = (row, col)
        self._ref_insert_start = None  # fresh token for this click
        self._apply_ref_selection(row, col, row, col)
        self._start_autoscroll("cell")
        return True

    def _grid_mouse_move(self, event):
        if self._ref_drag_anchor is None:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self._drag_last_pos = pos
        index = self.table.indexAt(pos)
        if index.isValid():
            r0, c0 = self._ref_drag_anchor
            self._apply_ref_selection(r0, c0, index.row(), index.column())
        return True

    def _grid_mouse_release(self, event):
        if self._ref_drag_anchor is None:
            return False
        self._ref_drag_anchor = None
        self._ref_insert_start = None
        self._ref_insert_end = None
        self._stop_autoscroll()
        self._formula_bar.setFocus()
        return True

    # ---- Autoscroll while dragging near a viewport edge ----------------
    # A plain drag can't reach rows/columns beyond what's currently
    # visible (indexAt() returns nothing for out-of-viewport positions),
    # so a selection drag silently stops short of the intended range
    # (e.g. "B1:B20" instead of the whole column) with no error or
    # warning -- confusingly incomplete. Qt's native drag-select handles
    # this via a timer-based autoscroll while the cursor lingers near an
    # edge; this grid's own mouse handling (via the event filter, which
    # bypasses native view mouse handling entirely) needs the same thing
    # built explicitly.

    def _start_autoscroll(self, kind):
        self._autoscroll_kind = kind
        self._drag_last_pos = None
        if self._autoscroll_timer is None:
            self._autoscroll_timer = QTimer(self)
            self._autoscroll_timer.setInterval(70)
            self._autoscroll_timer.timeout.connect(self._on_autoscroll_tick)
        self._autoscroll_timer.start()

    def _stop_autoscroll(self):
        self._autoscroll_kind = None
        self._drag_last_pos = None
        if self._autoscroll_timer is not None:
            self._autoscroll_timer.stop()

    def _on_autoscroll_tick(self):
        if self._autoscroll_kind is None or self._drag_last_pos is None:
            return
        margin = 24
        step = 3
        if self._autoscroll_kind == "cell":
            vp = self.table.viewport().rect()
            pos = self._drag_last_pos
            vbar = self.table.verticalScrollBar()
            hbar = self.table.horizontalScrollBar()
            scrolled = False
            if pos.y() < margin:
                vbar.setValue(vbar.value() - step)
                scrolled = True
            elif pos.y() > vp.height() - margin:
                vbar.setValue(vbar.value() + step)
                scrolled = True
            if pos.x() < margin:
                hbar.setValue(hbar.value() - step)
                scrolled = True
            elif pos.x() > vp.width() - margin:
                hbar.setValue(hbar.value() + step)
                scrolled = True
            if scrolled and self._ref_drag_anchor is not None:
                index = self.table.indexAt(pos)
                if index.isValid():
                    r0, c0 = self._ref_drag_anchor
                    self._apply_ref_selection(r0, c0, index.row(), index.column())
        elif self._autoscroll_kind == "col_header":
            hdr = self.table.horizontalHeader()
            vp = hdr.viewport().rect()
            pos = self._drag_last_pos
            hbar = self.table.horizontalScrollBar()
            if pos.x() < margin:
                hbar.setValue(hbar.value() - step)
            elif pos.x() > vp.width() - margin:
                hbar.setValue(hbar.value() + step)
            else:
                return
            col = hdr.logicalIndexAt(pos)
            if col >= 0 and self._header_col_anchor is not None:
                self._apply_ref_column_range(self._header_col_anchor, col)
        elif self._autoscroll_kind == "row_header":
            vhdr = self.table.verticalHeader()
            vp = vhdr.viewport().rect()
            pos = self._drag_last_pos
            vbar = self.table.verticalScrollBar()
            if pos.y() < margin:
                vbar.setValue(vbar.value() - step)
            elif pos.y() > vp.height() - margin:
                vbar.setValue(vbar.value() + step)
            else:
                return
            row = vhdr.logicalIndexAt(pos)
            if row >= 0 and self._header_row_anchor is not None:
                self._apply_ref_row_range(self._header_row_anchor, row)

    def _on_column_header_clicked(self, col):
        # sectionClicked fires only for a plain click with no drag -- a
        # real drag across headers fires sectionPressed/sectionEntered
        # instead (handled below) and never sectionClicked at all. While
        # composing a formula, _on_column_header_pressed already handled
        # this same click (pressed always fires first, for both a plain
        # click and a drag) -- skip here to avoid double-processing it.
        if self._ref_editing_active():
            return
        mods = QApplication.keyboardModifiers()
        rng = QTableWidgetSelectionRange(0, col, self.N_ROWS - 1, col)
        if (mods & Qt.KeyboardModifier.ShiftModifier) and self._last_header_col is not None:
            lo, hi = sorted((self._last_header_col, col))
            if not (mods & Qt.KeyboardModifier.ControlModifier):
                self.table.clearSelection()
            self.table.setRangeSelected(QTableWidgetSelectionRange(0, lo, self.N_ROWS - 1, hi), True)
        elif mods & Qt.KeyboardModifier.ControlModifier:
            self.table.setRangeSelected(rng, True)
            self._last_header_col = col
        else:
            self.table.clearSelection()
            self.table.setRangeSelected(rng, True)
            self._last_header_col = col
        self.table.setFocus()

    def _on_row_header_clicked(self, row):
        if self._ref_editing_active():
            return
        mods = QApplication.keyboardModifiers()
        rng = QTableWidgetSelectionRange(row, 0, row, self.N_COLS - 1)
        if (mods & Qt.KeyboardModifier.ShiftModifier) and self._last_header_row is not None:
            lo, hi = sorted((self._last_header_row, row))
            if not (mods & Qt.KeyboardModifier.ControlModifier):
                self.table.clearSelection()
            self.table.setRangeSelected(QTableWidgetSelectionRange(lo, 0, hi, self.N_COLS - 1), True)
        elif mods & Qt.KeyboardModifier.ControlModifier:
            self.table.setRangeSelected(rng, True)
            self._last_header_row = row
        else:
            self.table.clearSelection()
            self.table.setRangeSelected(rng, True)
            self._last_header_row = row
        self.table.setFocus()

    # ---- Header press+drag -> reference insertion while composing a
    # formula. sectionPressed fires on the initial press (both for a
    # plain click AND the start of a drag); sectionEntered fires for
    # every NEW section the mouse moves over during a drag. Together
    # these correctly build a growing multi-column/row reference exactly
    # like clicking/dragging over cells does (_grid_mouse_press/_move).

    def _on_column_header_pressed(self, col):
        if not self._ref_editing_active():
            return
        self._header_col_anchor = col
        self._ref_insert_start = None  # fresh token for this press
        self._apply_ref_column_range(col, col)
        self._start_autoscroll("col_header")

    def _on_column_header_entered(self, col):
        if self._header_col_anchor is None or not self._ref_editing_active():
            return
        self._apply_ref_column_range(self._header_col_anchor, col)

    def _apply_ref_column_range(self, c0, c1):
        lo, hi = sorted((c0, c1))
        addr = "%s:%s" % (fe.format_address(0, lo), fe.format_address(self.N_ROWS - 1, hi))
        self._insert_ref_text(addr)

    def _on_row_header_pressed(self, row):
        if not self._ref_editing_active():
            return
        self._header_row_anchor = row
        self._ref_insert_start = None
        self._apply_ref_row_range(row, row)
        self._start_autoscroll("row_header")

    def _on_row_header_entered(self, row):
        if self._header_row_anchor is None or not self._ref_editing_active():
            return
        self._apply_ref_row_range(self._header_row_anchor, row)

    def _apply_ref_row_range(self, r0, r1):
        lo, hi = sorted((r0, r1))
        addr = "%s:%s" % (fe.format_address(lo, 0), fe.format_address(hi, self.N_COLS - 1))
        self._insert_ref_text(addr)

    def _end_header_drag(self):
        if self._header_col_anchor is None and self._header_row_anchor is None:
            return
        self._header_col_anchor = None
        self._header_row_anchor = None
        self._stop_autoscroll()
        if self._ref_editing_active():
            self._formula_bar.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.table.viewport():
            et = event.type()
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self._grid_mouse_press(event):
                    return True
            elif et == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                if self._grid_mouse_move(event):
                    return True
            elif et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._grid_mouse_release(event):
                    return True
        elif obj in (self.table.horizontalHeader().viewport(), self.table.verticalHeader().viewport()):
            if (event.type() == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton):
                self._end_header_drag()
            elif event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                # Tracked only for autoscroll -- sectionEntered already
                # drives the actual reference-range extension.
                self._drag_last_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        elif obj is self._formula_bar:
            if event.type() == QEvent.Type.KeyPress and not self._completer.popup().isVisible():
                # While the function-name autocomplete popup is open,
                # Escape/Tab/Enter are its own navigation keys (close the
                # popup / accept a suggestion) -- QCompleter's own event
                # filter (installed via setWidget()) handles those; this
                # branch must stand aside rather than cancelling or
                # committing the whole cell edit out from under it.
                key = event.key()
                if key == Qt.Key.Key_Escape:
                    self._cancel_edit()
                    return True
                if key == Qt.Key.Key_Tab:
                    self._commit_formula_bar(advance=(0, 1))
                    return True
                if key == Qt.Key.Key_Backtab:
                    self._commit_formula_bar(advance=(0, -1))
                    return True
            elif event.type() == QEvent.Type.FocusIn:
                if self._ref_target is None:
                    row, col = self.table.currentRow(), self.table.currentColumn()
                    if row >= 0 and col >= 0:
                        self._ref_target = (row, col)
        return super().eventFilter(obj, event)

    def _writeback_all(self):
        prev = self._loading
        self._loading = True
        try:
            for (r, c), cell in self.sheet.cells.items():
                if r >= self.N_ROWS or c >= self.N_COLS:
                    continue
                item = self._cell_item(r, c)
                text = cell.display
                if item.text() != text:
                    item.setText(text)
                item.setForeground(self._error_brush if cell.is_error else self._normal_brush)
        finally:
            self._loading = prev

    def load_dataframe(self, df):
        """Import a pandas DataFrame as literal values — never re-parse a
        source file's embedded formulas."""
        prev = self._loading
        self._loading = True
        try:
            for c, col_name in enumerate(df.columns):
                if c >= self.N_COLS:
                    break
                fe.set_cell_raw(self.sheet, 0, c, str(col_name))
            n_rows = min(len(df), self.N_ROWS - 1)
            n_cols = min(len(df.columns), self.N_COLS)
            for r in range(n_rows):
                for c in range(n_cols):
                    v = df.iat[r, c]
                    if v is None or (isinstance(v, float) and v != v):
                        text = ""
                    else:
                        text = str(v)
                    fe.set_cell_raw(self.sheet, r + 1, c, text)
        finally:
            self._loading = prev
        fe.recalculate(self.sheet)
        self._writeback_all()

    def load_worksheet(self, ws):
        """Import an openpyxl worksheet directly (not via a pandas
        DataFrame), preserving formula text: a cell whose stored value is
        already a string starting with '=' (openpyxl's own marker for a
        formula cell, when read with data_only=False) is passed straight
        into set_cell_raw as-is, so it comes back as a live, recalculating
        formula in this sheet -- exactly reversing what save_current now
        writes for .xlsx. Row/column layout otherwise matches
        load_dataframe (row 1 = header)."""
        prev = self._loading
        self._loading = True
        try:
            header_cells = next(ws.iter_rows(min_row=1, max_row=1), ())
            for c, cell in enumerate(header_cells):
                if c >= self.N_COLS:
                    break
                fe.set_cell_raw(self.sheet, 0, c, "" if cell.value is None else str(cell.value))
            for r, row in enumerate(ws.iter_rows(min_row=2, max_row=ws.max_row or 1), start=1):
                if r >= self.N_ROWS:
                    break
                for c, cell in enumerate(row):
                    if c >= self.N_COLS:
                        break
                    v = cell.value
                    if v is None:
                        text = ""
                    elif isinstance(v, str):
                        text = v  # a formula string ("=...") passes through unchanged
                    else:
                        text = str(v)
                    fe.set_cell_raw(self.sheet, r, c, text)
        finally:
            self._loading = prev
        fe.recalculate(self.sheet)
        self._writeback_all()

    def selected_range_values(self):
        """(x_vals, y_vals) from the two left-most columns of the LARGEST
        selected range (not just the first — if an old single-cell selection
        happens to still be reported alongside a fresh drag-selected block,
        the block is what the user actually means), or None if fewer than 2
        numeric pairs are found."""
        ranges = self.table.selectedRanges()
        if not ranges:
            return None
        rng = max(ranges, key=lambda r: (r.rowCount() * r.columnCount()))
        cols = list(range(rng.leftColumn(), rng.rightColumn() + 1))
        if len(cols) < 2:
            return None
        xs, ys = [], []
        for r in range(rng.topRow(), rng.bottomRow() + 1):
            cx = self.sheet.get_cell(r, cols[0])
            cy = self.sheet.get_cell(r, cols[1])
            if cx is None or cy is None:
                continue
            if (isinstance(cx.value, (int, float)) and not isinstance(cx.value, bool)
                    and isinstance(cy.value, (int, float)) and not isinstance(cy.value, bool)):
                xs.append(float(cx.value))
                ys.append(float(cy.value))
        return (xs, ys) if len(xs) >= 2 else None

    def selected_range_columns(self):
        """(x_col, y_col), 0-indexed, for the same largest selected range
        selected_range_values() would use -- lets a caller (Curve Fit)
        label exactly which columns are being treated as X and Y, so the
        user can visually confirm the orientation matches what they
        intended (and cross-check against e.g. a =SLOPE() formula, which
        takes known_y's first, known_x's second -- easy to get swapped)."""
        ranges = self.table.selectedRanges()
        if not ranges:
            return None
        rng = max(ranges, key=lambda r: (r.rowCount() * r.columnCount()))
        if rng.columnCount() < 2:
            return None
        return (rng.leftColumn(), rng.leftColumn() + 1)

    def selected_single_column_values(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return None
        vals = []
        for rng in ranges:
            for r in range(rng.topRow(), rng.bottomRow() + 1):
                for c in range(rng.leftColumn(), rng.rightColumn() + 1):
                    cell = self.sheet.get_cell(r, c)
                    if cell is not None and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                        vals.append(float(cell.value))
        return vals if vals else None


# Shared light-Excel styling for the analysis dialogs (Quick Plot, Curve
# Fit) -- must be COMPLETE and self-contained, explicitly covering every
# sub-widget type used, including ones easy to forget: a QComboBox's
# dropdown POPUP is a separate internal widget that does NOT automatically
# pick up the QComboBox rule's own background/color, and a QMessageBox's
# QLabel likewise needs its own explicit rule -- both are exactly the
# "background set on the ancestor but not the specific descendant type"
# gap that has caused invisible text before in this app.
_ANALYSIS_DIALOG_QSS = (
    "QDialog { background:#ffffff; color:#000000; }"
    "QLabel { color:#000000; background:transparent; }"
    "QLineEdit { background:#ffffff; color:#000000; border:1px solid #b0b0b0;"
    "  border-radius:2px; padding:4px; }"
    "QComboBox { background:#ffffff; color:#000000; border:1px solid #b0b0b0;"
    "  border-radius:2px; padding:4px; }"
    "QComboBox QAbstractItemView { background:#ffffff; color:#000000;"
    "  selection-background-color:#c9dfef; selection-color:#000000; }"
    "QMessageBox { background:#ffffff; }"
    "QMessageBox QLabel { color:#000000; background:transparent; }"
    "QPushButton { background:#f3f2f1; color:#333333; border:1px solid #c8c8c8;"
    "  border-radius:3px; padding:6px 12px; }"
    "QPushButton:hover { background:#e5f1fb; border:1px solid #217346; color:#217346; }"
    "QGroupBox { font-weight:bold; color:#217346; border:1px solid #d4d4d4;"
    "  border-radius:4px; margin-top:9px; padding-top:10px; background:#ffffff; }"
    "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }")


def _style_axes_light(ax, fig):
    """Light-theme matplotlib styling matching the Excel tab's palette,
    shared by Quick Plot and Curve Fit so their charts look consistent
    with each other and with the sheet around them."""
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#ffffff')
    ax.grid(True, linestyle='--', color='#b0b0b0', alpha=0.6)
    for spine in ax.spines.values():
        spine.set_edgecolor('#888888')
    ax.tick_params(colors='#000000')
    ax.xaxis.label.set_color('#000000')
    ax.yaxis.label.set_color('#000000')
    ax.title.set_color('#000000')


class QuickPlotDialog(QDialog):
    def __init__(self, xs, ys, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Plot")
        self.resize(650, 500)
        self.setStyleSheet(_ANALYSIS_DIALOG_QSS)
        layout = QVBoxLayout(self)

        info = QLabel("%d points plotted" % len(xs))
        info.setStyleSheet("color:#3a3a3a; font-size:11px;")
        layout.addWidget(info)

        fig = Figure(figsize=(6, 4.5), dpi=100)
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        ax.plot(xs, ys, 'o-', color='#1f6fbf', markersize=5)
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        _style_axes_light(ax, fig)
        fig.tight_layout()
        layout.addWidget(canvas)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "background:#217346; color:#ffffff; padding:6px; border-radius:4px; font-weight:bold;")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class CurveFitDialog(QDialog):
    """Linear / polynomial / custom-expression curve fit on a selected X/Y
    range. Custom-expression fitting mirrors AnalysisWindow._fit_1w_custom's
    pattern: regex-detected free parameters, a restricted eval namespace
    ({'np': np, '__builtins__': {}}), and a two-stage curve_fit retry."""

    def __init__(self, xs, ys, x_label, y_label, grid, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Curve Fit")
        self.resize(540, 580)
        self.xs = xs
        self.ys = ys
        self.x_label = x_label
        self.y_label = y_label
        self.grid = grid
        self._canvas = None
        self.setStyleSheet(_ANALYSIS_DIALOG_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # ---- Data group: which columns are X and Y, and a peek at the
        # actual values -- both so the data being fit is visibly
        # confirmable, and so an unexpected result can be cross-checked
        # against e.g. a =SLOPE() formula, which takes (known_y's,
        # known_x's) in THAT order -- easy to get flipped relative to
        # whichever column was selected first here, which inverts the
        # fitted slope (roughly to its reciprocal).
        #
        # X/Y is deliberately controlled ONLY by this explicit Swap
        # button, not by "which column you selected first": Qt's
        # QTableWidgetSelectionRange has no concept of drag direction at
        # all -- a drag from column A to B and a drag from B to A produce
        # an identical (leftColumn, rightColumn) range object, so which
        # one the user "selected first" genuinely cannot be recovered
        # from the selection afterward. A direct, reliable toggle here
        # replaces something Qt has no way to report in the first place.
        data_box = QGroupBox("Data")
        data_layout = QVBoxLayout(data_box)
        self.info_lbl = QLabel()
        self.info_lbl.setStyleSheet(
            "color:#3a3a3a; font-family:Consolas,'Courier New',monospace; font-size:11px;"
            " background:#f8f8f8; border:1px solid #d4d4d4; border-radius:3px; padding:8px;")
        self.info_lbl.setWordWrap(True)
        data_layout.addWidget(self.info_lbl)
        swap_btn = QPushButton("⇄  Swap X / Y")
        swap_btn.setToolTip("Swap which selected column is treated as X and which as Y")
        swap_btn.clicked.connect(self._swap_xy)
        data_layout.addWidget(swap_btn)
        layout.addWidget(data_box)
        self._update_data_info()

        # ---- Fit settings group ----
        fit_box = QGroupBox("Fit")
        fit_layout = QVBoxLayout(fit_box)
        fit_layout.setSpacing(8)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Fit type:"))
        self.type_box = QComboBox()
        self.type_box.addItems(["Linear (degree 1)", "Polynomial (degree N)", "Custom expression"])
        self.type_box.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self.type_box, 1)
        fit_layout.addLayout(type_row)

        self.degree_row = QWidget()
        drow = QHBoxLayout(self.degree_row)
        drow.setContentsMargins(0, 0, 0, 0)
        drow.addWidget(QLabel("Degree:"))
        self.degree_e = QLineEdit("2")
        self.degree_e.setFixedWidth(50)
        drow.addWidget(self.degree_e)
        drow.addStretch(1)
        fit_layout.addWidget(self.degree_row)
        self.degree_row.hide()

        self.custom_row = QWidget()
        crow = QVBoxLayout(self.custom_row)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.addWidget(QLabel("Expression in x (parameters auto-detected), e.g. a*x+b :"))
        self.custom_e = QLineEdit("a*x+b")
        crow.addWidget(self.custom_e)
        fit_layout.addWidget(self.custom_row)
        self.custom_row.hide()

        fit_btn = QPushButton("▶  Run Fit")
        fit_btn.setStyleSheet(
            "background:#217346; color:#ffffff; font-weight:bold; padding:9px; border-radius:4px; font-size:12px;")
        fit_btn.clicked.connect(self.run_fit)
        fit_layout.addWidget(fit_btn)
        layout.addWidget(fit_box)

        # ---- Results group ----
        results_box = QGroupBox("Result")
        results_layout = QVBoxLayout(results_box)
        self.result_lbl = QLabel("Run a fit to see the coefficients here.")
        self.result_lbl.setWordWrap(True)
        self.result_lbl.setStyleSheet(
            "color:#000000; font-family:Consolas,'Courier New',monospace;"
            " background:#f8f8f8; border:1px solid #d4d4d4; border-radius:3px;"
            " padding:8px; font-size:12px;")
        results_layout.addWidget(self.result_lbl)
        self.canvas_holder = QVBoxLayout()
        results_layout.addLayout(self.canvas_holder)
        layout.addWidget(results_box, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def _update_data_info(self):
        n = len(self.xs)
        preview_n = min(n, 3)
        x_preview = ", ".join("%.6g" % v for v in self.xs[:preview_n])
        y_preview = ", ".join("%.6g" % v for v in self.ys[:preview_n])
        ellipsis = ", ..." if n > preview_n else ""
        self.info_lbl.setText(
            "X = column %s   Y = column %s   (%d points)\n"
            "X: %s%s\nY: %s%s" % (self.x_label, self.y_label, n, x_preview, ellipsis, y_preview, ellipsis))

    def _swap_xy(self):
        self.xs, self.ys = self.ys, self.xs
        self.x_label, self.y_label = self.y_label, self.x_label
        self._update_data_info()
        # The previous result/plot belonged to the old X/Y assignment --
        # clear them rather than leave a result on screen that no longer
        # corresponds to what "X"/"Y" now mean, silently mismatched.
        self.result_lbl.setText("X/Y swapped -- run the fit again to see the new result.")
        if self._canvas is not None:
            self.canvas_holder.removeWidget(self._canvas)
            self._canvas.setParent(None)
            self._canvas = None

    def _on_type_changed(self, idx):
        self.degree_row.setVisible(idx == 1)
        self.custom_row.setVisible(idx == 2)

    def run_fit(self):
        import numpy as np
        import re as _re
        x = np.array(self.xs, dtype=float)
        y = np.array(self.ys, dtype=float)
        idx = self.type_box.currentIndex()
        try:
            if idx == 0:
                coeffs, cov = np.polyfit(x, y, 1, cov=True)
                errs = np.sqrt(np.diag(cov))
                fitted = np.polyval(coeffs, x)
                names = ["slope", "intercept"]
                popt = coeffs
            elif idx == 1:
                deg = int(self.degree_e.text())
                coeffs, cov = np.polyfit(x, y, deg, cov=True)
                errs = np.sqrt(np.diag(cov))
                fitted = np.polyval(coeffs, x)
                names = ["c%d" % (deg - i) for i in range(deg + 1)]
                popt = coeffs
            else:
                from scipy.optimize import curve_fit as _cf
                expr = self.custom_e.text().strip()
                _skip = set(dir(np)) | {'x', 'np', 'math', 'e', 'pi', 'inf', 'nan', 'True', 'False'}
                tokens = _re.findall(r'\b([A-Za-z_]\w*)\b', expr)
                params = list(dict.fromkeys(t for t in tokens if t not in _skip))
                if not params:
                    raise ValueError("No free parameters detected in expression")
                _safe = {'np': np, '__builtins__': {}}

                def fit_fn(xv, *vals):
                    local = dict(zip(params, vals))
                    local['x'] = xv
                    local.update(_safe)
                    return eval(expr, _safe, local)

                p0 = [1.0] * len(params)
                try:
                    popt, cov = _cf(fit_fn, x, y, p0=p0, maxfev=20000)
                except Exception:
                    p0_fallback = [0.5] * len(params)
                    popt, cov = _cf(fit_fn, x, y, p0=p0_fallback, maxfev=40000)
                errs = np.sqrt(np.diag(cov))
                fitted = fit_fn(x, *popt)
                names = params

            ss_res = float(np.sum((y - fitted) ** 2))
            ss_tot = float(np.sum((y - np.mean(y)) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot != 0 else float('nan')

            lines = []
            for name, val, err in zip(names, popt, errs):
                lines.append("%s = %.6g \u00b1 %.4g" % (name, val, err))
            lines.append("R\u00b2 = %.6f" % r2)
            self.result_lbl.setText("\n".join(lines))
            self._plot_fit(x, y, fitted)
        except Exception as exc:
            QMessageBox.critical(self, "Fit Error", str(exc))

    def _plot_fit(self, x, y, fitted):
        if self._canvas is not None:
            self.canvas_holder.removeWidget(self._canvas)
            self._canvas.setParent(None)
        fig = Figure(figsize=(5, 3.2), dpi=100)
        self._canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        order = x.argsort()
        ax.plot(x, y, 'o', color='#1f6fbf', markersize=5, label='data')
        ax.plot(x[order], fitted[order], '-', color='#d9822b', linewidth=1.5, label='fit')
        # Explicit colors, not just fontsize -- matplotlib.rcParams sets a
        # dark legend.facecolor/edgecolor globally for the app's main
        # (still dark-themed) measurement plots; left at the default here
        # it renders as a dark box floating on this light-themed plot.
        legend = ax.legend(fontsize=8, facecolor='#ffffff', edgecolor='#888888')
        for text in legend.get_texts():
            text.set_color('#000000')
        _style_axes_light(ax, fig)
        fig.tight_layout()
        self.canvas_holder.addWidget(self._canvas)


# (name, signature, one-line description) grouped by Excel's own category
# names, for the Insert Function (fx) picker -- covers every function
# registered in formula_engine.FUNCTIONS.
_FUNCTION_CATALOG = {
    "Math & Trig": [
        ("SUM", "SUM(number1, [number2], ...)", "Adds all the numbers in a range or list."),
        ("PRODUCT", "PRODUCT(number1, [number2], ...)", "Multiplies all the numbers given."),
        ("ABS", "ABS(number)", "Absolute value of a number."),
        ("SQRT", "SQRT(number)", "Square root of a number."),
        ("EXP", "EXP(number)", "e raised to the given power."),
        ("LN", "LN(number)", "Natural logarithm."),
        ("LOG", "LOG(number, [base])", "Logarithm to a given base (default 10)."),
        ("LOG10", "LOG10(number)", "Base-10 logarithm."),
        ("POWER", "POWER(number, power)", "Raises a number to a power."),
        ("MOD", "MOD(number, divisor)", "Remainder after division."),
        ("ROUND", "ROUND(number, num_digits)", "Rounds to a given number of digits."),
        ("ROUNDUP", "ROUNDUP(number, num_digits)", "Rounds up, away from zero."),
        ("ROUNDDOWN", "ROUNDDOWN(number, num_digits)", "Rounds down, toward zero."),
        ("INT", "INT(number)", "Rounds down to the nearest integer."),
        ("TRUNC", "TRUNC(number, [num_digits])", "Truncates toward zero."),
        ("CEILING", "CEILING(number, significance)", "Rounds up to the nearest multiple."),
        ("FLOOR", "FLOOR(number, significance)", "Rounds down to the nearest multiple."),
        ("SIGN", "SIGN(number)", "Returns -1, 0, or 1."),
        ("PI", "PI()", "The value of pi."),
        ("E", "E()", "The value of e."),
        ("SIN", "SIN(number)", "Sine (radians)."),
        ("COS", "COS(number)", "Cosine (radians)."),
        ("TAN", "TAN(number)", "Tangent (radians)."),
        ("ASIN", "ASIN(number)", "Arcsine, in radians."),
        ("ACOS", "ACOS(number)", "Arccosine, in radians."),
        ("ATAN", "ATAN(number)", "Arctangent, in radians."),
        ("ATAN2", "ATAN2(x_num, y_num)", "Arctangent from x and y coordinates."),
        ("GCD", "GCD(number1, [number2], ...)", "Greatest common divisor."),
        ("LCM", "LCM(number1, [number2], ...)", "Least common multiple."),
        ("COMBIN", "COMBIN(number, number_chosen)", "Number of combinations."),
        ("PERMUT", "PERMUT(number, number_chosen)", "Number of permutations."),
        ("SUMPRODUCT", "SUMPRODUCT(array1, array2, ...)", "Sum of pairwise products of equal-sized ranges."),
        ("RAND", "RAND()", "Random number between 0 and 1."),
        ("RANDBETWEEN", "RANDBETWEEN(bottom, top)", "Random integer in a range."),
    ],
    "Statistical": [
        ("AVERAGE", "AVERAGE(number1, [number2], ...)", "Arithmetic mean."),
        ("MEDIAN", "MEDIAN(number1, [number2], ...)", "Middle value."),
        ("MIN", "MIN(number1, [number2], ...)", "Smallest value."),
        ("MAX", "MAX(number1, [number2], ...)", "Largest value."),
        ("COUNT", "COUNT(value1, [value2], ...)", "Counts numeric cells."),
        ("COUNTA", "COUNTA(value1, [value2], ...)", "Counts non-blank cells."),
        ("COUNTBLANK", "COUNTBLANK(range)", "Counts blank cells."),
        ("COUNTIF", "COUNTIF(range, criteria)", "Counts cells matching a condition."),
        ("COUNTIFS", "COUNTIFS(range1, criteria1, ...)", "Counts cells matching multiple conditions."),
        ("SUMIF", "SUMIF(range, criteria, [sum_range])", "Sums cells matching a condition."),
        ("SUMIFS", "SUMIFS(sum_range, range1, criteria1, ...)", "Sums cells matching multiple conditions."),
        ("AVERAGEIF", "AVERAGEIF(range, criteria, [avg_range])", "Averages cells matching a condition."),
        ("AVERAGEIFS", "AVERAGEIFS(avg_range, range1, criteria1, ...)", "Averages cells matching multiple conditions."),
        ("MAXIFS", "MAXIFS(max_range, range1, criteria1, ...)", "Max of cells matching multiple conditions."),
        ("MINIFS", "MINIFS(min_range, range1, criteria1, ...)", "Min of cells matching multiple conditions."),
        ("STDEV", "STDEV(number1, [number2], ...)", "Sample standard deviation."),
        ("STDEVP", "STDEVP(number1, [number2], ...)", "Population standard deviation."),
        ("VAR", "VAR(number1, [number2], ...)", "Sample variance."),
        ("VARP", "VARP(number1, [number2], ...)", "Population variance."),
        ("RANK", "RANK(number, ref, [order])", "Rank of a number within a range."),
        ("LARGE", "LARGE(range, k)", "k-th largest value."),
        ("SMALL", "SMALL(range, k)", "k-th smallest value."),
        ("MODE", "MODE(number1, [number2], ...)", "Most frequently occurring value."),
        ("PERCENTILE", "PERCENTILE(range, k)", "k-th percentile (0-1)."),
        ("QUARTILE", "QUARTILE(range, quart)", "Quartile value (0-4)."),
        ("SLOPE", "SLOPE(known_ys, known_xs)", "Slope of the linear regression line."),
        ("INTERCEPT", "INTERCEPT(known_ys, known_xs)", "Y-intercept of the regression line."),
        ("RSQ", "RSQ(known_ys, known_xs)", "R-squared of the regression line."),
        ("TREND", "TREND(known_ys, known_xs, [new_x])", "Predicted y for a linear trend."),
        ("FORECAST", "FORECAST(x, known_ys, known_xs)", "Predicts a value along a linear trend."),
    ],
    "Logical": [
        ("IF", "IF(logical_test, value_if_true, [value_if_false])", "Returns one value if TRUE, another if FALSE."),
        ("IFS", "IFS(cond1, val1, [cond2, val2], ...)", "First TRUE condition's value."),
        ("SWITCH", "SWITCH(expr, val1, res1, [val2, res2], ..., [default])", "Matches an expression against values."),
        ("AND", "AND(logical1, [logical2], ...)", "TRUE if all arguments are TRUE."),
        ("OR", "OR(logical1, [logical2], ...)", "TRUE if any argument is TRUE."),
        ("NOT", "NOT(logical)", "Reverses a logical value."),
        ("XOR", "XOR(logical1, [logical2], ...)", "TRUE if an odd number of arguments are TRUE."),
        ("IFERROR", "IFERROR(value, value_if_error)", "Returns a fallback value on error."),
        ("ISERROR", "ISERROR(value)", "TRUE if value is an error."),
        ("ISNA", "ISNA(value)", "TRUE if value is #N/A."),
        ("ISBLANK", "ISBLANK(value)", "TRUE if the cell is empty."),
        ("ISNUMBER", "ISNUMBER(value)", "TRUE if value is a number."),
        ("ISTEXT", "ISTEXT(value)", "TRUE if value is text."),
        ("ISLOGICAL", "ISLOGICAL(value)", "TRUE if value is TRUE/FALSE."),
        ("NA", "NA()", "Returns the #N/A error."),
    ],
    "Text": [
        ("CONCATENATE", "CONCATENATE(text1, [text2], ...)", "Joins text values together."),
        ("CONCAT", "CONCAT(text1, [text2], ...)", "Like CONCATENATE, but also accepts ranges."),
        ("TEXTJOIN", "TEXTJOIN(delimiter, ignore_empty, text1, ...)", "Joins text with a delimiter."),
        ("LEN", "LEN(text)", "Number of characters in text."),
        ("UPPER", "UPPER(text)", "Converts text to upper case."),
        ("LOWER", "LOWER(text)", "Converts text to lower case."),
        ("PROPER", "PROPER(text)", "Capitalizes the first letter of each word."),
        ("TRIM", "TRIM(text)", "Removes extra spaces."),
        ("LEFT", "LEFT(text, [num_chars])", "Leftmost characters."),
        ("RIGHT", "RIGHT(text, [num_chars])", "Rightmost characters."),
        ("MID", "MID(text, start_num, num_chars)", "Characters from the middle of text."),
        ("FIND", "FIND(find_text, within_text, [start_num])", "Case-sensitive text search (position)."),
        ("SEARCH", "SEARCH(find_text, within_text, [start_num])", "Case-insensitive text search (position)."),
        ("SUBSTITUTE", "SUBSTITUTE(text, old_text, new_text, [instance_num])", "Replaces occurrences of text."),
        ("REPLACE", "REPLACE(old_text, start_num, num_chars, new_text)", "Replaces text by position."),
        ("REPT", "REPT(text, number_times)", "Repeats text a given number of times."),
        ("EXACT", "EXACT(text1, text2)", "Case-sensitive text comparison."),
        ("VALUE", "VALUE(text)", "Converts text that looks like a number into a number."),
        ("TEXT", "TEXT(value, format_text)", "Formats a number as text."),
        ("CHAR", "CHAR(number)", "Character for a given code."),
        ("CODE", "CODE(text)", "Numeric code of the first character."),
    ],
    "Date & Time": [
        ("TODAY", "TODAY()", "Current date."),
        ("NOW", "NOW()", "Current date and time."),
        ("DATE", "DATE(year, month, day)", "Builds a date."),
        ("YEAR", "YEAR(date)", "Year of a date."),
        ("MONTH", "MONTH(date)", "Month of a date."),
        ("DAY", "DAY(date)", "Day of a date."),
        ("WEEKDAY", "WEEKDAY(date, [return_type])", "Day of the week."),
        ("HOUR", "HOUR(time)", "Hour component."),
        ("MINUTE", "MINUTE(time)", "Minute component."),
        ("SECOND", "SECOND(time)", "Second component."),
        ("DAYS", "DAYS(end_date, start_date)", "Days between two dates."),
        ("DATEDIF", "DATEDIF(start_date, end_date, unit)", "Difference between dates (Y/M/D/MD/YM/YD)."),
        ("EDATE", "EDATE(start_date, months)", "Date some months before/after a start date."),
        ("EOMONTH", "EOMONTH(start_date, months)", "Last day of the month some months away."),
    ],
    "Lookup & Reference": [
        ("VLOOKUP", "VLOOKUP(lookup_value, table, col_index, [range_lookup])", "Looks up a value in the first column of a range."),
        ("HLOOKUP", "HLOOKUP(lookup_value, table, row_index, [range_lookup])", "Looks up a value in the first row of a range."),
        ("INDEX", "INDEX(range, row_num, [col_num])", "Value at a given position in a range."),
        ("MATCH", "MATCH(lookup_value, lookup_array, [match_type])", "Position of a value within a range."),
        ("CHOOSE", "CHOOSE(index_num, value1, [value2], ...)", "Picks a value by position."),
        ("ROW", "ROW([reference])", "Row number of a reference."),
        ("COLUMN", "COLUMN([reference])", "Column number of a reference."),
        ("ROWS", "ROWS(range)", "Number of rows in a range."),
        ("COLUMNS", "COLUMNS(range)", "Number of columns in a range."),
    ],
}


class FunctionPickerDialog(QDialog):
    """Excel-style 'Insert Function' (fx) browser: search or pick a
    category, see each function's signature and description, and insert
    'FUNCNAME(' into the formula currently being composed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Function")
        self.resize(480, 420)
        self.selected_function = None
        self.setStyleSheet(
            "QDialog { background:#ffffff; }"
            "QWidget { background:#ffffff; color:#000000; }"
            "QLineEdit, QComboBox { background:#ffffff; color:#000000;"
            "  border:1px solid #b0b0b0; border-radius:2px; padding:4px; }"
            "QListWidget { background:#ffffff; color:#000000; border:1px solid #b0b0b0; }"
            "QListWidget::item:selected { background:#c9dfef; color:#000000; }"
            "QLabel#desc { color:#3a3a3a; }"
            "QPushButton { background:#217346; color:#ffffff; border:none;"
            "  border-radius:3px; padding:6px 16px; font-weight:bold; }"
            "QPushButton:hover { background:#1a5c38; }"
            "QPushButton:disabled { background:#c8c8c8; color:#808080; }")

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search for a function...")
        self.category_box = QComboBox()
        self.category_box.addItem("All Categories")
        for cat in _FUNCTION_CATALOG:
            self.category_box.addItem(cat)
        top.addWidget(self.search_box, 1)
        top.addWidget(self.category_box)
        layout.addLayout(top)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        self.desc_label = QLabel("Select a function to see its description.")
        self.desc_label.setObjectName("desc")
        self.desc_label.setWordWrap(True)
        self.desc_label.setMinimumHeight(48)
        layout.addWidget(self.desc_label)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.insert_btn = QPushButton("Insert")
        self.insert_btn.setEnabled(False)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background:#f3f2f1; color:#333333; border:1px solid #c8c8c8; }"
            "QPushButton:hover { background:#e5e5e5; }")
        btns.addWidget(self.insert_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self.search_box.textChanged.connect(self._refresh_list)
        self.category_box.currentIndexChanged.connect(self._refresh_list)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._accept())
        self.insert_btn.clicked.connect(self._accept)
        cancel_btn.clicked.connect(self.reject)

        self._refresh_list()

    def _refresh_list(self):
        query = self.search_box.text().strip().upper()
        category = self.category_box.currentText()
        self.list_widget.clear()
        for cat, funcs in _FUNCTION_CATALOG.items():
            if category != "All Categories" and cat != category:
                continue
            for name, sig, desc in funcs:
                if query and query not in name:
                    continue
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, (sig, desc))
                self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        else:
            self.desc_label.setText("No matching functions.")
            self.insert_btn.setEnabled(False)

    def _on_selection_changed(self, current, previous):
        if current is None:
            self.insert_btn.setEnabled(False)
            return
        sig, desc = current.data(Qt.ItemDataRole.UserRole)
        self.desc_label.setText("%s\n%s" % (sig, desc))
        self.insert_btn.setEnabled(True)

    def _accept(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_function = item.text()
        self.accept()


class ExcelTabContainer(QWidget):
    """The 'Excel' tab's content: a toolbar (open/new/save/analysis actions)
    plus an inner QTabWidget with one SpreadsheetGrid per opened/new file."""

    # Excel-authentic sheet tabs, at the bottom like real Excel, with the
    # classic green underline on the active sheet.
    _TAB_QSS = (
        "QTabWidget::tab-bar { alignment: left; }"
        "QTabBar::tab {"
        "  background: #f3f2f1; color: #444444; padding: 6px 18px; font-size: 12px;"
        "  border: 1px solid #d4d4d4; border-top: none; margin-right: 1px; }"
        "QTabBar::tab:selected {"
        "  background: #ffffff; color: #217346; font-weight: bold; font-size: 12px;"
        "  border: 1px solid #d4d4d4; border-top: 3px solid #217346; }"
        "QTabBar::tab:hover:!selected { background: #e5f1fb; color: #217346; }"
        "QTabWidget::pane { border: 1px solid #d4d4d4; background: #ffffff; }")

    def __init__(self, main_win=None, parent=None):
        super().__init__(parent)
        self._main_win = main_win
        self._sheet_counter = 0
        self.setStyleSheet("background:#ffffff;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Ribbon-style toolbar strip (Excel's ribbon is light gray, distinct
        # from the white sheet area below it).
        ribbon = QFrame()
        ribbon.setStyleSheet("background:#f3f2f1; border-bottom:1px solid #d4d4d4;")
        toolbar = QHBoxLayout(ribbon)
        toolbar.setContentsMargins(8, 6, 8, 6)
        toolbar.setSpacing(6)
        _btn_style = (
            "QPushButton { background:#ffffff; color:#333333; border:1px solid #c8c8c8;"
            "  border-radius:3px; padding:6px 10px; font-weight:bold; font-size:11px; }"
            "QPushButton:hover { background:#e5f1fb; border:1px solid #217346; color:#217346; }"
            "QPushButton:pressed { background:#d0e7d8; }")

        def _mkbtn(text, slot):
            b = QPushButton(text)
            b.setStyleSheet(_btn_style)
            b.clicked.connect(slot)
            toolbar.addWidget(b)
            return b

        _mkbtn("📂 Open File", self.open_file)
        _mkbtn("＋ New Sheet", self.new_sheet)
        _mkbtn("💾 Save", self.save_current)
        toolbar.addSpacing(16)
        _mkbtn("Σ Quick Stats", self.quick_stats)
        _mkbtn("📈 Quick Plot", self.quick_plot)
        _mkbtn("📉 Curve Fit", self.open_curve_fit)
        _mkbtn("𝑓x Insert Function", self.open_function_picker)
        toolbar.addStretch(1)
        layout.addWidget(ribbon)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(self._TAB_QSS)
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)  # Excel: sheet tabs at the bottom
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        self._restore_last_file_or_new()

    def _restore_last_file_or_new(self):
        """Silently reopen whatever file was last opened (in this session or
        a previous one) if it's still there, instead of always starting on
        a blank sheet. Never opened one, or it's since moved/deleted? Fall
        back to one blank sheet exactly as before -- no error dialog, since
        an automatic restore failing on startup shouldn't interrupt anyone."""
        last_path = load_settings().get("excel_last_file")
        if last_path and os.path.isfile(last_path):
            try:
                if self._open_one_file(last_path, silent=True):
                    return
            except Exception:
                pass
        self.new_sheet()

    def current_grid(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, SpreadsheetGrid) else None

    def _on_tab_changed(self, index):
        grid = self.current_grid()
        if grid is not None:
            grid.table.setFocus()

    def new_sheet(self):
        self._sheet_counter += 1
        name = "Sheet%d" % self._sheet_counter
        grid = SpreadsheetGrid(self, sheet=fe.Sheet(name))
        idx = self.tabs.addTab(grid, name)
        self.tabs.setCurrentIndex(idx)
        return grid

    def _close_tab(self, index):
        if self.tabs.count() <= 1:
            QMessageBox.information(self, "MathFunctions", "At least one sheet must stay open.")
            return
        w = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if w is not None:
            w.deleteLater()

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open File(s)", "",
            "Spreadsheet Files (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv);;All Files (*)")
        for path in paths:
            self._open_one_file(path)

    def _open_one_file(self, path, silent=False):
        """Returns True if at least one sheet tab was successfully opened.
        silent=True (used only by the startup auto-restore) reports failures
        by returning False instead of popping an error dialog -- a failed
        automatic reopen on startup shouldn't interrupt anyone."""
        name = os.path.basename(path)
        try:
            if path.lower().endswith(".csv"):
                import pandas as pd
                # CSV has no native formula concept, but pandas reads a
                # "=A1+A2"-looking cell back as the plain literal string
                # unchanged (verified directly) -- load_dataframe's
                # set_cell_raw re-parses that string as a live formula
                # again on its own, so CSV round-trips formulas correctly
                # as long as save_current writes the raw text, not the
                # value (see save_current).
                sheets = [(name, pd.read_csv(path))]
            else:
                try:
                    import openpyxl
                    # data_only=False (the default) reads a formula cell's
                    # FORMULA TEXT, not its cached value -- pandas.read_excel
                    # always does the opposite (cached value, None if there
                    # isn't one), which would silently discard every
                    # formula this app itself saved (see save_current).
                    # Reading every sheet directly this way also preserves
                    # multi-sheet workbooks, same as before.
                    wb = openpyxl.load_workbook(path, data_only=False)
                except ImportError:
                    if not silent:
                        QMessageBox.critical(self, "Missing dependency",
                            "Reading .xlsx files requires the 'openpyxl' package, which isn't installed.")
                    return False
                sheets = [(sn, wb[sn]) for sn in wb.sheetnames]
        except Exception as exc:
            if not silent:
                QMessageBox.critical(self, "Open File Error", "Could not open %s:\n%s" % (path, exc))
            return False
        first_idx = None
        multi = len(sheets) > 1
        for sheet_name, source in sheets:
            tab_label = sheet_name if multi else name
            grid = SpreadsheetGrid(self, sheet=fe.Sheet(sheet_name), file_path=path)
            if path.lower().endswith(".csv"):
                grid.load_dataframe(source)
            else:
                grid.load_worksheet(source)
            idx = self.tabs.addTab(grid, tab_label)
            if first_idx is None:
                first_idx = idx
        self.tabs.setCurrentIndex(first_idx)

        # Remember this as "the last opened file" so it's silently reopened
        # next time MathFunctions starts fresh (see _restore_last_file_or_new).
        s = load_settings()
        s["excel_last_file"] = path
        save_settings(s)
        return True

    def _sibling_grids(self, grid):
        """Every open tab sharing grid's file_path, in tab order,
        including grid itself -- these are exactly the sheets that came
        from the same multi-sheet workbook import (_open_one_file gives
        every sheet from one file the same file_path), so Save should
        write them all back together rather than silently dropping the
        others. A grid with no file_path (a brand-new, never-saved
        sheet) has no siblings and saves alone, as it always has."""
        if not grid.file_path:
            return [grid]
        siblings = [self.tabs.widget(i) for i in range(self.tabs.count())]
        siblings = [w for w in siblings if isinstance(w, SpreadsheetGrid) and w.file_path == grid.file_path]
        return siblings if siblings else [grid]

    def _write_grid_cells(self, ws, grid):
        """Write one grid's cells into an openpyxl worksheet, preserving
        live formulas as real Excel formulas (see save_current)."""
        keys = list(grid.sheet.cells.keys())
        max_row = max((r for (r, c) in keys), default=-1)
        max_col = max((c for (r, c) in keys), default=-1)
        for r in range(max_row + 1):
            for c in range(max_col + 1):
                cell = grid.sheet.get_cell(r, c)
                if cell is None:
                    continue
                value = cell.raw if cell.raw.startswith("=") else cell.value
                if isinstance(value, fe.ErrorValue):
                    value = cell.display  # openpyxl can't store an ErrorValue object directly
                ws.cell(row=r + 1, column=c + 1, value=value)

    _INVALID_SHEET_CHARS = re.compile(r'[:\\/?*\[\]]')

    def _safe_sheet_name(self, name, used):
        """openpyxl sheet titles: <=31 chars, no : \\ / ? * [ ], and must
        be unique within one workbook -- sanitize and de-duplicate so an
        arbitrary sheet.name (typed by the user, or from whatever the
        source file originally called it) can never make wb.create_sheet
        raise partway through a multi-sheet save."""
        base = (self._INVALID_SHEET_CHARS.sub("_", (name or "Sheet").strip()) or "Sheet")[:31]
        candidate = base
        n = 2
        while candidate in used:
            suffix = " (%d)" % n
            candidate = base[:31 - len(suffix)] + suffix
            n += 1
        used.add(candidate)
        return candidate

    def save_current(self):
        grid = self.current_grid()
        if grid is None:
            return
        default = grid.file_path or (self.tabs.tabText(self.tabs.currentIndex()) + ".xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Save Sheet", default, "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        siblings = self._sibling_grids(grid)
        try:
            if path.lower().endswith(".csv"):
                import pandas as pd
                if len(siblings) > 1:
                    QMessageBox.information(self, "Save",
                        "This file has %d sheets, but a .csv file can only hold one sheet.\n\n"
                        "Only the current sheet (\"%s\") will be saved. Save as .xlsx instead "
                        "to keep all sheets together." % (len(siblings), grid.sheet.name))
                # Write each cell's RAW text, not its computed value, so
                # a formula like "=A1+A2" round-trips as a live formula
                # when reopened rather than a frozen number -- CSV has no
                # formula concept of its own, but pandas reads the string
                # back unchanged (verified directly) and set_cell_raw
                # re-parses it as a formula on its own (see _open_one_file).
                keys = list(grid.sheet.cells.keys())
                max_row = max((r for (r, c) in keys), default=-1)
                max_col = max((c for (r, c) in keys), default=-1)
                rows = []
                for r in range(max_row + 1):
                    row_vals = []
                    for c in range(max_col + 1):
                        cell = grid.sheet.get_cell(r, c)
                        row_vals.append(cell.raw if cell else None)
                    rows.append(row_vals)
                pd.DataFrame(rows).to_csv(path, index=False, header=False)
                grid.file_path = path
                self.tabs.setTabText(self.tabs.indexOf(grid), os.path.basename(path))
            else:
                try:
                    import openpyxl
                except ImportError:
                    QMessageBox.critical(self, "Missing dependency",
                        "Saving .xlsx files requires the 'openpyxl' package, which isn't installed.")
                    return
                # Written directly via openpyxl (not pandas.to_excel) so a
                # formula cell is saved as an ACTUAL Excel formula
                # (openpyxl auto-detects a "=..." string value as one):
                # real Excel recalculates it itself on open, and
                # reopening the file in THIS app (load_worksheet, which
                # reads with data_only=False) gets the formula text back
                # too, instead of a frozen number -- pandas.to_excel/
                # read_excel can only ever round-trip the computed VALUE,
                # never the formula (verified directly: it always reads a
                # formula cell's cached value, which is None here since
                # nothing ever computed one, and can silently drop a row
                # that becomes entirely blank as a result).
                #
                # ALL sheets sharing this file's path are written
                # together into one workbook (not just the active tab),
                # so a multi-sheet file that was opened, lightly edited
                # on one sheet, and saved doesn't silently lose its other
                # sheets.
                wb = openpyxl.Workbook()
                wb.remove(wb.active)
                used_names = set()
                for sib in siblings:
                    ws = wb.create_sheet(title=self._safe_sheet_name(sib.sheet.name, used_names))
                    self._write_grid_cells(ws, sib)
                wb.save(path)
                multi = len(siblings) > 1
                for sib in siblings:
                    sib.file_path = path
                    label = sib.sheet.name if multi else os.path.basename(path)
                    self.tabs.setTabText(self.tabs.indexOf(sib), label)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", "Could not save:\n%s" % exc)

    def quick_stats(self):
        grid = self.current_grid()
        if grid is None:
            return
        vals = grid.selected_single_column_values()
        if not vals:
            QMessageBox.information(self, "Quick Stats", "Select one or more numeric cells first.")
            return
        import numpy as np
        arr = np.array(vals)
        msg = (
            "Count: %d\n"
            "Mean: %.6g\n"
            "Std Dev: %.6g\n"
            "Min: %.6g\n"
            "Max: %.6g" % (
                len(arr), float(np.mean(arr)),
                float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
                float(np.min(arr)), float(np.max(arr))))
        QMessageBox.information(self, "Quick Stats", msg)

    def quick_plot(self):
        grid = self.current_grid()
        if grid is None:
            return
        pair = grid.selected_range_values()
        if pair is None:
            QMessageBox.information(self, "Quick Plot",
                "Select two adjacent numeric columns (X then Y) first.")
            return
        xs, ys = pair
        QuickPlotDialog(xs, ys, self).exec()

    def open_curve_fit(self):
        grid = self.current_grid()
        if grid is None:
            return
        pair = grid.selected_range_values()
        if pair is None:
            QMessageBox.information(self, "Curve Fit",
                "Select two adjacent numeric columns (X then Y) first.")
            return
        xs, ys = pair
        cols = grid.selected_range_columns()
        x_label = fe.index_to_col(cols[0]) if cols else "X"
        y_label = fe.index_to_col(cols[1]) if cols else "Y"
        CurveFitDialog(xs, ys, x_label, y_label, grid, self).exec()

    def open_function_picker(self):
        grid = self.current_grid()
        if grid is None:
            return
        dlg = FunctionPickerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_function:
            grid.insert_function_call(dlg.selected_function)


class MathFunctionsWindow(QMainWindow):
    """Outer 2-tab container: Calculator + Excel (real formula-engine
    spreadsheet). Created once, shown/raised on demand — see
    MeasurementInterface.open_math_functions()."""

    _TAB_QSS = (
        "QTabBar::tab {"
        "  background: #1a2535; color: #7a9ab5; padding: 10px 28px; font-size: 13px;"
        "  border: 1px solid #2d3f52; border-bottom: none; margin-right: 2px; }"
        "QTabBar::tab:selected {"
        "  background: #1f6fbf; color: #ffffff; font-weight: bold; font-size: 13px;"
        "  border: 1px solid #4a90d9; border-bottom: none; }"
        "QTabBar::tab:hover:!selected { background: #243447; color: #c0d8f0; }"
        "QTabWidget::pane { border: 1px solid #2d3f52; background: #141e2b; }")

    def __init__(self, main_win=None):
        super().__init__()
        self.main_win = main_win
        self.setWindowTitle("MathFunctions")
        self.resize(1050, 740)
        self.setStyleSheet(
            "QMainWindow { background:#1e1e2f; }"
            "QWidget { background:#1e1e2f; color:white; }"
            "QMessageBox QLabel { color:white; background:transparent; }")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(self._TAB_QSS)
        layout.addWidget(self.tabs)

        self.calculator = CalculatorWidget()
        calc_wrap = QWidget()
        calc_layout = QHBoxLayout(calc_wrap)
        calc_layout.addStretch(1)
        calc_inner = QWidget()
        calc_inner.setMaximumWidth(420)
        calc_inner_layout = QVBoxLayout(calc_inner)
        calc_inner_layout.addWidget(self.calculator)
        calc_layout.addWidget(calc_inner)
        calc_layout.addStretch(1)
        self.tabs.addTab(calc_wrap, "🖩  Calculator")

        self.excel = ExcelTabContainer(main_win)
        self.tabs.addTab(self.excel, "📊  Excel")


class ResultsWindow(QMainWindow):
    """Results viewer window — shows past measurements with plots and fitting."""

    def __init__(self, main_window):
        super().__init__()
        self.main_win = main_window
        self.setWindowTitle("Results — Measurement Viewer")
        self.setMinimumSize(1300, 750)
        self.resize(1400, 850)
        self._selected_idx  = None
        self._last_hist_len = 0   # track history length to detect new measurements

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar_layout = QVBoxLayout()

        # Header row: label + live indicator + refresh button
        hdr = QHBoxLayout()
        sidebar_label = QLabel("MEASUREMENTS")
        sidebar_label.setStyleSheet("font-weight:bold; color:#818cf8; padding:4px;")
        hdr.addWidget(sidebar_label)
        hdr.addStretch()
        self._live_dot = QLabel("●")
        self._live_dot.setStyleSheet("color:#3be362; font-size:10px;")
        self._live_dot.setToolTip("Auto-refreshing while experiment runs")
        hdr.addWidget(self._live_dot)
        refresh_btn = QPushButton("↺")
        refresh_btn.setMaximumWidth(28)
        refresh_btn.setToolTip("Refresh now")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#555;color:#fff;padding:3px;border-radius:3px;border:none;}"
            "QPushButton:hover{background:#666;}")
        refresh_btn.clicked.connect(self._refresh_sidebar)
        hdr.addWidget(refresh_btn)
        sidebar_layout.addLayout(hdr)

        self.sidebar_list = QListWidget()
        self.sidebar_list.setStyleSheet(
            "QListWidget { font-size:12px; }"
            "QListWidget::item { padding:6px 4px; border-bottom:1px solid #2b2b3d; }"
            "QListWidget::item:selected { background:#2d2d4f; }"
        )
        self.sidebar_list.itemClicked.connect(self._on_select_measurement)
        self.sidebar_list.itemDoubleClicked.connect(self._show_params_dialog)
        sidebar_layout.addWidget(self.sidebar_list)

        # Copy All button below sidebar
        self.copy_all_btn = QPushButton("📋  Copy All Results")
        self.copy_all_btn.clicked.connect(self._copy_all_results)
        self.copy_all_btn.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #818cf8,stop:1 #4f46e5); color:white; font-weight:bold; padding:5px;"
        )
        sidebar_layout.addWidget(self.copy_all_btn)

        sidebar_w = QWidget()
        sidebar_w.setLayout(sidebar_layout)
        sidebar_w.setMaximumWidth(260)

        # ── Auto-refresh timer (2 s) ──────────────────────────────────────
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2000)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start()

        # ── Empty state ───────────────────────────────────────────────────
        self.empty_label = QLabel("No measurement performed")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("font-size:16px; color:#666;")

        # ── Tabs ─────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)

        self.tab_iv       = self._setup_tab_iv()
        self.tab_v3w      = self._setup_tab_v3w_theta()
        self.tab_global   = self._setup_tab_fit("global")
        self.tab_phase    = self._setup_tab_fit("phase")
        self.tab_accurate = self._setup_tab_fit("accurate")

        self.tabs.addTab(self.tab_iv,       "IV")
        self.tabs.addTab(self.tab_v3w,      "V₃ω & θ")
        self.tabs.addTab(self.tab_global,   "Global Fit")
        self.tabs.addTab(self.tab_phase,    "Phase Fit")
        self.tabs.addTab(self.tab_accurate, "Accurate Fit")

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.empty_label)
        self.content_stack.addWidget(self.tabs)

        layout.addWidget(sidebar_w, 1)
        layout.addWidget(self.content_stack, 4)

        self._refresh_sidebar()

    # ── Tab builders ─────────────────────────────────────────────────────

    def _make_canvas_with_zoom(self, parent_widget):
        """Create a FigureCanvas with a minimal zoom-only toolbar."""
        canvas = FigureCanvas(Figure())
        toolbar = NavigationToolbar(canvas, parent_widget)
        # Keep only Home, Zoom, Pan, Save — hide the rest
        for action in toolbar.actions():
            if action.text() not in ('Home', 'Zoom', 'Pan', 'Save', ''):
                toolbar.removeAction(action)
        toolbar.setMaximumHeight(30)
        toolbar.setStyleSheet("background:#1e1e2f; border:none;")
        return canvas, toolbar

    def _make_result_label(self):
        """Selectable monospace text panel for fit results (Ctrl+C to copy)."""
        from PySide6.QtWidgets import QPlainTextEdit
        lbl = QPlainTextEdit("—")
        lbl.setReadOnly(True)
        lbl.setStyleSheet(
            "QPlainTextEdit {"
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 12px; padding: 8px;"
            "background:#2b2b3d; color:#e0e0e0; border:none; border-radius:4px;"
            "}"
            "QPlainTextEdit::selection{background:#4af4a8; color:#000;}"
        )
        lbl.setMaximumHeight(120)
        return lbl

    def _setup_tab_iv(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.canvas_iv, toolbar = self._make_canvas_with_zoom(tab)
        layout.addWidget(toolbar)
        layout.addWidget(self.canvas_iv, 4)
        self.text_iv = self._make_result_label()
        layout.addWidget(self.text_iv, 1)
        return tab

    def _setup_tab_v3w_theta(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.canvas_v3w_theta, toolbar = self._make_canvas_with_zoom(tab)
        layout.addWidget(toolbar)
        layout.addWidget(self.canvas_v3w_theta)
        return tab

    def _setup_tab_fit(self, fit_type):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        canvas, toolbar = self._make_canvas_with_zoom(tab)
        setattr(self, f'canvas_{fit_type}', canvas)
        layout.addWidget(toolbar)
        layout.addWidget(canvas, 4)

        text_lbl = self._make_result_label()
        text_lbl.setPlainText("Not fitted yet — click Fit Now to fit this measurement")
        setattr(self, f'text_{fit_type}', text_lbl)
        layout.addWidget(text_lbl, 1)

        btn_row = QHBoxLayout()
        fit_btn = QPushButton("⚙  Fit Now")
        fit_btn.setMaximumWidth(130)
        fit_btn.setStyleSheet("background:#3be362; color:black; font-weight:bold; padding:5px;")
        fit_btn.clicked.connect(lambda _, ft=fit_type: self._fit_now(ft))

        copy_btn = QPushButton("📋  Copy Results")
        copy_btn.setMaximumWidth(140)
        copy_btn.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #818cf8,stop:1 #4f46e5); color:white; font-weight:bold; padding:5px;"
        )
        copy_btn.clicked.connect(lambda _, ft=fit_type: self._copy_fit_results(ft))

        btn_row.addWidget(fit_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return tab

    # ── Sidebar ───────────────────────────────────────────────────────────

    def _auto_refresh(self):
        """Called every 2 s — refresh sidebar only if history has grown."""
        cur_len = len(self.main_win._measurement_history)
        is_running = self.main_win.stop_button.isEnabled()
        # Pulse live dot green when running, grey when idle
        self._live_dot.setStyleSheet(
            "color:#3be362; font-size:10px;" if is_running else "color:#555; font-size:10px;")
        if cur_len != self._last_hist_len:
            self._last_hist_len = cur_len
            # Preserve the current selection index before refreshing
            prev_idx = self._selected_idx
            self._refresh_sidebar()
            # Re-select the same item if it still exists
            if prev_idx is not None and prev_idx < self.sidebar_list.count():
                self.sidebar_list.setCurrentRow(prev_idx)

    def _refresh_sidebar(self):
        self.sidebar_list.clear()
        if not self.main_win._measurement_history:
            self.content_stack.setCurrentWidget(self.empty_label)
            return
        self.content_stack.setCurrentWidget(self.tabs)

        for i, meas in enumerate(self.main_win._measurement_history):
            name   = meas['name']
            status = meas['status']
            ts     = meas.get('timestamp')
            time_str = ts.strftime('%H:%M') if ts else ''

            if status == 'completed':
                icon, color = '✓', '#3be362'
            elif status == 'interrupted':
                icon, color = '⚠', '#ff6b6b'
            elif status == 'iv':
                icon, color = '◆', '#4a9eff'
            else:
                icon, color = '•', '#ffffff'

            text = f"{icon}  {name}   [{time_str}]"
            item = QListWidgetItem(text)
            item.setForeground(QColor(color))
            item.setData(Qt.UserRole, i)
            item.setToolTip("Double-click to view parameters")
            self.sidebar_list.addItem(item)

    def _on_select_measurement(self, item):
        idx = item.data(Qt.UserRole)
        self._selected_idx = idx
        self._plot_measurement(self.main_win._measurement_history[idx])

    def _show_params_dialog(self, item):
        """Show measurement parameters in a dialog on double-click."""
        idx  = item.data(Qt.UserRole)
        meas = self.main_win._measurement_history[idx]
        p    = meas.get('params', {})
        calibrated    = meas.get('calibrated', False)
        calib_deg     = meas.get('calib_phase_deg')
        ts            = meas.get('timestamp')
        time_str      = ts.strftime('%Y-%m-%d  %H:%M:%S') if ts else 'Unknown'
        status        = meas['status'].upper()

        lines = [
            "=" * 52,
            f"  {meas['name']}  —  {status}",
            f"  Timestamp : {time_str}",
            "=" * 52,
            "",
            "--- Measurement Settings ---",
        ]
        field_map = [
            ('AC Voltage',           'AC_VOLTAGE',         '{:.4f} V'),
            ('AC Current',           'AC_CURRENT',         '{:.6g} A'),
            ('Global Wait Time',     'WAIT_TIME',           '{:.1f} s'),
            ('Averaging Time',       'AVERAGE_TIME',        '{:.1f} s'),
            ('Stabilisation Time',   'STABILIZATION_TIME',  '{:.1f} s'),
            ('Polling dt',           'dt',                  '{:.3f} s'),
        ]
        _freqs = p.get('FREQUENCIES') or [p.get('START_FREQ', '?')]
        lines.append(f"  {'Frequencies (Hz)':<28}:  {', '.join(f'{f:.4g}' for f in _freqs)}")
        for label, key, fmt in field_map:
            val = p.get(key)
            if val is not None:
                lines.append(f"  {label:<28}:  {fmt.format(val)}")

        lines += [
            "",
            "--- Sample Parameters ---",
            f"  {'Resistance R':<28}:  {p.get('R', '?'):.4f} Ω",
            f"  {'dR/dT  r':<28}:  {p.get('r', '?'):.4f} Ω K⁻¹",
            f"  {'Length L':<28}:  {p.get('L', '?'):.4e} m",
            f"  {'Cross Section S':<28}:  {p.get('S', '?'):.4e} m²",
            "",
            "--- 1ω Phase Calibration ---",
            f"  {'Calibrated':<28}:  {'Yes' if calibrated else 'No'}",
        ]
        if calibrated and calib_deg is not None:
            lines.append(f"  {'Calibrated PHAS':<28}:  {calib_deg:.4f}°")
        lines += ["", "=" * 52]

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Parameters — {meas['name']}")
        dlg.setMinimumSize(480, 420)
        dlg_layout = QVBoxLayout(dlg)

        text_area = QLabel("\n".join(lines))
        text_area.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size:12px;"
            "background:#2b2b3d; padding:12px; border-radius:4px;"
        )
        text_area.setWordWrap(False)

        scroll = QScrollArea()
        scroll.setWidget(text_area)
        scroll.setWidgetResizable(True)
        dlg_layout.addWidget(scroll)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        close_btn.setMaximumWidth(100)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        dlg_layout.addLayout(row)

        dlg.exec()

    # ── Plotting ──────────────────────────────────────────────────────────

    def _plot_measurement(self, meas):
        import numpy as np
        data_3w  = meas.get('data_3w', [])
        data_iv  = meas.get('data_iv', [])
        fit_res  = meas.get('fit_results')
        status   = meas.get('status')

        self._plot_iv(data_iv)

        if status == 'iv':
            self._clear_tab(self.canvas_v3w_theta)
            for ft in ['global', 'phase', 'accurate']:
                self._clear_tab(getattr(self, f'canvas_{ft}'),
                                getattr(self, f'text_{ft}'))
            return

        self._plot_v3w_theta(data_3w)
        self._plot_fits(data_3w, fit_res)

    def _clear_tab(self, canvas, text_lbl=None, msg="Not fitted yet"):
        if canvas is None:
            return
        fig = canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, msg, ha='center', va='center',
                transform=ax.transAxes, color='#888', fontsize=12)
        canvas.draw()
        if text_lbl is not None:
            text_lbl.setPlainText(msg)

    def _plot_iv(self, data_iv):
        import numpy as np
        fig = self.canvas_iv.figure
        fig.clear()
        if not data_iv:
            self._clear_tab(self.canvas_iv, self.text_iv, "No IV data")
            return
        try:
            d   = np.array(data_iv)
            i3  = d[:, 2]
            v3w = d[:, 3]
            ax  = fig.add_subplot(111)
            ax.scatter(i3, v3w, s=25, alpha=0.7, color='#3be362', label='Data')
            # Linear fit through origin for IV
            if len(i3) > 1:
                coeffs = np.polyfit(i3, v3w, 1)
                x_fit  = np.linspace(i3.min(), i3.max(), 200)
                ax.plot(x_fit, np.polyval(coeffs, x_fit), '--', color='#ff9f43',
                        linewidth=1.5, label=f'Fit slope={coeffs[0]:.3e}')
            ax.set_xlabel(r"$I^3\ (\mathrm{A}^3)$", fontsize=10)
            ax.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$", fontsize=10)
            ax.set_title(r"IV Check: $V_{3\omega}$ vs $I^3$", fontsize=11)
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            self.canvas_iv.draw()
            self.text_iv.setPlainText(
                f"Points: {len(i3)}\n"
                f"I³ range:   {i3.min():.3e} – {i3.max():.3e} A³\n"
                f"V₃ω range: {v3w.min():.3e} – {v3w.max():.3e} V"
            )
        except Exception as e:
            self._clear_tab(self.canvas_iv, self.text_iv, f"Plot error: {e}")

    def _plot_v3w_theta(self, data_3w):
        import numpy as np
        fig = self.canvas_v3w_theta.figure
        fig.clear()
        if not data_3w:
            self._clear_tab(self.canvas_v3w_theta, msg="No data")
            return
        try:
            d     = np.array(data_3w)
            f     = d[:, 0]
            v3w   = d[:, 4]
            theta = d[:, 6]

            ax1 = fig.add_subplot(211)
            ax1.scatter(f, v3w, s=20, alpha=0.7, color='#3be362')
            ax1.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$", fontsize=10)
            ax1.set_title(r"$V_{3\omega}$ vs Frequency", fontsize=11)
            ax1.grid(True, alpha=0.3)

            ax2 = fig.add_subplot(212)
            ax2.scatter(f, theta, s=20, alpha=0.7, color='#818cf8')
            ax2.set_xlabel("Frequency (Hz)", fontsize=10)
            ax2.set_ylabel(r"$\theta\ (°)$", fontsize=10)
            ax2.set_title(r"Phase $\theta$ vs Frequency", fontsize=11)
            ax2.grid(True, alpha=0.3)

            fig.tight_layout()
            self.canvas_v3w_theta.draw()
        except Exception as e:
            self._clear_tab(self.canvas_v3w_theta, msg=f"Plot error: {e}")

    def _plot_fits(self, data_3w, fit_res):
        import numpy as np
        if not data_3w:
            for ft in ['global', 'phase', 'accurate']:
                self._clear_tab(getattr(self, f'canvas_{ft}'),
                                getattr(self, f'text_{ft}'), "No data")
            return

        d   = np.array(data_3w)
        f   = d[:, 0]
        v3w = d[:, 4]

        # ── Global Fit ──
        if fit_res and fit_res.get('global') is not None:
            k, gm, ke, gme = fit_res['global']
            curve = fit_res.get('global_curve')
            self._draw_fit_plot(self.canvas_global, f, v3w, curve,
                                r"Global Fit: $V_{3\omega}$ vs Frequency")
            self.text_global.setPlainText(
                f"{'Parameter':<22} {'Value':>18}   Unit\n"
                f"{'─'*48}\n"
                f"{'k (Global Fit)':<22} {k:>12.6f} ± {ke:<8.6f}  W m⁻¹ K⁻¹\n"
                f"{'γ (Global Fit)':<22} {gm:>12.6f} ± {gme:<8.6f}  s⁻¹"
            )
        else:
            self._clear_tab(self.canvas_global, self.text_global)

        # ── Phase Fit ──
        if fit_res and fit_res.get('phase') is not None:
            gp, gpe = fit_res['phase']
            phase_data  = fit_res.get('phase_data')
            phase_curve = fit_res.get('phase_curve')
            fig = self.canvas_phase.figure
            fig.clear()
            ax  = fig.add_subplot(111)
            if phase_data:
                fs, tp = phase_data
                ax.scatter(fs, np.abs(tp), s=20, alpha=0.7, color='#818cf8', label=r'$|\tan(\varphi)|$')
            if phase_curve:
                fx, fy = phase_curve
                ax.plot(fx, np.abs(fy), '-', color='#ff9f43', linewidth=2, label='Linear fit')
            ax.set_xlabel("Frequency (Hz)", fontsize=10)
            ax.set_ylabel(r"$|\tan(\varphi)|$", fontsize=10)
            ax.set_title(r"Phase Fit: $|\tan(\varphi)|$ vs Frequency", fontsize=11)
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            self.canvas_phase.draw()
            self.text_phase.setPlainText(
                f"{'Parameter':<22} {'Value':>18}   Unit\n"
                f"{'─'*48}\n"
                f"{'γ (Phase Fit)':<22} {gp:>12.6f} ± {gpe:<8.6f}  s⁻¹"
            )
        else:
            self._clear_tab(self.canvas_phase, self.text_phase)

        # ── Accurate Fit ──
        if fit_res and fit_res.get('accurate') is not None:
            ka, kae = fit_res['accurate']
            curve   = fit_res.get('accurate_curve')
            self._draw_fit_plot(self.canvas_accurate, f, v3w, curve,
                                r"Accurate Fit: $V_{3\omega}$ vs Frequency (fixed $\gamma$)")
            gp_val = fit_res['phase'][0] if fit_res.get('phase') else float('nan')
            self.text_accurate.setPlainText(
                f"{'Parameter':<22} {'Value':>18}   Unit\n"
                f"{'─'*48}\n"
                f"{'k (Accurate Fit)':<22} {ka:>12.6f} ± {kae:<8.6f}  W m⁻¹ K⁻¹\n"
                f"{'γ (fixed, Phase)':<22} {gp_val:>12.6f}              s⁻¹"
            )
        else:
            self._clear_tab(self.canvas_accurate, self.text_accurate)

    def _draw_fit_plot(self, canvas, f_data, v3w_data, curve, title):
        """Draw scatter + fit curve on a canvas."""
        fig = canvas.figure
        fig.clear()
        ax  = fig.add_subplot(111)
        ax.scatter(f_data, v3w_data, s=20, alpha=0.7, color='#3be362', label='Data', zorder=3)
        if curve is not None:
            fx, fy = curve
            ax.plot(fx, fy, '-', color='#ff9f43', linewidth=2, label='Fit', zorder=4)
        ax.set_xlabel("Frequency (Hz)", fontsize=10)
        ax.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$", fontsize=10)
        ax.set_title(title, fontsize=11)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        canvas.draw()

    # ── Fit Now / Copy ────────────────────────────────────────────────────

    def _fit_now(self, fit_type):
        import numpy as np
        if self._selected_idx is None:
            QMessageBox.warning(self, "No selection", "Select a measurement from the sidebar first.")
            return
        meas    = self.main_win._measurement_history[self._selected_idx]
        data_3w = meas.get('data_3w', [])
        if not data_3w:
            QMessageBox.warning(self, "No data", "This measurement has no 3ω data to fit.")
            return

        p = meas.get('params', {})
        try:
            A = (4 * p['L'] * p['R'] * p['r']) / (np.pi**4 * p['S'])
        except (KeyError, TypeError, ZeroDivisionError):
            QMessageBox.warning(self, "Missing params",
                "Sample parameters (R, r, L, S) are missing — cannot fit.")
            return

        core = self.main_win.core
        if not meas.get('fit_results'):
            meas['fit_results'] = {
                'global': None, 'global_curve': None,
                'phase':  None, 'phase_curve':  None, 'phase_data': None,
                'accurate': None, 'accurate_curve': None,
            }
        fr = meas['fit_results']

        def _smooth_v3w(f_lo, f_hi, I_mean, k, gm):
            ff = np.logspace(np.log10(max(f_lo, 1e-9)), np.log10(f_hi), 300)
            vv = (A * I_mean**3) / (k * np.sqrt(1 + (4 * np.pi * ff * gm)**2))
            return list(ff), list(vv)

        try:
            d = np.array(data_3w)
            f_lo, f_hi = float(d[:, 0].min()), float(d[:, 0].max())
            I_mean = float(np.mean(d[:, 1]))

            if fit_type in ('global', 'accurate'):
                k, gm, ke, gme, _, _, _ = core.fit_3omega_fixed_A(data_3w, A)
                fr['global']       = (k, gm, ke, gme)
                fr['global_curve'] = _smooth_v3w(f_lo, f_hi, I_mean, k, gm)

            if fit_type in ('phase', 'accurate'):
                gp, gpe, fs, tp, sl, ic = core.phase_fit(data_3w)
                fr['phase']      = (gp, gpe)
                fr['phase_data'] = (list(fs), list(tp))
                f_ph = np.logspace(np.log10(max(f_lo, 1e-9)), np.log10(f_hi), 300)
                fr['phase_curve'] = (list(f_ph), list(sl * f_ph + ic))

                if fit_type == 'accurate':
                    ka, kae, _, _, _ = core.fit_3omega_fixed_A_gamma(
                        data_3w, A, gamma=gp)
                    fr['accurate']       = (ka, kae)
                    fr['accurate_curve'] = _smooth_v3w(f_lo, f_hi, I_mean, ka, gp)

            self._plot_measurement(meas)
        except Exception as e:
            QMessageBox.critical(self, "Fit Error", f"Fitting failed:\n{e}")

    def _copy_fit_results(self, fit_type):
        if self._selected_idx is None:
            QMessageBox.warning(self, "No selection", "Select a measurement first.")
            return
        meas    = self.main_win._measurement_history[self._selected_idx]
        fit_res = meas.get('fit_results') or {}
        if not fit_res.get(fit_type):
            QMessageBox.information(self, "No fit", "No fitting results available for this tab.")
            return
        lines = ["Parameter\tValue\tUnit"]
        if fit_type == 'global':
            k, gm, ke, gme = fit_res['global']
            lines += [f"k (Global Fit)\t{k:.6f}±{ke:.6f}\tW m⁻¹ K⁻¹",
                      f"γ (Global Fit)\t{gm:.6f}±{gme:.6f}\ts⁻¹"]
        elif fit_type == 'phase':
            gp, gpe = fit_res['phase']
            lines.append(f"γ (Phase Fit)\t{gp:.6f}±{gpe:.6f}\ts⁻¹")
        elif fit_type == 'accurate':
            ka, kae = fit_res['accurate']
            lines.append(f"k (Accurate Fit)\t{ka:.6f}±{kae:.6f}\tW m⁻¹ K⁻¹")
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "Copied", "Results copied to clipboard (TSV).")

    def _copy_all_results(self):
        """Copy all fit results from all measurements to clipboard."""
        if not self.main_win._measurement_history:
            QMessageBox.information(self, "No data", "No measurements in session.")
            return
        lines = ["Sample\tParameter\tValue\tUnit"]
        for meas in self.main_win._measurement_history:
            name    = meas['name']
            fit_res = meas.get('fit_results') or {}
            if fit_res.get('global'):
                k, gm, ke, gme = fit_res['global']
                lines += [f"{name}\tk (Global Fit)\t{k:.6f}±{ke:.6f}\tW m⁻¹ K⁻¹",
                          f"{name}\tγ (Global Fit)\t{gm:.6f}±{gme:.6f}\ts⁻¹"]
            if fit_res.get('phase'):
                gp, gpe = fit_res['phase']
                lines.append(f"{name}\tγ (Phase Fit)\t{gp:.6f}±{gpe:.6f}\ts⁻¹")
            if fit_res.get('accurate'):
                ka, kae = fit_res['accurate']
                lines.append(f"{name}\tk (Accurate Fit)\t{ka:.6f}±{kae:.6f}\tW m⁻¹ K⁻¹")
        if len(lines) == 1:
            QMessageBox.information(self, "No fits", "No fitting results found in any measurement.")
            return
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, "Copied",
            f"Copied {len(lines)-1} rows to clipboard (TSV — paste into Excel or Word).")


class AnalysisWindow(QMainWindow):
    """Multi-sample analysis: overlay plotting, masking, comparative fitting."""

    _PALETTE = [
        '#3be362','#818cf8','#ff9f43','#ff6b6b','#4a9eff',
        '#a55eea','#26de81','#fd9644','#45aaf2','#fc5c65',
        '#ffdd59','#00b894','#e17055','#74b9ff','#fd79a8',
    ]
    _PARAM_KEYS = ['R', 'r', 'L', 'S']

    def __init__(self, main_window):
        super().__init__()
        self.main_win = main_window
        self.setWindowTitle("Analysis — Multi-Sample")
        self.setMinimumSize(1450, 820)
        self.resize(1600, 960)
        self._samples     = []
        self._color_idx   = 0
        self._col_cache   = {}   # folder → column mapping
        self._rect_sel      = None
        self._cur_mask_tab  = None
        self._session_names = set()  # names already loaded from session
        self._build_ui()
        self._load_session_data()

        # Auto-sync timer: adds new session measurements while experiment runs
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(2000)
        self._sync_timer.timeout.connect(self._auto_sync)
        self._sync_timer.start()

    # ── Colors ────────────────────────────────────────────────────────────
    def _next_color(self):
        c = self._PALETTE[self._color_idx % len(self._PALETTE)]
        self._color_idx += 1
        return c

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(self._build_sidebar(), 0)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6,6,6,6)
        rl.setSpacing(4)
        rl.addWidget(self._build_fit_controls())
        rl.addWidget(self._build_toolbar())
        self.tabs = QTabWidget()
        self._build_tabs()
        rl.addWidget(self.tabs, 1)
        root.addWidget(right, 1)

    def _build_sidebar(self):
        w = QWidget()
        w.setFixedWidth(280)
        w.setStyleSheet("background:#1a1a2e; color:#fff;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8,8,8,6)
        lay.setSpacing(5)

        hdr = QHBoxLayout()
        title = QLabel("SAMPLES")
        title.setStyleSheet("font-weight:bold; color:#4af4a8; font-size:13px;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._live_dot = QLabel("●")
        self._live_dot.setStyleSheet("color:#555; font-size:10px;")
        self._live_dot.setToolTip("Green = experiment running, auto-syncing new measurements")
        hdr.addWidget(self._live_dot)
        refresh_btn = QPushButton("↺")
        refresh_btn.setMaximumWidth(28)
        refresh_btn.setToolTip("Sync new session measurements now")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#555;color:#fff;padding:3px;border-radius:3px;border:none;}"
            "QPushButton:hover{background:#666;}")
        refresh_btn.clicked.connect(self._sync_session)
        hdr.addWidget(refresh_btn)
        lay.addLayout(hdr)

        add_btn = QPushButton("📂  Add Files")
        add_btn.clicked.connect(self._add_files)
        add_btn.setStyleSheet("background:#4af4a8; color:#000; font-weight:bold; padding:6px; border-radius:4px; border:none;")
        lay.addWidget(add_btn)

        r2 = QHBoxLayout()
        clr_s = QPushButton("✕ Selected")
        clr_s.clicked.connect(self._clear_selected)
        clr_s.setStyleSheet("background:#ff6b6b; color:#fff; padding:5px; border-radius:4px; border:none; font-weight:bold;")
        clr_a = QPushButton("✕ All")
        clr_a.clicked.connect(self._clear_all)
        clr_a.setStyleSheet("background:#ff6b6b; color:#fff; padding:5px; border-radius:4px; border:none; font-weight:bold;")
        r2.addWidget(clr_s); r2.addWidget(clr_a)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        sa = QPushButton("☑ All")
        sa.clicked.connect(lambda: self._check_all(True))
        sa.setStyleSheet("background:#818cf8; color:#fff; padding:4px; border-radius:4px; border:none;")
        da = QPushButton("☐ None")
        da.clicked.connect(lambda: self._check_all(False))
        da.setStyleSheet("background:#818cf8; color:#fff; padding:4px; border-radius:4px; border:none;")
        r3.addWidget(sa); r3.addWidget(da)
        lay.addLayout(r3)

        self.sample_list = QListWidget()
        self.sample_list.setStyleSheet(
            "QListWidget{font-size:11px; background:#2b2b3d; color:#fff; border:1px solid #3d3d5f;}"
            "QListWidget::item{padding:6px 4px; border-bottom:1px solid #3d3d5f;}"
            "QListWidget::item:selected{background:#4af4a8; color:#000; font-weight:bold;}"
        )
        self.sample_list.itemChanged.connect(self._on_check_changed)
        lay.addWidget(self.sample_list, 1)
        return w

    def _build_fit_controls(self):
        w = QWidget()
        w.setStyleSheet("background:#2b2b3d; border-radius:4px; color:#fff;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10,5,10,5)
        lay.setSpacing(8)
        lbl = QLabel("Fit range:")
        lbl.setStyleSheet("color:#4af4a8; font-weight:bold;")
        lay.addWidget(lbl)
        self.fmin_inp = QLineEdit(); self.fmin_inp.setPlaceholderText("f_min"); self.fmin_inp.setMaximumWidth(65)
        self.fmin_inp.setStyleSheet("background:#3d3d5f; color:#fff; border:1px solid #555; padding:3px; border-radius:3px;")
        self.fmax_inp = QLineEdit(); self.fmax_inp.setPlaceholderText("f_max"); self.fmax_inp.setMaximumWidth(65)
        self.fmax_inp.setStyleSheet("background:#3d3d5f; color:#fff; border:1px solid #555; padding:3px; border-radius:3px;")
        lay.addWidget(self.fmin_inp)
        sep = QLabel("–")
        sep.setStyleSheet("color:#666;")
        lay.addWidget(sep)
        lay.addWidget(self.fmax_inp)
        hz = QLabel("Hz")
        hz.setStyleSheet("color:#ccc;")
        lay.addWidget(hz)
        self.same_range_cb = QCheckBox("Same range for all")
        self.same_range_cb.setStyleSheet("color:#fff; spacing:4px;")
        self.same_range_cb.setChecked(True)
        lay.addWidget(self.same_range_cb)
        lay.addStretch()
        return w

    def _build_toolbar(self):
        w = QWidget()
        w.setStyleSheet("background:#2b2b3d; border-radius:4px; color:#fff;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10,5,10,5)
        lay.setSpacing(8)
        lbl = QLabel("Tools:")
        lbl.setStyleSheet("color:#4af4a8; font-weight:bold;")
        lay.addWidget(lbl)

        self.zoom_btn = QPushButton("🔍 Zoom")
        self.zoom_btn.setCheckable(True)
        self.zoom_btn.setMaximumWidth(85)
        self.zoom_btn.setStyleSheet(
            "QPushButton{background:#555; color:#fff; padding:4px; border-radius:3px; border:none;}"
            "QPushButton:hover{background:#666;}"
            "QPushButton:checked{background:#4af4a8; color:#000; font-weight:bold;}"
        )
        self.zoom_btn.toggled.connect(lambda on: self._tool_toggle('zoom', on))

        self.pan_btn = QPushButton("✋ Pan")
        self.pan_btn.setCheckable(True)
        self.pan_btn.setMaximumWidth(75)
        self.pan_btn.setStyleSheet(
            "QPushButton{background:#555; color:#fff; padding:4px; border-radius:3px; border:none;}"
            "QPushButton:hover{background:#666;}"
            "QPushButton:checked{background:#4af4a8; color:#000; font-weight:bold;}"
        )
        self.pan_btn.toggled.connect(lambda on: self._tool_toggle('pan', on))

        self.mask_btn = QPushButton("⊘ Mask")
        self.mask_btn.setCheckable(True)
        self.mask_btn.setMaximumWidth(85)
        self.mask_btn.setStyleSheet(
            "QPushButton{background:#555; color:#fff; padding:4px; border-radius:3px; border:none;}"
            "QPushButton:hover{background:#666;}"
            "QPushButton:checked{background:#ff6b6b; color:#fff; font-weight:bold;}"
        )
        self.mask_btn.toggled.connect(lambda on: self._tool_toggle('mask', on))

        self.mask_all_cb = QCheckBox("Mask All")
        self.mask_all_cb.setStyleSheet("color:#fff; spacing:4px;")
        self.mask_all_cb.setToolTip("Apply mask to all loaded samples")

        for b in [self.zoom_btn, self.pan_btn, self.mask_btn]:
            lay.addWidget(b)
        lay.addWidget(self.mask_all_cb)
        sep = QLabel("  |")
        sep.setStyleSheet("color:#666;")
        lay.addWidget(sep)
        vlab = QLabel("View X:")
        vlab.setStyleSheet("color:#4af4a8; margin-left:4px;")
        lay.addWidget(vlab)

        self.vxmin = QLineEdit(); self.vxmin.setPlaceholderText("min"); self.vxmin.setMaximumWidth(60)
        self.vxmin.setStyleSheet("background:#3d3d5f; color:#fff; border:1px solid #555; padding:2px; border-radius:3px;")
        self.vxmax = QLineEdit(); self.vxmax.setPlaceholderText("max"); self.vxmax.setMaximumWidth(60)
        self.vxmax.setStyleSheet("background:#3d3d5f; color:#fff; border:1px solid #555; padding:2px; border-radius:3px;")
        self.vymin = QLineEdit(); self.vymin.setPlaceholderText("min"); self.vymin.setMaximumWidth(60)
        self.vymin.setStyleSheet("background:#3d3d5f; color:#fff; border:1px solid #555; padding:2px; border-radius:3px;")
        self.vymax = QLineEdit(); self.vymax.setPlaceholderText("max"); self.vymax.setMaximumWidth(60)
        self.vymax.setStyleSheet("background:#3d3d5f; color:#fff; border:1px solid #555; padding:2px; border-radius:3px;")
        for inp in [self.vxmin, self.vxmax, self.vymin, self.vymax]:
            inp.returnPressed.connect(self._apply_view)

        lay.addWidget(self.vxmin)
        sep2 = QLabel("–")
        sep2.setStyleSheet("color:#666;")
        lay.addWidget(sep2)
        lay.addWidget(self.vxmax)
        ylab = QLabel(" Y:")
        ylab.setStyleSheet("color:#4af4a8;")
        lay.addWidget(ylab)
        lay.addWidget(self.vymin)
        sep3 = QLabel("–")
        sep3.setStyleSheet("color:#666;")
        lay.addWidget(sep3)
        lay.addWidget(self.vymax)

        reset_btn = QPushButton("↺")
        reset_btn.setMaximumWidth(32)
        reset_btn.setStyleSheet(
            "QPushButton{background:#555; color:#fff; padding:4px; border-radius:3px; border:none;}"
            "QPushButton:hover{background:#666;}"
        )
        reset_btn.setToolTip("Reset view")
        reset_btn.clicked.connect(self._reset_view)
        lay.addWidget(reset_btn)

        sep4 = QLabel("  |")
        sep4.setStyleSheet("color:#666;")
        lay.addWidget(sep4)
        scale_lbl = QLabel(" Scale:")
        scale_lbl.setStyleSheet("color:#4af4a8; font-weight:bold;")
        lay.addWidget(scale_lbl)

        _btn_ss = ("QPushButton{background:#555;color:#fff;padding:3px 6px;"
                   "border-radius:3px;border:none;font-size:10px;}"
                   "QPushButton:hover{background:#666;}"
                   "QPushButton:checked{background:#4af4a8;color:#000;font-weight:bold;}")
        self.scale_lin_btn  = QPushButton("Lin");     self.scale_lin_btn.setCheckable(True);  self.scale_lin_btn.setChecked(True)
        self.scale_logx_btn = QPushButton("Log-X");   self.scale_logx_btn.setCheckable(True)
        self.scale_logy_btn = QPushButton("Log-Y");   self.scale_logy_btn.setCheckable(True)
        self.scale_ll_btn   = QPushButton("Log-Log"); self.scale_ll_btn.setCheckable(True)
        self._scale_btns = [self.scale_lin_btn, self.scale_logx_btn,
                            self.scale_logy_btn, self.scale_ll_btn]
        for _sb in self._scale_btns:
            _sb.setMaximumWidth(58)
            _sb.setStyleSheet(_btn_ss)
            _sb.clicked.connect(self._on_scale_clicked)
            lay.addWidget(_sb)

        lay.addStretch()
        return w

    # ── Scale tool ────────────────────────────────────────────────────────
    def _on_scale_clicked(self):
        clicked = self.sender()
        for b in self._scale_btns:
            if b is not clicked:
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        clicked.setChecked(True)
        self._apply_scale()

    def _apply_scale(self):
        """Apply selected scale and compute proper limits from positive data only."""
        import numpy as np
        if   self.scale_lin_btn.isChecked():  xsc, ysc = 'linear', 'linear'
        elif self.scale_logx_btn.isChecked(): xsc, ysc = 'log',    'linear'
        elif self.scale_logy_btn.isChecked(): xsc, ysc = 'linear', 'log'
        else:                                 xsc, ysc = 'log',    'log'
        canvas = self._active_canvas()
        if not canvas:
            return

        for ax in canvas.figure.axes:
            try:
                ax.set_xscale(xsc)
                ax.set_yscale(ysc)

                # Gather all x and y values from every plotted artist
                all_x, all_y = [], []
                for art in ax.get_children():
                    # Line2D (fit curves, line plots)
                    if hasattr(art, 'get_xdata') and hasattr(art, 'get_ydata'):
                        xd = np.asarray(art.get_xdata(), dtype=float).ravel()
                        yd = np.asarray(art.get_ydata(), dtype=float).ravel()
                        all_x.append(xd); all_y.append(yd)
                    # PathCollection (scatter plots)
                    elif hasattr(art, 'get_offsets'):
                        off = np.asarray(art.get_offsets())
                        if off.ndim == 2 and off.shape[1] == 2:
                            all_x.append(off[:, 0]); all_y.append(off[:, 1])

                if not all_x:
                    continue

                xs = np.concatenate(all_x)
                ys = np.concatenate(all_y)
                xs = xs[np.isfinite(xs)]
                ys = ys[np.isfinite(ys)]

                # X limits
                if xsc == 'log':
                    xp = xs[xs > 0]
                    if len(xp):
                        ax.set_xlim(xp.min() * 0.8, xp.max() * 1.25)
                else:
                    if len(xs):
                        pad = (xs.max() - xs.min()) * 0.05 or abs(xs.mean()) * 0.05 or 0.1
                        ax.set_xlim(xs.min() - pad, xs.max() + pad)

                # Y limits
                if ysc == 'log':
                    yp = ys[ys > 0]
                    if len(yp):
                        ax.set_ylim(yp.min() * 0.8, yp.max() * 1.25)
                else:
                    if len(ys):
                        pad = (ys.max() - ys.min()) * 0.05 or abs(ys.mean()) * 0.05 or 0.1
                        ax.set_ylim(ys.min() - pad, ys.max() + pad)

            except Exception as e:
                print(f"Scale error on ax: {e}")

        try:
            canvas.figure.tight_layout()
        except Exception:
            pass
        canvas.draw_idle()

    # ── Time Series tab builder ───────────────────────────────────────────
    def _make_ts_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setSpacing(4)

        # ── Filter controls ───────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Freq filter:"))
        self.ts_freq_cb = QComboBox()
        self.ts_freq_cb.addItem("All frequencies")
        self.ts_freq_cb.setMinimumWidth(140)
        self.ts_freq_cb.setStyleSheet(
            "background:#3d3d5f; color:#fff; border:1px solid #555; padding:2px; border-radius:3px;")
        ctrl.addWidget(self.ts_freq_cb)

        ctrl.addWidget(QLabel("  t range:"))
        self.ts_tmin = QLineEdit(); self.ts_tmin.setPlaceholderText("t_min")
        self.ts_tmin.setMaximumWidth(70)
        self.ts_tmin.setStyleSheet("background:#3d3d5f;color:#fff;border:1px solid #555;padding:2px;border-radius:3px;")
        self.ts_tmax = QLineEdit(); self.ts_tmax.setPlaceholderText("t_max")
        self.ts_tmax.setMaximumWidth(70)
        self.ts_tmax.setStyleSheet("background:#3d3d5f;color:#fff;border:1px solid #555;padding:2px;border-radius:3px;")
        ctrl.addWidget(self.ts_tmin); ctrl.addWidget(QLabel("–")); ctrl.addWidget(self.ts_tmax)
        ctrl.addWidget(QLabel("s"))
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(lambda: self._plot_ts(self._checked() or self._samples))
        apply_btn.setStyleSheet("background:#4af4a8;color:#000;padding:4px;border-radius:3px;border:none;")
        ctrl.addWidget(apply_btn)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        # ── Time series canvas (3 subplots) ───────────────────────────────
        lay.addWidget(self._make_canvas('ts'), 3)

        # ── FT controls ───────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#555;")
        lay.addWidget(sep)

        ft_ctrl = QHBoxLayout()
        ft_lbl = QLabel("FT:")
        ft_lbl.setStyleSheet("color:#4af4a8;font-weight:bold;")
        ft_ctrl.addWidget(ft_lbl)

        ft_ctrl.addWidget(QLabel("Channel:"))
        self.ft_channel_cb = QComboBox()
        self.ft_channel_cb.addItems(["V₃ω (r)", "θ (theta)", "I (current)"])
        self.ft_channel_cb.setStyleSheet(
            "background:#3d3d5f;color:#fff;border:1px solid #555;padding:2px;border-radius:3px;")
        ft_ctrl.addWidget(self.ft_channel_cb)

        ft_ctrl.addWidget(QLabel("  t range:"))
        self.ft_tmin = QLineEdit(); self.ft_tmin.setPlaceholderText("t_min")
        self.ft_tmin.setMaximumWidth(70)
        self.ft_tmin.setStyleSheet("background:#3d3d5f;color:#fff;border:1px solid #555;padding:2px;border-radius:3px;")
        self.ft_tmax = QLineEdit(); self.ft_tmax.setPlaceholderText("t_max")
        self.ft_tmax.setMaximumWidth(70)
        self.ft_tmax.setStyleSheet("background:#3d3d5f;color:#fff;border:1px solid #555;padding:2px;border-radius:3px;")
        ft_ctrl.addWidget(self.ft_tmin); ft_ctrl.addWidget(QLabel("–")); ft_ctrl.addWidget(self.ft_tmax)
        ft_ctrl.addWidget(QLabel("s"))

        ft_ctrl.addWidget(QLabel("  3ω ref Hz:"))
        self.ft_ref_inp = QLineEdit(); self.ft_ref_inp.setPlaceholderText("3×f")
        self.ft_ref_inp.setMaximumWidth(70)
        self.ft_ref_inp.setStyleSheet("background:#3d3d5f;color:#fff;border:1px solid #555;padding:2px;border-radius:3px;")
        ft_ctrl.addWidget(self.ft_ref_inp)

        ft_compute_btn = QPushButton("▶ Compute FT")
        ft_compute_btn.clicked.connect(self._compute_ft)
        ft_compute_btn.setStyleSheet(
            "background:#818cf8;color:#fff;font-weight:bold;padding:5px;border-radius:4px;border:none;")
        ft_ctrl.addWidget(ft_compute_btn)

        ft_clr_btn = QPushButton("✕")
        ft_clr_btn.setMaximumWidth(28)
        ft_clr_btn.clicked.connect(lambda: self._clear_canvas('ts_ft'))
        ft_clr_btn.setStyleSheet("background:#555;color:#fff;padding:4px;border-radius:3px;border:none;")
        ft_ctrl.addWidget(ft_clr_btn)
        ft_ctrl.addStretch()
        lay.addLayout(ft_ctrl)

        # FT hint label
        self.ft_hint_lbl = QLabel("Drag on time series to set FT range, or enter manually above")
        self.ft_hint_lbl.setStyleSheet("color:#888;font-size:10px;padding:2px 4px;")
        lay.addWidget(self.ft_hint_lbl)

        # ── FT canvas ─────────────────────────────────────────────────────
        lay.addWidget(self._make_canvas('ts_ft'), 2)

        # ── Bottom buttons ────────────────────────────────────────────────
        lay.addLayout(self._btn_row('ts', has_fit=False))
        return tab

    def _find_ts_file(self, csv_path):
        """Search for a matching Time series_*.csv alongside a data CSV,
        in its own folder first, then a Backup_data subfolder.

        Prefers an EXACT name match ("Time series_<base_name>.csv") over a
        substring match -- two files like "sample.csv" and "sample_v2.csv"
        both contain "sample" as a substring of each other's time-series
        file name, so a pure substring search could silently attach the
        wrong series to a file. Substring matching is kept only as a
        fallback for files that were never named to exactly line up.
        """
        import pandas as pd
        folder    = os.path.dirname(csv_path)
        base_name = os.path.splitext(os.path.basename(csv_path))[0]

        def _load_ts(ts_path):
            try:
                df = pd.read_csv(ts_path)
                return {
                    't':     df['Time (s)'].tolist()       if 'Time (s)'      in df.columns else [],
                    'freq':  df['Frequency (Hz)'].tolist() if 'Frequency (Hz)' in df.columns else [],
                    'I':     df['Current (A)'].tolist()    if 'Current (A)'   in df.columns else [],
                    'r':     df['V_3ω (V)'].tolist()       if 'V_3ω (V)'      in df.columns else [],
                    'theta': df['θ (°)'].tolist()          if 'θ (°)'         in df.columns else [],
                }
            except Exception:
                return None

        def _search(dir_path):
            if not os.path.isdir(dir_path):
                return None
            candidates = [f for f in os.listdir(dir_path)
                          if f.lower().startswith('time series_') and f.lower().endswith('.csv')]
            exact_name = f"time series_{base_name}.csv".lower()
            exact = [f for f in candidates if f.lower() == exact_name]
            chosen = exact if exact else [f for f in candidates if base_name.lower() in f.lower()]
            for fname in chosen:
                result = _load_ts(os.path.join(dir_path, fname))
                if result is not None:
                    return result
            return None

        return _search(folder) or _search(os.path.join(folder, 'Backup_data'))

    def _build_tabs(self):
        self.tabs.addTab(self._make_plot_tab('iv',       has_fit=False), "IV")
        self.tabs.addTab(self._make_ts_tab(),                            "Time Series")
        self.tabs.addTab(self._make_plot_tab('v3w',      has_fit=False), "V₃ω & θ")
        self.tabs.addTab(self._make_1w_tab(),                            "R₁ω & θ vs f")
        self.tabs.addTab(self._make_fit_tab('global'),                   "Global Fit")
        self.tabs.addTab(self._make_fit_tab('phase'),                    "Phase Fit")
        self.tabs.addTab(self._make_fit_tab('accurate'),                 "Accurate Fit")
        self.tabs.addTab(self._make_compare_tab(),                       "Compare k/γ")

    def _make_canvas(self, name):
        from matplotlib.figure import Figure
        fig = Figure(figsize=(8, 5), dpi=100)
        fig.set_facecolor('#1e1e2f')
        canvas = FigureCanvas(fig)
        canvas.setMinimumHeight(300)
        setattr(self, f'fig_{name}',    fig)
        setattr(self, f'canvas_{name}', canvas)
        return canvas

    def _make_plot_tab(self, name, has_fit=False):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(self._make_canvas(name), 4)
        lay.addLayout(self._btn_row(name, has_fit))
        return tab

    def _make_fit_tab(self, name):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(self._make_canvas(name), 3)
        from PySide6.QtWidgets import QPlainTextEdit
        lbl = QPlainTextEdit("No fit results yet — click Fit Selected or Fit All")
        lbl.setReadOnly(True)
        lbl.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace; font-size:11px;"
            "background:#2b2b3d; color:#e0e0e0; padding:6px; border:none; border-radius:4px;}"
            "QPlainTextEdit::selection{background:#4af4a8; color:#000;}"
        )
        lbl.setMaximumHeight(130)
        setattr(self, f'tbl_{name}', lbl)
        lay.addWidget(lbl, 1)
        lay.addLayout(self._btn_row(name, has_fit=True))
        return tab

    def _make_compare_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)

        cb_row = QHBoxLayout()
        cb_row.addWidget(QLabel("Show:"))
        self.cmp_global_cb   = QCheckBox("k Global"); self.cmp_global_cb.setChecked(True)
        self.cmp_accurate_cb = QCheckBox("k Accurate"); self.cmp_accurate_cb.setChecked(True)
        self.cmp_phase_cb    = QCheckBox("γ Phase"); self.cmp_phase_cb.setChecked(False)
        for cb in [self.cmp_global_cb, self.cmp_accurate_cb, self.cmp_phase_cb]:
            cb_row.addWidget(cb)
        cb_row.addStretch()
        lay.addLayout(cb_row)

        lay.addWidget(self._make_canvas('compare'), 3)

        from PySide6.QtWidgets import QPlainTextEdit
        self.cmp_stats_lbl = QPlainTextEdit("")
        self.cmp_stats_lbl.setReadOnly(True)
        self.cmp_stats_lbl.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace; font-size:11px;"
            "background:#2b2b3d; color:#e0e0e0; padding:6px; border:none; border-radius:4px;}"
            "QPlainTextEdit::selection{background:#4af4a8; color:#000;}"
        )
        self.cmp_stats_lbl.setMaximumHeight(130)
        lay.addWidget(self.cmp_stats_lbl, 1)

        btn_row = QHBoxLayout()
        for label, fn, style in [
            ("▶ Build Chart",     self._plot_compare,       "background:#3be362;color:black;font-weight:bold;padding:5px;"),
            ("⚙ Fit All Selected",self._fit_all_for_compare,"background:#818cf8;color:white;font-weight:bold;padding:5px;"),
            ("📊 Export CSV",      lambda: self._export_csv('compare'), "background:#ff9f43;color:black;padding:5px;"),
            ("💾 Save",            lambda: self._save_plot('compare'),  "background:#4a9eff;color:white;padding:5px;"),
        ]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            b.setStyleSheet(style)
            btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return tab

    def _btn_row(self, name, has_fit=False):
        row = QHBoxLayout()
        ps = QPushButton("▶ Plot Selected")
        ps.clicked.connect(lambda: self._plot(name, 'selected'))
        ps.setStyleSheet("background:#3be362;color:black;font-weight:bold;padding:5px;border-radius:4px;")
        pa = QPushButton("▶▶ Plot All")
        pa.clicked.connect(lambda: self._plot(name, 'all'))
        pa.setStyleSheet("background:#3be362;color:black;padding:5px;border-radius:4px;")
        cl = QPushButton("✕ Clear")
        cl.clicked.connect(lambda: self._clear_canvas(name))
        cl.setStyleSheet("background:#555;color:white;padding:5px;border-radius:4px;")
        row.addWidget(ps); row.addWidget(pa)
        if has_fit:
            fs = QPushButton("⚙ Fit Selected")
            fs.clicked.connect(lambda: self._fit_selected(name))
            fs.setStyleSheet("background:#818cf8;color:white;font-weight:bold;padding:5px;border-radius:4px;")
            fa = QPushButton("⚙ Fit All")
            fa.clicked.connect(lambda: self._fit_all(name))
            fa.setStyleSheet("background:#818cf8;color:white;padding:5px;border-radius:4px;")
            exp = QPushButton("📊 Export Table")
            exp.clicked.connect(lambda: self._export_csv(name))
            exp.setStyleSheet("background:#ff9f43;color:black;padding:5px;border-radius:4px;")
            row.addWidget(fs); row.addWidget(fa); row.addWidget(exp)
        row.addWidget(cl)
        sv = QPushButton("💾 Save")
        sv.clicked.connect(lambda: self._save_plot(name))
        sv.setStyleSheet("background:#4a9eff;color:white;padding:5px;border-radius:4px;")
        row.addWidget(sv)
        row.addStretch()
        return row

    # ── Session data ──────────────────────────────────────────────────────
    def _load_session_data(self):
        print(f"[Analysis] Loading {len(self.main_win._measurement_history)} entries from session history")
        for entry in self.main_win._measurement_history:
            n_3w = len(entry.get('data_3w', []))
            n_iv = len(entry.get('data_iv', []))
            print(f"  - {entry['name']}: status={entry.get('status')} n_3w={n_3w} n_iv={n_iv}")
            base = {
                'name':        entry['name'], 'source': 'session',
                'filepath':    None, 'color': self._next_color(), 'checked': True,
                'fit_results': None, 'mask_3w': set(), 'mask_iv': set(),
                'params':      entry.get('params', {}),
                'timestamp':   entry.get('timestamp'),
                'ts_data':     entry.get('ts_data'),  # {t, freq, I, r, theta}
                'data_1w':     entry.get('data_1w', []),
            }
            if entry.get('status') == 'iv':
                self._add_sample({**base,
                    'data_3w': [], 'data_iv': entry.get('data_iv', []),
                    'status': 'iv',
                })
            else:
                self._add_sample({**base,
                    'data_3w': entry.get('data_3w', []),
                    'data_iv': entry.get('data_iv', []),
                    'status':  entry.get('status', 'completed'),
                })
        # Track which session entry names are already loaded
        self._session_names = {s['name'] for s in self._samples if s.get('source') == 'session'}
        print(f"[Analysis] Loaded {len(self._samples)} samples")
        self._refresh_sidebar()

    def _auto_sync(self):
        """Called every 2 s — add new session entries and pulse the live dot."""
        is_running = self.main_win.stop_button.isEnabled()
        self._live_dot.setStyleSheet(
            "color:#3be362; font-size:10px;" if is_running else "color:#555; font-size:10px;")
        if is_running:
            self._sync_session()

    def _sync_session(self):
        """Add any new session measurements not yet in the sidebar."""
        added = 0
        for entry in self.main_win._measurement_history:
            if entry['name'] in self._session_names:
                continue
            # New entry — add it
            base = {
                'name':        entry['name'], 'source': 'session',
                'filepath':    None, 'color': self._next_color(), 'checked': True,
                'fit_results': None, 'mask_3w': set(), 'mask_iv': set(),
                'params':      entry.get('params', {}),
                'timestamp':   entry.get('timestamp'),
                'ts_data':     entry.get('ts_data'),
                'data_1w':     entry.get('data_1w', []),
            }
            if entry.get('status') == 'iv':
                self._add_sample({**base, 'data_3w': [], 'data_iv': entry.get('data_iv', []),
                                   'status': 'iv'})
            else:
                self._add_sample({**base, 'data_3w': entry.get('data_3w', []),
                                   'data_iv': entry.get('data_iv', []),
                                   'status': entry.get('status', 'completed')})
            self._session_names.add(entry['name'])
            added += 1
        if added:
            self._refresh_sidebar()

    def _add_sample(self, s):
        existing = [x['name'] for x in self._samples]
        name = s['name']
        if name in existing:
            n = 1
            while f"{name}_{n}" in existing:
                n += 1
            s['name'] = f"{name}_{n}"
        self._samples.append(s)

    # ── File loading ──────────────────────────────────────────────────────
    def _add_files(self):
        _s = load_settings()
        _start = _s.get("last_open_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load Data Files", _start,
            "CSV/Text Files (*.csv *.txt *.tsv);;All Files (*)"
        )
        if paths:
            import os as _os
            _s["last_open_dir"] = _os.path.dirname(paths[0])
            save_settings(_s)
        for path in paths:
            self._load_file(path)
        self._refresh_sidebar()

    def _load_file(self, path):
        import pandas as pd
        try:
            df = None
            for sep in [',', '\t', ';', ' ']:
                try:
                    tmp = pd.read_csv(path, sep=sep)
                    if len(tmp.columns) > 2:
                        df = tmp; break
                except Exception:
                    continue
            if df is None:
                raise ValueError("Could not parse file")

            folder = os.path.dirname(path)
            cached = self._col_cache.get(folder)
            # Only reuse a folder's cached mapping if every column it points
            # to actually exists in THIS file -- a folder can hold files of
            # different shapes (e.g. a 3w save and an IV save side by side),
            # and blindly reusing a mismatched mapping used to silently
            # produce an empty or all-zero dataset with no warning.
            if cached and all(col in df.columns for col in cached.values()):
                mapping = cached
            else:
                mapping = self._auto_detect(df) or self._auto_detect_iv(df)
            if mapping is None:
                mapping = self._col_mapping_dialog(df, path)
                if mapping is None:
                    return
            self._col_cache[folder] = mapping

            params = self._load_params_txt(path)
            if params is None:
                params = self._ask_params(path)
                if params is None:
                    # User cancelled — fall back to main-panel defaults so the
                    # file still loads; fitting will warn if values are wrong.
                    p_def = self.main_win.read_parameters()
                    params = {k: p_def.get(k, 0.0) for k in ('R', 'r', 'L', 'S')}

            data_3w = self._extract_3w(df, mapping)
            data_iv = self._extract_iv(df, mapping)
            data_1w = self._extract_1w(df)
            ts_data = self._find_ts_file(path)
            name    = os.path.splitext(os.path.basename(path))[0]
            self._add_sample({
                'name': name, 'source': 'file', 'filepath': path,
                'color': self._next_color(), 'checked': True,
                'data_3w': data_3w, 'data_iv': data_iv, 'data_1w': data_1w,
                'fit_results': None, 'mask_3w': set(), 'mask_iv': set(),
                'params': params, 'status': 'file', 'timestamp': None,
                'ts_data': ts_data,
            })
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Could not load:\n{path}\n\n{e}")

    _3W_ALIASES = {
        'frequency': ['frequency (hz)','freq (hz)','frequency','freq'],
        'current':   ['current (a)','current','i (a)'],
        'x':         ['in phase voltage (v)','x (v)','x'],
        'y':         ['out of phase voltage (v)','y (v)','y'],
        'v3w':       ['v3w_measured (v)','v3w_measured','r (v)','v3w','v3omega'],
        'v3w_calc':  ['v_3omega_calculated (v)','v3w_calc','v3omega_calc'],
        'theta':     ['theta (degree)','theta (deg)','theta','phase (deg)','phase'],
    }
    _IV_ALIASES = {
        # Unit-suffixed variants first -- these are the exact column names
        # IVDialog.save_data() itself writes ("Voltage (V)", "Current (A)",
        # "I^3 (A^3)", "V3w (V)"), so the app's own saved IV files are
        # recognized without ever needing the manual mapping dialog.
        'voltage': ['voltage (v)','voltage','v (v)','v','volt'],
        'current': ['current (a)','current','i (a)','i'],
        'i3':      ['i^3 (a^3)','i^3','i3','current^3','i³'],
        'v3w':     ['v3w (v)','v3w','v3omega'],
    }

    def _auto_detect(self, df):
        low = {c.lower().strip(): c for c in df.columns}
        mapping = {}
        for field, aliases in self._3W_ALIASES.items():
            for a in aliases:
                if a in low:
                    mapping[field] = low[a]; break
        if 'frequency' in mapping and ('v3w' in mapping or 'v3w_calc' in mapping):
            return mapping
        return None

    def _auto_detect_iv(self, df):
        """Same idea as _auto_detect but for IV-shaped files (Voltage/
        Current/V3w, no Frequency column) -- lets a standalone IV CSV be
        recognized and plotted with its real voltage values instead of
        silently defaulting every point to 0."""
        low = {c.lower().strip(): c for c in df.columns}
        mapping = {}
        for field, aliases in self._IV_ALIASES.items():
            for a in aliases:
                if a in low:
                    mapping[field] = low[a]; break
        if 'voltage' in mapping and 'current' in mapping:
            return mapping
        return None

    def _col_mapping_dialog(self, df, path):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Map Columns — {os.path.basename(path)}")
        dlg.setMinimumSize(520, 360)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"Columns found: {list(df.columns)}"))
        lay.addWidget(QLabel("Assign columns (skip = not available):"))
        cols = ['(skip)'] + list(df.columns)
        combos = {}
        form = QFormLayout()
        for field in ['frequency','current','v3w','theta','x','y']:
            cb = QComboBox(); cb.addItems(cols)
            for i,c in enumerate(cols):
                if field[:4] in c.lower():
                    cb.setCurrentIndex(i); break
            combos[field] = cb
            form.addRow(QLabel(field), cb)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() == QDialog.Accepted:
            return {f: cb.currentText() for f,cb in combos.items() if cb.currentText() != '(skip)'}
        return None

    def _load_params_txt(self, csv_path):
        p_path = csv_path.rsplit('.', 1)[0] + '_params.txt'
        if not os.path.exists(p_path):
            return None
        params = {}
        try:
            with open(p_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if ':' not in line or line.startswith('=') or line.startswith('-'):
                        continue
                    key, val = line.split(':', 1)
                    key = key.strip().lower(); val = val.strip().split()[0] if val.strip() else ''
                    try:
                        v = float(val)
                        if 'resistance (r)' in key or key == 'resistance (r)':
                            params['R'] = v
                        elif 'dr/dt' in key or 'r)' in key and 'dr' in key:
                            params['r'] = v
                        elif 'length' in key:
                            params['L'] = v
                        elif 'cross section' in key or 'section (s)' in key:
                            params['S'] = v
                        elif 'ac voltage' in key:
                            params['AC_VOLTAGE'] = v
                    except (ValueError, TypeError):
                        pass
        except Exception:
            return None
        return params if all(k in params for k in ['R','r','L','S']) else None

    def _ask_params(self, path):
        """Prompt for sample params when _params.txt not found, pre-filled from main interface."""
        p_def = self.main_win.read_parameters()
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Sample Parameters — {os.path.basename(path)}")
        dlg.setMinimumSize(400, 280)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            "No _params.txt found for this file.\n"
            "Values pre-filled from main interface — edit if different sample:"
        ))
        form = QFormLayout()
        fields = {}
        for key, label, unit in [('R','Resistance R','Ω'),('r','dR/dT  r','Ω/K'),
                                   ('L','Length L','m'),('S','Cross Section S','m²')]:
            inp = QLineEdit(str(p_def.get(key, '')))
            form.addRow(QLabel(f"{label} ({unit})"), inp)
            fields[key] = inp
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() == QDialog.Accepted:
            try:
                return {k: float(v.text()) for k,v in fields.items()}
            except ValueError:
                QMessageBox.warning(self, "Invalid", "Invalid parameter values.")
                return None
        return None

    def _extract_3w(self, df, mapping):
        rows = []
        fc = mapping.get('frequency')
        if not fc:
            return rows
        for _, row in df.iterrows():
            try:
                f     = float(row[fc])
                curr  = float(row[mapping['current']]) if 'current'  in mapping else 0.0
                x     = float(row[mapping['x']])       if 'x'        in mapping else 0.0
                y     = float(row[mapping['y']])       if 'y'        in mapping else 0.0
                v3w   = float(row[mapping['v3w']])     if 'v3w'      in mapping else 0.0
                v3wc  = float(row[mapping.get('v3w_calc','')]) if 'v3w_calc' in mapping else v3w
                theta = float(row[mapping['theta']])   if 'theta'    in mapping else 0.0
                rows.append([f, curr, x, y, v3w, v3wc, theta])
            except (ValueError, KeyError):
                continue
        return rows

    def _extract_iv(self, df, mapping):
        rows = []
        for _, row in df.iterrows():
            try:
                v   = float(row[mapping['voltage']]) if 'voltage' in mapping else 0.0
                i   = float(row[mapping['current']]) if 'current' in mapping else 0.0
                i3  = i**3
                v3w = float(row[mapping['v3w']])     if 'v3w'    in mapping else 0.0
                rows.append([v, i, i3, v3w])
            except (ValueError, KeyError):
                continue
        return rows

    def _extract_1w(self, df):
        """Extract [freq, R1w, theta] rows from a 1ω frequency-dependent CSV."""
        cols_lower = {c.lower().strip(): c for c in df.columns}
        freq_col = next((cols_lower[k] for k in cols_lower
                         if 'frequency' in k or 'freq' in k), None)
        r1w_col  = next((cols_lower[k] for k in cols_lower
                         if 'r_1w' in k or 'r1w' in k), None)
        th_col   = next((cols_lower[k] for k in cols_lower
                         if 'theta' in k), None)
        if not (freq_col and r1w_col):
            return []
        rows = []
        for _, row in df.iterrows():
            try:
                f  = float(row[freq_col])
                r  = float(row[r1w_col])
                th = float(row[th_col]) if th_col else 0.0
                rows.append([f, r, th])
            except (ValueError, KeyError):
                continue
        return rows

    # ── Sidebar ───────────────────────────────────────────────────────────
    def _refresh_sidebar(self):
        self.sample_list.blockSignals(True)
        self.sample_list.clear()
        for i, s in enumerate(self._samples):
            ts  = s.get('timestamp')
            tstr = ts.strftime('%H:%M') if ts else (os.path.basename(s.get('filepath') or '')[:14])
            st = s.get('status','')
            icon = '✓' if st=='completed' else '⚠' if st=='interrupted' else '◆' if st=='iv' else '📂'
            text = f"{icon}  {s['name']}  [{tstr}]"
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if s['checked'] else Qt.Unchecked)
            item.setForeground(QColor(s['color']))
            item.setData(Qt.UserRole, i)
            item.setToolTip(f"Source: {s.get('filepath') or 'session'}\nParams: R={s['params'].get('R','?')} Ω  L={s['params'].get('L','?')} m")
            self.sample_list.addItem(item)
        self.sample_list.blockSignals(False)

    def _on_check_changed(self, item):
        idx = item.data(Qt.UserRole)
        if idx is not None and 0 <= idx < len(self._samples):
            self._samples[idx]['checked'] = (item.checkState() == Qt.Checked)

    def _check_all(self, state):
        for i in range(self.sample_list.count()):
            self.sample_list.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)

    def _clear_selected(self):
        to_rm = [i for i,s in enumerate(self._samples) if s['checked']]
        for i in reversed(to_rm):
            self._samples.pop(i)
        self._refresh_sidebar()

    def _clear_all(self):
        self._samples.clear(); self._color_idx = 0
        self._refresh_sidebar()

    def _checked(self):
        return [s for s in self._samples if s['checked']]

    # ── Param grouping ────────────────────────────────────────────────────
    def _param_key(self, s):
        """Return a hashable key from R, r, L, S — used to group same-sample files."""
        p = s.get('params', {})
        try:
            return (float(p['R']), float(p['r']), float(p['L']), float(p['S']))
        except (KeyError, TypeError, ValueError):
            return id(s)  # ungroupable — treat as unique

    def _group_by_params(self, samples):
        """
        Returns list of groups. Each group is a list of samples with identical params.
        Groups with >1 sample are same-sample files at different freq ranges.
        Order within a group preserves insertion order.
        """
        from collections import OrderedDict
        groups = OrderedDict()
        for s in samples:
            key = self._param_key(s)
            groups.setdefault(key, []).append(s)
        return list(groups.values())

    def _combined_data(self, group, data_key):
        """Concatenate masked data from all samples in a group (sorted by frequency/i3)."""
        import numpy as np
        parts = [self._masked(s, data_key) for s in group]
        parts = [p for p in parts if len(p)]
        if not parts:
            ncols = 7 if data_key == 'data_3w' else 4
            return np.empty((0, ncols))
        combined = np.vstack(parts)
        sort_col = 0  # frequency for 3w, I³ col=2 for IV
        if data_key == 'data_iv':
            sort_col = 2
        idx = np.argsort(combined[:, sort_col])
        return combined[idx]

    def _group_label(self, group):
        """Compact legend label for a group (file names joined)."""
        names = [s['name'] for s in group]
        if len(names) == 1:
            return names[0]
        # common prefix, then list suffixes
        prefix = os.path.commonprefix(names)
        if len(prefix) > 4:
            suffixes = [n[len(prefix):] or '…' for n in names]
            return f"{prefix}[{','.join(suffixes)}]"
        return ' + '.join(names)

    # ── Masked data helper ────────────────────────────────────────────────
    def _masked(self, s, key):
        import numpy as np
        data = s.get(key, [])
        mask = s.get('mask_' + key.split('_')[1], set())
        if not data:
            return np.empty((0, 7 if key=='data_3w' else 4))
        d = np.array(data)
        keep = [i for i in range(len(d)) if i not in mask]
        return d[keep] if keep else np.empty((0, d.shape[1]))

    # ── Plotting ──────────────────────────────────────────────────────────
    def _plot(self, tab, mode):
        try:
            samples = self._checked() if mode == 'selected' else self._samples
            print(f"[Analysis._plot] tab={tab}, mode={mode}, total_samples={len(self._samples)}, checked={len(self._checked())}")
            for i, s in enumerate(samples):
                n_3w = len(s.get('data_3w', []))
                n_iv = len(s.get('data_iv', []))
                print(f"  Sample {i}: {s['name']} n_3w={n_3w} n_iv={n_iv}")
            if tab == 'ts':
                filtered = [s for s in samples if s.get('ts_data')]
            else:
                filtered = [s for s in samples if s.get('data_3w') or s.get('data_iv')]
            samples = filtered
            print(f"[Analysis._plot] After filtering: {len(samples)} samples with data")
            if not samples:
                msg = ("No time series data available. Load files with matching Time series_*.csv "
                       "or perform a measurement first.") if tab == 'ts' else "No samples with data to plot."
                QMessageBox.information(self, "No data", msg)
                return
            plot_func = {
                'iv':       self._plot_iv,
                'ts':       self._plot_ts,
                'v3w':      self._plot_v3w,
                'global':   lambda ss: self._plot_fit(ss, 'global'),
                'phase':    lambda ss: self._plot_fit(ss, 'phase'),
                'accurate': lambda ss: self._plot_fit(ss, 'accurate'),
            }[tab]
            plot_func(samples)
            print(f"[Analysis._plot] Plot completed successfully")
        except Exception as e:
            import traceback
            print(f"[Analysis._plot] Error: {e}")
            print(traceback.format_exc())
            QMessageBox.critical(self, "Plot Error",
                f"Error plotting data:\n{str(e)}\n\n{traceback.format_exc()}")

    def _plot_iv(self, samples):
        import numpy as np
        fig = self.fig_iv
        fig.clear()
        ax = fig.add_subplot(111)
        plotted_any = False
        groups = self._group_by_params(samples)
        for group in groups:
            try:
                # Each file in the group gets its own color scatter
                for s in group:
                    d = self._masked(s, 'data_iv')
                    if len(d) == 0:
                        continue
                    plotted_any = True
                    i3, v3w = d[:,2], d[:,3]
                    ax.scatter(i3, v3w, s=25, alpha=0.7, color=s['color'], label=s['name'], zorder=3)
                # One linear fit using ALL combined data in the group
                combined = self._combined_data(group, 'data_iv')
                if len(combined) > 1:
                    i3c, v3wc = combined[:,2], combined[:,3]
                    c = np.polyfit(i3c, v3wc, 1)
                    xf = np.linspace(i3c.min(), i3c.max(), 200)
                    # Use first sample's color for the fit line; dashed
                    ax.plot(xf, np.polyval(c, xf), '--', color=group[0]['color'], lw=2,
                            label=f"{self._group_label(group)} fit" if len(group) > 1 else None)
            except Exception as e:
                print(f"Error plotting IV group: {e}")
        if plotted_any:
            ax.set_xlabel(r"$I^3\ (\mathrm{A}^3)$", fontsize=10)
            ax.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$", fontsize=10)
            ax.set_title(r"IV: $V_{3\omega}$ vs $I^3$", fontsize=11)
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
        else:
            ax.text(0.5, 0.5, "No IV data to plot", ha='center', va='center',
                   transform=ax.transAxes, fontsize=12, color='white')
        fig.tight_layout()
        self.canvas_iv.draw()
        self._attach_mask('iv', ax)

    def _plot_v3w(self, samples):
        import numpy as np
        fig = self.fig_v3w
        fig.clear()
        ax1 = fig.add_subplot(211)
        ax2 = fig.add_subplot(212)
        plotted_any = False
        groups = self._group_by_params(samples)
        for group in groups:
            try:
                for s in group:
                    d = self._masked(s, 'data_3w')
                    if len(d) == 0:
                        continue
                    plotted_any = True
                    f, v3w, theta = d[:,0], d[:,4], d[:,6]
                    ax1.scatter(f, v3w,   s=20, alpha=0.7, color=s['color'], label=s['name'])
                    ax2.scatter(f, theta, s=20, alpha=0.7, color=s['color'], label=s['name'])
            except Exception as e:
                print(f"Error plotting V3w group: {e}")
        if plotted_any:
            ax1.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$", fontsize=10)
            ax1.set_title(r"$V_{3\omega}$ and $\theta$ vs Frequency", fontsize=11)
            ax1.legend(fontsize=8)
            ax1.grid(True, alpha=0.3)
            ax2.set_xlabel("Frequency (Hz)", fontsize=10)
            ax2.set_ylabel(r"$\theta\ (°)$", fontsize=10)
            ax2.legend(fontsize=8)
            ax2.grid(True, alpha=0.3)
        else:
            ax1.text(0.5, 0.5, "No 3ω data to plot", ha='center', va='center',
                    transform=ax1.transAxes, fontsize=12, color='white')
        fig.tight_layout()
        self.canvas_v3w.draw()
        self._attach_mask('v3w', ax1)

    def _plot_fit(self, samples, fit_type):
        import numpy as np
        fig = getattr(self, f'fig_{fit_type}')
        fig.clear()
        ax = fig.add_subplot(111)
        plotted_any = False
        groups = self._group_by_params(samples)

        for group in groups:
            try:
                # Plot each file in the group with its own color
                for s in group:
                    d = self._masked(s, 'data_3w')
                    if len(d) == 0:
                        continue
                    plotted_any = True
                    f = d[:,0]
                    if fit_type == 'phase':
                        y = np.abs(np.tan(np.deg2rad(d[:,6])))
                        ax.scatter(f, y, s=20, alpha=0.7, color=s['color'], label=s['name'])
                    else:
                        ax.scatter(f, d[:,4], s=20, alpha=0.7, color=s['color'], label=s['name'])

                # Draw ONE fit curve per group (stored on first sample of group)
                rep = group[0]  # representative sample holds group fit result
                fr = rep.get('fit_results') or {}
                curve = fr.get(f'{fit_type}_curve')
                if curve:
                    fx, fy = np.array(curve[0]), np.array(curve[1])
                    if fit_type == 'phase':
                        fy = np.abs(fy)  # core stores -tan(phi); display as |tan(phi)|
                    grp_lbl = self._group_label(group)
                    if fit_type != 'phase':
                        k = (fr.get(fit_type) or [None])[0]
                        grp_lbl = f"{grp_lbl}  k={k:.4f}" if k else grp_lbl
                    ax.plot(fx, fy, '-', color='white', lw=2.5, alpha=0.9,
                            label=f"Fit: {grp_lbl}")
            except Exception as e:
                print(f"Error plotting {fit_type} group: {e}")

        if plotted_any:
            if fit_type == 'phase':
                ax.set_ylabel(r"$|\tan(\varphi)|$", fontsize=10)
                ax.set_title(r"Phase Fit: $|\tan(\varphi)|$ vs Frequency", fontsize=11)
            else:
                ax.set_ylabel(r"$V_{3\omega}\ (\mathrm{V})$", fontsize=10)
                ax.set_title(f"{'Global' if fit_type=='global' else 'Accurate'} Fit: "
                             r"$V_{3\omega}$ vs Frequency", fontsize=11)
            ax.set_xlabel("Frequency (Hz)", fontsize=10)
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
        else:
            ax.text(0.5, 0.5, f"No {fit_type} data to plot", ha='center', va='center',
                   transform=ax.transAxes, fontsize=12, color='white')
        fig.tight_layout()
        getattr(self, f'canvas_{fit_type}').draw()
        self._attach_mask(fit_type, ax)

    # ── Time series plotting ──────────────────────────────────────────────
    def _get_ts_data(self, s):
        """Return ts_data dict or None."""
        return s.get('ts_data') or None

    def _ts_filtered(self, s):
        """Return ts arrays filtered by current freq/time controls."""
        import numpy as np
        ts = self._get_ts_data(s)
        if ts is None or not ts.get('t'):
            return None
        t     = np.array(ts['t'])
        freq  = np.array(ts.get('freq', [0]*len(t)))
        r     = np.array(ts.get('r',    [0]*len(t)))
        theta = np.array(ts.get('theta',[0]*len(t)))
        I     = np.array(ts.get('I',    [0]*len(t)))

        # Frequency filter
        sel_freq = self.ts_freq_cb.currentText()
        if sel_freq != "All frequencies":
            try:
                fval = float(sel_freq.split()[0])
                mask = np.isclose(freq, fval, rtol=0.05)
                t, freq, r, theta, I = t[mask], freq[mask], r[mask], theta[mask], I[mask]
            except ValueError:
                pass

        # Time range filter
        try:
            tmin = float(self.ts_tmin.text()) if self.ts_tmin.text() else t.min()
            tmax = float(self.ts_tmax.text()) if self.ts_tmax.text() else t.max()
            mask = (t >= tmin) & (t <= tmax)
            t, freq, r, theta, I = t[mask], freq[mask], r[mask], theta[mask], I[mask]
        except (ValueError, Exception):
            pass

        return {'t': t, 'freq': freq, 'r': r, 'theta': theta, 'I': I}

    def _refresh_ts_freq_filter(self, samples):
        """Populate the frequency filter combobox from loaded samples."""
        import numpy as np
        freqs = set()
        for s in samples:
            ts = self._get_ts_data(s)
            if ts and ts.get('freq'):
                for f in ts['freq']:
                    if f and not np.isnan(float(f)):
                        freqs.add(round(float(f), 4))
        self.ts_freq_cb.blockSignals(True)
        self.ts_freq_cb.clear()
        self.ts_freq_cb.addItem("All frequencies")
        for fv in sorted(freqs):
            self.ts_freq_cb.addItem(f"{fv} Hz")
        self.ts_freq_cb.blockSignals(False)

    def _plot_ts(self, samples):
        import numpy as np
        # Filter to samples that actually have ts_data
        samples = [s for s in samples if self._get_ts_data(s)]
        if not samples:
            fig = self.fig_ts; fig.clear()
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "No time series data available\n(session measurements or files with Time series_*.csv)",
                   ha='center', va='center', transform=ax.transAxes, color='#888', fontsize=11)
            self.canvas_ts.draw()
            return

        self._refresh_ts_freq_filter(samples)
        groups = self._group_by_params(samples)

        fig = self.fig_ts; fig.clear()
        ax1 = fig.add_subplot(311)
        ax2 = fig.add_subplot(312, sharex=ax1)
        ax3 = fig.add_subplot(313, sharex=ax1)
        plotted_any = False

        for group in groups:
            for s in group:
                d = self._ts_filtered(s)
                if d is None or len(d['t']) == 0:
                    continue
                plotted_any = True
                t, r, theta, I = d['t'], d['r'], d['theta'], d['I']
                ax1.plot(t, r,     color=s['color'], lw=1, alpha=0.8, label=s['name'])
                ax2.plot(t, theta, color=s['color'], lw=1, alpha=0.8, label=s['name'])
                ax3.plot(t, I,     color=s['color'], lw=1, alpha=0.8, label=s['name'])

        if plotted_any:
            ax1.set_ylabel(r"$V_{3\omega}$ (V)", fontsize=9)
            ax1.legend(fontsize=7, loc='upper right'); ax1.grid(True, alpha=0.3)
            ax2.set_ylabel(r"$\theta$ (°)", fontsize=9)
            ax2.legend(fontsize=7, loc='upper right'); ax2.grid(True, alpha=0.3)
            ax3.set_ylabel("I (A)", fontsize=9)
            ax3.set_xlabel("Time (s)", fontsize=9)
            ax3.legend(fontsize=7, loc='upper right'); ax3.grid(True, alpha=0.3)
            fig.suptitle("Time Series Data", fontsize=11)
        else:
            ax1.text(0.5, 0.5, "No data after filtering", ha='center', va='center',
                    transform=ax1.transAxes, color='#888', fontsize=11)

        fig.tight_layout()
        self.canvas_ts.draw()
        self._setup_ts_span_selector(ax1)

    def _setup_ts_span_selector(self, ax):
        """Attach a horizontal SpanSelector to the top axes to set FT time range."""
        from matplotlib.widgets import SpanSelector
        if hasattr(self, '_ts_span_sel') and self._ts_span_sel:
            try: self._ts_span_sel.set_active(False)
            except Exception: pass

        def on_span(tmin, tmax):
            self.ft_tmin.setText(f"{tmin:.4g}")
            self.ft_tmax.setText(f"{tmax:.4g}")
            self.ft_hint_lbl.setText(f"FT range set: {tmin:.4g} – {tmax:.4g} s  (click ▶ Compute FT)")
            self.ft_hint_lbl.setStyleSheet("color:#4af4a8;font-size:10px;padding:2px 4px;")

        self._ts_span_sel = SpanSelector(
            ax, on_span, 'horizontal', useblit=True,
            props=dict(alpha=0.25, facecolor='#818cf8'),
            interactive=True, drag_from_anywhere=True
        )

    def _compute_ft(self):
        """Compute FFT of selected channel over selected time range."""
        import numpy as np
        samples = [s for s in (self._checked() or self._samples) if self._get_ts_data(s)]
        if not samples:
            QMessageBox.warning(self, "No data", "No time series data available.")
            return

        channel_map = {"V₃ω (r)": 'r', "θ (theta)": 'theta', "I (current)": 'I'}
        ch_key = channel_map.get(self.ft_channel_cb.currentText(), 'r')

        try:
            t_min = float(self.ft_tmin.text()) if self.ft_tmin.text() else None
            t_max = float(self.ft_tmax.text()) if self.ft_tmax.text() else None
        except ValueError:
            t_min = t_max = None

        try:
            ref_3f = float(self.ft_ref_inp.text()) if self.ft_ref_inp.text() else None
        except ValueError:
            ref_3f = None

        fig = self.fig_ts_ft; fig.clear()
        ax  = fig.add_subplot(111)
        groups = self._group_by_params(samples)
        plotted_any = False

        for group in groups:
            for s in group:
                ts = self._get_ts_data(s)
                if not ts or not ts.get('t'):
                    continue
                t     = np.array(ts['t'])
                sig   = np.array(ts.get(ch_key, []))
                if len(t) == 0 or len(sig) == 0:
                    continue

                # Time range selection
                if t_min is not None and t_max is not None:
                    mask = (t >= t_min) & (t <= t_max)
                else:
                    mask = np.ones(len(t), dtype=bool)
                t_sel   = t[mask]
                sig_sel = sig[mask]
                if len(t_sel) < 8:
                    continue

                # Estimate dt (median interval for robustness)
                dt = np.median(np.diff(t_sel))
                if dt <= 0:
                    continue

                # Compute FFT
                N   = len(sig_sel)
                win = np.hanning(N)
                fft_mag = np.abs(np.fft.rfft(sig_sel * win)) * 2 / N
                freqs   = np.fft.rfftfreq(N, d=dt)

                # Skip DC
                freqs   = freqs[1:]
                fft_mag = fft_mag[1:]

                ax.semilogy(freqs, fft_mag, color=s['color'], lw=1.2,
                            alpha=0.85, label=s['name'])

                # Mark dominant peaks (top 5)
                from scipy.signal import find_peaks
                peaks, _ = find_peaks(fft_mag, height=fft_mag.max()*0.05, distance=3)
                top = sorted(peaks, key=lambda p: fft_mag[p], reverse=True)[:5]
                for p in top:
                    ax.annotate(f"{freqs[p]:.3g} Hz",
                               xy=(freqs[p], fft_mag[p]),
                               xytext=(5, 5), textcoords='offset points',
                               fontsize=7, color=s['color'], alpha=0.9)
                    ax.plot(freqs[p], fft_mag[p], 'o', color=s['color'], ms=5)

                plotted_any = True

        # Reference line at 3ω
        if ref_3f is not None:
            ax.axvline(ref_3f, color='#ff9f43', lw=1.5, ls='--',
                      label=f"3ω ref ({ref_3f:.3g} Hz)")
            ax.text(ref_3f, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1,
                   f" 3ω\n {ref_3f:.3g} Hz",
                   color='#ff9f43', fontsize=8, va='top')

        ch_labels = {'r': r"$V_{3\omega}$", 'theta': r"$\theta$", 'I': "I"}
        ax.set_xlabel("Frequency (Hz)", fontsize=10)
        ax.set_ylabel(f"|FFT| of {ch_labels.get(ch_key, ch_key)}", fontsize=10)
        ax.set_title(f"Frequency Spectrum — {ch_labels.get(ch_key, ch_key)}"
                     + (f"  |  t = {t_min:.3g}–{t_max:.3g} s" if t_min is not None else ""),
                     fontsize=11)
        if plotted_any:
            ax.legend(fontsize=8)
        else:
            ax.text(0.5, 0.5, "No data in selected range",
                   ha='center', va='center', transform=ax.transAxes, color='#888')
        ax.grid(True, alpha=0.3, which='both')
        fig.tight_layout()
        self.canvas_ts_ft.draw()

    def _clear_canvas(self, name):
        fig = getattr(self, f'fig_{name}', None)
        if not fig: return
        fig.clear()
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "Cleared", ha='center', va='center',
                transform=ax.transAxes, color='#888')
        getattr(self, f'canvas_{name}').draw()

    # ── Masking ───────────────────────────────────────────────────────────
    def _attach_mask(self, tab_name, ax):
        from matplotlib.widgets import RectangleSelector
        if self._rect_sel:
            try: self._rect_sel.set_active(False)
            except Exception: pass
        self._cur_mask_tab = tab_name
        self._cur_mask_ax  = ax

        # Ensure NavigationToolbar exists for this canvas so it records the
        # initial home position — ↺ Reset can then call toolbar.home() reliably.
        canvas = getattr(self, f'canvas_{tab_name}', None)
        if canvas and (not hasattr(canvas, '_nav_toolbar') or canvas._nav_toolbar is None):
            try:
                canvas._nav_toolbar = NavigationToolbar(canvas, self)
                canvas._nav_toolbar.hide()
                canvas._nav_toolbar.push_current()  # save initial view as home
            except Exception:
                pass

        def on_sel(ec, er):
            if not self.mask_btn.isChecked(): return
            x1,x2 = sorted([ec.xdata, er.xdata])
            y1,y2 = sorted([ec.ydata, er.ydata])
            if x1 is None: return
            self._mask_action(tab_name, x1, x2, y1, y2)

        self._rect_sel = RectangleSelector(
            ax, on_sel, useblit=True, button=[1],
            minspanx=5, minspany=5, spancoords='pixels', interactive=False,
            props=dict(facecolor='red', edgecolor='red', alpha=0.2, fill=True)
        )
        self._rect_sel.set_active(self.mask_btn.isChecked())

    def _mask_action(self, tab_name, x1, x2, y1, y2):
        dlg = QDialog(self)
        dlg.setWindowTitle("Region Action")
        dlg.setFixedSize(300, 120)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"x=[{x1:.3g}, {x2:.3g}]   y=[{y1:.3g}, {y2:.3g}]"))
        row = QHBoxLayout()
        zb = QPushButton("Zoom to Region")
        mb = QPushButton("Mask Data")
        cb = QPushButton("Cancel")
        zb.clicked.connect(lambda: (self._zoom_region(x1,x2,y1,y2), dlg.accept()))
        mb.clicked.connect(lambda: (self._apply_mask(tab_name, x1, x2), dlg.accept()))
        cb.clicked.connect(dlg.reject)
        for b in [zb, mb, cb]: row.addWidget(b)
        lay.addLayout(row)
        dlg.exec()

    def _zoom_region(self, x1, x2, y1, y2):
        self.vxmin.setText(f"{x1:.4g}"); self.vxmax.setText(f"{x2:.4g}")
        self.vymin.setText(f"{y1:.4g}"); self.vymax.setText(f"{y2:.4g}")
        self._apply_view()

    def _apply_mask(self, tab_name, xmin, xmax):
        import numpy as np
        targets = self._samples if self.mask_all_cb.isChecked() else self._checked()
        n_masked = 0
        for s in targets:
            if tab_name == 'iv':
                d = np.array(s['data_iv']) if s['data_iv'] else None
                if d is not None and len(d):
                    for idx, val in enumerate(d[:,2]):
                        if xmin <= val <= xmax:
                            s['mask_iv'].add(idx); n_masked += 1
            else:
                d = np.array(s['data_3w']) if s['data_3w'] else None
                if d is not None and len(d):
                    for idx, val in enumerate(d[:,0]):
                        if xmin <= val <= xmax:
                            s['mask_3w'].add(idx); n_masked += 1
        QMessageBox.information(self, "Masked",
            f"Masked {n_masked} point(s) in range [{xmin:.3g}, {xmax:.3g}].\n"
            "Re-plot to see updated data.")

    # ── Toolbar tools ─────────────────────────────────────────────────────
    def _get_nav(self, canvas):
        """Return (creating if needed) a hidden NavigationToolbar for canvas."""
        if not hasattr(canvas, '_nav_toolbar') or canvas._nav_toolbar is None:
            canvas._nav_toolbar = NavigationToolbar(canvas, self)
            canvas._nav_toolbar.hide()
        return canvas._nav_toolbar

    def _deactivate_nav(self, canvas):
        """Ensure zoom and pan are both OFF on a canvas toolbar."""
        try:
            tb = self._get_nav(canvas)
            mode = tb.mode.name if hasattr(tb.mode, 'name') else str(tb.mode)
            if mode == 'ZOOM':
                tb.zoom()   # toggle off
            elif mode == 'PAN':
                tb.pan()    # toggle off
        except Exception:
            pass

    def _tool_toggle(self, tool, on):
        # Uncheck every OTHER button without retriggering their toggled signals
        for t, btn in [('zoom', self.zoom_btn), ('pan', self.pan_btn), ('mask', self.mask_btn)]:
            if t != tool and btn.isChecked():
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)

        canvas = self._active_canvas()
        if not canvas:
            return

        # Always deactivate the rect selector first so it never fights the toolbar
        if self._rect_sel:
            try:
                self._rect_sel.set_active(False)
            except Exception:
                pass

        if tool == 'mask':
            self._deactivate_nav(canvas)   # kill zoom/pan before enabling mask
            if on and self._rect_sel:
                self._rect_sel.set_active(True)

        elif tool in ('zoom', 'pan'):
            # Reset toolbar to neutral first, then activate the chosen mode
            self._deactivate_nav(canvas)
            if on:
                try:
                    getattr(self._get_nav(canvas), tool)()
                except Exception:
                    pass

        try:
            canvas.draw_idle()
        except Exception:
            pass

    def _active_canvas(self):
        names = ['iv','ts','v3w','global','phase','accurate','compare']
        idx = self.tabs.currentIndex()
        n   = names[idx] if idx < len(names) else None
        return getattr(self, f'canvas_{n}', None) if n else None

    # ── View range ────────────────────────────────────────────────────────
    def _apply_view(self):
        canvas = self._active_canvas()
        if not canvas: return
        for ax in canvas.figure.axes:
            try:
                if self.vxmin.text() and self.vxmax.text():
                    ax.set_xlim(float(self.vxmin.text()), float(self.vxmax.text()))
                if self.vymin.text() and self.vymax.text():
                    ax.set_ylim(float(self.vymin.text()), float(self.vymax.text()))
            except ValueError:
                pass
        canvas.draw()

    def _reset_view(self):
        canvas = self._active_canvas()
        if not canvas:
            return
        # Try NavigationToolbar home first (restores original view from history)
        try:
            if not hasattr(canvas, '_nav_toolbar') or canvas._nav_toolbar is None:
                canvas._nav_toolbar = NavigationToolbar(canvas, self)
                canvas._nav_toolbar.hide()
            canvas._nav_toolbar.home()
        except Exception:
            # Fallback: relim + autoscale from actual data extents
            for ax in canvas.figure.axes:
                ax.relim()
                ax.autoscale_view()
            canvas.draw()
        # Clear the manual range input boxes
        for inp in [self.vxmin, self.vxmax, self.vymin, self.vymax]:
            inp.clear()

    # ── Fitting ───────────────────────────────────────────────────────────
    def _check_params_consistency(self, samples):
        """Return True if all samples have same params, else show warning."""
        if len(samples) <= 1:
            return True
        def _round(v, n=4):
            return round(float(v), n) if v else None
        ref = {k: _round(samples[0]['params'].get(k)) for k in self._PARAM_KEYS}
        diff = [s['name'] for s in samples[1:] if
                any(_round(s['params'].get(k)) != ref[k] for k in self._PARAM_KEYS)]
        if diff:
            QMessageBox.warning(self, "Different Parameters",
                f"The following samples have different physical parameters "
                f"(R, r, L, S) from the first sample:\n\n{', '.join(diff)}\n\n"
                "Each sample will be fitted separately using its own parameters.")
            return False
        return True

    def _get_fit_range(self, sample=None):
        if self.same_range_cb.isChecked():
            try:
                fm = float(self.fmin_inp.text()) if self.fmin_inp.text() else None
                fx = float(self.fmax_inp.text()) if self.fmax_inp.text() else None
                return fm, fx
            except ValueError:
                return None, None
        return None, None

    def _compute_A(self, sample):
        import numpy as np
        p = sample.get('params', {})
        try:
            return (4 * p['L'] * p['R'] * p['r']) / (np.pi**4 * p['S'])
        except (KeyError, TypeError, ZeroDivisionError):
            return None

    def _tab_status(self, fit_type, msg):
        """Write a status/warning line to the results panel for fit_type."""
        lbl = getattr(self, f'tbl_{fit_type}', None)
        if lbl is not None:
            lbl.setPlainText(msg)

    def _fit_group(self, group, fit_type, f_min, f_max):
        """
        Fit combined data from all samples in a group (same params = same sample).
        Stores results on group[0] (representative). All samples in group share
        the same fit_results dict reference so the plot can find it from any member.
        """
        import numpy as np
        core = self.main_win.core
        A = self._compute_A(group[0])
        if A is None:
            names = ', '.join(s['name'] for s in group)
            self._tab_status(fit_type,
                f"⚠  Missing sample parameters (R / r / L / S) for:\n"
                f"   {names}\n\n"
                f"Right-click the sample in the sidebar → Edit Params,\n"
                f"or reload the file alongside its _params.txt.")
            return

        # Combine ALL masked data from every file in the group
        combined = self._combined_data(group, 'data_3w').tolist()
        if not combined:
            return

        blank = {
            'global': None, 'global_curve': None,
            'phase':  None, 'phase_curve':  None, 'phase_data': None,
            'accurate': None, 'accurate_curve': None,
        }
        # Initialise on rep if not present
        rep = group[0]
        if not rep.get('fit_results'):
            rep['fit_results'] = dict(blank)

        def _smooth_v3w(f_min_c, f_max_c, I_mean, k, gm):
            """Evaluate the model at 300 log-spaced points → smooth curve."""
            ff = np.logspace(np.log10(max(f_min_c, 1e-9)), np.log10(f_max_c), 300)
            vv = (A * I_mean**3) / (k * np.sqrt(1 + (4 * np.pi * ff * gm)**2))
            return list(ff), list(vv)

        try:
            d_arr  = np.array(combined)
            fc_min = f_min if f_min is not None else float(d_arr[:, 0].min())
            fc_max = f_max if f_max is not None else float(d_arr[:, 0].max())
            mask_r = (d_arr[:, 0] >= fc_min) & (d_arr[:, 0] <= fc_max)
            I_mean = float(np.mean(d_arr[mask_r, 1])) if mask_r.any() else float(np.mean(d_arr[:, 1]))

            if fit_type in ('global', 'accurate'):
                k, gm, ke, gme, _, _, _ = core.fit_3omega_fixed_A(
                    combined, A, f_min=fc_min, f_max=fc_max)
                rep['fit_results']['global']       = (k, gm, ke, gme)
                rep['fit_results']['global_curve'] = _smooth_v3w(fc_min, fc_max, I_mean, k, gm)

            if fit_type in ('phase', 'accurate'):
                gp, gpe, fs, tp, sl, ic = core.phase_fit(
                    combined, f_min=fc_min, f_max=fc_max)
                rep['fit_results']['phase']      = (gp, gpe)
                rep['fit_results']['phase_data'] = (list(fs), list(tp))
                # 300 log-spaced points for smooth phase line
                f_ph = np.logspace(np.log10(max(fc_min, 1e-9)), np.log10(fc_max), 300)
                rep['fit_results']['phase_curve'] = (list(f_ph), list(sl * f_ph + ic))

                if fit_type == 'accurate':
                    ka, kae, _, _, _ = core.fit_3omega_fixed_A_gamma(
                        combined, A, f_min=fc_min, f_max=fc_max, gamma=gp)
                    rep['fit_results']['accurate']       = (ka, kae)
                    rep['fit_results']['accurate_curve'] = _smooth_v3w(fc_min, fc_max, I_mean, ka, gp)

            # Share the same fit_results object with every other member so
            # _plot_fit can find it regardless of which sample it looks at.
            for s in group[1:]:
                s['fit_results'] = rep['fit_results']

        except Exception as e:
            import traceback
            print(f"  Fit error [group {self._group_label(group)}]: {e}")
            print(traceback.format_exc())

    def _range_warning(self):
        """Return a note string when same-range is checked but fields are empty."""
        if self.same_range_cb.isChecked():
            fmin_empty = not self.fmin_inp.text().strip()
            fmax_empty = not self.fmax_inp.text().strip()
            if fmin_empty or fmax_empty:
                missing = []
                if fmin_empty: missing.append("f min")
                if fmax_empty: missing.append("f max")
                return (f"⚠  Frequency range ({', '.join(missing)}) not specified — "
                        f"fitted using the full data range.\n\n")
        return ""

    def _fit_selected(self, fit_type):
        samples = [s for s in self._checked() if s.get('data_3w')]
        if not samples:
            QMessageBox.warning(self, "No data", "No checked samples with 3ω data.")
            return
        fm, fx = self._get_fit_range()
        range_note = self._range_warning()
        groups = self._group_by_params(samples)
        diff_groups = [g for g in groups if len(g) > 1]
        if diff_groups:
            names = [self._group_label(g) for g in diff_groups]
            QMessageBox.information(self, "Group Fit",
                f"Combining data within {len(diff_groups)} same-parameter group(s) "
                f"before fitting:\n\n" + "\n".join(f"  • {n}" for n in names))
        for group in groups:
            self._fit_group(group, fit_type, fm, fx)
        self._plot_fit(samples, fit_type)
        self._update_table(fit_type, groups, prefix=range_note)

    def _fit_all(self, fit_type):
        samples = [s for s in self._samples if s.get('data_3w')]
        if not samples:
            QMessageBox.warning(self, "No data", "No samples with 3ω data.")
            return
        fm, fx = self._get_fit_range()
        range_note = self._range_warning()
        groups = self._group_by_params(samples)
        for group in groups:
            self._fit_group(group, fit_type, fm, fx)
        self._plot_fit(samples, fit_type)
        self._update_table(fit_type, groups, prefix=range_note)

    def _fit_all_for_compare(self):
        samples = [s for s in self._checked() if s.get('data_3w')]
        if not samples:
            QMessageBox.warning(self, "No data", "No checked samples with 3ω data.")
            return
        fm, fx = self._get_fit_range()
        groups = self._group_by_params(samples)
        for group in groups:
            for ft in ['global', 'phase', 'accurate']:
                self._fit_group(group, ft, fm, fx)
        self._plot_compare()

    def _update_table(self, fit_type, groups, prefix=""):
        """groups is a list of lists (output of _group_by_params).
        Each group has ONE fit result (on group[0]). Show one row per group."""
        import numpy as np
        lbl = getattr(self, f'tbl_{fit_type}', None)
        if not lbl:
            return
        # Accept flat list too (for backwards compat)
        if groups and not isinstance(groups[0], list):
            groups = [[s] for s in groups]
        fitted_groups = [g for g in groups
                         if g[0].get('fit_results') and g[0]['fit_results'].get(fit_type)]
        if not fitted_groups:
            # Preserve any warning already written by _tab_status (e.g. missing params)
            existing = lbl.toPlainText()
            if existing and existing != "No fit results yet — click Fit Selected or Fit All":
                if prefix:
                    lbl.setPlainText(prefix + existing)
            else:
                lbl.setPlainText(prefix + "No fit results")
            return

        lines = [f"{'Group / Sample':<28} {'Result'}", '─'*70]
        k_vals, g_vals = [], []
        for group in fitted_groups:
            rep  = group[0]
            fr   = rep['fit_results']
            name = self._group_label(group)
            files = f"  ({len(group)} files)" if len(group) > 1 else ""
            if fit_type == 'global':
                k, gm, ke, gme = fr['global']
                lines.append(f"{name[:26]:<28}{files}")
                lines.append(f"  {'k':<6} = {k:.5f} ± {ke:.5f}  W m⁻¹ K⁻¹")
                lines.append(f"  {'γ':<6} = {gm:.5f} ± {gme:.5f}  s⁻¹")
                k_vals.append(k); g_vals.append(gm)
            elif fit_type == 'phase':
                gp, gpe = fr['phase']
                lines.append(f"{name[:26]:<28}{files}")
                lines.append(f"  {'γ':<6} = {gp:.5f} ± {gpe:.5f}  s⁻¹")
                g_vals.append(gp)
            elif fit_type == 'accurate':
                ka, kae = fr['accurate']
                lines.append(f"{name[:26]:<28}{files}")
                lines.append(f"  {'k':<6} = {ka:.5f} ± {kae:.5f}  W m⁻¹ K⁻¹")
                k_vals.append(ka)
            lines.append('')

        lines.append('─'*70)
        if k_vals:
            lines.append(f"k  n={len(k_vals)}  mean={np.mean(k_vals):.5f}  "
                         f"std={np.std(k_vals):.5f}  "
                         f"min={np.min(k_vals):.5f}  max={np.max(k_vals):.5f}  W m⁻¹ K⁻¹")
        if g_vals:
            lines.append(f"γ  n={len(g_vals)}  mean={np.mean(g_vals):.5f}  "
                         f"std={np.std(g_vals):.5f}  "
                         f"min={np.min(g_vals):.5f}  max={np.max(g_vals):.5f}  s⁻¹")
        lbl.setPlainText(prefix + '\n'.join(lines))

    # ── Compare k/γ tab ──────────────────────────────────────────────────
    def _plot_compare(self):
        try:
            import numpy as np
            fig = self.fig_compare
            fig.clear()
            ax = fig.add_subplot(111)
            # One bar per param-group (same params = same sample)
            checked  = self._checked()
            groups   = self._group_by_params(checked)
            samples  = [g[0] for g in groups]          # representative per group
            names    = [self._group_label(g)[:16] for g in groups]
            x        = np.arange(len(names))
            width   = 0.25
            offset  = 0
            ax2     = None

            def _bar(vals, errs, label, color, twin=False):
                nonlocal offset, ax2
                target = ax if not twin else ax2
                if twin and ax2 is None:
                    ax2 = ax.twinx()
                    ax2.set_ylabel(r"$\gamma\ (\mathrm{s}^{-1})$", fontsize=10)
                    target = ax2
                cols = [color if not np.isnan(v) else '#555' for v in vals]
                vs   = [0 if np.isnan(v) else v for v in vals]
                es   = [0 if np.isnan(e) else e for e in errs]
                target.bar(x + offset, vs, width, label=label, color=cols,
                           yerr=es, capsize=3, error_kw={'ecolor':'#aaa'}, alpha=0.85)
                offset += width

            def _get(s, ft, idx):
                fr = s.get('fit_results') or {}
                d  = fr.get(ft)
                return d[idx] if d else np.nan

            if self.cmp_global_cb.isChecked():
                _bar([_get(s,'global',0) for s in samples],
                     [_get(s,'global',2) for s in samples],
                     'k (Global)', '#3be362')
            if self.cmp_accurate_cb.isChecked():
                _bar([_get(s,'accurate',0) for s in samples],
                     [_get(s,'accurate',1) for s in samples],
                     'k (Accurate)', '#818cf8')
            if self.cmp_phase_cb.isChecked():
                _bar([_get(s,'phase',0) for s in samples],
                     [_get(s,'phase',1) for s in samples],
                     'γ (Phase)', '#ff9f43', twin=True)

            if not names:
                ax.text(0.5,0.5,"No samples selected",ha='center',va='center',
                       transform=ax.transAxes, fontsize=12, color='white')
            else:
                ax.set_xticks(x + width)
                ax.set_xticklabels(names, rotation=25, ha='right', fontsize=9)
                ax.set_ylabel(r"$k\ (\mathrm{W\ m^{-1}\ K^{-1}})$", fontsize=10)
                ax.set_title("Comparison: k and γ across samples", fontsize=11)
                ax.legend(fontsize=9, loc='upper left')
                ax.grid(True, axis='y', alpha=0.3)
            fig.tight_layout()
            self.canvas_compare.draw()
            self._update_compare_stats(samples)
        except Exception as e:
            import traceback
            print(f"Compare plot error: {e}")
            print(traceback.format_exc())

    def _update_compare_stats(self, samples):
        import numpy as np
        lines = ['Statistical Summary', '─'*60]
        for ft, key, unit in [('global','k','W m⁻¹ K⁻¹'),('accurate','k','W m⁻¹ K⁻¹'),('phase','γ','s⁻¹')]:
            idx = 0
            vals = []
            for s in samples:
                fr = s.get('fit_results') or {}
                d  = fr.get(ft)
                if d: vals.append(d[idx])
            if vals:
                lbl = f"{key} ({ft})"
                lines.append(f"{lbl:<22} n={len(vals)}  mean={np.mean(vals):.5f}  "
                             f"std={np.std(vals):.5f}  min={np.min(vals):.5f}  max={np.max(vals):.5f}  {unit}")
        self.cmp_stats_lbl.setPlainText('\n'.join(lines))

    # ── Export / Save ─────────────────────────────────────────────────────
    def _save_fig_publication(self, fig, path):
        """Save fig with Times New Roman publication fonts, then restore originals.
        On-screen appearance is unchanged — only the saved file is affected."""
        _TNR  = 'Times New Roman'
        _SZ   = {'title': 14, 'label': 13, 'tick': 11, 'legend': 11, 'suptitle': 15}
        _saved = []

        def _patch(obj, sz_key):
            _saved.append((obj, obj.get_fontfamily()[0] if obj.get_fontfamily() else 'sans-serif',
                            obj.get_fontsize()))
            obj.set_fontfamily(_TNR)
            obj.set_fontsize(_SZ[sz_key])

        for ax in fig.get_axes():
            _patch(ax.title, 'title')
            _patch(ax.xaxis.label, 'label')
            _patch(ax.yaxis.label, 'label')
            for tick in ax.get_xticklabels() + ax.get_yticklabels():
                _patch(tick, 'tick')
            leg = ax.get_legend()
            if leg:
                for t in leg.get_texts():
                    _patch(t, 'legend')
        for t in fig.texts:
            _patch(t, 'suptitle')

        try:
            fig.savefig(path, dpi=200, bbox_inches='tight')
        finally:
            for obj, fname, fsize in _saved:
                obj.set_fontfamily(fname)
                obj.set_fontsize(fsize)

    def _save_plot(self, name):
        canvas = getattr(self, f'canvas_{name}', None)
        if not canvas: return
        import os as _os
        _s = load_settings()
        base    = self.main_win.save_name_entry.text().strip() or 'analysis'
        _dir    = (_s.get("last_save_dir")
                   or self.main_win.save_dir_entry.text().strip()
                   or _s.get("last_browse_dir", ""))
        default = _os.path.join(_dir, f"{base}_analysis_{name}.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save Plot", default,
                                               "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if path:
            _s["last_save_dir"] = _os.path.dirname(path)
            save_settings(_s)
            self._save_fig_publication(canvas.figure, path)
            QMessageBox.information(self, "Saved", f"Saved:\n{path}")

    def _export_csv(self, fit_type):
        import pandas as pd
        rows = []
        groups = self._group_by_params(self._samples)
        for group in groups:
            rep  = group[0]
            fr   = rep.get('fit_results') or {}
            name = self._group_label(group)
            files = '; '.join(s.get('filepath') or s['name'] for s in group)
            row = {
                'Group': name,
                'Files': files,
                'n_files': len(group),
                'R (Ohm)':  rep['params'].get('R',''),
                'r (Ohm/K)':rep['params'].get('r',''),
                'L (m)':    rep['params'].get('L',''),
                'S (m2)':   rep['params'].get('S',''),
            }
            if fr.get('global'):
                k, gm, ke, gme = fr['global']
                row.update({'k_global (W/mK)': k, 'k_global_err': ke,
                             'gamma_global (1/s)': gm, 'gamma_global_err': gme})
            if fr.get('phase'):
                gp, gpe = fr['phase']
                row.update({'gamma_phase (1/s)': gp, 'gamma_phase_err': gpe})
            if fr.get('accurate'):
                ka, kae = fr['accurate']
                row.update({'k_accurate (W/mK)': ka, 'k_accurate_err': kae})
            rows.append(row)
        if not rows:
            QMessageBox.information(self, "Empty", "No data to export."); return
        import os as _os
        _s = load_settings()
        base    = self.main_win.save_name_entry.text().strip() or 'analysis'
        _dir    = (_s.get("last_save_dir")
                   or self.main_win.save_dir_entry.text().strip()
                   or _s.get("last_browse_dir", ""))
        default = _os.path.join(_dir, f"{base}_analysis_results.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export Results", default, "CSV (*.csv)")
        if path:
            _s["last_save_dir"] = _os.path.dirname(path)
            save_settings(_s)
            pd.DataFrame(rows).to_csv(path, index=False)
            QMessageBox.information(self, "Saved", f"Exported:\n{path}")


    # ── R1w & theta vs frequency tab ─────────────────────────────────────
    def _make_1w_tab(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _FC
        from PySide6.QtWidgets import QPlainTextEdit

        tab = QWidget()
        lay = QVBoxLayout(tab)

        fig = Figure(figsize=(8, 5), dpi=100)
        fig.set_facecolor('#1e1e2f')
        canvas = _FC(fig)
        canvas.setMinimumHeight(300)
        self.fig_1w    = fig
        self.canvas_1w = canvas
        lay.addWidget(canvas, 4)

        self._1w_fit_results = QPlainTextEdit("No fit yet — click Plot then a Fit button.")
        self._1w_fit_results.setReadOnly(True)
        self._1w_fit_results.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace; font-size:11px;"
            "background:#2b2b3d; color:#e0e0e0; padding:6px; border:none; border-radius:4px;}"
        )
        self._1w_fit_results.setMaximumHeight(90)
        lay.addWidget(self._1w_fit_results)

        # Fit controls
        fit_row = QHBoxLayout()
        fit_row.addWidget(QLabel("Fit:"))
        self._1w_fit_which = QComboBox()
        self._1w_fit_which.addItems(["R₁ω", "θ"])
        self._1w_fit_which.setFixedWidth(62)
        fit_row.addWidget(self._1w_fit_which)
        fit_row.addWidget(QLabel("  f(x) ="))
        self._1w_fit_expr = QLineEdit("a + b * x")
        self._1w_fit_expr.setToolTip(
            "Python expression in x (= frequency in Hz).\n"
            "Use single letters (a, b, c …) for free parameters.\n"
            "numpy is available as np.\n"
            "Examples:\n"
            "  a + b*x\n"
            "  a * np.exp(-b*x) + c\n"
            "  a + b*np.log(x)\n"
            "  a + b*np.log10(x)"
        )
        fit_row.addWidget(self._1w_fit_expr, 2)
        lin_btn = QPushButton("Linear Fit")
        lin_btn.setStyleSheet(
            "background:#818cf8;color:white;font-weight:bold;padding:5px;border-radius:4px;")
        lin_btn.clicked.connect(self._fit_1w_linear)
        fit_row.addWidget(lin_btn)
        cust_btn = QPushButton("Custom Fit")
        cust_btn.setStyleSheet(
            "background:#a55eea;color:white;font-weight:bold;padding:5px;border-radius:4px;")
        cust_btn.clicked.connect(self._fit_1w_custom)
        fit_row.addWidget(cust_btn)
        fit_row.addStretch()
        lay.addLayout(fit_row)

        # Action buttons
        btn_row = QHBoxLayout()
        _SS = {
            'green':  "background:#3be362;color:black;font-weight:bold;padding:5px;border-radius:4px;",
            'green2': "background:#3be362;color:black;padding:5px;border-radius:4px;",
            'grey':   "background:#555;color:white;padding:5px;border-radius:4px;",
            'orange': "background:#ff9f43;color:black;padding:5px;border-radius:4px;",
            'blue':   "background:#4a9eff;color:white;padding:5px;border-radius:4px;",
        }
        for label, style, fn in [
            ("▶ Plot Selected",  _SS['green'],  lambda: self._plot_1w('selected')),
            ("▶▶ Plot All", _SS['green2'], lambda: self._plot_1w('all')),
            ("✕ Clear",          _SS['grey'],   lambda: self._clear_canvas('1w')),
            ("📂 Load 1ω CSV", _SS['orange'], self._load_1w_csv),
            ("📊 Export CSV", _SS['orange'], self._export_1w_csv),
            ("💾 Save",       _SS['blue'],   lambda: self._save_plot('1w')),
        ]:
            b = QPushButton(label)
            b.setStyleSheet(style)
            b.clicked.connect(fn)
            btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return tab

    def _plot_1w(self, mode='selected'):
        import numpy as np
        samples = self._checked() if mode == 'selected' else self._samples
        samples = [s for s in samples if s.get('data_1w')]
        if not samples:
            QMessageBox.information(
                self, "No R₁ω data",
                "No R₁ω/θ data found in the selected samples.\n\n"
                "This data is produced when \'Auto 1ω calibration\' is enabled during a 3ω run,\n"
                "or load a *_1w_frequency_dependent.csv file via \'Load 1ω CSV\'.")
            return
        fig = self.fig_1w
        fig.clear()
        ax_r, ax_th = fig.subplots(2, 1, sharex=True)
        for ax in (ax_r, ax_th):
            ax.set_facecolor('#1a1a2f')
            ax.tick_params(colors='#aaa', labelsize=8)
            for spine in ax.spines.values():
                spine.set_color('#444')
            ax.grid(True, alpha=0.25, linestyle='--')
        plotted = False
        for s in samples:
            d = s['data_1w']
            if not d:
                continue
            import numpy as _np
            arr = _np.array(d, dtype=float)
            f, r1w, theta = arr[:, 0], arr[:, 1], arr[:, 2]
            idx = _np.argsort(f)
            f, r1w, theta = f[idx], r1w[idx], theta[idx]
            c = s['color']
            ax_r.plot(f, r1w,   'o-', color=c, label=s['name'], markersize=4,
                      linewidth=1.2, alpha=0.9)
            ax_th.plot(f, theta, 's-', color=c, label=s['name'], markersize=4,
                       linewidth=1.2, alpha=0.9)
            plotted = True
        if plotted:
            ax_r.set_ylabel(r"$R_{1\omega}\ (\Omega)$", color='#e0e0e0', fontsize=10)
            ax_th.set_ylabel(r"$\theta\ (\degree)$", color='#e0e0e0', fontsize=10)
            ax_th.set_xlabel("Frequency (Hz)", color='#e0e0e0', fontsize=10)
            ax_r.set_title(r"$R_{1\omega}$ and $\theta$ vs Frequency",
                           color='#e0e0e0', fontsize=11, pad=6)
            ax_r.set_xscale('log')
            for ax in (ax_r, ax_th):
                leg = ax.legend(fontsize=7, facecolor='#2a2a3d', edgecolor='#555',
                                labelcolor='#e0e0e0')
        else:
            ax_r.text(0.5, 0.5, "No data to plot", ha='center', va='center',
                      transform=ax_r.transAxes, color='#888', fontsize=12)
        fig.tight_layout()
        self.canvas_1w.draw()

    def _gather_1w_xy(self):
        """Return (f, y) arrays for the currently selected channel (R1w or theta)."""
        import numpy as _np
        col = 1 if self._1w_fit_which.currentIndex() == 0 else 2
        samples = self._checked() or self._samples
        samples = [s for s in samples if s.get('data_1w')]
        all_f, all_y = [], []
        for s in samples:
            d = s['data_1w']
            if d:
                arr = _np.array(d, dtype=float)
                all_f.extend(arr[:, 0].tolist())
                all_y.extend(arr[:, col].tolist())
        if not all_f:
            return None, None
        f = _np.array(all_f)
        y = _np.array(all_y)
        idx = _np.argsort(f)
        return f[idx], y[idx]

    def _fit_1w_linear(self):
        import numpy as _np
        f, y = self._gather_1w_xy()
        if f is None:
            QMessageBox.information(self, "No data", "No 1ω data in checked samples.")
            return
        which = "R₁ω" if self._1w_fit_which.currentIndex() == 0 else "θ"
        c = _np.polyfit(f, y, 1)
        y_fit = _np.polyval(c, f)
        ss_res = _np.sum((y - y_fit) ** 2)
        ss_tot = _np.sum((y - y.mean()) ** 2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float('nan')
        axs = self.fig_1w.get_axes()
        if axs:
            ax = axs[0] if self._1w_fit_which.currentIndex() == 0 else axs[1]
            xf = _np.linspace(f.min(), f.max(), 400)
            ax.plot(xf, _np.polyval(c, xf), '--', color='#ffdd59', lw=2,
                    label=f"Linear fit ({which})")
            ax.legend(fontsize=7, facecolor='#2a2a3d', edgecolor='#555',
                      labelcolor='#e0e0e0')
            self.canvas_1w.draw()
        self._1w_fit_results.setPlainText(
            f"Linear fit  [{which}] = a*f + b\n"
            f"  a = {c[0]:.6g}\n"
            f"  b = {c[1]:.6g}\n"
            f"  R² = {r2:.6f}    n = {len(f)} points"
        )

    def _fit_1w_custom(self):
        import numpy as _np, re as _re
        expr = self._1w_fit_expr.text().strip()
        if not expr:
            QMessageBox.warning(self, "No expression", "Enter a fit expression first.")
            return
        f, y = self._gather_1w_xy()
        if f is None:
            QMessageBox.information(self, "No data", "No 1ω data in checked samples.")
            return
        which = "R₁ω" if self._1w_fit_which.currentIndex() == 0 else "θ"
        # Detect free parameters: identifiers not in known namespaces or 'x'
        _skip = set(dir(_np)) | {'x', 'np', 'math', 'e', 'pi', 'inf', 'nan', 'True', 'False'}
        tokens = _re.findall(r'\b([A-Za-z_]\w*)\b', expr)
        params = list(dict.fromkeys(t for t in tokens if t not in _skip))
        if not params:
            QMessageBox.warning(
                self, "No parameters",
                "No free parameters detected.\n"
                "Use letters like a, b, c for parameters (not x which is frequency).")
            return
        _safe = {'np': _np, '__builtins__': {}}
        def fit_fn(x, *vals):
            local = dict(zip(params, vals))
            local['x'] = x
            local.update(_safe)
            return eval(expr, _safe, local)
        try:
            from scipy.optimize import curve_fit as _cf
            p0 = [1.0] * len(params)
            popt, pcov = _cf(fit_fn, f, y, p0=p0, maxfev=20000)
        except Exception as ex1:
            try:
                p0 = [float(y.mean())] + [0.0] * (len(params) - 1)
                popt, pcov = _cf(fit_fn, f, y, p0=p0, maxfev=40000)
            except Exception as ex2:
                self._1w_fit_results.setPlainText(
                    f"Fit failed: {ex2}\n\nExpression: {expr}\nParams: {params}")
                return
        perr = _np.sqrt(_np.diag(pcov))
        y_fit = fit_fn(f, *popt)
        ss_res = _np.sum((y - y_fit) ** 2)
        ss_tot = _np.sum((y - y.mean()) ** 2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float('nan')
        axs = self.fig_1w.get_axes()
        if axs:
            ax = axs[0] if self._1w_fit_which.currentIndex() == 0 else axs[1]
            xf = _np.linspace(f.min(), f.max(), 600)
            ax.plot(xf, fit_fn(xf, *popt), '--', color='#ff6b6b', lw=2,
                    label=f"Custom fit ({which})")
            ax.legend(fontsize=7, facecolor='#2a2a3d', edgecolor='#555',
                      labelcolor='#e0e0e0')
            self.canvas_1w.draw()
        lines = [f"Custom fit  [{which}] = {expr}"]
        for p, v, e in zip(params, popt, perr):
            lines.append(f"  {p} = {v:.6g} ± {e:.2g}")
        lines.append(f"  R² = {r2:.6f}    n = {len(f)} points")
        self._1w_fit_results.setPlainText('\n'.join(lines))

    def _load_1w_csv(self):
        """Load standalone 1ω frequency-dependent CSV files."""
        import pandas as _pd, os as _os
        _s = load_settings()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load 1ω CSV Files", _s.get("last_open_dir", ""),
            "CSV Files (*.csv);;All Files (*)")
        if not paths:
            return
        _s["last_open_dir"] = _os.path.dirname(paths[0])
        save_settings(_s)
        loaded = 0
        for path in paths:
            try:
                df = _pd.read_csv(path)
                data_1w = self._extract_1w(df)
                if not data_1w:
                    QMessageBox.warning(
                        self, "Not a 1ω file",
                        f"No R₁ω data found in:\n{path}\n\n"
                        "Expected columns: \'Frequency (Hz)\', \'R_1w_avg (Ohm)\', \'theta_avg (deg)\'")
                    continue
                name = _os.path.splitext(_os.path.basename(path))[0]
                self._add_sample({
                    'name': name, 'source': 'file', 'filepath': path,
                    'color': self._next_color(), 'checked': True,
                    'data_3w': [], 'data_iv': [], 'data_1w': data_1w,
                    'fit_results': None, 'mask_3w': set(), 'mask_iv': set(),
                    'params': {}, 'status': 'file', 'timestamp': None, 'ts_data': None,
                })
                loaded += 1
            except Exception as ex:
                QMessageBox.critical(self, "Load Error", f"Could not load:\n{path}\n\n{ex}")
        if loaded:
            self._refresh_sidebar()

    def _export_1w_csv(self):
        """Export R₁ω and θ data for checked samples to CSV."""
        import pandas as _pd, os as _os
        samples = self._checked() or self._samples
        samples = [s for s in samples if s.get('data_1w')]
        if not samples:
            QMessageBox.information(self, "Empty", "No 1ω data in checked samples.")
            return
        rows = []
        for s in samples:
            for row in s['data_1w']:
                rows.append({'Sample': s['name'],
                             'Frequency (Hz)': row[0],
                             'R_1w_avg (Ohm)': row[1],
                             'theta_avg (deg)': row[2]})
        _s = load_settings()
        base = self.main_win.save_name_entry.text().strip() or 'analysis'
        _dir = (_s.get("last_save_dir")
                or self.main_win.save_dir_entry.text().strip()
                or _s.get("last_browse_dir", ""))
        default = _os.path.join(_dir, f"{base}_1w_analysis.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export 1ω CSV", default, "CSV (*.csv)")
        if path:
            _s["last_save_dir"] = _os.path.dirname(path)
            save_settings(_s)
            _pd.DataFrame(rows).to_csv(path, index=False)
            QMessageBox.information(self, "Saved", f"Exported:\n{path}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Settings writes are debounced (see save_settings above) — force any
    # still-pending write to disk on exit so a change made right before
    # closing is never silently dropped.
    app.aboutToQuit.connect(_flush_settings_now)
    window = MeasurementInterface()
    window.showMaximized()
    sys.exit(app.exec())

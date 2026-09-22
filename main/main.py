import sys
import os
import subprocess
import json
import uuid
from datetime import date
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QMessageBox, QStyleFactory, QRadioButton, QButtonGroup,
    QDialog, QCheckBox, QFrame, QTabWidget, QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor, QPainter

LAST_PATHS_FILE = "structify_last_paths.json"
EDITOR_FONT_FAMILY = "SF Mono"
EDITOR_FONT_SIZE   = 12
EDITOR_LINE_HEIGHT = 16

# ── Folder structure helpers ─────────────────────────────────────────────────

def get_folder_structure_with_paths(root_path, recursive=True,
                                     include_folders=True, include_files=True):
    display_lines, abs_paths = [], []
    if not recursive:
        try: entries = sorted(os.listdir(root_path))
        except PermissionError: return display_lines, abs_paths
        for name in entries:
            fp = os.path.join(root_path, name)
            if os.path.isdir(fp) and include_folders:
                display_lines.append(name); abs_paths.append(fp)
            elif os.path.isfile(fp) and include_files:
                display_lines.append(name); abs_paths.append(fp)
        return display_lines, abs_paths
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        dirnames.sort()
        rel = os.path.relpath(dirpath, root_path)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        indent = '  ' * (depth - 1) if depth > 0 else ''
        if rel != '.':
            fn = os.path.basename(dirpath)
            if include_folders:
                display_lines.append(f"{indent}{fn}"); abs_paths.append(dirpath)
            if include_files:
                for f in sorted(filenames):
                    display_lines.append(f"{'  '*depth}{f}")
                    abs_paths.append(os.path.join(dirpath, f))
        else:
            if include_files:
                for f in sorted(filenames):
                    display_lines.append(f); abs_paths.append(os.path.join(dirpath, f))
    return display_lines, abs_paths

# ── Tree diagram generator ───────────────────────────────────────────────────

def build_tree_diagram(lines, root_name="project"):
    items = []
    for line in lines:
        if not line.strip(): continue
        indent = len(line) - len(line.lstrip())
        items.append((indent // 2, line.strip()))
    if not items: return ""

    def is_file(name): return '.' in name and not name.startswith('.')
    def has_children(i): return i+1 < len(items) and items[i+1][0] > items[i][0]
    def is_last_at_depth(i):
        d = items[i][0]
        for j in range(i+1, len(items)):
            if items[j][0] == d: return False
            if items[j][0] < d: break
        return True
    def bar_prefix(i, up_to):
        parts = []
        for d in range(up_to):
            still = any(items[j][0] == d for j in range(i+1, len(items))
                        if not any(items[k][0] < d for k in range(i+1, j)))
            parts.append("│   " if still else "    ")
        return "".join(parts)
    def sep(i, depth): return bar_prefix(i, depth) + "│"

    result = [f"{root_name}/", "│", "│"]
    for i, (depth, name) in enumerate(items):
        is_last = is_last_at_depth(i)
        hc      = has_children(i)
        folder  = not is_file(name)
        display = name + ("/" if folder and hc else "")
        full    = bar_prefix(i, depth) + ("└── " if is_last else "├── ") + display
        pad     = max(1, 52 - len(full))
        result.append(full + " " * pad + "# ← add description here")
        if folder and hc:
            result.append(sep(i, items[i+1][0]))
        next_idx = i + 1
        if next_idx < len(items) and items[next_idx][0] == 0:
            result.append("│")
    return "\n".join(result)

# ── LineNumberArea & LineNumberedEditor ──────────────────────────────────────

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor
    def sizeHint(self):
        from PyQt6.QtCore import QSize as S
        return S(self._editor._gutter_width(), 0)
    def paintEvent(self, event):
        self._editor._paint_gutter(event)


class LineNumberedEditor(QWidget):
    text_changed = pyqtSignal()

    def _make_font(self): return QFont(EDITOR_FONT_FAMILY, EDITOR_FONT_SIZE)

    def _apply_fixed_format(self):
        from PyQt6.QtGui import QTextBlockFormat, QTextCharFormat as TCF
        doc = self.editor.document()
        raw = doc.toPlainText()
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        clean = "\n".join(lines)
        if raw != clean:
            cur = self.editor.textCursor(); pos = cur.position()
            doc.blockSignals(True); self.editor.blockSignals(True)
            try: self.editor.setPlainText(clean)
            finally: doc.blockSignals(False); self.editor.blockSignals(False)
            cur2 = self.editor.textCursor()
            cur2.setPosition(min(pos, len(clean))); self.editor.setTextCursor(cur2)
        cf = TCF(); cf.setFont(self._make_font()); cf.setBackground(QColor("white"))
        bf = QTextBlockFormat()
        bf.setLineHeight(EDITOR_LINE_HEIGHT, 4); bf.setTopMargin(0); bf.setBottomMargin(0)
        doc.blockSignals(True)
        try:
            cur = QTextCursor(doc); cur.beginEditBlock()
            cur.select(QTextCursor.SelectionType.Document)
            cur.setCharFormat(cf); cur.setBlockFormat(bf)
            cur.clearSelection(); cur.endEditBlock()
        finally: doc.blockSignals(False)
        self._update_gutter_width(); self._gutter.update()

    def setPlainText(self, text):
        doc = self.editor.document()
        doc.blockSignals(True); self.editor.blockSignals(True)
        try:
            lines = [ln for ln in text.splitlines() if ln.strip()]
            self.editor.setPlainText("\n".join(lines))
        finally: doc.blockSignals(False); self.editor.blockSignals(False)
        self._apply_fixed_format()
        self.editor.horizontalScrollBar().setValue(0)
        self.text_changed.emit()

    def toPlainText(self):    return self.editor.toPlainText()
    def setReadOnly(self, v): self.editor.setReadOnly(v)
    def setFont(self, font):  self.editor.setFont(font)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = QTextEdit(self)
        self.editor.setFont(self._make_font())
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor.setStyleSheet("""
            QTextEdit { background-color:#ffffff; color:#000000; border:none; padding:2px 8px; }
            QScrollBar:vertical { background:#d8d8d8; width:12px; border-radius:6px; }
            QScrollBar::handle:vertical { background:#888888; min-height:24px; border-radius:6px; }
            QScrollBar::handle:vertical:hover { background:#555555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
            QScrollBar:horizontal { background:#d8d8d8; height:12px; border-radius:6px; }
            QScrollBar::handle:horizontal { background:#888888; min-width:24px; border-radius:6px; }
            QScrollBar::handle:horizontal:hover { background:#555555; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0px; }
        """)
        self._gutter = LineNumberArea(self)
        self._gutter.setStyleSheet("")
        h = QHBoxLayout(self); h.setContentsMargins(0,0,0,0); h.setSpacing(0)
        h.addWidget(self._gutter); h.addWidget(self.editor)
        self.setStyleSheet("LineNumberedEditor{border:1px solid #d0d4d8;border-radius:6px;background-color:#ffffff;}")
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.editor.document().blockCountChanged.connect(self._update_gutter_width)
        self.editor.verticalScrollBar().valueChanged.connect(self._gutter.update)
        self.editor.document().documentLayout().documentSizeChanged.connect(lambda _: self._gutter.update())
        self._norm_timer = QTimer(self)
        self._norm_timer.setSingleShot(True); self._norm_timer.setInterval(80)
        self._norm_timer.timeout.connect(self._on_normalize_timer)
        self._normalizing = False
        self.editor.document().contentsChanged.connect(self._schedule_normalize)
        self.editor.document().contentsChanged.connect(self.text_changed)
        self._update_gutter_width(); self._apply_fixed_format()

    def _schedule_normalize(self):
        if not self._normalizing: self._norm_timer.start()
    def _on_normalize_timer(self):
        if self._normalizing: return
        self._normalizing = True
        try: self._apply_fixed_format()
        finally: self._normalizing = False
    def _gutter_width(self):
        digits = max(2, len(str(self.editor.document().blockCount())))
        return 12 + self.editor.fontMetrics().horizontalAdvance('9') * digits
    def _update_gutter_width(self):
        self._gutter.setFixedWidth(self._gutter_width())
    def _paint_gutter(self, event):
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor("#f0f0f0"))
        block = self.editor.document().begin(); block_num = 1
        editor_top = self.editor.contentsMargins().top()
        scroll_y = self.editor.verticalScrollBar().value()
        doc_layout = self.editor.document().documentLayout()
        while block.isValid():
            br = doc_layout.blockBoundingRect(block)
            top = int(br.top()) - scroll_y + editor_top
            if top > event.rect().bottom(): break
            if top + int(br.height()) >= event.rect().top():
                painter.setPen(QColor("#999999"))
                f = self.editor.font(); f.setPointSize(f.pointSize() - 1); painter.setFont(f)
                painter.drawText(0, top, self._gutter.width()-4, int(br.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(block_num))
            block = block.next(); block_num += 1
        painter.end()


# ── ComparisonDialog ─────────────────────────────────────────────────────────

class ComparisonDialog(QDialog):
    def __init__(self, left_lines, right_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Structure Comparison — Level-by-Level")
        self.resize(1000, 720)
        layout = QVBoxLayout(self)

        # Legend for this dialog
        legend_widget = QWidget()
        leg_lay = QHBoxLayout(legend_widget)
        leg_lay.setContentsMargins(4,4,4,4); leg_lay.setSpacing(20)
        LS = "font-family:'Segoe UI',sans-serif;font-size:11px;color:#333;font-weight:600;"
        for color, prefix, desc in [
            ("#e6ffe6", "",  "Found in BOTH structures (same level)"),
            ("#ffe6e6", "L", "Only in LEFT  structure — missing from Right"),
            ("#ffe6e6", "R", "Only in RIGHT structure — missing from Left"),
        ]:
            w = QWidget(); hl = QHBoxLayout(w); hl.setContentsMargins(4,2,8,2); hl.setSpacing(6)
            sw = QLabel(prefix); sw.setFixedSize(24,20)
            sw.setStyleSheet(f"background-color:{color};border:1px solid #bbb;border-radius:3px;"
                             f"font-weight:bold;color:#333;font-size:11px;qproperty-alignment:AlignCenter;")
            lb = QLabel(desc); lb.setStyleSheet(LS)
            hl.addWidget(sw); hl.addWidget(lb); leg_lay.addWidget(w)
        leg_lay.addStretch()
        layout.addWidget(legend_widget)

        lbl = QLabel("Comparison is order-insensitive — items are grouped by folder depth level.")
        lbl.setStyleSheet("font-size:11px;color:#555;padding:2px 4px;")
        layout.addWidget(lbl)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True); self.preview.setFont(QFont("SF Mono", 12))
        self.preview.setStyleSheet("QTextEdit{background-color:#fafafa;color:#000;border:1px solid #c0c0c0;border-radius:6px;padding:10px;}")
        layout.addWidget(self.preview, stretch=1)
        from PyQt6.QtWidgets import QDialogButtonBox
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept); layout.addWidget(bb)
        self._compare_and_highlight(left_lines, right_lines)

    def _compare_and_highlight(self, left_lines, right_lines):
        doc = self.preview.document()
        cursor = QTextCursor(doc); cursor.beginEditBlock()
        green = QColor("#e6ffe6"); red = QColor("#ffe6e6")
        lbl, rbl = {}, {}
        for line in left_lines:
            ind = len(line)-len(line.lstrip()); lv = ind//2; nm = line.strip()
            lbl.setdefault(lv, set())
            if nm: lbl[lv].add(nm)
        for line in right_lines:
            ind = len(line)-len(line.lstrip()); lv = ind//2; nm = line.strip()
            rbl.setdefault(lv, set())
            if nm: rbl[lv].add(nm)
        mx = max(max(lbl.keys(), default=0), max(rbl.keys(), default=0))
        for level in range(mx+1):
            ln = lbl.get(level, set()); rn = rbl.get(level, set())
            for nm in sorted(ln & rn):
                f=QTextCharFormat(); f.setBackground(green); cursor.setCharFormat(f)
                cursor.insertText(f"    {'  '*level}{nm}\n")
            for nm in sorted(ln - rn):
                f=QTextCharFormat(); f.setBackground(red); cursor.setCharFormat(f)
                cursor.insertText(f"  L {'  '*level}{nm}\n")
            for nm in sorted(rn - ln):
                f=QTextCharFormat(); f.setBackground(red); cursor.setCharFormat(f)
                cursor.insertText(f"  R {'  '*level}{nm}\n")
            if level < mx: cursor.insertText("\n")
        cursor.endEditBlock(); self.preview.setTextCursor(cursor)


# ── Main Application ──────────────────────────────────────────────────────────

class FolderStructureApp(QMainWindow):

    LS = ("font-family:'Segoe UI','SF Pro Text','Helvetica Neue',Arial,sans-serif;"
          "font-size:11px;color:#e0e0e0;")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Structify — Folder Structure Tool")
        screen = QApplication.primaryScreen().availableGeometry()
        w = int(screen.width() * 0.60); h = int(screen.height() * 0.85)
        self.resize(w, h)
        self.setMinimumSize(QSize(880, 620))
        self.move(screen.x() + (screen.width()-w)//2,
                  screen.y() + (screen.height()-h)//2)
        if 'Fusion' in QStyleFactory.keys():
            QApplication.setStyle('Fusion')

        # ── Per-tab state (each tab manages its own left path independently) ──
        # tab1: left_path_edit, right_path_edit → shared source of truth for scan
        # tab2: separate left path (initially synced from tab1 on first scan)
        # tab3: separate left path
        self._line_compare_active  = False
        self._coloring_in_progress = False
        self._sync_scroll_active   = False
        self._syncing_scroll       = False
        self._left_abs_paths       = []
        # Track whether each tab has received its "first load" from tab1
        self._tab2_initialized     = False
        self._tab3_initialized     = False

        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border:none; }
            QTabBar::tab { background:#3a3a3a; color:#bbbbbb;
                padding:6px 24px; font-size:12px; font-weight:bold;
                border-top-left-radius:5px; border-top-right-radius:5px; margin-right:2px; }
            QTabBar::tab:selected { background:#555555; color:#ffffff; }
            QTabBar::tab:hover:!selected { background:#444444; }
        """)
        root.addWidget(self.tabs)

        self._build_tab1()
        self._build_tab2()
        self._build_tab3()

        self.tabs.addTab(self.tab1, "①  Compare & Explore")
        self.tabs.addTab(self.tab2, "②  Rename Files & Folders")
        self.tabs.addTab(self.tab3, "③  Generate Tree Diagram")

        self._load_last_paths()
        self.left_preview.text_changed.connect(self._on_left_changed)
        self.right_preview.text_changed.connect(self._on_right_changed)

    # ────────────────────────────────────────────────────────────────────────
    # Shared widget helpers
    # ────────────────────────────────────────────────────────────────────────

    def _hr(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#555;margin:1px 0;"); return f

    def _legend_item(self, color, text, prefix=""):
        w = QWidget(); hl = QHBoxLayout(w)
        hl.setContentsMargins(2,1,6,1); hl.setSpacing(5)
        sw = QLabel(prefix); sw.setFixedSize(20,18)
        sw.setStyleSheet(f"background-color:{color};border:1px solid #999;border-radius:3px;"
                         f"font-weight:bold;color:#333;font-size:10px;qproperty-alignment:AlignCenter;")
        lb = QLabel(text); lb.setStyleSheet(self.LS+"font-weight:600;font-size:10px;")
        hl.addWidget(sw); hl.addWidget(lb); return w

    def _blue_btn(self): return (
        "QPushButton{background-color:#0066cc;color:white;font-weight:bold;"
        "min-width:180px;border-radius:5px;padding:3px 12px;}"
        "QPushButton:hover{background-color:#0077e6;}"
        "QPushButton:pressed{background-color:#0055b3;}")

    def _green_btn(self): return (
        "QPushButton{background-color:#4CAF50;color:white;font-weight:bold;"
        "min-width:180px;border-radius:5px;padding:3px 12px;}"
        "QPushButton:hover{background-color:#66BB6A;}"
        "QPushButton:pressed{background-color:#388E3C;}")

    def _orange_btn(self): return (
        "QPushButton{background-color:#e65c00;color:white;font-weight:bold;"
        "min-width:200px;border-radius:5px;padding:3px 12px;}"
        "QPushButton:hover{background-color:#ff6a00;}"
        "QPushButton:pressed{background-color:#c24f00;}")

    def _make_btn(self, text, style, height=26, tooltip=""):
        b = QPushButton(text); b.setStyleSheet(style); b.setFixedHeight(height)
        if tooltip: b.setToolTip(tooltip)
        return b

    # ────────────────────────────────────────────────────────────────────────
    # Panel builder (reused by tab1 and standalone tabs)
    # ────────────────────────────────────────────────────────────────────────

    def _build_preview_panel(self, parent_layout, title, prefix,
                              scan_cb, export_cb, import_cb, browse_cb,
                              read_only=False, stretch=1):
        """Build a scan panel with path, options, action buttons, and preview."""
        col = QVBoxLayout(); col.setSpacing(4)
        parent_layout.addLayout(col, stretch=stretch)

        lbl = QLabel(title); lbl.setStyleSheet("font-weight:bold;font-size:12px;")
        col.addWidget(lbl)

        pr = QHBoxLayout(); pr.setSpacing(4)
        pl = QLabel("Source:"); pl.setFixedWidth(52)
        pl.setStyleSheet(self.LS); pr.addWidget(pl)
        edit = QLineEdit(); edit.setPlaceholderText("Select a folder …")
        edit.setFixedHeight(24); pr.addWidget(edit)
        bb = QPushButton("Browse"); bb.setFixedWidth(68); bb.setFixedHeight(24)
        bb.clicked.connect(browse_cb); pr.addWidget(bb)
        col.addLayout(pr)
        setattr(self, f"{prefix}_path_edit", edit)

        or_ = QHBoxLayout(); or_.setSpacing(14)
        r_root = QRadioButton("Only root items"); r_root.setChecked(True)
        r_rec  = QRadioButton("All subfolders (recursive)")
        r_root.setStyleSheet("font-size:11px;"); r_rec.setStyleSheet("font-size:11px;")
        grp = QButtonGroup(self); grp.addButton(r_root); grp.addButton(r_rec)
        or_.addWidget(r_root); or_.addWidget(r_rec)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color:#666;"); or_.addWidget(sep2)
        cb_fold = QCheckBox("Folders"); cb_fold.setChecked(True)
        cb_file = QCheckBox("Files");   cb_file.setChecked(False)
        cb_fold.setStyleSheet("font-size:11px;"); cb_file.setStyleSheet("font-size:11px;")
        def make_guard(a, b):
            def g(_):
                if not a.isChecked() and not b.isChecked(): a.setChecked(True)
            return g
        cb_fold.stateChanged.connect(make_guard(cb_fold, cb_file))
        cb_file.stateChanged.connect(make_guard(cb_file, cb_fold))
        or_.addWidget(cb_fold); or_.addWidget(cb_file); or_.addStretch()
        col.addLayout(or_)
        setattr(self, f"{prefix}_radio_only_root", r_root)
        setattr(self, f"{prefix}_radio_recursive",  r_rec)
        setattr(self, f"{prefix}_cb_folders", cb_fold)
        setattr(self, f"{prefix}_cb_files",   cb_file)

        br = QHBoxLayout(); br.setSpacing(6)
        bs = QPushButton("Scan"); be = QPushButton("Export Preview TXT")
        bi = QPushButton("Import TXT")
        bs.setToolTip("Read the folder at Source and fill the preview.")
        be.setToolTip("Save current preview as a .txt file inside the source folder.")
        bi.setToolTip("Load a .txt file into the preview.")
        bs.clicked.connect(scan_cb); be.clicked.connect(export_cb); bi.clicked.connect(import_cb)
        for b in (bs, be, bi): b.setFixedHeight(24); br.addWidget(b)
        col.addLayout(br)

        pl2 = QLabel("Structure Preview" + (" (read-only)" if read_only else " (editable)"))
        pl2.setStyleSheet("font-weight:bold;font-size:11px;")
        col.addWidget(pl2)

        preview = LineNumberedEditor()
        if read_only:
            preview.setReadOnly(True)
            preview.editor.setStyleSheet(
                preview.editor.styleSheet().replace("#ffffff","#f5f5f5"))
        col.addWidget(preview, stretch=1)
        setattr(self, f"{prefix}_preview", preview)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 1 — Compare & Explore
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab1(self):
        self.tab1 = QWidget()
        lay = QVBoxLayout(self.tab1)
        lay.setContentsMargins(10,8,10,6); lay.setSpacing(5)

        # Hint
        hint = QLabel(
            "Scan or import two folder structures.  "
            "Use Compare Structures to see which items exist in one but not the other.")
        hint.setStyleSheet(self.LS); hint.setWordWrap(True)
        lay.addWidget(hint)

        # Two scan panels
        panels = QHBoxLayout(); panels.setSpacing(12)
        lay.addLayout(panels, stretch=1)
        self._build_preview_panel(panels, "Source Folder 1", "left",
                                  self.scan_left, self.export_left,
                                  self.import_txt_left, self.browse_left_source)
        self._build_preview_panel(panels, "Source Folder 2", "right",
                                  self.scan_right, self.export_right,
                                  self.import_txt_right, self.browse_right_source)

        # Sync scroll
        sr = QHBoxLayout(); sr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(sr)
        self.cb_sync_scroll = QCheckBox(
            "Sync scroll — scrolling one preview scrolls the other simultaneously")
        self.cb_sync_scroll.setStyleSheet(self.LS+"font-weight:500;")
        self.cb_sync_scroll.stateChanged.connect(self._on_sync_scroll_toggled)
        self.cb_sync_scroll.setChecked(True)   # ON by default
        sr.addWidget(self.cb_sync_scroll)

        lay.addWidget(self._hr())

        # Legend for Compare Structures
        leg_lbl = QLabel("Compare Structures legend:")
        leg_lbl.setStyleSheet(self.LS+"font-weight:600;")
        lay.addWidget(leg_lbl)
        leg_row = QHBoxLayout(); leg_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        leg_row.setSpacing(16)
        for color, prefix, desc in [
            ("#e6ffe6", "",  "Found in both structures"),
            ("#ffe6e6", "L", "Only in Left  — missing from Right"),
            ("#ffe6e6", "R", "Only in Right — missing from Left"),
        ]:
            leg_row.addWidget(self._legend_item(color, desc, prefix))
        leg_row.addStretch()
        lay.addLayout(leg_row)

        # Compare button
        row_cs = QHBoxLayout(); row_cs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(row_cs)
        btn_cs = self._make_btn(
            "Compare Structures  (level-by-level, order-insensitive)",
            self._green_btn(), 28,
            "Open a side-by-side view showing items that exist in one structure but not the other.")
        btn_cs.clicked.connect(self.compare_previews)
        row_cs.addWidget(btn_cs)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 2 — Rename Files & Folders
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab2(self):
        self.tab2 = QWidget()
        outer = QVBoxLayout(self.tab2)
        outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)

        # Main content area
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(10,8,10,6); lay.setSpacing(5)

        hint = QLabel(
            "LEFT = current names on disk (auto-loaded from Tab 1 scan, or scan independently below).  "
            "RIGHT = type the desired new names here, one per line in the same order.  "
            "Line N left → renamed to Line N right on disk.")
        hint.setStyleSheet(self.LS); hint.setWordWrap(True)
        lay.addWidget(hint)

        # Three-column layout: Left panel | Center buttons | Right panel
        panels = QHBoxLayout(); panels.setSpacing(8)
        lay.addLayout(panels, stretch=1)

        # Left panel — independent scan in tab2
        self._build_preview_panel(
            panels,
            "Current Names  (left = names that exist on disk right now)",
            "t2_left",
            self._scan_t2_left, self._export_t2_left,
            self._import_t2_left, self._browse_t2_left,
            read_only=False)

        # ── Center column: 3 vertically centered action buttons ──
        center_col = QVBoxLayout()
        center_col.setSpacing(10)
        center_col.setContentsMargins(4, 0, 4, 0)
        center_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        panels.addLayout(center_col)

        center_col.addStretch()

        # Button 1 — Copy Left → Right
        btn_copy = QPushButton("→")
        btn_copy.setFixedSize(48, 48)
        btn_copy.setToolTip(
            "Copy the Left preview into the Right preview.\n"
            "Edit the Right preview to type the desired new names.")
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #4a90c4; color: white;
                font-size: 20px; font-weight: bold;
                border-radius: 24px;
            }
            QPushButton:hover  { background-color: #5aa0d4; }
            QPushButton:pressed{ background-color: #3a80b4; }
        """)
        btn_copy.clicked.connect(self._copy_left_to_right_t2)
        center_col.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignHCenter)

        copy_lbl = QLabel("Copy")
        copy_lbl.setStyleSheet(self.LS+"font-size:10px;font-weight:600;")
        copy_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center_col.addWidget(copy_lbl)

        center_col.addSpacing(12)

        # Button 2 — Compare line by line
        self.btn_compare_names = QPushButton("≡?")
        self.btn_compare_names.setFixedSize(48, 48)
        self.btn_compare_names.setToolTip(
            "Compare left and right names line by line.\n"
            "Green = same, Red = different, Yellow = only on one side.")
        self.btn_compare_names.setStyleSheet("""
            QPushButton {
                background-color: #707070; color: white;
                font-size: 16px; font-weight: bold;
                border-radius: 24px;
            }
            QPushButton:hover  { background-color: #888888; }
            QPushButton:pressed{ background-color: #555555; }
        """)
        self.btn_compare_names.clicked.connect(self.toggle_line_compare)
        center_col.addWidget(self.btn_compare_names, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.cmp_lbl = QLabel("Compare")
        self.cmp_lbl.setStyleSheet(self.LS+"font-size:10px;font-weight:600;")
        self.cmp_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center_col.addWidget(self.cmp_lbl)

        center_col.addSpacing(12)

        # Button 3 — Apply rename
        btn_apply = QPushButton("✓")
        btn_apply.setFixedSize(48, 48)
        btn_apply.setToolTip(
            "Apply Right Names to Left Source Folder.\n"
            "Each item on disk (named by Left line N) is renamed to Right line N.\n"
            "A confirmation dialog is shown before any changes are made.")
        btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #e65c00; color: white;
                font-size: 20px; font-weight: bold;
                border-radius: 24px;
            }
            QPushButton:hover  { background-color: #ff6a00; }
            QPushButton:pressed{ background-color: #c24f00; }
        """)
        btn_apply.clicked.connect(self.batch_rename)
        center_col.addWidget(btn_apply, alignment=Qt.AlignmentFlag.AlignHCenter)

        apply_lbl = QLabel("Apply")
        apply_lbl.setStyleSheet(self.LS+"font-size:10px;font-weight:600;color:#ff8040;")
        apply_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center_col.addWidget(apply_lbl)

        center_col.addStretch()

        # Right panel — manual input
        right_col = QVBoxLayout(); right_col.setSpacing(4)
        panels.addLayout(right_col, stretch=1)
        rl = QLabel("New Names  (right = desired names — edit here)")
        rl.setStyleSheet("font-weight:bold;font-size:12px;"); right_col.addWidget(rl)
        # Spacer matching path/options/buttons rows height on the left
        spacer_h = QWidget(); spacer_h.setFixedHeight(80)
        right_col.addWidget(spacer_h)
        rp_lbl = QLabel("New Names Preview (editable — one name per line)")
        rp_lbl.setStyleSheet("font-weight:bold;font-size:11px;"); right_col.addWidget(rp_lbl)
        self.tab2_right_editor = LineNumberedEditor()
        right_col.addWidget(self.tab2_right_editor, stretch=1)

        # ── Bottom: workflow info + legend ──
        lay.addWidget(self._hr())

        # Workflow explanation — centred, concise, crystal-clear
        wf_row = QHBoxLayout(); wf_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(wf_row)
        wf = QLabel(
            "<b>Workflow:</b>  "
            "<b>① Scan</b> a folder (left) — it shows every file/folder name on disk.  "
            "<b>②  →</b> copies those names to the right.  "
            "<b>③ Edit</b> the right side — type the desired new name on each line.  "
            "<b>④ ✓ Apply</b> renames each item on disk:  "
            "the item whose current name is on <i>Left line N</i> "
            "is permanently renamed to <i>Right line N</i>.  "
            "A confirmation dialog appears before any file is touched."
        )
        wf.setStyleSheet(self.LS+"font-size:10px;")
        wf.setWordWrap(True); wf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wf_row.addWidget(wf)

        # Legend — centred
        leg2_row = QHBoxLayout(); leg2_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        leg2_row.setSpacing(12); lay.addLayout(leg2_row)
        leg2_lbl = QLabel("≡? Compare line colours:")
        leg2_lbl.setStyleSheet(self.LS+"font-weight:600;font-size:10px;")
        leg2_row.addWidget(leg2_lbl)
        for color, desc in [
            ("#b8f0b8", "Same name on both lines (no rename needed)"),
            ("#f0b8b8", "Different names — will be renamed"),
            ("#f0f0b0", "Line exists on one side only"),
        ]:
            leg2_row.addWidget(self._legend_item(color, desc))

        outer.addWidget(content, stretch=1)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 3 — Generate Tree Diagram
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab3(self):
        self.tab3 = QWidget()
        outer = QVBoxLayout(self.tab3)
        outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(10,8,10,6); lay.setSpacing(5)

        hint = QLabel(
            "Scan a folder (auto-loaded from Tab 1 on first use, or scan independently below).  "
            "Click Generate Tree to build a ├── └── │ diagram with  # ← description  placeholders.  "
            "Export saves  directory_structure_explained.md  into the source folder.")
        hint.setStyleSheet(self.LS); hint.setWordWrap(True)
        lay.addWidget(hint)

        # Root name row (above the panels so it's always visible)
        rn_row = QHBoxLayout(); rn_row.setSpacing(4); lay.addLayout(rn_row)
        rnl = QLabel("Root name:"); rnl.setFixedWidth(80); rnl.setStyleSheet(self.LS)
        rn_row.addWidget(rnl)
        self.tree_root_edit = QLineEdit()
        self.tree_root_edit.setPlaceholderText(
            "Leave empty to use the folder name, or type a custom root/project name …")
        self.tree_root_edit.setFixedHeight(24); rn_row.addWidget(self.tree_root_edit)

        # Two panels
        panels3 = QHBoxLayout(); panels3.setSpacing(12)
        lay.addLayout(panels3, stretch=1)

        # Left panel — full independent scan controls (identical to Tab 1 / Tab 2)
        self._build_preview_panel(
            panels3,
            "Source Structure  (scan a folder here — edit to customise before generating)",
            "t3_left",
            self._scan_t3, self._export_t3_left,
            self._import_t3_left, self._browse_t3,
            read_only=False)

        right3 = QVBoxLayout(); right3.setSpacing(4)
        panels3.addLayout(right3, stretch=1)
        rl3 = QLabel("Generated Tree Diagram  (editable — # ← add description here)")
        rl3.setStyleSheet("font-weight:bold;font-size:11px;"); right3.addWidget(rl3)
        self.tree_output = QTextEdit()
        self.tree_output.setReadOnly(False)
        self.tree_output.setFont(QFont("Courier New", 11))
        self.tree_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.tree_output.setStyleSheet("""
            QTextEdit{background-color:#1e1e1e;color:#d4d4d4;
                border:1px solid #444;border-radius:5px;padding:6px;}
            QScrollBar:vertical{background:#3a3a3a;width:12px;border-radius:6px;}
            QScrollBar::handle:vertical{background:#666;min-height:24px;border-radius:6px;}
            QScrollBar::handle:vertical:hover{background:#888;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}
            QScrollBar:horizontal{background:#3a3a3a;height:12px;border-radius:6px;}
            QScrollBar::handle:horizontal{background:#666;min-width:24px;border-radius:6px;}
            QScrollBar::handle:horizontal:hover{background:#888;}
            QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0px;}
        """)
        right3.addWidget(self.tree_output, stretch=1)

        # Buttons
        lay.addWidget(self._hr())
        btn3_row = QHBoxLayout(); btn3_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn3_row.setSpacing(16); lay.addLayout(btn3_row)

        btn_gen = self._make_btn(
            "▶  Generate Tree from Scanned Structure",
            self._green_btn(), 28,
            "Build the │ ├── └── tree from the left structure preview.")
        btn_gen.clicked.connect(self._generate_tree)
        btn3_row.addWidget(btn_gen)

        btn_exp = self._make_btn(
            "💾  Export as directory_structure_explained.md",
            self._blue_btn(), 28,
            "Save the tree diagram as 'directory_structure_explained.md' "
            "inside the source folder.")
        btn_exp.clicked.connect(self._export_tree)
        btn3_row.addWidget(btn_exp)

        outer.addWidget(content, stretch=1)

    # ── Tab 2 actions ────────────────────────────────────────────────────────

    def _copy_left_to_right_t2(self):
        """Copy the current Left preview into the Right editor so the user
        can see all names and edit only the ones that need changing."""
        text = self.t2_left_preview.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Copy Left → Right",
                "The Left preview is empty.\n"
                "Please scan a folder first using the Scan button above.")
            return
        self.tab2_right_editor.setPlainText(text)

    # ── Tab 2 independent scan/browse/export/import ──────────────────────────

    def _browse_t2_left(self):
        f = QFileDialog.getExistingDirectory(self, "Select Folder",
                                             self.t2_left_path_edit.text())
        if f: self.t2_left_path_edit.setText(f)

    def _scan_t2_left(self):
        path = self.t2_left_path_edit.text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self,"Error","Source path is not a valid folder."); return
        rec  = self.t2_left_radio_recursive.isChecked()
        incf = self.t2_left_cb_folders.isChecked()
        inci = self.t2_left_cb_files.isChecked()
        try:
            lines, abs_paths = get_folder_structure_with_paths(path, rec, incf, inci)
            self.t2_left_preview.setPlainText("\n".join(lines))
            self._left_abs_paths = abs_paths
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot read structure:\n{e}")

    def _export_t2_left(self):
        path = self.t2_left_path_edit.text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self,"Error","Invalid source folder."); return
        self._safe_export(path, self.t2_left_preview.toPlainText().rstrip())

    def _import_t2_left(self):
        txt,_=QFileDialog.getOpenFileName(self,"Select .txt","","Text files (*.txt);;All files (*.*)")
        if not txt: return
        try:
            with open(txt,encoding="utf-8") as f:
                lines=[l.rstrip() for l in f if l.strip() and not l.strip().startswith('#')]
            self.t2_left_preview.setPlainText("\n".join(lines))
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot load file:\n{e}")

    # ── Tab 3 independent scan/browse ──────────────────────────────────────

    def _browse_t3(self):
        f = QFileDialog.getExistingDirectory(self,"Select Folder",self.t3_left_path_edit.text())
        if f: self.t3_left_path_edit.setText(f)

    def _scan_t3(self):
        path = self.t3_left_path_edit.text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self,"Error","Source path is not a valid folder."); return
        rec  = self.t3_left_radio_recursive.isChecked()
        incf = self.t3_left_cb_folders.isChecked()
        inci = self.t3_left_cb_files.isChecked()
        try:
            lines, _ = get_folder_structure_with_paths(path, rec, incf, inci)
            self.t3_left_preview.setPlainText("\n".join(lines))
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot read structure:\n{e}")

    def _export_t3_left(self):
        path = self.t3_left_path_edit.text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self,"Error","Invalid source folder."); return
        self._safe_export(path, self.t3_left_preview.toPlainText().rstrip())

    def _import_t3_left(self):
        txt,_=QFileDialog.getOpenFileName(self,"Select .txt","","Text files (*.txt);;All files (*.*)")
        if not txt: return
        try:
            with open(txt,encoding="utf-8") as f:
                lines=[l.rstrip() for l in f if l.strip() and not l.strip().startswith('#')]
            self.t3_left_preview.setPlainText("\n".join(lines))
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot load file:\n{e}")

    # ── Content propagation (Tab 1 → Tab 2 & 3, first load only) ──────────

    def _on_left_changed(self):
        """Tab 1 left preview changed — propagate to Tab 2 and Tab 3 ONLY on first load."""
        text = self.left_preview.toPlainText()
        current_lines = [l for l in text.splitlines() if l.strip()]
        if len(current_lines) != len(self._left_abs_paths):
            self._left_abs_paths = []

        # First-load propagation to Tab 2
        if not self._tab2_initialized and text.strip():
            self.t2_left_preview.setPlainText(text)
            # Mirror path and settings to tab 2
            self.t2_left_path_edit.setText(self.left_path_edit.text())
            if self.left_radio_recursive.isChecked():
                self.t2_left_radio_recursive.setChecked(True)
            else:
                self.t2_left_radio_only_root.setChecked(True)
            self.t2_left_cb_folders.blockSignals(True)
            self.t2_left_cb_files.blockSignals(True)
            self.t2_left_cb_folders.setChecked(self.left_cb_folders.isChecked())
            self.t2_left_cb_files.setChecked(self.left_cb_files.isChecked())
            self.t2_left_cb_folders.blockSignals(False)
            self.t2_left_cb_files.blockSignals(False)
            self._tab2_initialized = True

        # First-load propagation to Tab 3
        if not self._tab3_initialized and text.strip():
            self.t3_left_preview.setPlainText(text)
            self.t3_left_path_edit.setText(self.left_path_edit.text())
            # Mirror scan options
            if self.left_radio_recursive.isChecked():
                self.t3_left_radio_recursive.setChecked(True)
            else:
                self.t3_left_radio_only_root.setChecked(True)
            self.t3_left_cb_folders.blockSignals(True)
            self.t3_left_cb_files.blockSignals(True)
            self.t3_left_cb_folders.setChecked(self.left_cb_folders.isChecked())
            self.t3_left_cb_files.setChecked(self.left_cb_files.isChecked())
            self.t3_left_cb_folders.blockSignals(False)
            self.t3_left_cb_files.blockSignals(False)
            self._tab3_initialized = True

    def _on_right_changed(self):
        """Tab 1 right preview changed — no propagation needed (Tab 2 right is independent)."""
        pass

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_last_paths(self):
        try:
            if not os.path.exists(LAST_PATHS_FILE): return
            with open(LAST_PATHS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if "left"  in data and os.path.isdir(data["left"]):
                self.left_path_edit.setText(data["left"])
            if "right" in data and os.path.isdir(data["right"]):
                self.right_path_edit.setText(data["right"])
            for prefix in ("left","right"):
                if data.get(f"{prefix}_recursive"):
                    getattr(self,f"{prefix}_radio_recursive").setChecked(True)
                elif f"{prefix}_recursive" in data:
                    getattr(self,f"{prefix}_radio_only_root").setChecked(True)
                kf,ki = f"{prefix}_folders",f"{prefix}_files"
                if kf in data and ki in data:
                    lf,li = bool(data[kf]),bool(data[ki])
                    cbf=getattr(self,f"{prefix}_cb_folders"); cbi=getattr(self,f"{prefix}_cb_files")
                    cbf.blockSignals(True); cbi.blockSignals(True)
                    cbf.setChecked(lf); cbi.setChecked(li)
                    if not lf and not li: cbf.setChecked(True)
                    cbf.blockSignals(False); cbi.blockSignals(False)
            fam  = data.get("font_family", EDITOR_FONT_FAMILY)
            size = int(data.get("font_size", EDITOR_FONT_SIZE))
            if fam and size > 0:
                font = QFont(fam, size)
                self.left_preview.editor.setFont(font)
                self.right_preview.editor.setFont(font)
        except Exception: pass

    def closeEvent(self, event):
        data = {
            "left":             self.left_path_edit.text().strip(),
            "right":            self.right_path_edit.text().strip(),
            "left_recursive":   self.left_radio_recursive.isChecked(),
            "left_folders":     self.left_cb_folders.isChecked(),
            "left_files":       self.left_cb_files.isChecked(),
            "right_recursive":  self.right_radio_recursive.isChecked(),
            "right_folders":    self.right_cb_folders.isChecked(),
            "right_files":      self.right_cb_files.isChecked(),
            "font_family":      self.left_preview.editor.font().family(),
            "font_size":        self.left_preview.editor.font().pointSize(),
        }
        try:
            with open(LAST_PATHS_FILE,"w",encoding="utf-8") as f:
                json.dump(data,f,indent=2)
        except Exception: pass
        super().closeEvent(event)

    # ── Sync scroll (Tab 1 only) ──────────────────────────────────────────

    def _on_sync_scroll_toggled(self, state):
        self._sync_scroll_active = bool(state)
        if self._sync_scroll_active:
            self.left_preview.editor.verticalScrollBar().valueChanged.connect(self._sync_l2r)
            self.right_preview.editor.verticalScrollBar().valueChanged.connect(self._sync_r2l)
        else:
            try: self.left_preview.editor.verticalScrollBar().valueChanged.disconnect(self._sync_l2r)
            except Exception: pass
            try: self.right_preview.editor.verticalScrollBar().valueChanged.disconnect(self._sync_r2l)
            except Exception: pass

    def _sync_l2r(self, val):
        if self._syncing_scroll: return
        self._syncing_scroll = True
        try:
            rb = self.right_preview.editor.verticalScrollBar()
            lb = self.left_preview.editor.verticalScrollBar()
            rb.setValue(int(val/lb.maximum()*rb.maximum()) if lb.maximum()>0 else 0)
        finally: self._syncing_scroll = False

    def _sync_r2l(self, val):
        if self._syncing_scroll: return
        self._syncing_scroll = True
        try:
            lb = self.left_preview.editor.verticalScrollBar()
            rb = self.right_preview.editor.verticalScrollBar()
            lb.setValue(int(val/rb.maximum()*lb.maximum()) if rb.maximum()>0 else 0)
        finally: self._syncing_scroll = False

    # ── Scan (Tab 1) ─────────────────────────────────────────────────────────

    def _do_scan(self, prefix):
        path = getattr(self, f"{prefix}_path_edit").text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self,"Error","Source path is not a valid folder."); return
        rec  = getattr(self,f"{prefix}_radio_recursive").isChecked()
        incf = getattr(self,f"{prefix}_cb_folders").isChecked()
        inci = getattr(self,f"{prefix}_cb_files").isChecked()
        try:
            lines, abs_paths = get_folder_structure_with_paths(path, rec, incf, inci)
            self._pause_compare()
            getattr(self, f"{prefix}_preview").setPlainText("\n".join(lines))
            self._resume_compare()
            if prefix == "left":
                self._left_abs_paths = abs_paths
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot read structure:\n{e}")

    def scan_left(self):  self._do_scan("left")
    def scan_right(self): self._do_scan("right")

    def browse_left_source(self):
        f = QFileDialog.getExistingDirectory(self,"Select Folder",self.left_path_edit.text())
        if f: self.left_path_edit.setText(f)

    def browse_right_source(self):
        f = QFileDialog.getExistingDirectory(self,"Select Folder",self.right_path_edit.text())
        if f: self.right_path_edit.setText(f)

    # ── Export / Import (Tab 1) ───────────────────────────────────────────────

    def _safe_export(self, source_path, content):
        if not content.strip():
            QMessageBox.warning(self,"Nothing to export","The preview is empty."); return
        today     = date.today().strftime("%Y.%m.%d")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_"
                            for c in os.path.basename(source_path)).strip("_")
        base_name = f"{today}_folder-structure_{safe_name}.txt"
        txt_path  = os.path.join(source_path, base_name)
        def _write(p):
            with open(p,"w",encoding="utf-8") as f: f.write(content+"\n")
            self._show_export_ok(p)
        if not os.path.exists(txt_path):
            try: _write(txt_path)
            except Exception as e: QMessageBox.critical(self,"Error",f"Export failed:\n{e}")
            return
        msg=QMessageBox(self); msg.setWindowTitle("File Already Exists")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(f"File already exists:\n{txt_path}"); msg.setInformativeText("What would you like to do?")
        ow=msg.addButton("Overwrite",QMessageBox.ButtonRole.YesRole)
        nc=msg.addButton("Create numbered copy",QMessageBox.ButtonRole.NoRole)
        msg.addButton("Cancel",QMessageBox.ButtonRole.RejectRole); msg.exec()
        if msg.clickedButton()==ow:
            try: _write(txt_path)
            except Exception as e: QMessageBox.critical(self,"Error",f"Overwrite failed:\n{e}")
        elif msg.clickedButton()==nc:
            i=1
            while True:
                np=os.path.join(source_path,f"{today}_folder-structure_{safe_name}_{i:02d}.txt")
                if not os.path.exists(np):
                    try: _write(np)
                    except Exception as e: QMessageBox.critical(self,"Error",f"Save failed:\n{e}")
                    break
                i+=1

    def _show_export_ok(self, path):
        msg=QMessageBox(self); msg.setWindowTitle("Export Successful")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("Preview exported"); msg.setInformativeText(f"Location:\n{path}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        ob=msg.addButton("Open Folder",QMessageBox.ButtonRole.ActionRole); msg.exec()
        if msg.clickedButton()==ob: self._open_folder(os.path.dirname(path))

    def export_left(self):
        p=self.left_path_edit.text().strip()
        if not os.path.isdir(p): QMessageBox.warning(self,"Error","Invalid source folder."); return
        self._safe_export(p, self.left_preview.toPlainText().rstrip())

    def export_right(self):
        p=self.right_path_edit.text().strip()
        if not os.path.isdir(p): QMessageBox.warning(self,"Error","Invalid source folder."); return
        self._safe_export(p, self.right_preview.toPlainText().rstrip())

    def _import_txt(self, prefix):
        txt,_=QFileDialog.getOpenFileName(self,"Select .txt","","Text files (*.txt);;All files (*.*)")
        if not txt: return
        try:
            with open(txt,encoding="utf-8") as f:
                lines=[l.rstrip() for l in f if l.strip() and not l.strip().startswith('#')]
            self._pause_compare()
            getattr(self,f"{prefix}_preview").setPlainText("\n".join(lines))
            self._resume_compare()
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot load TXT file:\n{e}")

    def import_txt_left(self):  self._import_txt("left")
    def import_txt_right(self): self._import_txt("right")

    # ── Line-by-line color compare (Tab 2) ───────────────────────────────────

    def _both_t2_have_content(self):
        return (bool(self.t2_left_preview.toPlainText().strip()) and
                bool(self.tab2_right_editor.toPlainText().strip()))

    def _pause_compare(self):
        if hasattr(self,'_compare_timer'): self._compare_timer.stop()
        self._coloring_in_progress = True

    def _resume_compare(self):
        self._coloring_in_progress = False
        if self._line_compare_active:
            if self._both_t2_have_content(): self._apply_tab2_line_colors()
            else: self._clear_tab2_line_colors()

    def toggle_line_compare(self):
        if not self._line_compare_active and not self._both_t2_have_content():
            QMessageBox.information(self,"Compare Names",
                "Please load a structure into the Left preview\n"
                "(scan a folder in Tab 1 or scan independently above),\n"
                "and type the new names into the Right preview first."); return
        self._line_compare_active = not self._line_compare_active
        if self._line_compare_active:
            self.btn_compare_names.setText("≡✔")
            self.cmp_lbl.setText("Compare ON")
            self.cmp_lbl.setStyleSheet(self.LS+"font-size:10px;font-weight:600;color:#66BB6A;")
            self.btn_compare_names.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50; color: white;
                    font-size: 16px; font-weight: bold;
                    border-radius: 24px;
                }
                QPushButton:hover  { background-color: #66BB6A; }
                QPushButton:pressed{ background-color: #388E3C; }
            """)
            if not hasattr(self,'_compare_timer'):
                self._compare_timer = QTimer(self)
                self._compare_timer.setSingleShot(True); self._compare_timer.setInterval(150)
                self._compare_timer.timeout.connect(self._apply_tab2_line_colors)
                self.t2_left_preview.text_changed.connect(self._schedule_color_update)
                self.tab2_right_editor.text_changed.connect(self._schedule_color_update)
            self._apply_tab2_line_colors()
        else:
            self.btn_compare_names.setText("≡?")
            self.cmp_lbl.setText("Compare")
            self.cmp_lbl.setStyleSheet(self.LS+"font-size:10px;font-weight:600;")
            self.btn_compare_names.setStyleSheet("""
                QPushButton {
                    background-color: #707070; color: white;
                    font-size: 16px; font-weight: bold;
                    border-radius: 24px;
                }
                QPushButton:hover  { background-color: #888888; }
                QPushButton:pressed{ background-color: #555555; }
            """)
            if hasattr(self,'_compare_timer'): self._compare_timer.stop()
            self._clear_tab2_line_colors()

    def _schedule_color_update(self):
        if self._line_compare_active and not self._coloring_in_progress:
            if hasattr(self,'_compare_timer'): self._compare_timer.start()

    def _clear_tab2_line_colors(self):
        self._coloring_in_progress = True
        try:
            for pv in (self.t2_left_preview, self.tab2_right_editor):
                doc=pv.editor.document(); doc.blockSignals(True)
                try:
                    cur=QTextCursor(doc); cur.beginEditBlock()
                    cur.select(QTextCursor.SelectionType.Document)
                    fmt=QTextCharFormat(); fmt.setBackground(QColor("white"))
                    cur.setCharFormat(fmt); cur.clearSelection(); cur.endEditBlock()
                finally: doc.blockSignals(False)
                pv._update_gutter_width(); pv._gutter.update()
        finally: self._coloring_in_progress = False

    def _apply_tab2_line_colors(self):
        if self._coloring_in_progress or not self._line_compare_active: return
        self._coloring_in_progress = True
        try:
            EQ=QColor("#b8f0b8"); DF=QColor("#f0b8b8"); ON=QColor("#f0f0b0")
            ll=self.t2_left_preview.editor.document().toPlainText().splitlines()
            rl=self.tab2_right_editor.editor.document().toPlainText().splitlines()
            def _col(pv, lines, partner):
                doc=pv.editor.document(); doc.blockSignals(True)
                try:
                    cur=QTextCursor(doc); cur.beginEditBlock()
                    for i in range(doc.blockCount()):
                        bl=doc.findBlockByNumber(i)
                        if not bl.isValid(): break
                        bc=QTextCursor(bl); bc.select(QTextCursor.SelectionType.BlockUnderCursor)
                        fmt=QTextCharFormat()
                        if i>=len(partner):                         fmt.setBackground(ON)
                        elif lines[i].strip()==partner[i].strip():  fmt.setBackground(EQ)
                        else:                                        fmt.setBackground(DF)
                        bc.setCharFormat(fmt)
                    cur.endEditBlock()
                finally: doc.blockSignals(False)
                pv._update_gutter_width(); pv._gutter.update()
            _col(self.t2_left_preview,   ll, rl)
            _col(self.tab2_right_editor, rl, ll)
        finally: self._coloring_in_progress = False

    # ── Compare Structures (Tab 1) ────────────────────────────────────────────

    def compare_previews(self):
        ll=[l.rstrip() for l in self.left_preview.toPlainText().splitlines()]
        rl=[l.rstrip() for l in self.right_preview.toPlainText().splitlines()]
        if not ll and not rl:
            QMessageBox.information(self,"Compare","Both previews are empty."); return
        ComparisonDialog(ll,rl,self).exec()

    # ── Replicate (kept internally) ───────────────────────────────────────────

    def _replicate(self, prefix):
        preview = getattr(self,f"{prefix}_preview")
        lines = [l.rstrip() for l in preview.toPlainText().splitlines() if l.strip()]
        if not lines:
            QMessageBox.warning(self,"Error","No structure in preview to replicate."); return
        dest=QFileDialog.getExistingDirectory(self,"Select destination folder")
        if not dest or not os.path.isdir(dest): return
        try:
            self.create_from_lines(dest,lines)
            msg=QMessageBox(self); msg.setWindowTitle("Replication Successful")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("Folder structure replicated.")
            msg.setInformativeText(f"Created in:\n{dest}")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            ob=msg.addButton("Open Folder",QMessageBox.ButtonRole.ActionRole); msg.exec()
            if msg.clickedButton()==ob: self._open_folder(dest)
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Failed to replicate:\n{e}")

    def replicate_left(self):  self._replicate("left")
    def replicate_right(self): self._replicate("right")

    # ── Batch Rename (Tab 2) ──────────────────────────────────────────────────

    def batch_rename(self):
        left_lines  = [l.rstrip() for l in self.t2_left_preview.toPlainText().splitlines()  if l.strip()]
        right_lines = [l.rstrip() for l in self.tab2_right_editor.toPlainText().splitlines() if l.strip()]

        if not left_lines or not right_lines:
            QMessageBox.warning(self,"Batch Rename","Both previews must contain names."); return
        if len(left_lines) != len(right_lines):
            QMessageBox.warning(self,"Batch Rename",
                f"Line count mismatch!\nLeft: {len(left_lines)} lines  |  "
                f"Right: {len(right_lines)} lines\n"
                "Both previews must have the same number of non-empty lines."); return

        root = self.t2_left_path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.warning(self,"Batch Rename",
                "Please set a valid Left source folder path in Tab 2."); return

        # Resolve absolute paths — use stored cache if available and matching
        if self._left_abs_paths and len(self._left_abs_paths) == len(left_lines):
            left_abs_paths = list(self._left_abs_paths)
        else:
            path_stack=[root]; left_abs_paths=[]
            for line in left_lines:
                ind=len(line)-len(line.lstrip()); level=ind//2; name=line.strip()
                while len(path_stack)>level+1: path_stack.pop()
                ap=os.path.join(path_stack[-1],name)
                left_abs_paths.append(ap); path_stack.append(ap)

        ops=[]
        for old_abs, right_line in zip(left_abs_paths, right_lines):
            old_name=os.path.basename(old_abs); new_name=right_line.strip()
            if not new_name or new_name==old_name: continue
            ops.append((old_abs, os.path.join(os.path.dirname(old_abs),new_name), old_name, new_name))

        if not ops:
            QMessageBox.information(self,"Batch Rename","No differences found — nothing to rename."); return

        # Confirm dialog
        dlg=QDialog(self); dlg.setWindowTitle("Confirm Batch Rename"); dlg.resize(700,440)
        cl=QVBoxLayout(dlg); cl.setContentsMargins(16,16,16,12); cl.setSpacing(8)
        hdr=QLabel(f"About to rename <b>{len(ops)}</b> item(s) inside:<br><code>{root}</code>")
        hdr.setWordWrap(True); cl.addWidget(hdr)
        wi=QLabel("⚠  Make sure no files or folders are open in other programs before proceeding.")
        wi.setWordWrap(True); wi.setStyleSheet("color:#cc6600;font-size:12px;"); cl.addWidget(wi)
        cl2=QLabel("<b>Current name (left)</b>  →  <b>New name (right)</b>")
        cl2.setStyleSheet("font-size:11px;color:#555;"); cl.addWidget(cl2)
        sc=QTextEdit(); sc.setReadOnly(True); sc.setFont(QFont("Courier New",11))
        sc.setPlainText("\n".join(f"  {o}  →  {n}" for _,_,o,n in ops))
        cl.addWidget(sc,stretch=1)
        br=QHBoxLayout(); br.setSpacing(10); br.addStretch()
        cn=QPushButton("Cancel"); cn.setFixedHeight(30); cn.setFixedWidth(110)
        cn.clicked.connect(dlg.reject); br.addWidget(cn)
        co=QPushButton("Rename"); co.setFixedHeight(30); co.setFixedWidth(110); co.setDefault(True)
        co.setStyleSheet("background-color:#e65c00;color:white;font-weight:bold;border-radius:4px;")
        co.clicked.connect(dlg.accept); br.addWidget(co); cl.addLayout(br)
        if dlg.exec() != QDialog.DialogCode.Accepted: return

        # Safe two-phase rename
        current_abs_map={}
        def _resolve(path):
            for op in sorted(current_abs_map,key=len,reverse=True):
                cp=current_abs_map[op]
                if path==op: return cp
                if path.startswith(op+os.sep): return cp+path[len(op):]
            return path

        renamed=[]; failed=[]; skipped=[]; conflicts=[]; phase2_ops=[]

        for old_abs,new_abs,old_name,new_name in ops:
            old_r=_resolve(old_abs)
            if not os.path.exists(old_r):
                skipped.append(f'SKIPPED  "{old_name}"\n  Path not found: {old_r}'); continue
            parent=os.path.dirname(old_r)
            tmp=os.path.join(parent,f"__structify_tmp_{uuid.uuid4().hex}")
            try:
                os.rename(old_r,tmp); current_abs_map[old_abs]=tmp
                phase2_ops.append((tmp,os.path.join(parent,new_name),old_r,old_name,new_name))
            except Exception as e:
                failed.append(f'FAILED phase1  "{old_name}"\n  {old_r}  →  (tmp)\n  {e}')

        for tmp,final,orig,old_name,new_name in phase2_ops:
            if os.path.exists(final):
                try: os.rename(tmp,orig); note="Original name preserved — no data lost."
                except Exception as re2: note=f"⚠ RESTORE FAILED — file still named:\n  {tmp}\n  {re2}"
                conflicts.append(
                    f'CONFLICT  "{old_name}"  →  "{new_name}"\n'
                    f'  "{new_name}" already exists in:\n  {os.path.dirname(final)}\n  {note}')
                continue
            try:
                os.rename(tmp,final); renamed.append(f"{old_name}  →  {new_name}")
            except Exception as e:
                try: os.rename(tmp,orig); rb="  (✔ rolled back to original)"
                except Exception as re2:
                    rb=(f"  ⚠ ROLLBACK FAILED — currently named:\n  {tmp}\n"
                        f"  Rename back to: {os.path.basename(orig)}\n  {re2}")
                failed.append(f'FAILED phase2  "{old_name}"  →  "{new_name}"\n  {e}\n{rb}')

        sl=[]
        if renamed: sl.append(f"✅  Renamed {len(renamed)} item(s) successfully.\n"); sl.extend(f"  {r}" for r in renamed)
        if conflicts:
            if sl: sl.append("")
            sl.append(f"⚠️  {len(conflicts)} conflict(s) — originals preserved:"); sl.append("")
            for c in conflicts: sl.append(f"  {c}"); sl.append("")
        if skipped:
            if sl: sl.append("")
            sl.append(f"⚠️  {len(skipped)} item(s) not found on disk:"); sl.append("")
            for s in skipped: sl.append(f"  {s}")
        if failed:
            if sl: sl.append("")
            sl.append(f"❌  {len(failed)} error(s):"); sl.append("")
            for fm in failed: sl.append(f"  {fm}"); sl.append("")
        full="\n".join(sl)

        rd=QDialog(self); rd.setWindowTitle("Batch Rename Complete"); rd.resize(720,420)
        rl2=QVBoxLayout(rd); rl2.setContentsMargins(16,16,16,12); rl2.setSpacing(8)
        se=QTextEdit(); se.setReadOnly(True); se.setFont(QFont("Courier New",11))
        se.setPlainText(full); rl2.addWidget(se,stretch=1)
        rb2=QHBoxLayout(); rb2.setSpacing(10)
        cb2=QPushButton("Copy to Clipboard"); cb2.setFixedHeight(30)
        cb2.clicked.connect(lambda: QApplication.clipboard().setText(full)); rb2.addWidget(cb2)
        rb2.addStretch()
        ob2=QPushButton("Open Folder"); ob2.setFixedHeight(30)
        ob2.clicked.connect(lambda: self._open_folder(root)); rb2.addWidget(ob2)
        ok2=QPushButton("OK"); ok2.setFixedHeight(30); ok2.setDefault(True)
        ok2.clicked.connect(rd.accept); rb2.addWidget(ok2); rl2.addLayout(rb2)
        rd.exec()

    # ── Tree Diagram (Tab 3) ──────────────────────────────────────────────────

    def _generate_tree(self):
        text = self.t3_left_preview.toPlainText().strip()
        if not text:
            QMessageBox.warning(self,"Generate Tree",
                "The structure preview is empty.\n"
                "Please scan a folder first (use the Scan button above)."); return
        lines = [l for l in text.splitlines() if l.strip()]
        root_name = self.tree_root_edit.text().strip()
        if not root_name:
            src = self.t3_left_path_edit.text().strip()
            root_name = os.path.basename(src) if src else "project"
        self.tree_output.setPlainText(build_tree_diagram(lines, root_name))

    def _export_tree(self):
        tree_text = self.tree_output.toPlainText().strip()
        if not tree_text:
            QMessageBox.warning(self,"Export Tree",
                "The tree diagram is empty.\nClick 'Generate Tree' first."); return
        src = self.t3_left_path_edit.text().strip()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self,"Export Tree",
                "No valid source folder set.\nPlease scan a folder first."); return
        out_path = os.path.join(src, "directory_structure_explained.md")
        if os.path.exists(out_path):
            msg=QMessageBox(self); msg.setWindowTitle("File Already Exists")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setText(f"File already exists:\n{out_path}")
            msg.setInformativeText("What would you like to do?")
            ow=msg.addButton("Overwrite",QMessageBox.ButtonRole.YesRole)
            msg.addButton("Cancel",QMessageBox.ButtonRole.RejectRole); msg.exec()
            if msg.clickedButton()!=ow: return
        try:
            with open(out_path,"w",encoding="utf-8") as f:
                f.write(tree_text+"\n")
            msg=QMessageBox(self); msg.setWindowTitle("Export Successful")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("Tree diagram exported.")
            msg.setInformativeText(f"Saved to:\n{out_path}")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            ob=msg.addButton("Open Folder",QMessageBox.ButtonRole.ActionRole); msg.exec()
            if msg.clickedButton()==ob: self._open_folder(os.path.dirname(out_path))
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Export failed:\n{e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _open_folder(self, path):
        if sys.platform=="win32": os.startfile(path)
        elif sys.platform=="darwin": subprocess.Popen(["open",path])
        else: subprocess.Popen(["xdg-open",path])

    def create_from_lines(self, path, lines):
        stack=[path]
        for line in lines:
            ind=len(line)-len(line.lstrip()); level=ind//2; name=line.strip()
            while len(stack)>level+1: stack.pop()
            current=os.path.join(stack[-1],name)
            os.makedirs(current,exist_ok=True); stack.append(current)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FolderStructureApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
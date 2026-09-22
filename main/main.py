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
    QDialog, QCheckBox, QFrame, QTabWidget
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
    """Convert indented name list into a │ ├── └── tree with # comment placeholders."""
    # Parse into (depth, name) pairs
    items = []
    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        depth  = indent // 2
        name   = line.strip()
        items.append((depth, name))

    if not items:
        return ""

    result = [f"{root_name}/"]

    def is_folder(name):
        return '.' not in name or name.startswith('.')

    def last_child_at_depth(idx, depth):
        for j in range(idx + 1, len(items)):
            if items[j][0] == depth:
                return False
            if items[j][0] < depth:
                break
        return True

    for i, (depth, name) in enumerate(items):
        # Build vertical bar prefix
        prefix_parts = []
        for d in range(depth):
            # Check if parent at this depth still has siblings below
            has_sibling = False
            for j in range(i + 1, len(items)):
                if items[j][0] == d:
                    has_sibling = True
                    break
                if items[j][0] < d:
                    break
            prefix_parts.append("│   " if has_sibling else "    ")

        is_last = last_child_at_depth(i, depth)
        connector = "└── " if is_last else "├── "
        prefix = "".join(prefix_parts) + connector

        # Add trailing slash for folders (items that have children)
        has_children = (i + 1 < len(items) and items[i + 1][0] > depth)
        display_name = name + ("/" if has_children and is_folder(name) else "")

        # Comment padding — align to column 52
        line_so_far = prefix + display_name
        pad = max(1, 52 - len(line_so_far))
        comment = " " * pad + "# ← add description here"

        result.append(line_so_far + comment)

        # Add │ separator line after folders that have children
        if has_children:
            next_depth = items[i + 1][0]
            bar_parts = []
            for d in range(next_depth):
                has_s = False
                for j in range(i + 1, len(items)):
                    if items[j][0] == d:
                        has_s = True; break
                    if items[j][0] < d: break
                bar_parts.append("│   " if has_s else "    ")
            result.append("".join(bar_parts) + "│")

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

    def _make_font(self):
        return QFont(EDITOR_FONT_FAMILY, EDITOR_FONT_SIZE)

    def _apply_fixed_format(self):
        from PyQt6.QtGui import QTextBlockFormat, QTextCharFormat as TCF
        doc = self.editor.document()
        raw   = doc.toPlainText()
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        clean = "\n".join(lines)
        if raw != clean:
            cur = self.editor.textCursor()
            pos = cur.position()
            doc.blockSignals(True); self.editor.blockSignals(True)
            try: self.editor.setPlainText(clean)
            finally: doc.blockSignals(False); self.editor.blockSignals(False)
            cur2 = self.editor.textCursor()
            cur2.setPosition(min(pos, len(clean)))
            self.editor.setTextCursor(cur2)
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
        h = QHBoxLayout(self)
        h.setContentsMargins(0,0,0,0); h.setSpacing(0)
        h.addWidget(self._gutter); h.addWidget(self.editor)
        self.setStyleSheet("LineNumberedEditor { border:1px solid #d0d4d8; border-radius:6px; background-color:#ffffff; }")
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
        block = self.editor.document().begin()
        block_num = 1
        editor_top = self.editor.contentsMargins().top()
        scroll_y = self.editor.verticalScrollBar().value()
        doc_layout = self.editor.document().documentLayout()
        while block.isValid():
            br = doc_layout.blockBoundingRect(block)
            top = int(br.top()) - scroll_y + editor_top
            if top > event.rect().bottom(): break
            if top + int(br.height()) >= event.rect().top():
                painter.setPen(QColor("#999999"))
                f = self.editor.font(); f.setPointSize(f.pointSize() - 1)
                painter.setFont(f)
                painter.drawText(0, top, self._gutter.width()-4, int(br.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(block_num))
            block = block.next(); block_num += 1
        painter.end()


# ── ComparisonDialog ─────────────────────────────────────────────────────────

class ComparisonDialog(QDialog):
    def __init__(self, left_lines, right_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Structure Comparison")
        self.resize(1000, 700)
        layout = QVBoxLayout(self)
        lbl = QLabel("Comparison: Left vs Right preview (order-insensitive per level)")
        lbl.setStyleSheet("font-weight:bold;font-size:14px;")
        layout.addWidget(lbl)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("SF Mono", 12))
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
                cursor.insertText(f"  {'  '*level}{nm}\n")
            for nm in sorted(ln - rn):
                f=QTextCharFormat(); f.setBackground(red); cursor.setCharFormat(f)
                cursor.insertText(f"L {'  '*level}{nm}\n")
            for nm in sorted(rn - ln):
                f=QTextCharFormat(); f.setBackground(red); cursor.setCharFormat(f)
                cursor.insertText(f"R {'  '*level}{nm}\n")
            if level < mx: cursor.insertText("\n")
        cursor.endEditBlock(); self.preview.setTextCursor(cursor)


# ── Main Application ──────────────────────────────────────────────────────────

class FolderStructureApp(QMainWindow):

    LABEL_S = ("font-family:'Segoe UI','SF Pro Text','Helvetica Neue',Arial,sans-serif;"
               "font-size:12px;color:#e0e0e0;")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Structify — Folder Structure Tool")
        screen = QApplication.primaryScreen().availableGeometry()
        w = int(screen.width() * 0.70); h = screen.height()
        self.resize(w, h)
        self.setMinimumSize(QSize(1000, 720))
        self.move(screen.x() + (screen.width()-w)//2, screen.y())
        if 'Fusion' in QStyleFactory.keys():
            QApplication.setStyle('Fusion')

        # ── State ──
        self._line_compare_active  = False
        self._coloring_in_progress = False
        self._sync_scroll_active   = False
        self._syncing_scroll       = False
        self._left_abs_paths       = []

        # ── Root layout with tabs ──
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border:none; }
            QTabBar::tab { background:#3a3a3a; color:#cccccc;
                padding:8px 28px; font-size:13px; font-weight:bold;
                border-top-left-radius:6px; border-top-right-radius:6px; margin-right:3px; }
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
        # Connect propagation AFTER load so initial setText doesn't clear abs paths
        self.left_preview.text_changed.connect(self._on_left_changed)
        self.right_preview.text_changed.connect(self._on_right_changed)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 1 — Compare & Explore
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab1(self):
        self.tab1 = QWidget()
        lay = QVBoxLayout(self.tab1)
        lay.setContentsMargins(16,12,16,10); lay.setSpacing(8)

        # Hint
        hint = QLabel(
            "Scan or import folder structures into the two previews.  "
            "Use the Compare button to see structural differences.  "
            "Edit previews freely — each line is one item.")
        hint.setStyleSheet(self.LABEL_S); hint.setWordWrap(True)
        lay.addWidget(hint)

        # Two panels
        panels = QHBoxLayout(); panels.setSpacing(16)
        lay.addLayout(panels, stretch=1)
        self._build_preview_panel(panels, "Source Folder 1 — Structure", "left",
                                  self.scan_left, self.export_left,
                                  self.import_txt_left, self.browse_left_source)
        self._build_preview_panel(panels, "Source Folder 2 — Structure", "right",
                                  self.scan_right, self.export_right,
                                  self.import_txt_right, self.browse_right_source)

        # Sync scroll
        sr = QHBoxLayout(); sr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(sr)
        self.cb_sync_scroll = QCheckBox(
            "Sync scroll — scrolling one preview automatically scrolls the other")
        self.cb_sync_scroll.setStyleSheet(self.LABEL_S+"font-weight:500;")
        self.cb_sync_scroll.stateChanged.connect(self._on_sync_scroll_toggled)
        sr.addWidget(self.cb_sync_scroll)

        lay.addWidget(self._hr())

        # Compare Structures button
        row_cs = QHBoxLayout(); row_cs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(row_cs)
        btn_cs = QPushButton("Compare Structures  (level-by-level, order-insensitive)")
        btn_cs.setStyleSheet(self._green_btn_style()); btn_cs.setFixedHeight(32)
        btn_cs.setToolTip("Opens a popup showing which names exist in one structure but not the other.")
        btn_cs.clicked.connect(self.compare_previews)
        row_cs.addWidget(btn_cs)

        # Copyright
        cr = QHBoxLayout(); cr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(cr)
        lc = QLabel("Developed by Ivan Sicaja © 2026. All rights reserved.")
        lc.setStyleSheet("color:#555;font-size:11px;font-style:italic;")
        cr.addWidget(lc)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 2 — Rename Files & Folders
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab2(self):
        self.tab2 = QWidget()
        lay = QVBoxLayout(self.tab2)
        lay.setContentsMargins(16,12,16,10); lay.setSpacing(8)

        hint = QLabel(
            "LEFT preview shows the current names on disk (scanned in Tab 1).  "
            "Type or paste the desired new names into the RIGHT preview — one name per line "
            "in the same order.  "
            "Line N on the left gets renamed to Line N on the right.  "
            "Click  ⟳ Apply  to rename on disk.")
        hint.setStyleSheet(self.LABEL_S); hint.setWordWrap(True)
        lay.addWidget(hint)

        # Two panels (shared previews — read-only mirrors for tab2)
        panels = QHBoxLayout(); panels.setSpacing(16)
        lay.addLayout(panels, stretch=1)

        for side, title in [("left",  "Current Names  (from scan — line N = item N on disk)"),
                             ("right", "New Names  (type here — line N = new name for item N)")]:
            box = QVBoxLayout(); box.setSpacing(6)
            panels.addLayout(box, stretch=1)
            lbl = QLabel(title); lbl.setStyleSheet("font-weight:bold;font-size:13px;")
            box.addWidget(lbl)
            mirror = LineNumberedEditor()
            if side == "left":
                mirror.setReadOnly(True)
                mirror.editor.setStyleSheet(
                    mirror.editor.styleSheet().replace("#ffffff","#f7f7f7"))
                self.tab2_left_mirror = mirror
            else:
                self.tab2_right_editor = mirror
            box.addWidget(mirror, stretch=1)

        # Buttons row
        lay.addWidget(self._hr())

        info_row = QHBoxLayout(); info_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(info_row)
        for txt in [
            "Left preview = current names as they exist on disk  |  "
            "Right preview = the desired final names  |  "
            "Names matched strictly line-by-line (line 1 ↔ line 1, line 2 ↔ line 2, …)"
        ]:
            lbl = QLabel(txt); lbl.setStyleSheet(self.LABEL_S)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info_row.addWidget(lbl)

        # Compare names line-by-line button
        row_cn = QHBoxLayout(); row_cn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(row_cn)
        self.btn_compare_names = QPushButton("Compare Left and Right Names Line by Line")
        self.btn_compare_names.setStyleSheet("""
            QPushButton { background-color:#707070; color:white;
                font-weight:bold; font-size:13px; border-radius:6px; }
            QPushButton:hover  { background-color:#888888; }
            QPushButton:pressed{ background-color:#555555; }
        """)
        self.btn_compare_names.setFixedHeight(32); self.btn_compare_names.setFixedWidth(520)
        self.btn_compare_names.setToolTip(
            "Highlights lines: green=same, red=different, yellow=only on one side.")
        self.btn_compare_names.clicked.connect(self.toggle_line_compare)
        row_cn.addWidget(self.btn_compare_names)

        # Legend
        leg = QHBoxLayout(); leg.setSpacing(20); leg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(leg)
        for color, text in [("#b8f0b8","Same name on both lines"),
                             ("#f0b8b8","Different names on same line"),
                             ("#f0f0b0","Line exists on one side only")]:
            leg.addWidget(self._legend_item(color, text))

        # Apply rename button
        row_rn = QHBoxLayout(); row_rn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addLayout(row_rn)
        btn_rn = QPushButton("⟳  Apply Right Preview Names → Left Source Folder")
        btn_rn.setStyleSheet("""
            QPushButton { background-color:#e65c00; color:white;
                font-weight:bold; font-size:13px; min-width:380px; border-radius:6px; }
            QPushButton:hover  { background-color:#ff6a00; }
            QPushButton:pressed{ background-color:#c24f00; }
        """)
        btn_rn.setFixedHeight(32)
        btn_rn.setToolTip(
            "Renames every item in the Left source folder using the corresponding line "
            "from the Right preview. Uses a safe two-phase rename with automatic rollback.")
        btn_rn.clicked.connect(self.batch_rename)
        row_rn.addWidget(btn_rn)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 3 — Generate Tree Diagram
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab3(self):
        self.tab3 = QWidget()
        lay = QVBoxLayout(self.tab3)
        lay.setContentsMargins(16,12,16,10); lay.setSpacing(8)

        hint = QLabel(
            "Generate a formatted folder-tree diagram with  ├──  └──  │  connectors "
            "and a  # ← add description here  placeholder for every item.  "
            "Scan a folder in Tab 1, then click  Generate Tree  below.  "
            "Click  Export TXT  to save the tree as a  directory_structure_explained.md  "
            "file inside the scanned folder.")
        hint.setStyleSheet(self.LABEL_S); hint.setWordWrap(True)
        lay.addWidget(hint)

        # Source folder row
        src_row = QHBoxLayout(); src_row.setSpacing(8)
        lay.addLayout(src_row)
        src_lbl = QLabel("Source folder:")
        src_lbl.setStyleSheet(self.LABEL_S); src_lbl.setFixedWidth(110)
        src_row.addWidget(src_lbl)
        self.tree_path_label = QLabel("(none — scan a folder in Tab 1 first)")
        self.tree_path_label.setStyleSheet(self.LABEL_S + "color:#aaaaaa;")
        src_row.addWidget(self.tree_path_label, stretch=1)

        # Root name row
        root_row = QHBoxLayout(); root_row.setSpacing(8)
        lay.addLayout(root_row)
        root_lbl = QLabel("Root name:")
        root_lbl.setStyleSheet(self.LABEL_S); root_lbl.setFixedWidth(110)
        root_row.addWidget(root_lbl)
        self.tree_root_edit = QLineEdit()
        self.tree_root_edit.setPlaceholderText(
            "Leave empty to use folder name, or type a custom project name …")
        self.tree_root_edit.setFixedHeight(28)
        root_row.addWidget(self.tree_root_edit, stretch=1)

        # Two panels: Left source (read-only) + Right tree output
        panels = QHBoxLayout(); panels.setSpacing(16)
        lay.addLayout(panels, stretch=1)

        # Left — source structure (read-only mirror)
        left_box = QVBoxLayout(); left_box.setSpacing(6)
        panels.addLayout(left_box, stretch=1)
        ll = QLabel("Source Structure  (from Tab 1)")
        ll.setStyleSheet("font-weight:bold;font-size:13px;")
        left_box.addWidget(ll)
        self.tab3_left_mirror = LineNumberedEditor()
        self.tab3_left_mirror.setReadOnly(True)
        self.tab3_left_mirror.editor.setStyleSheet(
            self.tab3_left_mirror.editor.styleSheet().replace("#ffffff","#f7f7f7"))
        left_box.addWidget(self.tab3_left_mirror, stretch=1)

        # Right — generated tree
        right_box = QVBoxLayout(); right_box.setSpacing(6)
        panels.addLayout(right_box, stretch=1)
        rl = QLabel("Generated Tree Diagram  (with description placeholders)")
        rl.setStyleSheet("font-weight:bold;font-size:13px;")
        right_box.addWidget(rl)
        self.tree_output = QTextEdit()
        self.tree_output.setReadOnly(False)   # allow manual edits
        self.tree_output.setFont(QFont("Courier New", 11))
        self.tree_output.setStyleSheet("""
            QTextEdit { background-color:#1e1e1e; color:#d4d4d4;
                border:1px solid #444; border-radius:6px; padding:8px; }
            QScrollBar:vertical { background:#3a3a3a; width:12px; border-radius:6px; }
            QScrollBar::handle:vertical { background:#666; min-height:24px; border-radius:6px; }
            QScrollBar::handle:vertical:hover { background:#888; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
            QScrollBar:horizontal { background:#3a3a3a; height:12px; border-radius:6px; }
            QScrollBar::handle:horizontal { background:#666; min-width:24px; border-radius:6px; }
            QScrollBar::handle:horizontal:hover { background:#888; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0px; }
        """)
        right_box.addWidget(self.tree_output, stretch=1)

        # Buttons
        lay.addWidget(self._hr())
        btn_row = QHBoxLayout(); btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.setSpacing(20); lay.addLayout(btn_row)

        btn_gen = QPushButton("▶  Generate Tree from Left Structure")
        btn_gen.setStyleSheet(self._green_btn_style()); btn_gen.setFixedHeight(34)
        btn_gen.setToolTip("Build the │ ├── └── tree from the scanned structure.")
        btn_gen.clicked.connect(self._generate_tree)
        btn_row.addWidget(btn_gen)

        btn_exp = QPushButton("💾  Export Tree as directory_structure_explained.md")
        btn_exp.setStyleSheet(self._blue_btn_style()); btn_exp.setFixedHeight(34)
        btn_exp.setToolTip(
            "Save the tree diagram as 'directory_structure_explained.md' "
            "inside the scanned source folder.")
        btn_exp.clicked.connect(self._export_tree)
        btn_row.addWidget(btn_exp)

    # ── Preview panel builder ─────────────────────────────────────────────────
    def _build_preview_panel(self, parent_layout, title_text, prefix,
                             scan_cb, export_cb, import_cb, browse_cb):
        lay = QVBoxLayout(); lay.setSpacing(8)
        parent_layout.addLayout(lay, stretch=1)

        lbl = QLabel(title_text); lbl.setStyleSheet("font-weight:bold;font-size:13px;")
        lay.addWidget(lbl)

        # Path row
        pr = QHBoxLayout(); pr.setSpacing(6)
        pl = QLabel("Source:"); pl.setFixedWidth(60); pr.addWidget(pl)
        edit = QLineEdit(); edit.setPlaceholderText("Select a folder …"); pr.addWidget(edit)
        bb = QPushButton("Browse"); bb.setFixedWidth(80); bb.setFixedHeight(26)
        bb.clicked.connect(browse_cb); pr.addWidget(bb)
        lay.addLayout(pr)
        setattr(self, f"{prefix}_path_edit", edit)

        # Options row
        or_ = QHBoxLayout(); or_.setSpacing(20)
        r_root = QRadioButton("Only root items"); r_root.setChecked(True)
        r_rec  = QRadioButton("All subfolders (recursive)")
        grp = QButtonGroup(self); grp.addButton(r_root); grp.addButton(r_rec)
        or_.addWidget(r_root); or_.addWidget(r_rec)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#aaaaaa;"); or_.addWidget(sep)
        cb_fold = QCheckBox("Folder names"); cb_fold.setChecked(True)
        cb_file = QCheckBox("File names"); cb_file.setChecked(False)
        def make_guard(a, b):
            def g(_):
                if not a.isChecked() and not b.isChecked(): a.setChecked(True)
            return g
        cb_fold.stateChanged.connect(make_guard(cb_fold, cb_file))
        cb_file.stateChanged.connect(make_guard(cb_file, cb_fold))
        or_.addWidget(cb_fold); or_.addWidget(cb_file); or_.addStretch()
        lay.addLayout(or_)
        setattr(self, f"{prefix}_radio_only_root", r_root)
        setattr(self, f"{prefix}_radio_recursive",  r_rec)
        setattr(self, f"{prefix}_cb_folders", cb_fold)
        setattr(self, f"{prefix}_cb_files",   cb_file)

        # Action buttons
        br = QHBoxLayout(); br.setSpacing(8)
        bs = QPushButton("Scan"); be = QPushButton("Export Preview TXT")
        bi = QPushButton("Import TXT")
        bs.setToolTip("Read the folder at Source path and fill the preview.")
        be.setToolTip("Save current preview to a .txt file inside the source folder.")
        bi.setToolTip("Load a previously exported .txt file into the preview.")
        bs.clicked.connect(scan_cb); be.clicked.connect(export_cb); bi.clicked.connect(import_cb)
        for b in (bs, be, bi): b.setFixedHeight(26); br.addWidget(b)
        lay.addLayout(br)

        pl2 = QLabel("Structure Preview  (editable)")
        pl2.setStyleSheet("font-weight:bold;font-size:12px;"); lay.addWidget(pl2)
        preview = LineNumberedEditor()
        lay.addWidget(preview, stretch=1)
        setattr(self, f"{prefix}_preview", preview)

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _hr(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#d0d0d0;"); return f

    def _legend_item(self, color, text):
        w = QWidget(); hl = QHBoxLayout(w)
        hl.setContentsMargins(4,2,8,2); hl.setSpacing(6)
        sw = QLabel(); sw.setFixedSize(18,18)
        sw.setStyleSheet(f"background-color:{color};border:1px solid #999;border-radius:3px;")
        lb = QLabel(text); lb.setStyleSheet(self.LABEL_S+"font-weight:600;font-size:11px;")
        hl.addWidget(sw); hl.addWidget(lb); return w

    def _blue_btn_style(self):
        return ("QPushButton{background-color:#0066cc;color:white;font-weight:bold;"
                "min-width:200px;border-radius:6px;}"
                "QPushButton:hover{background-color:#0077e6;}"
                "QPushButton:pressed{background-color:#0055b3;}")

    def _green_btn_style(self):
        return ("QPushButton{background-color:#4CAF50;color:white;font-weight:bold;"
                "min-width:200px;border-radius:6px;}"
                "QPushButton:hover{background-color:#66BB6A;}"
                "QPushButton:pressed{background-color:#388E3C;}")

    # ── Content propagation ──────────────────────────────────────────────────
    def _on_left_changed(self):
        text = self.left_preview.toPlainText()
        current_lines = [l for l in text.splitlines() if l.strip()]
        if len(current_lines) != len(self._left_abs_paths):
            self._left_abs_paths = []
        # Propagate to Tab 2 left mirror and Tab 3 left mirror
        self.tab2_left_mirror.setPlainText(text)
        self.tab3_left_mirror.setPlainText(text)
        # Update Tree tab source path label
        src = self.left_path_edit.text().strip()
        if src and os.path.isdir(src):
            self.tree_path_label.setText(src)
            self.tree_path_label.setStyleSheet(self.LABEL_S)
        else:
            self.tree_path_label.setText("(none — scan a folder in Tab 1 first)")
            self.tree_path_label.setStyleSheet(self.LABEL_S+"color:#aaaaaa;")

    def _on_right_changed(self):
        text = self.right_preview.toPlainText()
        self.tab2_right_editor.setPlainText(text)

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
            for prefix in ("left", "right"):
                kr = f"{prefix}_recursive"
                if kr in data:
                    if data[kr]: getattr(self,f"{prefix}_radio_recursive").setChecked(True)
                    else:        getattr(self,f"{prefix}_radio_only_root").setChecked(True)
                kf, ki = f"{prefix}_folders", f"{prefix}_files"
                if kf in data and ki in data:
                    lf, li = bool(data[kf]), bool(data[ki])
                    cbf = getattr(self,f"{prefix}_cb_folders")
                    cbi = getattr(self,f"{prefix}_cb_files")
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
        except Exception:
            pass

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
            with open(LAST_PATHS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception: pass
        super().closeEvent(event)

    # ── Sync scroll ──────────────────────────────────────────────────────────
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

    # ── Scan ─────────────────────────────────────────────────────────────────
    def _do_scan(self, prefix):
        path = getattr(self, f"{prefix}_path_edit").text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Error", "Source path is not a valid folder."); return
        rec  = getattr(self, f"{prefix}_radio_recursive").isChecked()
        incf = getattr(self, f"{prefix}_cb_folders").isChecked()
        inci = getattr(self, f"{prefix}_cb_files").isChecked()
        try:
            lines, abs_paths = get_folder_structure_with_paths(path, rec, incf, inci)
            self._pause_compare()
            getattr(self, f"{prefix}_preview").setPlainText("\n".join(lines))
            self._resume_compare()
            if prefix == "left":
                self._left_abs_paths = abs_paths
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot read structure:\n{e}")

    def scan_left(self):  self._do_scan("left")
    def scan_right(self): self._do_scan("right")

    # ── Browse ───────────────────────────────────────────────────────────────
    def browse_left_source(self):
        f = QFileDialog.getExistingDirectory(self,"Select Folder",self.left_path_edit.text())
        if f: self.left_path_edit.setText(f)

    def browse_right_source(self):
        f = QFileDialog.getExistingDirectory(self,"Select Folder",self.right_path_edit.text())
        if f: self.right_path_edit.setText(f)

    # ── Export / Import ──────────────────────────────────────────────────────
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
        msg = QMessageBox(self); msg.setWindowTitle("File Already Exists")
        msg.setIcon(QMessageBox.Icon.Question); msg.setText(f"File already exists:\n{txt_path}")
        msg.setInformativeText("What would you like to do?")
        ow = msg.addButton("Overwrite", QMessageBox.ButtonRole.YesRole)
        nc = msg.addButton("Create numbered copy", QMessageBox.ButtonRole.NoRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole); msg.exec()
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
        msg = QMessageBox(self); msg.setWindowTitle("Export Successful")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("Preview exported"); msg.setInformativeText(f"Location:\n{path}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        ob = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        msg.exec()
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
        txt,_=QFileDialog.getOpenFileName(self,"Select .txt file","","Text files (*.txt);;All files (*.*)")
        if not txt: return
        try:
            with open(txt, encoding="utf-8") as f:
                lines=[l.rstrip() for l in f if l.strip() and not l.strip().startswith('#')]
            self._pause_compare()
            getattr(self, f"{prefix}_preview").setPlainText("\n".join(lines))
            self._resume_compare()
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot load TXT file:\n{e}")

    def import_txt_left(self):  self._import_txt("left")
    def import_txt_right(self): self._import_txt("right")

    # ── Line-by-line color compare ───────────────────────────────────────────
    def _both_previews_have_content(self):
        return (bool(self.left_preview.toPlainText().strip()) and
                bool(self.right_preview.toPlainText().strip()))

    def _pause_compare(self):
        if hasattr(self,'_compare_timer'): self._compare_timer.stop()
        self._coloring_in_progress = True

    def _resume_compare(self):
        self._coloring_in_progress = False
        if self._line_compare_active:
            if self._both_previews_have_content(): self._apply_line_colors()
            else: self._clear_line_colors()

    def toggle_line_compare(self):
        if not self._line_compare_active and not self._both_previews_have_content():
            QMessageBox.information(self,"Compare Names",
                "Please scan or load a structure into both previews first."); return
        self._line_compare_active = not self._line_compare_active
        if self._line_compare_active:
            self.btn_compare_names.setText("Compare Left and Right Names Line by Line  ✔  ON")
            self.btn_compare_names.setStyleSheet("""
                QPushButton{background-color:#4CAF50;color:white;font-weight:bold;
                    font-size:13px;border-radius:6px;}
                QPushButton:hover{background-color:#66BB6A;}
                QPushButton:pressed{background-color:#388E3C;}""")
            if not hasattr(self,'_compare_timer'):
                self._compare_timer = QTimer(self)
                self._compare_timer.setSingleShot(True); self._compare_timer.setInterval(150)
                self._compare_timer.timeout.connect(self._apply_line_colors)
                self.left_preview.text_changed.connect(self._schedule_color_update)
                self.right_preview.text_changed.connect(self._schedule_color_update)
            self._apply_line_colors()
        else:
            self.btn_compare_names.setText("Compare Left and Right Names Line by Line")
            self.btn_compare_names.setStyleSheet("""
                QPushButton{background-color:#707070;color:white;font-weight:bold;
                    font-size:13px;border-radius:6px;}
                QPushButton:hover{background-color:#888888;}
                QPushButton:pressed{background-color:#555555;}""")
            if hasattr(self,'_compare_timer'): self._compare_timer.stop()
            self._clear_line_colors()

    def _schedule_color_update(self):
        if self._line_compare_active and not self._coloring_in_progress:
            if hasattr(self,'_compare_timer'): self._compare_timer.start()

    def _clear_line_colors(self):
        self._coloring_in_progress = True
        try:
            for pv in (self.left_preview, self.right_preview):
                doc=pv.editor.document(); doc.blockSignals(True)
                try:
                    cur=QTextCursor(doc); cur.beginEditBlock()
                    cur.select(QTextCursor.SelectionType.Document)
                    fmt=QTextCharFormat(); fmt.setBackground(QColor("white"))
                    cur.setCharFormat(fmt); cur.clearSelection(); cur.endEditBlock()
                finally: doc.blockSignals(False)
                pv._update_gutter_width(); pv._gutter.update()
        finally: self._coloring_in_progress = False

    def _apply_line_colors(self):
        if self._coloring_in_progress or not self._line_compare_active: return
        self._coloring_in_progress = True
        try:
            EQ=QColor("#b8f0b8"); DF=QColor("#f0b8b8"); ON=QColor("#f0f0b0")
            ll=self.left_preview.editor.document().toPlainText().splitlines()
            rl=self.right_preview.editor.document().toPlainText().splitlines()
            def _col(pv, lines, partner):
                doc=pv.editor.document(); doc.blockSignals(True)
                try:
                    cur=QTextCursor(doc); cur.beginEditBlock()
                    for i in range(doc.blockCount()):
                        bl=doc.findBlockByNumber(i)
                        if not bl.isValid(): break
                        bc=QTextCursor(bl); bc.select(QTextCursor.SelectionType.BlockUnderCursor)
                        fmt=QTextCharFormat()
                        if i>=len(partner): fmt.setBackground(ON)
                        elif lines[i].strip()==partner[i].strip(): fmt.setBackground(EQ)
                        else: fmt.setBackground(DF)
                        bc.setCharFormat(fmt)
                    cur.endEditBlock()
                finally: doc.blockSignals(False)
                pv._update_gutter_width(); pv._gutter.update()
            _col(self.left_preview, ll, rl)
            _col(self.right_preview, rl, ll)
        finally: self._coloring_in_progress = False

    # ── Compare Structures ───────────────────────────────────────────────────
    def compare_previews(self):
        ll=[l.rstrip() for l in self.left_preview.toPlainText().splitlines()]
        rl=[l.rstrip() for l in self.right_preview.toPlainText().splitlines()]
        if not ll and not rl:
            QMessageBox.information(self,"Compare","Both previews are empty."); return
        ComparisonDialog(ll, rl, self).exec()

    # ── Replicate (kept for completeness — no dedicated button in new layout,
    #    but batch_rename still calls it; user can also call via Python REPL) ──
    def _replicate(self, prefix):
        preview = getattr(self, f"{prefix}_preview")
        lines = [l.rstrip() for l in preview.toPlainText().splitlines() if l.strip()]
        if not lines:
            QMessageBox.warning(self,"Error","No structure in preview to replicate."); return
        dest = QFileDialog.getExistingDirectory(
            self,"Select destination folder for new structure")
        if not dest or not os.path.isdir(dest): return
        try:
            self.create_from_lines(dest, lines)
            msg = QMessageBox(self); msg.setWindowTitle("Replication Successful")
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

    # ── Batch Rename ──────────────────────────────────────────────────────────
    def batch_rename(self):
        # Read from the Tab-2 mirrors (which are always in sync with tab1 previews)
        left_lines_raw  = self.tab2_left_mirror.toPlainText().splitlines()
        right_lines_raw = self.tab2_right_editor.toPlainText().splitlines()

        left_lines  = [l.rstrip() for l in left_lines_raw  if l.strip()]
        right_lines = [l.rstrip() for l in right_lines_raw if l.strip()]

        if not left_lines or not right_lines:
            QMessageBox.warning(self,"Batch Rename","Both previews must contain names."); return
        if len(left_lines) != len(right_lines):
            QMessageBox.warning(self,"Batch Rename",
                f"Line count mismatch!\nLeft: {len(left_lines)} lines  |  "
                f"Right: {len(right_lines)} lines\n"
                "Both previews must have the same number of non-empty lines."); return

        root = self.left_path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.warning(self,"Batch Rename","Please set a valid Left source folder path."); return

        # Resolve absolute paths
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
        for i,(old_abs,right_line) in enumerate(zip(left_abs_paths,right_lines)):
            old_name=os.path.basename(old_abs); new_name=right_line.strip()
            if not new_name or new_name==old_name: continue
            new_abs=os.path.join(os.path.dirname(old_abs),new_name)
            ops.append((old_abs,new_abs,old_name,new_name))

        if not ops:
            QMessageBox.information(self,"Batch Rename","No differences found — nothing to rename."); return

        # Confirm dialog
        dlg=QDialog(self); dlg.setWindowTitle("Confirm Batch Rename"); dlg.resize(680,420)
        cl=QVBoxLayout(dlg); cl.setContentsMargins(16,16,16,12); cl.setSpacing(10)
        hdr=QLabel(f"About to rename <b>{len(ops)}</b> item(s) inside:<br><code>{root}</code>")
        hdr.setWordWrap(True); cl.addWidget(hdr)
        wi=QLabel("⚠  Make sure no files or folders are open in other programs before proceeding.")
        wi.setWordWrap(True); wi.setStyleSheet("color:#cc6600;"); cl.addWidget(wi)
        cl2=QLabel("<b>Current name (left)</b>  →  <b>New name (right)</b>")
        cl2.setStyleSheet("font-family:'Segoe UI',sans-serif;font-size:12px;color:#555;")
        cl.addWidget(cl2)
        sc=QTextEdit(); sc.setReadOnly(True); sc.setFont(QFont("Courier New",11))
        sc.setPlainText("\n".join(f"  {o}  →  {n}" for _,_,o,n in ops))
        cl.addWidget(sc,stretch=1)
        br=QHBoxLayout(); br.setSpacing(10); br.addStretch()
        cn=QPushButton("Cancel"); cn.setFixedHeight(34); cn.setFixedWidth(120)
        cn.clicked.connect(dlg.reject); br.addWidget(cn)
        co=QPushButton("Rename"); co.setFixedHeight(34); co.setFixedWidth(120)
        co.setDefault(True)
        co.setStyleSheet("background-color:#e65c00;color:white;font-weight:bold;border-radius:4px;")
        co.clicked.connect(dlg.accept); br.addWidget(co); cl.addLayout(br)
        if dlg.exec() != QDialog.DialogCode.Accepted: return

        # Two-phase safe rename with conflict detection and rollback
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
                os.rename(old_r,tmp)
                current_abs_map[old_abs]=tmp
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
                os.rename(tmp,final)
                renamed.append(f"{old_name}  →  {new_name}")
            except Exception as e:
                try: os.rename(tmp,orig); rb="  (✔ rolled back to original)"
                except Exception as re2:
                    rb=(f"  ⚠ ROLLBACK FAILED — currently named:\n  {tmp}\n"
                        f"  Rename back to: {os.path.basename(orig)}\n  {re2}")
                failed.append(f'FAILED phase2  "{old_name}"  →  "{new_name}"\n  {e}\n{rb}')

        # Result
        sl=[]
        if renamed:
            sl.append(f"✅  Renamed {len(renamed)} item(s) successfully.\n")
            sl.extend(f"  {r}" for r in renamed)
        if conflicts:
            if sl: sl.append("")
            sl.append(f"⚠️  {len(conflicts)} conflict(s) — originals preserved:")
            sl.append("")
            for c in conflicts: sl.append(f"  {c}"); sl.append("")
        if skipped:
            if sl: sl.append("")
            sl.append(f"⚠️  {len(skipped)} item(s) not found on disk:")
            sl.append("")
            for s in skipped: sl.append(f"  {s}")
        if failed:
            if sl: sl.append("")
            sl.append(f"❌  {len(failed)} error(s):")
            sl.append("")
            for fm in failed: sl.append(f"  {fm}"); sl.append("")
        full="\n".join(sl)

        rd=QDialog(self); rd.setWindowTitle("Batch Rename Complete"); rd.resize(700,400)
        rl2=QVBoxLayout(rd); rl2.setContentsMargins(16,16,16,12); rl2.setSpacing(10)
        se=QTextEdit(); se.setReadOnly(True); se.setFont(QFont("Courier New",11))
        se.setPlainText(full); rl2.addWidget(se,stretch=1)
        rb2=QHBoxLayout(); rb2.setSpacing(10)
        cb2=QPushButton("Copy to Clipboard"); cb2.setFixedHeight(34)
        cb2.clicked.connect(lambda: QApplication.clipboard().setText(full)); rb2.addWidget(cb2)
        rb2.addStretch()
        ob2=QPushButton("Open Folder"); ob2.setFixedHeight(34)
        ob2.clicked.connect(lambda: self._open_folder(root)); rb2.addWidget(ob2)
        ok2=QPushButton("OK"); ok2.setFixedHeight(34); ok2.setDefault(True)
        ok2.clicked.connect(rd.accept); rb2.addWidget(ok2); rl2.addLayout(rb2)
        rd.exec()

    # ── Tree diagram tab actions ──────────────────────────────────────────────
    def _generate_tree(self):
        text = self.left_preview.toPlainText().strip()
        if not text:
            QMessageBox.warning(self,"Generate Tree",
                "The left preview is empty.\nPlease scan a folder in Tab 1 first."); return
        lines = [l for l in text.splitlines() if l.strip()]
        # Root name: custom or folder name
        root_name = self.tree_root_edit.text().strip()
        if not root_name:
            src = self.left_path_edit.text().strip()
            root_name = os.path.basename(src) if src else "project"
        tree_text = build_tree_diagram(lines, root_name)
        self.tree_output.setPlainText(tree_text)

    def _export_tree(self):
        tree_text = self.tree_output.toPlainText().strip()
        if not tree_text:
            QMessageBox.warning(self,"Export Tree",
                "The tree diagram is empty.\nClick 'Generate Tree' first."); return
        src = self.left_path_edit.text().strip()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self,"Export Tree",
                "No valid source folder is set.\nPlease scan a folder in Tab 1 first."); return
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
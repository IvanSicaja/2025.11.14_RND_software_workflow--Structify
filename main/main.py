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
    QDialog, QCheckBox, QFrame, QTabWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor, QPainter,
    QKeySequence, QTextBlockFormat
)

LAST_PATHS_FILE = "structify_last_paths.json"
EDITOR_FONT_FAMILY = "SF Mono"
EDITOR_FONT_SIZE   = 12
EDITOR_LINE_HEIGHT = 16

# ── Folder structure helpers ──────────────────────────────────────────────────

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

# ── Tree diagram generator ────────────────────────────────────────────────────

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
        is_last = is_last_at_depth(i); hc = has_children(i); folder = not is_file(name)
        display = name + ("/" if folder and hc else "")
        full = bar_prefix(i, depth) + ("└── " if is_last else "├── ") + display
        pad = max(1, 52 - len(full))
        result.append(full + " " * pad + "# ← add description here")
        if folder and hc:
            result.append(sep(i, items[i+1][0]))
        if i+1 < len(items) and items[i+1][0] == 0:
            result.append("│")
    return "\n".join(result)

# ── LineNumberArea ────────────────────────────────────────────────────────────

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor
    def sizeHint(self):
        from PyQt6.QtCore import QSize as S
        return S(self._editor._gutter_width(), 0)
    def paintEvent(self, event):
        self._editor._paint_gutter(event)

# ── LineNumberedEditor ────────────────────────────────────────────────────────
#
# Key design decisions:
#
# 1. Blank-line handling: blank lines are only stripped when content is LOADED
#    programmatically (setPlainText). While the user types, blank lines are
#    preserved so that Enter, Backspace, and cursor movement all feel natural.
#
# 2. Paste normalization: pasted text is stripped of foreign fonts/sizes/colours
#    but blank lines in the pasted content ARE preserved.  Only fully-empty
#    paragraphs that appear at the very start or end are trimmed.
#
# 3. Shift+Alt+Up/Down moves the current line (or selection) up/down exactly
#    like PyCharm / VS Code. Works safely — no file is touched.
#
# 4. Fixed line-height is applied without removing content or cursor position.

class LineNumberedEditor(QWidget):
    text_changed = pyqtSignal()

    def _make_font(self): return QFont(EDITOR_FONT_FAMILY, EDITOR_FONT_SIZE)

    # ── Apply uniform formatting without removing blank lines ─────────────────
    def _apply_char_format_only(self):
        """Apply font + line-height to every block WITHOUT removing blank lines."""
        doc = self.editor.document()
        cf = QTextCharFormat(); cf.setFont(self._make_font())
        bf = QTextBlockFormat()
        bf.setLineHeight(EDITOR_LINE_HEIGHT, 4)
        bf.setTopMargin(0); bf.setBottomMargin(0)
        doc.blockSignals(True)
        try:
            cur = QTextCursor(doc); cur.beginEditBlock()
            cur.select(QTextCursor.SelectionType.Document)
            cur.setCharFormat(cf); cur.setBlockFormat(bf)
            cur.clearSelection(); cur.endEditBlock()
        finally:
            doc.blockSignals(False)
        self._update_gutter_width(); self._gutter.update()

    # ── Public proxy methods ──────────────────────────────────────────────────
    def setPlainText(self, text):
        """Load content (blank lines stripped), reset scroll, emit text_changed."""
        doc = self.editor.document()
        doc.blockSignals(True); self.editor.blockSignals(True)
        try:
            lines = [ln for ln in text.splitlines() if ln.strip()]
            self.editor.setPlainText("\n".join(lines))
        finally:
            doc.blockSignals(False); self.editor.blockSignals(False)
        self._apply_char_format_only()
        self.editor.horizontalScrollBar().setValue(0)
        self.text_changed.emit()

    def toPlainText(self):    return self.editor.toPlainText()
    def setReadOnly(self, v): self.editor.setReadOnly(v)
    def setFont(self, font):  self.editor.setFont(font)

    # ── Constructor ───────────────────────────────────────────────────────────
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = QTextEdit(self)
        self.editor.setFont(self._make_font())
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor.setStyleSheet("""
            QTextEdit { background-color:#ffffff; color:#000000; border:none; padding:2px 8px; }
            QScrollBar:vertical { background:#d8d8d8; width:12px; border-radius:6px; }
            QScrollBar::handle:vertical { background:#888; min-height:24px; border-radius:6px; }
            QScrollBar::handle:vertical:hover { background:#555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
            QScrollBar:horizontal { background:#d8d8d8; height:12px; border-radius:6px; }
            QScrollBar::handle:horizontal { background:#888; min-width:24px; border-radius:6px; }
            QScrollBar::handle:horizontal:hover { background:#555; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0px; }
        """)
        self._gutter = LineNumberArea(self)
        h = QHBoxLayout(self); h.setContentsMargins(0,0,0,0); h.setSpacing(0)
        h.addWidget(self._gutter); h.addWidget(self.editor)
        self.setStyleSheet(
            "LineNumberedEditor{border:1px solid #d0d4d8;border-radius:6px;"
            "background-color:#ffffff;}")
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.editor.document().blockCountChanged.connect(self._update_gutter_width)
        self.editor.verticalScrollBar().valueChanged.connect(self._gutter.update)
        self.editor.document().documentLayout().documentSizeChanged.connect(
            lambda _: self._gutter.update())
        # Debounced formatting (font/line-height only, no blank-line removal)
        self._fmt_timer = QTimer(self)
        self._fmt_timer.setSingleShot(True); self._fmt_timer.setInterval(120)
        self._fmt_timer.timeout.connect(self._on_fmt_timer)
        self._formatting = False
        self.editor.document().contentsChanged.connect(self._schedule_fmt)
        self.editor.document().contentsChanged.connect(self.text_changed)
        # Install key-event filter for Shift+Alt+Up/Down (move line)
        self.editor.installEventFilter(self)
        self._update_gutter_width(); self._apply_char_format_only()

    def _schedule_fmt(self):
        if not self._formatting: self._fmt_timer.start()

    def _on_fmt_timer(self):
        if self._formatting: return
        self._formatting = True
        try: self._apply_char_format_only()
        finally: self._formatting = False

    # ── Shift+Alt+Up/Down — move line(s) ─────────────────────────────────────
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent
        if obj is self.editor and event.type() == QEvent.Type.KeyPress:
            ke = event
            shift = ke.modifiers() & Qt.KeyboardModifier.ShiftModifier
            alt   = ke.modifiers() & Qt.KeyboardModifier.AltModifier
            key   = ke.key()
            if shift and alt and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._move_line(up=(key == Qt.Key.Key_Up))
                return True   # consumed
        return super().eventFilter(obj, event)

    def _move_line(self, up: bool):
        """Move the line(s) under the cursor (or selection) one position up/down."""
        cur = self.editor.textCursor()
        doc = self.editor.document()

        # Determine the range of blocks to move
        sel_start = cur.selectionStart()
        sel_end   = cur.selectionEnd()
        block_start = doc.findBlock(sel_start).blockNumber()
        block_end   = doc.findBlock(sel_end).blockNumber()
        # If selection ends at the very start of a block, don't include that block
        if cur.hasSelection():
            tmp = QTextCursor(doc.findBlockByNumber(block_end))
            if tmp.position() == sel_end and block_end > block_start:
                block_end -= 1

        n_blocks = doc.blockCount()

        if up and block_start == 0: return
        if not up and block_end == n_blocks - 1: return

        # Collect all lines as plain text
        all_lines = doc.toPlainText().split("\n")

        if up:
            swap_with = block_start - 1
            # Move the block range up by one
            moved = all_lines[block_start:block_end+1]
            pivot = [all_lines[swap_with]]
            new_lines = (all_lines[:swap_with] + moved + pivot +
                         all_lines[block_end+1:])
            new_anchor = block_start - 1
        else:
            swap_with = block_end + 1
            # Move the block range down by one
            moved = all_lines[block_start:block_end+1]
            pivot = [all_lines[swap_with]]
            new_lines = (all_lines[:block_start] + pivot + moved +
                         all_lines[swap_with+1:])
            new_anchor = block_start + 1

        # Replace document content without triggering normalizer
        doc.blockSignals(True); self.editor.blockSignals(True)
        try:
            self.editor.setPlainText("\n".join(new_lines))
        finally:
            doc.blockSignals(False); self.editor.blockSignals(False)

        # Restore selection on moved blocks
        n_moved = block_end - block_start + 1
        new_b_start = new_anchor
        new_b_end   = new_anchor + n_moved - 1

        new_start_pos = doc.findBlockByNumber(new_b_start).position()
        new_end_block = doc.findBlockByNumber(new_b_end)
        new_end_pos   = new_end_block.position() + new_end_block.length() - 1

        c2 = self.editor.textCursor()
        c2.setPosition(new_start_pos)
        c2.setPosition(new_end_pos, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(c2)

        self._apply_char_format_only()
        self.text_changed.emit()

    # ── Gutter ────────────────────────────────────────────────────────────────
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
                f = self.editor.font(); f.setPointSize(f.pointSize()-1); painter.setFont(f)
                painter.drawText(0, top, self._gutter.width()-4, int(br.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(block_num))
            block = block.next(); block_num += 1
        painter.end()

# ── Main Application ──────────────────────────────────────────────────────────

class FolderStructureApp(QMainWindow):

    LS = ("font-family:'Segoe UI','SF Pro Text','Helvetica Neue',Arial,sans-serif;"
          "font-size:11px;color:#e0e0e0;")

    # ── Colour constants ──────────────────────────────────────────────────────
    C_BOTH  = QColor("#b8f0b8")   # green  — same / found in both
    C_DIFF  = QColor("#f0b8b8")   # red    — different (tab2 line compare)
    C_ONLY  = QColor("#f0f0b0")   # yellow — only on one side
    C_CLEAR = QColor("white")

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

        # ── State flags ──
        self._tab1_compare_active   = False   # inline colour compare for Tab 1
        self._t2_compare_active     = False   # line-by-line compare for Tab 2
        self._coloring_in_progress  = False   # reentrancy guard (shared)
        self._sync_scroll_active    = False
        self._syncing_scroll        = False
        self._left_abs_paths        = []
        self._tab2_initialized      = False
        self._tab3_initialized      = False

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

    # ── Shared widget helpers ─────────────────────────────────────────────────
    def _hr(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#555;margin:1px 0;"); return f

    def _legend_item(self, color, text, prefix=""):
        w = QWidget(); hl = QHBoxLayout(w)
        hl.setContentsMargins(2,1,6,1); hl.setSpacing(5)
        sw = QLabel(prefix); sw.setFixedSize(20,18)
        sw.setStyleSheet(
            f"background-color:{color};border:1px solid #999;border-radius:3px;"
            f"font-weight:bold;color:#333;font-size:10px;"
            f"qproperty-alignment:AlignCenter;")
        lb = QLabel(text); lb.setStyleSheet(self.LS+"font-weight:600;font-size:10px;")
        hl.addWidget(sw); hl.addWidget(lb); return w

    def _blue_btn(self): return (
        "QPushButton{background-color:#0066cc;color:white;font-weight:bold;"
        "min-width:160px;border-radius:5px;padding:3px 10px;}"
        "QPushButton:hover{background-color:#0077e6;}"
        "QPushButton:pressed{background-color:#0055b3;}")
    def _green_btn(self): return (
        "QPushButton{background-color:#4CAF50;color:white;font-weight:bold;"
        "min-width:160px;border-radius:5px;padding:3px 10px;}"
        "QPushButton:hover{background-color:#66BB6A;}"
        "QPushButton:pressed{background-color:#388E3C;}")
    def _orange_btn(self): return (
        "QPushButton{background-color:#e65c00;color:white;font-weight:bold;"
        "min-width:180px;border-radius:5px;padding:3px 10px;}"
        "QPushButton:hover{background-color:#ff6a00;}"
        "QPushButton:pressed{background-color:#c24f00;}")
    def _make_btn(self, text, style, height=26, tooltip=""):
        b = QPushButton(text); b.setStyleSheet(style); b.setFixedHeight(height)
        if tooltip: b.setToolTip(tooltip); return b

    # ── Shared preview panel builder ──────────────────────────────────────────
    def _build_preview_panel(self, parent_layout, title, prefix,
                              scan_cb, export_cb, import_cb, browse_cb,
                              read_only=False, stretch=1):
        col = QVBoxLayout(); col.setSpacing(4)
        parent_layout.addLayout(col, stretch=stretch)
        lbl = QLabel(title); lbl.setStyleSheet("font-weight:bold;font-size:12px;")
        col.addWidget(lbl)
        # Path row
        pr = QHBoxLayout(); pr.setSpacing(4)
        pl = QLabel("Source:"); pl.setFixedWidth(52); pl.setStyleSheet(self.LS)
        pr.addWidget(pl)
        edit = QLineEdit(); edit.setPlaceholderText("Select a folder …")
        edit.setFixedHeight(24); pr.addWidget(edit)
        bb = QPushButton("Browse"); bb.setFixedWidth(68); bb.setFixedHeight(24)
        bb.clicked.connect(browse_cb); pr.addWidget(bb)
        col.addLayout(pr)
        setattr(self, f"{prefix}_path_edit", edit)
        # Options row
        or_ = QHBoxLayout(); or_.setSpacing(14)
        r_root = QRadioButton("Only root items"); r_root.setChecked(True)
        r_rec  = QRadioButton("All subfolders (recursive)")
        for r in (r_root, r_rec): r.setStyleSheet("font-size:11px;")
        grp = QButtonGroup(self); grp.addButton(r_root); grp.addButton(r_rec)
        or_.addWidget(r_root); or_.addWidget(r_rec)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color:#666;"); or_.addWidget(sep2)
        cb_fold = QCheckBox("Folders"); cb_fold.setChecked(True)
        cb_file = QCheckBox("Files");   cb_file.setChecked(False)
        for c in (cb_fold, cb_file): c.setStyleSheet("font-size:11px;")
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
        # Action buttons row
        br = QHBoxLayout(); br.setSpacing(6)
        bs = QPushButton("Scan"); be = QPushButton("Export TXT"); bi = QPushButton("Import TXT")
        bs.setToolTip("Read the folder at Source and fill the preview.")
        be.setToolTip("Save current preview as a .txt file inside the source folder.")
        bi.setToolTip("Load a .txt file into the preview.")
        bs.clicked.connect(scan_cb); be.clicked.connect(export_cb)
        bi.clicked.connect(import_cb)
        for b in (bs, be, bi): b.setFixedHeight(24); br.addWidget(b)
        col.addLayout(br)
        # Preview label
        pl2 = QLabel("Structure Preview" + (" (read-only)" if read_only else " (editable)"))
        pl2.setStyleSheet("font-weight:bold;font-size:11px;"); col.addWidget(pl2)
        preview = LineNumberedEditor()
        if read_only:
            preview.setReadOnly(True)
            preview.editor.setStyleSheet(
                preview.editor.styleSheet().replace("#ffffff","#f5f5f5"))
        col.addWidget(preview, stretch=1)
        setattr(self, f"{prefix}_preview", preview)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 1 — Compare & Explore  (inline colour compare, no popup)
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab1(self):
        self.tab1 = QWidget()
        lay = QVBoxLayout(self.tab1)
        lay.setContentsMargins(10,8,10,6); lay.setSpacing(5)

        hint = QLabel(
            "Scan two folder structures and compare them directly in the previews below.  "
            "Green = same name exists in both (at same depth level).  "
            "Yellow = only on one side.  Comparison is order-insensitive.")
        hint.setStyleSheet(self.LS); hint.setWordWrap(True); lay.addWidget(hint)

        # Two scan panels
        panels = QHBoxLayout(); panels.setSpacing(12)
        lay.addLayout(panels, stretch=1)
        self._build_preview_panel(panels, "Source Folder 1", "left",
                                  self.scan_left, self.export_left,
                                  self.import_txt_left, self.browse_left_source)
        self._build_preview_panel(panels, "Source Folder 2", "right",
                                  self.scan_right, self.export_right,
                                  self.import_txt_right, self.browse_right_source)

        # Sync scroll + Compare toggle row
        bot = QHBoxLayout(); bot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bot.setSpacing(20); lay.addLayout(bot)

        self.cb_sync_scroll = QCheckBox(
            "Sync scroll — both previews scroll together")
        self.cb_sync_scroll.setStyleSheet(self.LS+"font-weight:500;")
        self.cb_sync_scroll.setChecked(True)
        self.cb_sync_scroll.stateChanged.connect(self._on_sync_scroll_toggled)
        bot.addWidget(self.cb_sync_scroll)

        self.btn_t1_compare = self._make_btn(
            "Compare Structures  (highlight differences)",
            self._green_btn(), 28,
            "Colour-highlight each line directly in the previews:\n"
            "Green = same name exists in both  |  Yellow = only on one side.\n"
            "Click again to clear colours.")
        self.btn_t1_compare.clicked.connect(self._toggle_tab1_compare)
        bot.addWidget(self.btn_t1_compare)

        lay.addWidget(self._hr())
        # Legend
        leg_row = QHBoxLayout(); leg_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        leg_row.setSpacing(16); lay.addLayout(leg_row)
        leg_row.addWidget(QLabel("Legend:", styleSheet=self.LS+"font-weight:600;"))
        for color, desc in [
            ("#b8f0b8", "Same name found in both structures (at this depth)"),
            ("#f0f0b0", "Only on this side — not found in the other structure"),
        ]:
            leg_row.addWidget(self._legend_item(color, desc))
        leg_row.addStretch()

    # ── Tab 1 inline compare ──────────────────────────────────────────────────

    def _toggle_tab1_compare(self):
        self._tab1_compare_active = not self._tab1_compare_active
        if self._tab1_compare_active:
            self.btn_t1_compare.setText("Clear Comparison  (click to remove colours)")
            self.btn_t1_compare.setStyleSheet(
                "QPushButton{background-color:#888;color:white;font-weight:bold;"
                "min-width:160px;border-radius:5px;padding:3px 10px;}"
                "QPushButton:hover{background-color:#aaa;}"
                "QPushButton:pressed{background-color:#666;}")
            self._apply_tab1_colors()
            if not hasattr(self, '_t1_timer'):
                self._t1_timer = QTimer(self)
                self._t1_timer.setSingleShot(True); self._t1_timer.setInterval(200)
                self._t1_timer.timeout.connect(self._apply_tab1_colors)
                self.left_preview.text_changed.connect(self._t1_timer.start)
                self.right_preview.text_changed.connect(self._t1_timer.start)
        else:
            self.btn_t1_compare.setText("Compare Structures  (highlight differences)")
            self.btn_t1_compare.setStyleSheet(self._green_btn())
            if hasattr(self, '_t1_timer'): self._t1_timer.stop()
            self._clear_colors(self.left_preview)
            self._clear_colors(self.right_preview)

    def _apply_tab1_colors(self):
        """
        Order-insensitive, level-by-level inline colouring for Tab 1.
        Green  = name exists in both structures at the same depth level.
        Yellow = name exists only on this side.
        """
        if self._coloring_in_progress or not self._tab1_compare_active: return
        self._coloring_in_progress = True
        try:
            def parse_levels(preview):
                by_level = {}
                for line in preview.editor.document().toPlainText().splitlines():
                    if not line.strip(): continue
                    depth = (len(line) - len(line.lstrip())) // 2
                    by_level.setdefault(depth, set()).add(line.strip())
                return by_level

            left_lv  = parse_levels(self.left_preview)
            right_lv = parse_levels(self.right_preview)

            def colour_preview(preview, my_levels, other_levels):
                doc = preview.editor.document()
                doc.blockSignals(True)
                try:
                    cur = QTextCursor(doc); cur.beginEditBlock()
                    for i in range(doc.blockCount()):
                        bl = doc.findBlockByNumber(i)
                        if not bl.isValid(): break
                        line = bl.text()
                        if not line.strip():
                            continue
                        depth = (len(line) - len(line.lstrip())) // 2
                        name  = line.strip()
                        other = other_levels.get(depth, set())
                        color = self.C_BOTH if name in other else self.C_ONLY
                        bc = QTextCursor(bl)
                        bc.select(QTextCursor.SelectionType.BlockUnderCursor)
                        fmt = QTextCharFormat(); fmt.setBackground(color)
                        bc.setCharFormat(fmt)
                    cur.endEditBlock()
                finally:
                    doc.blockSignals(False)
                preview._update_gutter_width(); preview._gutter.update()

            colour_preview(self.left_preview,  left_lv,  right_lv)
            colour_preview(self.right_preview, right_lv, left_lv)
        finally:
            self._coloring_in_progress = False

    # ════════════════════════════════════════════════════════════════════════
    # TAB 2 — Rename Files & Folders
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab2(self):
        self.tab2 = QWidget()
        outer = QVBoxLayout(self.tab2)
        outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        content = QWidget(); lay = QVBoxLayout(content)
        lay.setContentsMargins(10,8,10,6); lay.setSpacing(5)

        hint = QLabel(
            "LEFT = current names on disk (scan a folder, or auto-loaded from Tab 1).  "
            "RIGHT = desired new names — one per line, same order as left.  "
            "Use  →  to copy left → right, then edit.  "
            "Shift+Alt+↑↓ moves a line up/down.")
        hint.setStyleSheet(self.LS); hint.setWordWrap(True); lay.addWidget(hint)

        # Three-column layout: left panel | centre buttons | right panel
        panels = QHBoxLayout(); panels.setSpacing(8)
        lay.addLayout(panels, stretch=1)

        # Left panel
        self._build_preview_panel(
            panels, "Current Names  (left = names that exist on disk right now)",
            "t2_left",
            self._scan_t2_left, self._export_t2_left,
            self._import_t2_left, self._browse_t2_left)

        # Centre action buttons (vertically centred)
        cc = QVBoxLayout(); cc.setSpacing(10)
        cc.setContentsMargins(4,0,4,0)
        cc.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        panels.addLayout(cc)
        cc.addStretch()

        def _circle_btn(symbol, color, tooltip, size=48):
            b = QPushButton(symbol); b.setFixedSize(size, size)
            b.setToolTip(tooltip)
            b.setStyleSheet(
                f"QPushButton{{background-color:{color};color:white;"
                f"font-size:20px;font-weight:bold;border-radius:{size//2}px;}}"
                f"QPushButton:hover{{background-color:{color}dd;}}"
                f"QPushButton:pressed{{background-color:{color}88;}}")
            return b

        btn_copy = _circle_btn("→","#4a90c4",
            "Copy Left preview → Right editor.\n"
            "Then edit the right side to set the desired new names.")
        btn_copy.clicked.connect(self._copy_left_to_right_t2)
        cc.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignHCenter)
        lbl_copy = QLabel("Copy"); lbl_copy.setStyleSheet(self.LS+"font-size:10px;font-weight:600;")
        lbl_copy.setAlignment(Qt.AlignmentFlag.AlignHCenter); cc.addWidget(lbl_copy)

        cc.addSpacing(10)

        self.btn_t2_compare = _circle_btn("≡?","#707070",
            "Compare left and right names line by line.\n"
            "Green = same, Red = different, Yellow = one side only.\nClick again to clear.")
        self.btn_t2_compare.clicked.connect(self._toggle_tab2_compare)
        cc.addWidget(self.btn_t2_compare, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.lbl_t2_cmp = QLabel("Compare")
        self.lbl_t2_cmp.setStyleSheet(self.LS+"font-size:10px;font-weight:600;")
        self.lbl_t2_cmp.setAlignment(Qt.AlignmentFlag.AlignHCenter); cc.addWidget(self.lbl_t2_cmp)

        cc.addSpacing(10)

        btn_apply = _circle_btn("✓","#e65c00",
            "Apply Right Names → rename on disk.\n"
            "Item on Left line N is renamed to Right line N.\n"
            "A confirmation dialog appears before any file is touched.\n"
            "Safe two-phase rename with automatic rollback.")
        btn_apply.clicked.connect(self.batch_rename)
        cc.addWidget(btn_apply, alignment=Qt.AlignmentFlag.AlignHCenter)
        lbl_apply = QLabel("Apply"); lbl_apply.setStyleSheet(self.LS+"font-size:10px;font-weight:600;color:#ff8040;")
        lbl_apply.setAlignment(Qt.AlignmentFlag.AlignHCenter); cc.addWidget(lbl_apply)
        cc.addStretch()

        # Right panel (manual input, no scan controls)
        right_col = QVBoxLayout(); right_col.setSpacing(4)
        panels.addLayout(right_col, stretch=1)
        rl = QLabel("New Names  (right = desired names — edit here)")
        rl.setStyleSheet("font-weight:bold;font-size:12px;"); right_col.addWidget(rl)
        sp = QWidget(); sp.setFixedHeight(80); right_col.addWidget(sp)
        rp_lbl = QLabel("New Names Preview  (editable — one name per line  |  Shift+Alt+↑↓ to move lines)")
        rp_lbl.setStyleSheet("font-weight:bold;font-size:11px;"); right_col.addWidget(rp_lbl)
        self.tab2_right_editor = LineNumberedEditor()
        right_col.addWidget(self.tab2_right_editor, stretch=1)

        # Bottom — workflow + legend
        lay.addWidget(self._hr())
        wf = QLabel(
            "<b>Workflow:</b>  "
            "<b>① Scan</b> a folder (left = current names on disk).  "
            "<b>② →</b> copies those names to the right.  "
            "<b>③ Edit</b> right: change what needs to change.  "
            "<b>④ ✓ Apply</b>: every item on disk whose name matches <i>Left line N</i> "
            "is permanently renamed to <i>Right line N</i>.  "
            "Confirmation required. Safe rollback if anything fails.")
        wf.setStyleSheet(self.LS+"font-size:10px;"); wf.setWordWrap(True)
        lay.addWidget(wf)

        leg_row = QHBoxLayout(); leg_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        leg_row.setSpacing(12); lay.addLayout(leg_row)
        leg_row.addWidget(QLabel("≡? colours:", styleSheet=self.LS+"font-weight:600;font-size:10px;"))
        for color, desc in [
            ("#b8f0b8","Same — no rename needed"),
            ("#f0b8b8","Different — will be renamed"),
            ("#f0f0b0","Line exists on one side only"),
        ]:
            leg_row.addWidget(self._legend_item(color, desc))
        leg_row.addStretch()

        outer.addWidget(content, stretch=1)

    # ── Tab 2 compare (line-by-line, strict index) ────────────────────────────

    def _toggle_tab2_compare(self):
        left_ok  = bool(self.t2_left_preview.toPlainText().strip())
        right_ok = bool(self.tab2_right_editor.toPlainText().strip())
        if not self._t2_compare_active and not (left_ok and right_ok):
            QMessageBox.information(self,"Compare Names",
                "Please load a structure into the Left preview\n"
                "and type new names into the Right preview first."); return
        self._t2_compare_active = not self._t2_compare_active
        if self._t2_compare_active:
            self.btn_t2_compare.setText("≡✔")
            self.btn_t2_compare.setStyleSheet(
                "QPushButton{background-color:#4CAF50;color:white;"
                "font-size:20px;font-weight:bold;border-radius:24px;}"
                "QPushButton:hover{background-color:#66BB6A;}"
                "QPushButton:pressed{background-color:#388E3C;}")
            self.lbl_t2_cmp.setText("ON")
            self.lbl_t2_cmp.setStyleSheet(self.LS+"font-size:10px;font-weight:600;color:#66BB6A;")
            if not hasattr(self,'_t2_timer'):
                self._t2_timer = QTimer(self)
                self._t2_timer.setSingleShot(True); self._t2_timer.setInterval(150)
                self._t2_timer.timeout.connect(self._apply_tab2_colors)
                self.t2_left_preview.text_changed.connect(self._t2_timer.start)
                self.tab2_right_editor.text_changed.connect(self._t2_timer.start)
            self._apply_tab2_colors()
        else:
            self.btn_t2_compare.setText("≡?")
            self.btn_t2_compare.setStyleSheet(
                "QPushButton{background-color:#707070;color:white;"
                "font-size:20px;font-weight:bold;border-radius:24px;}"
                "QPushButton:hover{background-color:#888;}"
                "QPushButton:pressed{background-color:#555;}")
            self.lbl_t2_cmp.setText("Compare")
            self.lbl_t2_cmp.setStyleSheet(self.LS+"font-size:10px;font-weight:600;")
            if hasattr(self,'_t2_timer'): self._t2_timer.stop()
            self._clear_colors(self.t2_left_preview)
            self._clear_colors(self.tab2_right_editor)

    def _apply_tab2_colors(self):
        if self._coloring_in_progress or not self._t2_compare_active: return
        self._coloring_in_progress = True
        try:
            ll = self.t2_left_preview.editor.document().toPlainText().splitlines()
            rl = self.tab2_right_editor.editor.document().toPlainText().splitlines()
            def _col(pv, lines, partner):
                doc = pv.editor.document(); doc.blockSignals(True)
                try:
                    cur = QTextCursor(doc); cur.beginEditBlock()
                    for i in range(doc.blockCount()):
                        bl = doc.findBlockByNumber(i)
                        if not bl.isValid(): break
                        bc = QTextCursor(bl)
                        bc.select(QTextCursor.SelectionType.BlockUnderCursor)
                        fmt = QTextCharFormat()
                        if i >= len(partner):                         fmt.setBackground(self.C_ONLY)
                        elif lines[i].strip() == partner[i].strip():  fmt.setBackground(self.C_BOTH)
                        else:                                          fmt.setBackground(self.C_DIFF)
                        bc.setCharFormat(fmt)
                    cur.endEditBlock()
                finally: doc.blockSignals(False)
                pv._update_gutter_width(); pv._gutter.update()
            _col(self.t2_left_preview,   ll, rl)
            _col(self.tab2_right_editor, rl, ll)
        finally:
            self._coloring_in_progress = False

    # ── Shared colour helpers ─────────────────────────────────────────────────

    def _clear_colors(self, preview):
        """Remove all background colours from a single preview widget."""
        doc = preview.editor.document(); doc.blockSignals(True)
        try:
            cur = QTextCursor(doc); cur.beginEditBlock()
            cur.select(QTextCursor.SelectionType.Document)
            fmt = QTextCharFormat(); fmt.setBackground(self.C_CLEAR)
            cur.setCharFormat(fmt); cur.clearSelection(); cur.endEditBlock()
        finally: doc.blockSignals(False)
        preview._update_gutter_width(); preview._gutter.update()

    # ════════════════════════════════════════════════════════════════════════
    # TAB 3 — Generate Tree Diagram
    # ════════════════════════════════════════════════════════════════════════

    def _build_tab3(self):
        self.tab3 = QWidget()
        outer = QVBoxLayout(self.tab3)
        outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        content = QWidget(); lay = QVBoxLayout(content)
        lay.setContentsMargins(10,8,10,6); lay.setSpacing(5)

        hint = QLabel(
            "Scan a folder (auto-loaded from Tab 1 on first use, or scan independently).  "
            "Click Generate Tree to build a ├── └── │ diagram with  # ← description  placeholders.  "
            "Export saves  directory_structure_explained.md  into the source folder.")
        hint.setStyleSheet(self.LS); hint.setWordWrap(True); lay.addWidget(hint)

        # Root name row
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
            "Source Structure  (scan a folder — edit before generating)",
            "t3_left",
            self._scan_t3, self._export_t3_left,
            self._import_t3_left, self._browse_t3)

        # Right panel — tree output
        right3 = QVBoxLayout(); right3.setSpacing(4)
        panels3.addLayout(right3, stretch=1)
        rl3 = QLabel("Generated Tree Diagram  (editable — # ← add description here)")
        rl3.setStyleSheet("font-weight:bold;font-size:11px;"); right3.addWidget(rl3)
        self.tree_output = QTextEdit()
        self.tree_output.setFont(QFont("Courier New", 11))
        self.tree_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.tree_output.setStyleSheet("""
            QTextEdit{background-color:#1e1e1e;color:#d4d4d4;
                border:1px solid #444;border-radius:5px;padding:6px;}
            QScrollBar:vertical{background:#3a3a3a;width:12px;border-radius:6px;}
            QScrollBar::handle:vertical{background:#666;min-height:24px;border-radius:6px;}
            QScrollBar::handle:vertical:hover{background:#888;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
            QScrollBar:horizontal{background:#3a3a3a;height:12px;border-radius:6px;}
            QScrollBar::handle:horizontal{background:#666;min-width:24px;border-radius:6px;}
            QScrollBar::handle:horizontal:hover{background:#888;}
            QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}
        """)
        right3.addWidget(self.tree_output, stretch=1)

        # Buttons
        lay.addWidget(self._hr())
        btn3 = QHBoxLayout(); btn3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn3.setSpacing(16); lay.addLayout(btn3)
        b_gen = self._make_btn("▶  Generate Tree", self._green_btn(), 28,
            "Build the │ ├── └── tree from the left structure preview.")
        b_gen.clicked.connect(self._generate_tree); btn3.addWidget(b_gen)
        b_exp = self._make_btn("💾  Export as directory_structure_explained.md",
                               self._blue_btn(), 28,
            "Save the tree as 'directory_structure_explained.md' "
            "inside the source folder.")
        b_exp.clicked.connect(self._export_tree); btn3.addWidget(b_exp)

        outer.addWidget(content, stretch=1)

    # ── Tab 2 helpers: copy, scan, browse, export, import ────────────────────

    def _copy_left_to_right_t2(self):
        text = self.t2_left_preview.toPlainText().strip()
        if not text:
            QMessageBox.information(self,"Copy Left → Right",
                "The Left preview is empty.\n"
                "Please scan a folder first."); return
        self.tab2_right_editor.setPlainText(text)

    def _browse_t2_left(self):
        f = QFileDialog.getExistingDirectory(self,"Select Folder",self.t2_left_path_edit.text())
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
        p = self.t2_left_path_edit.text().strip()
        if not os.path.isdir(p): QMessageBox.warning(self,"Error","Invalid source folder."); return
        self._safe_export(p, self.t2_left_preview.toPlainText().rstrip())

    def _import_t2_left(self):
        txt,_=QFileDialog.getOpenFileName(self,"Select .txt","","Text files (*.txt);;All files (*.*)")
        if not txt: return
        try:
            with open(txt,encoding="utf-8") as f:
                lines=[l.rstrip() for l in f if l.strip() and not l.strip().startswith('#')]
            self.t2_left_preview.setPlainText("\n".join(lines))
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot load file:\n{e}")

    # ── Tab 3 helpers: browse, scan, export, import ───────────────────────────

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
        p = self.t3_left_path_edit.text().strip()
        if not os.path.isdir(p): QMessageBox.warning(self,"Error","Invalid source folder."); return
        self._safe_export(p, self.t3_left_preview.toPlainText().rstrip())

    def _import_t3_left(self):
        txt,_=QFileDialog.getOpenFileName(self,"Select .txt","","Text files (*.txt);;All files (*.*)")
        if not txt: return
        try:
            with open(txt,encoding="utf-8") as f:
                lines=[l.rstrip() for l in f if l.strip() and not l.strip().startswith('#')]
            self.t3_left_preview.setPlainText("\n".join(lines))
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot load file:\n{e}")

    # ── Content propagation (Tab 1 → Tab 2 & 3, first scan only) ────────────

    def _on_left_changed(self):
        text = self.left_preview.toPlainText()
        cl = [l for l in text.splitlines() if l.strip()]
        if len(cl) != len(self._left_abs_paths): self._left_abs_paths = []
        if self._tab1_compare_active:
            if hasattr(self,'_t1_timer'): self._t1_timer.start()
        if not self._tab2_initialized and text.strip():
            self.t2_left_preview.setPlainText(text)
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
        if not self._tab3_initialized and text.strip():
            self.t3_left_preview.setPlainText(text)
            self.t3_left_path_edit.setText(self.left_path_edit.text())
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
        if self._tab1_compare_active:
            if hasattr(self,'_t1_timer'): self._t1_timer.start()

    # ── Persistence ───────────────────────────────────────────────────────────

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
        except Exception: pass

    def closeEvent(self, event):
        data = {
            "left":            self.left_path_edit.text().strip(),
            "right":           self.right_path_edit.text().strip(),
            "left_recursive":  self.left_radio_recursive.isChecked(),
            "left_folders":    self.left_cb_folders.isChecked(),
            "left_files":      self.left_cb_files.isChecked(),
            "right_recursive": self.right_radio_recursive.isChecked(),
            "right_folders":   self.right_cb_folders.isChecked(),
            "right_files":     self.right_cb_files.isChecked(),
            "font_family":     self.left_preview.editor.font().family(),
            "font_size":       self.left_preview.editor.font().pointSize(),
        }
        try:
            with open(LAST_PATHS_FILE,"w",encoding="utf-8") as f:
                json.dump(data,f,indent=2)
        except Exception: pass
        super().closeEvent(event)

    # ── Sync scroll ───────────────────────────────────────────────────────────

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

    def _sync_l2r(self, v):
        if self._syncing_scroll: return
        self._syncing_scroll = True
        try:
            rb = self.right_preview.editor.verticalScrollBar()
            lb = self.left_preview.editor.verticalScrollBar()
            rb.setValue(int(v/lb.maximum()*rb.maximum()) if lb.maximum()>0 else 0)
        finally: self._syncing_scroll = False

    def _sync_r2l(self, v):
        if self._syncing_scroll: return
        self._syncing_scroll = True
        try:
            lb = self.left_preview.editor.verticalScrollBar()
            rb = self.right_preview.editor.verticalScrollBar()
            lb.setValue(int(v/rb.maximum()*lb.maximum()) if rb.maximum()>0 else 0)
        finally: self._syncing_scroll = False

    # ── Scan (Tab 1) ──────────────────────────────────────────────────────────

    def _do_scan(self, prefix):
        path = getattr(self,f"{prefix}_path_edit").text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self,"Error","Source path is not a valid folder."); return
        rec  = getattr(self,f"{prefix}_radio_recursive").isChecked()
        incf = getattr(self,f"{prefix}_cb_folders").isChecked()
        inci = getattr(self,f"{prefix}_cb_files").isChecked()
        try:
            lines, abs_paths = get_folder_structure_with_paths(path, rec, incf, inci)
            getattr(self,f"{prefix}_preview").setPlainText("\n".join(lines))
            if prefix == "left": self._left_abs_paths = abs_paths
        except Exception as e:
            QMessageBox.critical(self,"Error",f"Cannot read structure:\n{e}")

    def scan_left(self):  self._do_scan("left")
    def scan_right(self): self._do_scan("right")

    def browse_left_source(self):
        f=QFileDialog.getExistingDirectory(self,"Select Folder",self.left_path_edit.text())
        if f: self.left_path_edit.setText(f)
    def browse_right_source(self):
        f=QFileDialog.getExistingDirectory(self,"Select Folder",self.right_path_edit.text())
        if f: self.right_path_edit.setText(f)

    # ── Export / Import (Tab 1) ───────────────────────────────────────────────

    def _safe_export(self, source_path, content):
        if not content.strip():
            QMessageBox.warning(self,"Nothing to export","The preview is empty."); return
        today     = date.today().strftime("%Y.%m.%d")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_"
                            for c in os.path.basename(source_path)).strip("_")
        base = f"{today}_folder-structure_{safe_name}.txt"
        txt_path = os.path.join(source_path, base)
        def _write(p):
            with open(p,"w",encoding="utf-8") as f: f.write(content+"\n")
            self._show_export_ok(p)
        if not os.path.exists(txt_path):
            try: _write(txt_path)
            except Exception as e: QMessageBox.critical(self,"Error",f"Export failed:\n{e}"); return
        else:
            msg=QMessageBox(self); msg.setWindowTitle("File Already Exists")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setText(f"File already exists:\n{txt_path}")
            msg.setInformativeText("What would you like to do?")
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
            getattr(self,f"{prefix}_preview").setPlainText("\n".join(lines))
        except Exception as e: QMessageBox.critical(self,"Error",f"Cannot load TXT:\n{e}")
    def import_txt_left(self):  self._import_txt("left")
    def import_txt_right(self): self._import_txt("right")

    # ── Batch Rename (Tab 2) — safe two-phase with rollback ──────────────────

    def batch_rename(self):
        left_lines  = [l.rstrip() for l in self.t2_left_preview.toPlainText().splitlines()  if l.strip()]
        right_lines = [l.rstrip() for l in self.tab2_right_editor.toPlainText().splitlines() if l.strip()]
        if not left_lines or not right_lines:
            QMessageBox.warning(self,"Batch Rename","Both previews must contain names."); return
        if len(left_lines) != len(right_lines):
            QMessageBox.warning(self,"Batch Rename",
                f"Line count mismatch!\nLeft: {len(left_lines)}  |  Right: {len(right_lines)}\n"
                "Both sides must have the same number of non-empty lines."); return
        root = self.t2_left_path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.warning(self,"Batch Rename",
                "Please set a valid Left source folder path."); return
        # Resolve paths
        if self._left_abs_paths and len(self._left_abs_paths)==len(left_lines):
            left_abs = list(self._left_abs_paths)
        else:
            stack=[root]; left_abs=[]
            for line in left_lines:
                ind=len(line)-len(line.lstrip()); level=ind//2; name=line.strip()
                while len(stack)>level+1: stack.pop()
                ap=os.path.join(stack[-1],name); left_abs.append(ap); stack.append(ap)
        ops=[]
        for old_abs, right_line in zip(left_abs, right_lines):
            old_name=os.path.basename(old_abs); new_name=right_line.strip()
            if not new_name or new_name==old_name: continue
            ops.append((old_abs, os.path.join(os.path.dirname(old_abs),new_name), old_name, new_name))
        if not ops:
            QMessageBox.information(self,"Batch Rename","No differences — nothing to rename."); return
        # Confirm dialog
        dlg=QDialog(self); dlg.setWindowTitle("Confirm Batch Rename"); dlg.resize(700,440)
        cl=QVBoxLayout(dlg); cl.setContentsMargins(16,16,16,12); cl.setSpacing(8)
        hdr=QLabel(f"About to rename <b>{len(ops)}</b> item(s) inside:<br><code>{root}</code>")
        hdr.setWordWrap(True); cl.addWidget(hdr)
        wi=QLabel("⚠  Make sure no files or folders are open in other programs before proceeding.")
        wi.setWordWrap(True); wi.setStyleSheet("color:#cc6600;"); cl.addWidget(wi)
        cl.addWidget(QLabel("<b>Current name</b>  →  <b>New name</b>",
                            styleSheet="font-size:11px;color:#555;"))
        sc=QTextEdit(); sc.setReadOnly(True); sc.setFont(QFont("Courier New",11))
        sc.setPlainText("\n".join(f"  {o}  →  {n}" for _,_,o,n in ops))
        cl.addWidget(sc,stretch=1)
        br=QHBoxLayout(); br.setSpacing(10); br.addStretch()
        cn=QPushButton("Cancel"); cn.setFixedHeight(30); cn.setFixedWidth(110)
        cn.clicked.connect(dlg.reject); br.addWidget(cn)
        co=QPushButton("Rename"); co.setFixedHeight(30); co.setFixedWidth(110)
        co.setDefault(True)
        co.setStyleSheet("background-color:#e65c00;color:white;font-weight:bold;border-radius:4px;")
        co.clicked.connect(dlg.accept); br.addWidget(co); cl.addLayout(br)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        # Two-phase rename
        abs_map={}
        def _resolve(p):
            for op in sorted(abs_map,key=len,reverse=True):
                cp=abs_map[op]
                if p==op: return cp
                if p.startswith(op+os.sep): return cp+p[len(op):]
            return p
        renamed=[]; failed=[]; skipped=[]; conflicts=[]; phase2=[]
        for old_abs,new_abs,old_name,new_name in ops:
            old_r=_resolve(old_abs)
            if not os.path.exists(old_r):
                skipped.append(f'SKIPPED  "{old_name}"\n  Path not found: {old_r}'); continue
            parent=os.path.dirname(old_r)
            tmp=os.path.join(parent,f"__structify_tmp_{uuid.uuid4().hex}")
            try:
                os.rename(old_r,tmp); abs_map[old_abs]=tmp
                phase2.append((tmp,os.path.join(parent,new_name),old_r,old_name,new_name))
            except Exception as e:
                failed.append(f'FAILED p1 "{old_name}"\n  {e}')
        for tmp,final,orig,old_name,new_name in phase2:
            if os.path.exists(final):
                try: os.rename(tmp,orig); note="Original preserved."
                except Exception as re2: note=f"⚠ RESTORE FAILED: {tmp}\n  {re2}"
                conflicts.append(f'CONFLICT "{old_name}" → "{new_name}"\n  Target exists.\n  {note}')
                continue
            try:
                os.rename(tmp,final); renamed.append(f"{old_name}  →  {new_name}")
            except Exception as e:
                try: os.rename(tmp,orig); rb="  (✔ rolled back)"
                except Exception as re2: rb=f"  ⚠ ROLLBACK FAILED: {tmp}\n  {re2}"
                failed.append(f'FAILED p2 "{old_name}" → "{new_name}"\n  {e}\n{rb}')
        # Result dialog
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
        rl=QVBoxLayout(rd); rl.setContentsMargins(16,16,16,12); rl.setSpacing(8)
        se=QTextEdit(); se.setReadOnly(True); se.setFont(QFont("Courier New",11))
        se.setPlainText(full); rl.addWidget(se,stretch=1)
        rb2=QHBoxLayout(); rb2.setSpacing(10)
        cb2=QPushButton("Copy to Clipboard"); cb2.setFixedHeight(30)
        cb2.clicked.connect(lambda: QApplication.clipboard().setText(full)); rb2.addWidget(cb2)
        rb2.addStretch()
        ob2=QPushButton("Open Folder"); ob2.setFixedHeight(30)
        ob2.clicked.connect(lambda: self._open_folder(root)); rb2.addWidget(ob2)
        ok2=QPushButton("OK"); ok2.setFixedHeight(30); ok2.setDefault(True)
        ok2.clicked.connect(rd.accept); rb2.addWidget(ok2); rl.addLayout(rb2); rd.exec()

    # ── Replicate (internal — used if needed) ─────────────────────────────────

    def _replicate(self, prefix):
        preview = getattr(self,f"{prefix}_preview")
        lines=[l.rstrip() for l in preview.toPlainText().splitlines() if l.strip()]
        if not lines: QMessageBox.warning(self,"Error","No structure in preview."); return
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
        except Exception as e: QMessageBox.critical(self,"Error",f"Failed:\n{e}")

    def replicate_left(self):  self._replicate("left")
    def replicate_right(self): self._replicate("right")

    # ── Tree diagram ──────────────────────────────────────────────────────────

    def _generate_tree(self):
        text = self.t3_left_preview.toPlainText().strip()
        if not text:
            QMessageBox.warning(self,"Generate Tree",
                "The structure preview is empty.\n"
                "Please scan a folder first."); return
        lines=[l for l in text.splitlines() if l.strip()]
        root_name=self.tree_root_edit.text().strip()
        if not root_name:
            src=self.t3_left_path_edit.text().strip()
            root_name=os.path.basename(src) if src else "project"
        self.tree_output.setPlainText(build_tree_diagram(lines,root_name))

    def _export_tree(self):
        tree=self.tree_output.toPlainText().strip()
        if not tree:
            QMessageBox.warning(self,"Export Tree","Tree is empty. Click Generate Tree first."); return
        src=self.t3_left_path_edit.text().strip()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self,"Export Tree","No valid source folder set."); return
        out=os.path.join(src,"directory_structure_explained.md")
        if os.path.exists(out):
            msg=QMessageBox(self); msg.setWindowTitle("File Already Exists")
            msg.setIcon(QMessageBox.Icon.Question); msg.setText(f"File already exists:\n{out}")
            msg.setInformativeText("What would you like to do?")
            ow=msg.addButton("Overwrite",QMessageBox.ButtonRole.YesRole)
            msg.addButton("Cancel",QMessageBox.ButtonRole.RejectRole); msg.exec()
            if msg.clickedButton()!=ow: return
        try:
            with open(out,"w",encoding="utf-8") as f: f.write(tree+"\n")
            msg=QMessageBox(self); msg.setWindowTitle("Export Successful")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("Tree diagram exported."); msg.setInformativeText(f"Saved to:\n{out}")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            ob=msg.addButton("Open Folder",QMessageBox.ButtonRole.ActionRole); msg.exec()
            if msg.clickedButton()==ob: self._open_folder(os.path.dirname(out))
        except Exception as e: QMessageBox.critical(self,"Error",f"Export failed:\n{e}")

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
            cur=os.path.join(stack[-1],name); os.makedirs(cur,exist_ok=True); stack.append(cur)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FolderStructureApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
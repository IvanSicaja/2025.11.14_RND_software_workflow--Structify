import sys
import os
import subprocess
import json
from datetime import date
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QMessageBox, QStyleFactory, QRadioButton, QButtonGroup,
    QDialog, QDialogButtonBox, QCheckBox, QFrame
)
from PyQt6.QtCore import Qt, QSize, QRect, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor, QPainter, QPalette

LAST_PATHS_FILE = "structify_last_paths.json"

# ── Fixed editor constants ───────────────────────────────────────────────────
EDITOR_FONT_FAMILY = "SF Mono"
EDITOR_FONT_SIZE   = 12          # pt
EDITOR_LINE_HEIGHT = 16          # px  (FixedHeight mode)


def get_folder_structure(root_path, recursive=True, include_folders=True, include_files=True):
    structure = []

    if not recursive:
        try:
            entries = sorted(os.listdir(root_path))
        except PermissionError:
            return structure
        for name in entries:
            full_path = os.path.join(root_path, name)
            if os.path.isdir(full_path) and include_folders:
                structure.append(name)
            elif os.path.isfile(full_path) and include_files:
                structure.append(name)
        return structure

    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        dirnames.sort()
        rel_path = os.path.relpath(dirpath, root_path)
        if rel_path == '.':
            depth = 0
        else:
            depth = rel_path.count(os.sep) + 1

        indent = '  ' * (depth - 1) if depth > 0 else ''

        if rel_path != '.':
            folder_name = os.path.basename(dirpath)
            if include_folders:
                structure.append(f"{indent}{folder_name}")
            child_indent = '  ' * depth
        else:
            child_indent = ''

        if include_files:
            for fname in sorted(filenames):
                structure.append(f"{child_indent}{fname}")

    return structure


def get_folder_structure_with_paths(root_path, recursive=True,
                                    include_folders=True, include_files=True):
    """Like get_folder_structure but also returns a parallel list of absolute paths."""
    display_lines = []
    abs_paths     = []

    if not recursive:
        try:
            entries = sorted(os.listdir(root_path))
        except PermissionError:
            return display_lines, abs_paths
        for name in entries:
            full_path = os.path.join(root_path, name)
            if os.path.isdir(full_path) and include_folders:
                display_lines.append(name)
                abs_paths.append(full_path)
            elif os.path.isfile(full_path) and include_files:
                display_lines.append(name)
                abs_paths.append(full_path)
        return display_lines, abs_paths

    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        dirnames.sort()
        rel_path = os.path.relpath(dirpath, root_path)
        if rel_path == '.':
            depth = 0
        else:
            depth = rel_path.count(os.sep) + 1

        indent      = '  ' * (depth - 1) if depth > 0 else ''
        child_indent = '  ' * depth if rel_path == '.' else '  ' * depth

        if rel_path != '.':
            folder_name = os.path.basename(dirpath)
            if include_folders:
                display_lines.append(f"{indent}{folder_name}")
                abs_paths.append(dirpath)
            if include_files:
                for fname in sorted(filenames):
                    display_lines.append(f"{'  ' * depth}{fname}")
                    abs_paths.append(os.path.join(dirpath, fname))
        else:
            if include_files:
                for fname in sorted(filenames):
                    display_lines.append(fname)
                    abs_paths.append(os.path.join(dirpath, fname))

    return display_lines, abs_paths


class LineNumberArea(QWidget):
    """Gutter widget that paints line numbers next to a QTextEdit."""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        from PyQt6.QtCore import QSize as _QSize
        return _QSize(self._editor._gutter_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_gutter(event)


class LineNumberedEditor(QWidget):
    """
    A QTextEdit wrapped in a container that shows a read-only line-number
    gutter on the left — styled like a professional code editor.

    Formatting is always normalised on every content change:
      • Fixed font (EDITOR_FONT_FAMILY / EDITOR_FONT_SIZE)
      • Fixed line height (EDITOR_LINE_HEIGHT px, FixedHeight mode)
      • No blank lines — empty lines are stripped on paste/type
      • No external paragraph/character formatting survives paste
    """

    text_changed = pyqtSignal()

    # ── Internal helpers ─────────────────────────────────────────────────────
    def _make_font(self):
        return QFont(EDITOR_FONT_FAMILY, EDITOR_FONT_SIZE)

    def _apply_fixed_format(self):
        """Strip ALL character/paragraph formatting and re-apply our standards.
        Called after every content change so pasted text can never survive
        with foreign fonts, sizes, line-heights, or blank lines."""
        from PyQt6.QtGui import QTextBlockFormat, QTextCharFormat

        doc = self.editor.document()

        # ── 1. Collect plain text, strip blank lines ──
        raw = doc.toPlainText()
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        clean = "\n".join(lines)

        # ── 2. Replace document content with clean plain text ──
        # We do this only when something actually changed to avoid
        # fighting with the user's cursor while they type normally.
        if raw != clean:
            cur = self.editor.textCursor()
            pos = cur.position()
            doc.blockSignals(True)
            self.editor.blockSignals(True)
            try:
                self.editor.setPlainText(clean)
            finally:
                doc.blockSignals(False)
                self.editor.blockSignals(False)
            # Restore cursor as best we can
            cur2 = self.editor.textCursor()
            cur2.setPosition(min(pos, len(clean)))
            self.editor.setTextCursor(cur2)

        # ── 3. Apply uniform character format (font) to every block ──
        char_fmt = QTextCharFormat()
        char_fmt.setFont(self._make_font())
        char_fmt.setBackground(QColor("white"))   # no colour bleed from paste

        # ── 4. Apply fixed line height to every block ──
        block_fmt = QTextBlockFormat()
        block_fmt.setLineHeight(EDITOR_LINE_HEIGHT, 4)  # 4 = FixedHeight
        block_fmt.setTopMargin(0)
        block_fmt.setBottomMargin(0)

        doc.blockSignals(True)
        try:
            cur = QTextCursor(doc)
            cur.beginEditBlock()
            cur.select(QTextCursor.SelectionType.Document)
            cur.setCharFormat(char_fmt)
            cur.setBlockFormat(block_fmt)
            cur.clearSelection()
            cur.endEditBlock()
        finally:
            doc.blockSignals(False)

        self._update_gutter_width()
        self._gutter.update()

    # ── Public proxy methods ─────────────────────────────────────────────────
    def setPlainText(self, text):
        """Load content, normalize formatting, reset horizontal scroll."""
        doc = self.editor.document()
        doc.blockSignals(True)
        self.editor.blockSignals(True)
        try:
            # Strip blank lines on load too
            lines = [ln for ln in text.splitlines() if ln.strip()]
            self.editor.setPlainText("\n".join(lines))
        finally:
            doc.blockSignals(False)
            self.editor.blockSignals(False)
        self._apply_fixed_format()
        self.editor.horizontalScrollBar().setValue(0)
        self.text_changed.emit()

    def toPlainText(self):   return self.editor.toPlainText()
    def setReadOnly(self, v): self.editor.setReadOnly(v)
    def setFont(self, font):  self.editor.setFont(font)

    # ── Constructor ──────────────────────────────────────────────────────────
    def __init__(self, parent=None):
        super().__init__(parent)

        self.editor = QTextEdit(self)
        self.editor.setFont(self._make_font())
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        self.editor.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #000000;
                border: none;
                padding: 2px 8px;
            }
            QScrollBar:vertical {
                background: #d8d8d8;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #888888;
                min-height: 24px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover { background: #555555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar:horizontal {
                background: #d8d8d8;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #888888;
                min-width: 24px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover { background: #555555; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
        """)

        self._gutter = LineNumberArea(self)
        self._gutter.setStyleSheet("")

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._gutter)
        h.addWidget(self.editor)

        self.setStyleSheet("""
            LineNumberedEditor {
                border: 1px solid #d0d4d8;
                border-radius: 6px;
                background-color: #ffffff;
            }
        """)

        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.editor.document().blockCountChanged.connect(self._update_gutter_width)
        self.editor.verticalScrollBar().valueChanged.connect(self._gutter.update)
        self.editor.document().documentLayout().documentSizeChanged.connect(
            lambda _: self._gutter.update()
        )

        # ── Normalise on every change (typing, paste, undo, etc.) ──
        # We use a 80 ms debounce timer so rapid keystrokes don't each
        # trigger a full reformat (which would fight the cursor).
        from PyQt6.QtCore import QTimer
        self._norm_timer = QTimer(self)
        self._norm_timer.setSingleShot(True)
        self._norm_timer.setInterval(80)
        self._norm_timer.timeout.connect(self._on_normalize_timer)
        self._normalizing = False
        self.editor.document().contentsChanged.connect(self._schedule_normalize)

        # Forward to our safe signal (used by compare feature)
        self.editor.document().contentsChanged.connect(self.text_changed)

        self._update_gutter_width()
        # Apply initial format to empty document
        self._apply_fixed_format()

    def _schedule_normalize(self):
        if not self._normalizing:
            self._norm_timer.start()

    def _on_normalize_timer(self):
        if self._normalizing:
            return
        self._normalizing = True
        try:
            self._apply_fixed_format()
        finally:
            self._normalizing = False

    # ── Gutter ───────────────────────────────────────────────────────────────
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
            block_rect = doc_layout.blockBoundingRect(block)
            top = int(block_rect.top()) - scroll_y + editor_top
            if top > event.rect().bottom():
                break
            bottom = top + int(block_rect.height())
            if bottom >= event.rect().top():
                painter.setPen(QColor("#999999"))
                font = self.editor.font()
                font.setPointSize(font.pointSize() - 1)
                painter.setFont(font)
                painter.drawText(
                    0, top,
                    self._gutter.width() - 4, int(block_rect.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(block_num)
                )
            block = block.next()
            block_num += 1

        painter.end()


class ComparisonDialog(QDialog):
    def __init__(self, left_lines, right_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Structure Comparison")
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        label = QLabel("Comparison: Left vs Right preview (order-insensitive per level)")
        label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(label)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("SF Mono", 12))
        self.preview.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                color: #000000;
                border: 1px solid #c0c0c0;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.preview, stretch=1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

        self._compare_and_highlight(left_lines, right_lines)

    def _compare_and_highlight(self, left_lines, right_lines):
        doc = self.preview.document()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()

        green = QColor("#e6ffe6")
        red   = QColor("#ffe6e6")

        left_by_level  = {}
        right_by_level = {}

        for line in left_lines:
            indent = len(line) - len(line.lstrip())
            level  = indent // 2
            name   = line.strip()
            if level not in left_by_level:
                left_by_level[level] = set()
            if name:
                left_by_level[level].add(name)

        for line in right_lines:
            indent = len(line) - len(line.lstrip())
            level  = indent // 2
            name   = line.strip()
            if level not in right_by_level:
                right_by_level[level] = set()
            if name:
                right_by_level[level].add(name)

        max_level = max(
            max(left_by_level.keys(),  default=0),
            max(right_by_level.keys(), default=0)
        )

        for level in range(max_level + 1):
            left_names  = left_by_level.get(level,  set())
            right_names = right_by_level.get(level, set())

            for name in sorted(left_names & right_names):
                fmt = QTextCharFormat()
                fmt.setBackground(green)
                cursor.setCharFormat(fmt)
                cursor.insertText(f"  {'  ' * level}{name}\n")

            for name in sorted(left_names - right_names):
                fmt = QTextCharFormat()
                fmt.setBackground(red)
                cursor.setCharFormat(fmt)
                cursor.insertText(f"L {'  ' * level}{name}\n")

            for name in sorted(right_names - left_names):
                fmt = QTextCharFormat()
                fmt.setBackground(red)
                cursor.setCharFormat(fmt)
                cursor.insertText(f"R {'  ' * level}{name}\n")

            if level < max_level:
                cursor.insertText("\n")

        cursor.endEditBlock()
        self.preview.setTextCursor(cursor)


class FolderStructureApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Structify - Folder Structure Replicator")
        screen = QApplication.primaryScreen().availableGeometry()
        w = int(screen.width() * 0.70)
        h = screen.height()
        self.resize(w, h)
        self.setMinimumSize(QSize(1000, 720))
        x = screen.x() + (screen.width() - w) // 2
        y = screen.y()
        self.move(x, y)

        if 'Fusion' in QStyleFactory.keys():
            QApplication.setStyle('Fusion')

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        panels_layout = QHBoxLayout()
        panels_layout.setSpacing(16)
        self.main_layout.addLayout(panels_layout, stretch=1)

        # ── Sync scroll checkbox ──
        sync_row = QHBoxLayout()
        sync_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sync_row.setSpacing(8)
        self.main_layout.addLayout(sync_row)

        self.cb_sync_scroll = QCheckBox("Sync scroll — scrolling one preview automatically scrolls the other")
        self.cb_sync_scroll.setChecked(False)
        self.cb_sync_scroll.setStyleSheet(
            "font-family: 'Segoe UI', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif; "
            "font-size: 12px; color: #e0e0e0; font-weight: 500; letter-spacing: 0.2px;"
        )
        self.cb_sync_scroll.stateChanged.connect(self._on_sync_scroll_toggled)
        sync_row.addWidget(self.cb_sync_scroll)

        # Left panel
        self._setup_panel(panels_layout, "Source Folder 1", "left",
                          self.scan_left, self.export_left, self.import_txt_left,
                          self.browse_left_source)
        # Right panel
        self._setup_panel(panels_layout, "Source Folder 2", "right",
                          self.scan_right, self.export_right, self.import_txt_right,
                          self.browse_right_source)

        # ── Bottom controls ──────────────────────────────────────────────────
        bottom_layout = QVBoxLayout()
        bottom_layout.setSpacing(8)
        bottom_layout.setContentsMargins(0, 12, 0, 0)
        self.main_layout.addLayout(bottom_layout)

        row1 = QHBoxLayout()
        row1.setSpacing(40)
        row1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addLayout(row1)

        btn_rep_left = QPushButton("Replicate Left Preview")
        btn_rep_left.setStyleSheet(self._blue_btn_style())
        btn_rep_left.setFixedHeight(32)
        btn_rep_left.clicked.connect(self.replicate_left)
        row1.addWidget(btn_rep_left)

        btn_compare = QPushButton("Compare Structures")
        btn_compare.setStyleSheet(self._green_btn_style())
        btn_compare.setFixedHeight(32)
        btn_compare.clicked.connect(self.compare_previews)
        row1.addWidget(btn_compare)

        btn_rep_right = QPushButton("Replicate Right Preview")
        btn_rep_right.setStyleSheet(self._blue_btn_style())
        btn_rep_right.setFixedHeight(32)
        btn_rep_right.clicked.connect(self.replicate_right)
        row1.addWidget(btn_rep_right)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #d0d0d0;")
        bottom_layout.addWidget(divider)

        LABEL_STYLE = (
            "font-family: 'Segoe UI', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif; "
            "font-size: 12px; color: #e0e0e0;"
        )

        rename_label = QLabel("Batch Rename")
        rename_label.setStyleSheet(LABEL_STYLE + " font-weight: 600; font-size: 13px;")
        rename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(rename_label)

        info_label = QLabel(
            "Left preview = current folder names (as they exist on disk)   |   "
            "Right preview = the final names after renaming   |   "
            "Names are matched line-by-line in the same order."
        )
        info_label.setStyleSheet(LABEL_STYLE)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(info_label)

        info_label2 = QLabel(
            "Clicking the button below will rename all items in the Left source folder "
            "so that every current name is replaced with the corresponding name from the Right preview."
        )
        info_label2.setStyleSheet(LABEL_STYLE)
        info_label2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(info_label2)

        row_compare_names = QHBoxLayout()
        row_compare_names.setSpacing(20)
        row_compare_names.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addLayout(row_compare_names)

        self.btn_compare_names = QPushButton("Compare Left and Right Names Line by Line")
        self.btn_compare_names.setStyleSheet("""
            QPushButton {
                background-color: #707070; color: white;
                font-weight: bold; font-size: 13px; border-radius: 6px;
            }
            QPushButton:hover  { background-color: #888888; }
            QPushButton:pressed{ background-color: #555555; }
        """)
        self.btn_compare_names.setFixedHeight(32)
        self.btn_compare_names.setFixedWidth(520)
        self.btn_compare_names.clicked.connect(self.toggle_line_compare)
        row_compare_names.addWidget(self.btn_compare_names)

        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(20)
        legend_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addLayout(legend_layout)

        def _legend_item(color_hex, text):
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(6, 4, 10, 4)
            hl.setSpacing(8)
            swatch = QLabel()
            swatch.setFixedSize(20, 20)
            swatch.setStyleSheet(
                f"background-color: {color_hex}; border: 1px solid #999; border-radius: 4px;"
            )
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "font-family: 'Segoe UI', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif; "
                "font-size: 11px; color: #e0e0e0; font-weight: 600;"
            )
            hl.addWidget(swatch)
            hl.addWidget(lbl)
            return w

        legend_layout.addWidget(_legend_item("#b8f0b8", "Same name on both lines"))
        legend_layout.addWidget(_legend_item("#f0b8b8", "Different names on same line"))
        legend_layout.addWidget(_legend_item("#f0f0b0", "Line exists on one side only"))

        row2 = QHBoxLayout()
        row2.setSpacing(20)
        row2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addLayout(row2)

        btn_rename = QPushButton("⟳  Apply Right Preview Names to Left Source Folder")
        btn_rename.setStyleSheet("""
            QPushButton {
                background-color: #e65c00; color: white;
                font-weight: bold; font-size: 13px;
                min-width: 380px; border-radius: 6px;
            }
            QPushButton:hover  { background-color: #ff6a00; }
            QPushButton:pressed{ background-color: #c24f00; }
        """)
        btn_rename.setFixedHeight(32)
        btn_rename.clicked.connect(self.batch_rename)
        row2.addWidget(btn_rename)

        copyright_layout = QHBoxLayout()
        copyright_layout.setContentsMargins(0, 8, 0, 4)
        copyright_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addLayout(copyright_layout)
        copyright_label = QLabel("Developed by Ivan Sicaja © 2026. All rights reserved.")
        copyright_label.setStyleSheet("color: #666666; font-size: 12px; font-style: italic;")
        copyright_layout.addWidget(copyright_label)

        self._line_compare_active  = False
        self._coloring_in_progress = False
        self._sync_scroll_active   = False
        self._syncing_scroll       = False
        # Stores the absolute path for every line produced by the last left Scan.
        # Index N here matches line N in left_preview exactly.
        # Cleared when the user edits the left preview manually.
        self._left_abs_paths = []
        self._load_last_paths()
        # If the user manually edits the left preview, the stored abs paths
        # are no longer valid — clear them so fallback reconstruction is used.
        # We connect after _load_last_paths so the initial setText doesn't clear.
        self.left_preview.text_changed.connect(self._on_left_preview_manually_changed)

    # ── Style helpers ────────────────────────────────────────────────────────
    def _blue_btn_style(self):
        return """
            QPushButton {
                background-color: #0066cc; color: white;
                font-weight: bold; min-width: 220px; border-radius: 6px;
            }
            QPushButton:hover  { background-color: #0077e6; }
            QPushButton:pressed{ background-color: #0055b3; }
        """

    def _green_btn_style(self):
        return """
            QPushButton {
                background-color: #4CAF50; color: white;
                font-weight: bold; min-width: 220px; border-radius: 6px;
            }
            QPushButton:hover  { background-color: #66BB6A; }
            QPushButton:pressed{ background-color: #388E3C; }
        """

    # ── Panel setup ──────────────────────────────────────────────────────────
    def _setup_panel(self, parent_layout, title_text, prefix,
                     scan_cb, export_cb, import_cb, browse_source_cb):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        parent_layout.addLayout(layout, stretch=1)

        title = QLabel(title_text)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        path_label = QLabel("Source:")
        path_label.setFixedWidth(70)
        path_layout.addWidget(path_label)
        edit = QLineEdit()
        edit.setPlaceholderText("Select a folder...")
        path_layout.addWidget(edit)
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(90)
        btn_browse.setFixedHeight(28)
        btn_browse.clicked.connect(browse_source_cb)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)
        setattr(self, f"{prefix}_path_edit", edit)

        options_layout = QHBoxLayout()
        options_layout.setSpacing(24)

        radio_only_root = QRadioButton("Only root items")
        radio_recursive = QRadioButton("All subfolders (recursive)")
        radio_only_root.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(radio_only_root)
        group.addButton(radio_recursive)
        options_layout.addWidget(radio_only_root)
        options_layout.addWidget(radio_recursive)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #aaaaaa;")
        options_layout.addWidget(sep)

        cb_folders = QCheckBox("Folder names")
        cb_folders.setChecked(True)
        cb_files = QCheckBox("File names")
        cb_files.setChecked(False)

        def make_guard(this_cb, other_cb):
            def guard(state):
                if not this_cb.isChecked() and not other_cb.isChecked():
                    this_cb.setChecked(True)
            return guard

        cb_folders.stateChanged.connect(make_guard(cb_folders, cb_files))
        cb_files.stateChanged.connect(make_guard(cb_files, cb_folders))

        options_layout.addWidget(cb_folders)
        options_layout.addWidget(cb_files)
        options_layout.addStretch()
        layout.addLayout(options_layout)
        setattr(self, f"{prefix}_radio_only_root", radio_only_root)
        setattr(self, f"{prefix}_radio_recursive", radio_recursive)
        setattr(self, f"{prefix}_cb_folders", cb_folders)
        setattr(self, f"{prefix}_cb_files",   cb_files)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_scan   = QPushButton("Scan")
        btn_export = QPushButton("Export Previewed TXT")
        btn_import = QPushButton("Import TXT")
        btn_scan.clicked.connect(scan_cb)
        btn_export.clicked.connect(export_cb)
        btn_import.clicked.connect(import_cb)
        for btn in (btn_scan, btn_export, btn_import):
            btn.setFixedHeight(28)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

        preview_label = QLabel("Structure Preview (editable)")
        preview_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(preview_label)

        preview = LineNumberedEditor()
        layout.addWidget(preview, stretch=1)
        setattr(self, f"{prefix}_preview", preview)

    # ── Left preview edit tracking ──────────────────────────────────────────
    def _on_left_preview_manually_changed(self):
        """Called whenever the left preview content changes (typing, paste, scan).
        If the line count no longer matches our stored abs-path list, clear it
        so batch_rename falls back to indentation reconstruction."""
        current_lines = [l for l in self.left_preview.toPlainText().splitlines()
                         if l.strip()]
        if len(current_lines) != len(self._left_abs_paths):
            self._left_abs_paths = []

    # ── Persistence ──────────────────────────────────────────────────────────
    def _load_last_paths(self):
        try:
            if not os.path.exists(LAST_PATHS_FILE):
                return
            with open(LAST_PATHS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "left"  in data and os.path.isdir(data["left"]):
                self.left_path_edit.setText(data["left"])
            if "right" in data and os.path.isdir(data["right"]):
                self.right_path_edit.setText(data["right"])

            if "left_recursive" in data:
                if data["left_recursive"]:
                    self.left_radio_recursive.setChecked(True)
                else:
                    self.left_radio_only_root.setChecked(True)
            if "left_folders" in data and "left_files" in data:
                lf, li = bool(data["left_folders"]), bool(data["left_files"])
                self.left_cb_folders.blockSignals(True)
                self.left_cb_files.blockSignals(True)
                self.left_cb_folders.setChecked(lf)
                self.left_cb_files.setChecked(li)
                if not lf and not li:
                    self.left_cb_folders.setChecked(True)
                self.left_cb_folders.blockSignals(False)
                self.left_cb_files.blockSignals(False)

            if "right_recursive" in data:
                if data["right_recursive"]:
                    self.right_radio_recursive.setChecked(True)
                else:
                    self.right_radio_only_root.setChecked(True)
            if "right_folders" in data and "right_files" in data:
                rf, ri = bool(data["right_folders"]), bool(data["right_files"])
                self.right_cb_folders.blockSignals(True)
                self.right_cb_files.blockSignals(True)
                self.right_cb_folders.setChecked(rf)
                self.right_cb_files.setChecked(ri)
                if not rf and not ri:
                    self.right_cb_folders.setChecked(True)
                self.right_cb_folders.blockSignals(False)
                self.right_cb_files.blockSignals(False)

            family = data.get("font_family", EDITOR_FONT_FAMILY)
            size   = int(data.get("font_size",   EDITOR_FONT_SIZE))
            if family and size > 0:
                font = QFont(family, size)
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
        except Exception:
            pass
        super().closeEvent(event)

    # ── Sync scroll ──────────────────────────────────────────────────────────
    def _on_sync_scroll_toggled(self, state):
        self._sync_scroll_active = bool(state)
        if self._sync_scroll_active:
            self.left_preview.editor.verticalScrollBar().valueChanged.connect(
                self._sync_scroll_left_to_right)
            self.right_preview.editor.verticalScrollBar().valueChanged.connect(
                self._sync_scroll_right_to_left)
        else:
            try:
                self.left_preview.editor.verticalScrollBar().valueChanged.disconnect(
                    self._sync_scroll_left_to_right)
            except Exception:
                pass
            try:
                self.right_preview.editor.verticalScrollBar().valueChanged.disconnect(
                    self._sync_scroll_right_to_left)
            except Exception:
                pass

    def _sync_scroll_left_to_right(self, value):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            r_bar = self.right_preview.editor.verticalScrollBar()
            l_bar = self.left_preview.editor.verticalScrollBar()
            l_max = l_bar.maximum()
            r_max = r_bar.maximum()
            r_bar.setValue(int(value / l_max * r_max) if l_max > 0 else 0)
        finally:
            self._syncing_scroll = False

    def _sync_scroll_right_to_left(self, value):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            l_bar = self.left_preview.editor.verticalScrollBar()
            r_bar = self.right_preview.editor.verticalScrollBar()
            r_max = r_bar.maximum()
            l_max = l_bar.maximum()
            l_bar.setValue(int(value / r_max * l_max) if r_max > 0 else 0)
        finally:
            self._syncing_scroll = False

    # ── Scan ─────────────────────────────────────────────────────────────────
    def _do_scan(self, prefix):
        path_edit = getattr(self, f"{prefix}_path_edit")
        path = path_edit.text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Error", "Selected source path is not a valid folder.")
            return
        recursive       = getattr(self, f"{prefix}_radio_recursive").isChecked()
        include_folders = getattr(self, f"{prefix}_cb_folders").isChecked()
        include_files   = getattr(self, f"{prefix}_cb_files").isChecked()
        try:
            lines, abs_paths = get_folder_structure_with_paths(
                path, recursive, include_folders, include_files)
            self._pause_compare()
            getattr(self, f"{prefix}_preview").setPlainText("\n".join(lines))
            self._resume_compare()
            # Store absolute paths for the left panel so batch_rename can use
            # them directly instead of reconstructing from indentation.
            if prefix == "left":
                self._left_abs_paths = abs_paths
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot read structure:\n{str(e)}")

    def scan_left(self):  self._do_scan("left")
    def scan_right(self): self._do_scan("right")

    # ── Browse ───────────────────────────────────────────────────────────────
    def browse_left_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder",
                                                  self.left_path_edit.text())
        if folder:
            self.left_path_edit.setText(folder)

    def browse_right_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder",
                                                  self.right_path_edit.text())
        if folder:
            self.right_path_edit.setText(folder)

    # ── Import / Export ──────────────────────────────────────────────────────
    def _safe_export(self, source_path, content):
        if not content.strip():
            QMessageBox.warning(self, "Nothing to export", "The preview is empty.")
            return
        today       = date.today().strftime("%Y.%m.%d")
        folder_name = os.path.basename(source_path)
        safe_name   = "".join(c if c.isalnum() or c in " -_" else "_" for c in folder_name).strip("_")
        base_name   = f"{today}_folder-structure_{safe_name}.txt"
        txt_path    = os.path.join(source_path, base_name)

        if not os.path.exists(txt_path):
            try:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(content + "\n")
                self._show_export_success(txt_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Export failed:\n{str(e)}")
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("File Already Exists")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(f"The file already exists:\n{txt_path}")
        msg.setInformativeText("What would you like to do?")
        overwrite_btn = msg.addButton("Overwrite",            QMessageBox.ButtonRole.YesRole)
        newfile_btn   = msg.addButton("Create numbered copy", QMessageBox.ButtonRole.NoRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == overwrite_btn:
            try:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(content + "\n")
                self._show_export_success(txt_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Overwrite failed:\n{str(e)}")
        elif clicked == newfile_btn:
            i = 1
            while True:
                new_path = os.path.join(source_path,
                    f"{today}_folder-structure_{safe_name}_{i:02d}.txt")
                if not os.path.exists(new_path):
                    try:
                        with open(new_path, "w", encoding="utf-8") as f:
                            f.write(content + "\n")
                        self._show_export_success(new_path)
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Save failed:\n{str(e)}")
                    break
                i += 1

    def _show_export_success(self, txt_path):
        msg = QMessageBox(self)
        msg.setWindowTitle("Export Successful")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("Current preview exported")
        msg.setInformativeText(f"Location:\n{txt_path}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        open_btn = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            self._open_folder(os.path.dirname(txt_path))

    def export_left(self):
        path = self.left_path_edit.text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Error", "Invalid source folder.")
            return
        self._safe_export(path, self.left_preview.toPlainText().rstrip())

    def export_right(self):
        path = self.right_path_edit.text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Error", "Invalid source folder.")
            return
        self._safe_export(path, self.right_preview.toPlainText().rstrip())

    def _import_txt(self, prefix):
        txt_file, _ = QFileDialog.getOpenFileName(
            self, "Select structure .txt file", "",
            "Text files (*.txt);;All files (*.*)"
        )
        if not txt_file:
            return
        try:
            with open(txt_file, encoding="utf-8") as f:
                lines = [line.rstrip() for line in f
                         if line.strip() and not line.strip().startswith('#')]
            self._pause_compare()
            getattr(self, f"{prefix}_preview").setPlainText("\n".join(lines))
            self._resume_compare()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot load TXT file:\n{str(e)}")

    def import_txt_left(self):  self._import_txt("left")
    def import_txt_right(self): self._import_txt("right")

    # ── Line-by-line color compare ───────────────────────────────────────────
    def _both_previews_have_content(self):
        return bool(self.left_preview.toPlainText().strip()) and \
               bool(self.right_preview.toPlainText().strip())

    def _pause_compare(self):
        if hasattr(self, '_compare_timer'):
            self._compare_timer.stop()
        self._coloring_in_progress = True

    def _resume_compare(self):
        self._coloring_in_progress = False
        if self._line_compare_active:
            if self._both_previews_have_content():
                self._apply_line_colors()
            else:
                self._clear_line_colors()

    def toggle_line_compare(self):
        if not self._line_compare_active and not self._both_previews_have_content():
            QMessageBox.information(
                self, "Compare Names",
                "Please scan or load a structure into both\n"
                "Source Folder 1 and Source Folder 2 previews first."
            )
            return
        self._line_compare_active = not self._line_compare_active
        if self._line_compare_active:
            self.btn_compare_names.setText("Compare Left and Right Names Line by Line  ✔  ON")
            self.btn_compare_names.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50; color: white;
                    font-weight: bold; font-size: 13px; border-radius: 6px;
                }
                QPushButton:hover  { background-color: #66BB6A; }
                QPushButton:pressed{ background-color: #388E3C; }
            """)
            if not hasattr(self, '_compare_timer'):
                from PyQt6.QtCore import QTimer
                self._compare_timer = QTimer(self)
                self._compare_timer.setSingleShot(True)
                self._compare_timer.setInterval(150)
                self._compare_timer.timeout.connect(self._apply_line_colors)
                self.left_preview.text_changed.connect(self._schedule_color_update)
                self.right_preview.text_changed.connect(self._schedule_color_update)
            self._apply_line_colors()
        else:
            self.btn_compare_names.setText("Compare Left and Right Names Line by Line")
            self.btn_compare_names.setStyleSheet("""
                QPushButton {
                    background-color: #707070; color: white;
                    font-weight: bold; font-size: 13px; border-radius: 6px;
                }
                QPushButton:hover  { background-color: #888888; }
                QPushButton:pressed{ background-color: #555555; }
            """)
            if hasattr(self, '_compare_timer'):
                self._compare_timer.stop()
            self._clear_line_colors()

    def _schedule_color_update(self):
        if self._line_compare_active and not self._coloring_in_progress:
            if hasattr(self, '_compare_timer'):
                self._compare_timer.start()

    def _clear_line_colors(self):
        self._coloring_in_progress = True
        try:
            for preview in (self.left_preview, self.right_preview):
                doc = preview.editor.document()
                doc.blockSignals(True)
                try:
                    cursor = QTextCursor(doc)
                    cursor.beginEditBlock()
                    cursor.select(QTextCursor.SelectionType.Document)
                    fmt = QTextCharFormat()
                    fmt.setBackground(QColor("white"))
                    cursor.setCharFormat(fmt)
                    cursor.clearSelection()
                    cursor.endEditBlock()
                finally:
                    doc.blockSignals(False)
                preview._update_gutter_width()
                preview._gutter.update()
        finally:
            self._coloring_in_progress = False

    def _apply_line_colors(self):
        if self._coloring_in_progress or not self._line_compare_active:
            return
        self._coloring_in_progress = True
        try:
            COLOR_EQUAL = QColor("#b8f0b8")
            COLOR_DIFF  = QColor("#f0b8b8")
            COLOR_ONLY  = QColor("#f0f0b0")

            left_lines  = self.left_preview.editor.document().toPlainText().splitlines()
            right_lines = self.right_preview.editor.document().toPlainText().splitlines()

            def _color_doc(preview, lines, partner_lines):
                doc = preview.editor.document()
                doc.blockSignals(True)
                try:
                    cursor = QTextCursor(doc)
                    cursor.beginEditBlock()
                    for i in range(doc.blockCount()):
                        block = doc.findBlockByNumber(i)
                        if not block.isValid():
                            break
                        bc = QTextCursor(block)
                        bc.select(QTextCursor.SelectionType.BlockUnderCursor)
                        fmt = QTextCharFormat()
                        if i >= len(partner_lines):
                            fmt.setBackground(COLOR_ONLY)
                        elif lines[i].strip() == partner_lines[i].strip():
                            fmt.setBackground(COLOR_EQUAL)
                        else:
                            fmt.setBackground(COLOR_DIFF)
                        bc.setCharFormat(fmt)
                    cursor.endEditBlock()
                finally:
                    doc.blockSignals(False)
                preview._update_gutter_width()
                preview._gutter.update()

            _color_doc(self.left_preview,  left_lines,  right_lines)
            _color_doc(self.right_preview, right_lines, left_lines)
        finally:
            self._coloring_in_progress = False

    # ── Compare ──────────────────────────────────────────────────────────────
    def compare_previews(self):
        left_lines  = [l.rstrip() for l in self.left_preview.toPlainText().splitlines()]
        right_lines = [l.rstrip() for l in self.right_preview.toPlainText().splitlines()]
        if not left_lines and not right_lines:
            QMessageBox.information(self, "Compare", "Both previews are empty.")
            return
        ComparisonDialog(left_lines, right_lines, self).exec()

    # ── Replicate ────────────────────────────────────────────────────────────
    def _replicate(self, prefix):
        preview = getattr(self, f"{prefix}_preview")
        lines = [l.rstrip() for l in preview.toPlainText().splitlines() if l.strip()]
        if not lines:
            QMessageBox.warning(self, "Error", "No structure in preview to replicate.")
            return
        dest_folder = QFileDialog.getExistingDirectory(
            self, "Select folder where you want to create the structure"
        )
        if not dest_folder or not os.path.isdir(dest_folder):
            return
        try:
            self.create_from_lines(dest_folder, lines)
            msg = QMessageBox(self)
            msg.setWindowTitle("Replication Successful")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("Folder structure replicated.")
            msg.setInformativeText(f"Created in:\n{dest_folder}")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            open_btn = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
            msg.exec()
            if msg.clickedButton() == open_btn:
                self._open_folder(dest_folder)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to replicate:\n{str(e)}")

    def replicate_left(self):  self._replicate("left")
    def replicate_right(self): self._replicate("right")

    # ── Batch Rename ─────────────────────────────────────────────────────────
    def batch_rename(self):
        left_lines_raw  = self.left_preview.toPlainText().splitlines()
        right_lines_raw = self.right_preview.toPlainText().splitlines()

        left_lines  = [l.rstrip() for l in left_lines_raw  if l.strip()]
        right_lines = [l.rstrip() for l in right_lines_raw if l.strip()]

        if not left_lines or not right_lines:
            QMessageBox.warning(self, "Batch Rename", "Both previews must contain names.")
            return

        if len(left_lines) != len(right_lines):
            QMessageBox.warning(
                self, "Batch Rename",
                f"Line count mismatch!\nLeft: {len(left_lines)} lines  |  "
                f"Right: {len(right_lines)} lines\n"
                "Both previews must have the same number of non-empty lines."
            )
            return

        root = self.left_path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.warning(self, "Batch Rename",
                                "Please set a valid Left source folder path.")
            return

        # ── Resolve absolute paths for each left preview line ──
        #
        # PRIORITY: if we have stored abs paths from the last Scan (and the
        # line count still matches), use them directly — 100% reliable even
        # when subfolder names are duplicated across the tree.
        #
        # FALLBACK: reconstruct from indentation (works for manually typed
        # content or when the user edited the preview after scanning).

        if self._left_abs_paths and len(self._left_abs_paths) == len(left_lines):
            left_abs_paths = list(self._left_abs_paths)
        else:
            # Indentation-based reconstruction
            path_stack     = [root]
            left_abs_paths = []
            for line in left_lines:
                indent = len(line) - len(line.lstrip())
                level  = indent // 2
                name   = line.strip()
                while len(path_stack) > level + 1:
                    path_stack.pop()
                abs_path = os.path.join(path_stack[-1], name)
                left_abs_paths.append(abs_path)
                path_stack.append(abs_path)

        ops = []
        for i, (old_abs, right_line) in enumerate(zip(left_abs_paths, right_lines)):
            old_name = os.path.basename(old_abs)
            new_name = right_line.strip()
            if not new_name or new_name == old_name:
                continue
            new_abs = os.path.join(os.path.dirname(old_abs), new_name)
            ops.append((old_abs, new_abs, old_name, new_name))

        if not ops:
            QMessageBox.information(self, "Batch Rename",
                                    "No differences found — nothing to rename.")
            return

        # ── Confirm dialog ──
        confirm_dlg = QDialog(self)
        confirm_dlg.setWindowTitle("Confirm Batch Rename")
        confirm_dlg.resize(680, 420)
        c_layout = QVBoxLayout(confirm_dlg)
        c_layout.setContentsMargins(16, 16, 16, 12)
        c_layout.setSpacing(10)

        c_header = QLabel(f"About to rename <b>{len(ops)}</b> item(s) inside:<br>"
                          f"<code>{root}</code>")
        c_header.setWordWrap(True)
        c_layout.addWidget(c_header)

        c_info = QLabel(
            "⚠  Make sure no files or folders are open in other programs before proceeding."
        )
        c_info.setWordWrap(True)
        c_info.setStyleSheet("color: #cc6600;")
        c_layout.addWidget(c_info)

        col_label = QLabel(
            "<b>Current name (left preview)</b>  →  <b>New name (right preview)</b>"
        )
        col_label.setStyleSheet(
            "font-family: 'Segoe UI', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif; "
            "font-size: 12px; color: #555;"
        )
        c_layout.addWidget(col_label)

        pairs_lines = "\n".join(f"  {o}  →  {n}" for _, _, o, n in ops)
        c_scroll = QTextEdit()
        c_scroll.setReadOnly(True)
        c_scroll.setFont(QFont("Courier New", 11))
        c_scroll.setPlainText(pairs_lines)
        c_layout.addWidget(c_scroll, stretch=1)

        c_btn_row = QHBoxLayout()
        c_btn_row.setSpacing(10)
        c_btn_row.addStretch()
        c_cancel = QPushButton("Cancel")
        c_cancel.setFixedHeight(34)
        c_cancel.setFixedWidth(120)
        c_cancel.clicked.connect(confirm_dlg.reject)
        c_btn_row.addWidget(c_cancel)
        c_ok = QPushButton("Rename")
        c_ok.setFixedHeight(34)
        c_ok.setFixedWidth(120)
        c_ok.setDefault(True)
        c_ok.setStyleSheet(
            "background-color: #e65c00; color: white; "
            "font-weight: bold; border-radius: 4px;"
        )
        c_ok.clicked.connect(confirm_dlg.accept)
        c_btn_row.addWidget(c_ok)
        c_layout.addLayout(c_btn_row)

        if confirm_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # ── Execute: safe two-phase with rollback ──
        import uuid

        current_abs_map = {}

        def _resolve(path):
            for old_prefix in sorted(current_abs_map, key=len, reverse=True):
                cur_prefix = current_abs_map[old_prefix]
                if path == old_prefix:
                    return cur_prefix
                if path.startswith(old_prefix + os.sep):
                    return cur_prefix + path[len(old_prefix):]
            return path

        renamed    = []
        failed     = []
        skipped    = []
        phase2_ops = []

        for old_abs, new_abs, old_name, new_name in ops:
            old_resolved = _resolve(old_abs)
            if not os.path.exists(old_resolved):
                skipped.append(
                    f'SKIPPED  "{old_name}"\n'
                    f'  Expected path not found: {old_resolved}'
                )
                continue
            parent    = os.path.dirname(old_resolved)
            temp_name = f"__structify_tmp_{uuid.uuid4().hex}"
            temp_abs  = os.path.join(parent, temp_name)
            try:
                os.rename(old_resolved, temp_abs)
                current_abs_map[old_abs] = temp_abs
                phase2_ops.append((temp_abs, os.path.join(parent, new_name),
                                   old_resolved, old_name, new_name))
            except Exception as e:
                failed.append(
                    f'FAILED Phase 1  "{old_name}"\n'
                    f'  {old_resolved}  →  (temp)\n'
                    f'  Error: {e}'
                )

        conflicts = []   # target name already exists — original preserved

        for temp_abs, final_abs, original_abs, old_name, new_name in phase2_ops:
            # ── Pre-check: target already exists? ──
            # Check among the files that are NOT currently temp-named.
            # (All files being renamed are in temp state now, so a conflict
            # means a completely different file already carries that name.)
            if os.path.exists(final_abs):
                # Roll back: restore original name immediately
                try:
                    os.rename(temp_abs, original_abs)
                    restore_note = "Original name preserved — no data lost."
                except Exception as re2:
                    restore_note = (
                        f"⚠ RESTORE FAILED — file is temporarily named:\n"
                        f"  {temp_abs}\n"
                        f"  Rename it back manually to: {os.path.basename(original_abs)}\n"
                        f"  Restore error: {re2}"
                    )
                conflicts.append(
                    f'CONFLICT  "{old_name}"  →  "{new_name}"\n'
                    f'  A file named "{new_name}" already exists in:\n'
                    f'  {os.path.dirname(final_abs)}\n'
                    f'  {restore_note}'
                )
                continue

            try:
                os.rename(temp_abs, final_abs)
                renamed.append(f"{old_name}  →  {new_name}")
            except Exception as e:
                try:
                    os.rename(temp_abs, original_abs)
                    rollback_note = "  (✔ safely rolled back to original name)"
                except Exception as re2:
                    rollback_note = (
                        f"  ⚠ ROLLBACK FAILED — file is currently named:\n"
                        f"  {temp_abs}\n"
                        f"  Rename it back manually to: {os.path.basename(original_abs)}\n"
                        f"  Rollback error: {re2}"
                    )
                failed.append(
                    f'FAILED Phase 2  "{old_name}"  →  "{new_name}"\n'
                    f'  Error: {e}\n'
                    f'{rollback_note}'
                )

        # ── Result dialog ──
        summary_lines = []
        if renamed:
            summary_lines.append(f"✅  Renamed {len(renamed)} item(s) successfully.")
            summary_lines.append("")
            for r in renamed:
                summary_lines.append(f"  {r}")
        if conflicts:
            if summary_lines:
                summary_lines.append("")
            summary_lines.append(
                f"⚠️  {len(conflicts)} conflict(s) — target name already exists "
                f"(originals preserved, nothing lost):"
            )
            summary_lines.append("")
            for c in conflicts:
                summary_lines.append(f"  {c}")
                summary_lines.append("")
        if skipped:
            if summary_lines:
                summary_lines.append("")
            summary_lines.append(
                f"⚠️  {len(skipped)} item(s) not found on disk (not attempted):"
            )
            summary_lines.append("")
            for s in skipped:
                summary_lines.append(f"  {s}")
        if failed:
            if summary_lines:
                summary_lines.append("")
            summary_lines.append(f"❌  {len(failed)} error(s) — see details below:")
            summary_lines.append("")
            for fm in failed:
                summary_lines.append(f"  {fm}")
                summary_lines.append("")

        full_text = "\n".join(summary_lines)

        result_dlg = QDialog(self)
        result_dlg.setWindowTitle("Batch Rename Complete")
        result_dlg.resize(700, 400)
        dlg_layout = QVBoxLayout(result_dlg)
        dlg_layout.setContentsMargins(16, 16, 16, 12)
        dlg_layout.setSpacing(10)

        scroll_edit = QTextEdit()
        scroll_edit.setReadOnly(True)
        scroll_edit.setFont(QFont("Courier New", 11))
        scroll_edit.setPlainText(full_text)
        dlg_layout.addWidget(scroll_edit, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setFixedHeight(34)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(full_text))
        btn_row.addWidget(copy_btn)

        btn_row.addStretch()

        open_btn = QPushButton("Open Folder")
        open_btn.setFixedHeight(34)
        open_btn.clicked.connect(lambda: self._open_folder(root))
        btn_row.addWidget(open_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(34)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(result_dlg.accept)
        btn_row.addWidget(ok_btn)

        dlg_layout.addLayout(btn_row)
        result_dlg.exec()

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _open_folder(self, path):
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def create_from_lines(self, path, lines):
        stack = [path]
        for line in lines:
            indent = len(line) - len(line.lstrip())
            level  = indent // 2
            name   = line.strip()
            while len(stack) > level + 1:
                stack.pop()
            current = os.path.join(stack[-1], name)
            os.makedirs(current, exist_ok=True)
            stack.append(current)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FolderStructureApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
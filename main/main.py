"""
Structify — Folder Structure Tool
=================================
Tab 1  Compare & Explore      : scan two folders, compare structures inline
Tab 2  Rename Files & Folders : rename on disk, line N (left) -> line N (right)
Tab 3  Generate Tree Diagram  : build a documented tree (├── └── │)

All text previews use one PyCharm-style code editor (plain text only, FIXED
line height whatever glyphs appear, line numbers, dark theme, move/duplicate/
indent shortcuts).
"""
import sys
import os
import subprocess
import json
import uuid
from datetime import date
from typing import NamedTuple

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QPlainTextEdit, QTextEdit, QFileDialog,
    QMessageBox, QStyleFactory, QRadioButton, QButtonGroup, QDialog,
    QCheckBox, QFrame, QTabWidget, QSizePolicy, QListWidget, QComboBox, QMenu,
)
from PyQt6.QtCore import (
    Qt, QSize, QRect, QRectF, QPoint, QEvent, QTimer, QMimeData, pyqtSignal,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QFontInfo, QFontMetrics, QColor, QPainter,
    QPalette, QTextBlockFormat, QTextCursor, QTextFormat, QPen,
)

LAST_PATHS_FILE = "structify_last_paths.json"

# ── Editor look & feel (PyCharm-style dark) ──────────────────────────────────
EDITOR_FONT_SIZE = 11
EDITOR_FONT_MIN = 8
EDITOR_FONT_MAX = 28
EDITOR_FONT_CANDIDATES = [
    "JetBrains Mono", "Cascadia Mono", "Cascadia Code", "Consolas", "SF Mono",
    "Menlo", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "monospace",
]
THEME = {
    "bg":                "#1e1f22",
    "text":              "#e6e8eb",
    "border":            "#393b40",
    "gutter_bg":         "#25262a",
    "gutter_fg":         "#6f737a",
    "gutter_fg_current": "#c9ccd3",
    "current_line":      "#2a2c31",
    "selection":         "#2f65ca",
}
# Compare colours (dark-theme friendly, readable with light text)
COLOR_BOTH = "#2f6f3e"   # green  : same / found in both
COLOR_DIFF = "#7d3333"   # red    : different
COLOR_ONLY = "#7a6a1f"   # yellow : only on one side

EDITOR_QSS = f"""
QTextEdit {{
    background-color: {THEME['bg']};
    color: {THEME['text']};
    border: 1px solid {THEME['border']};
    selection-background-color: {THEME['selection']};
    selection-color: #ffffff;
}}
QAbstractScrollArea::corner {{ background: #2b2d30; }}
QScrollBar:vertical   {{ background: #2b2d30; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: #2b2d30; height: 12px; margin: 0; }}
QScrollBar::handle:vertical   {{ background: #4e5157; min-height: 28px; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #4e5157; min-width: 28px;  border-radius: 4px; margin: 2px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: #6f737a; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def make_editor_font(size=EDITOR_FONT_SIZE, family=None):
    """Monospace font with a safe fallback chain (never a proportional font)."""
    f = QFont()
    families = ([family] if family else []) + EDITOR_FONT_CANDIDATES
    f.setFamilies(families)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    f.setPointSize(max(EDITOR_FONT_MIN, min(EDITOR_FONT_MAX, int(size))))
    return f


# ── Text helpers ─────────────────────────────────────────────────────────────

def normalize_text(text, drop_blank_lines):
    """Make arbitrary (pasted / imported) text safe for the editors.

    - one line ending style, no zero-width / non-breaking characters
    - tabs become 2 spaces (the app uses 2 spaces per hierarchy level)
    - trailing whitespace removed
    - optionally blank lines removed
    """
    for ch in ("\r\n", "\r", "\u2028", "\u2029"):
        text = text.replace(ch, "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    out = []
    for ln in text.split("\n"):
        ln = ln.replace("\t", "  ").rstrip()
        if drop_blank_lines and not ln.strip():
            continue
        out.append(ln)
    return "\n".join(out)


def nonblank_lines(text):
    """Non-empty lines of editor text, indentation kept, trailing blanks cut."""
    return [ln.rstrip() for ln in text.split("\n") if ln.strip()]


def interior_blank_line_numbers(text):
    """1-based numbers of blank lines that sit BETWEEN content lines."""
    lines = text.split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    if not idx:
        return []
    return [i + 1 for i in range(idx[0], idx[-1]) if not lines[i].strip()]


# ── Ignore rules (folders that are left out of a scan) ───────────────────────

RULE_KINDS = (("starts", "starts with"), ("ends", "ends with"),
              ("contains", "contains"), ("equals", "is exactly"))
_RULE_LABEL = dict(RULE_KINDS)
MAX_RULES = 200
IGNORE_PANELS = ("left", "right", "t2_left", "t3_left")


def validate_rule_text(text):
    """Error text if `text` cannot be used in a rule, else None."""
    if not isinstance(text, str) or not text.strip():
        return "Please enter some text."
    if "/" in text or "\\" in text or "\x00" in text:
        return "A folder name cannot contain / or \\ ."
    if len(text.strip()) > 255:
        return "That is too long for a folder name."
    return None


class IgnoreRules(NamedTuple):
    """hidden: ignore folders starting with a dot.
    custom: tuple of (kind, text); kind is starts / ends / contains / equals."""
    hidden: bool = True
    custom: tuple = ()

    def is_active(self):
        return bool(self.hidden or self.custom)

    def matches(self, folder_name):
        if self.hidden and folder_name.startswith("."):
            return True
        if not self.custom:
            return False
        n = folder_name.casefold()
        for kind, text in self.custom:
            t = text.casefold()
            if ((kind == "starts" and n.startswith(t)) or (kind == "ends" and n.endswith(t))
                    or (kind == "contains" and t in n) or (kind == "equals" and n == t)):
                return True
        return False

    def describe(self):
        parts = ["starts with “.”"] if self.hidden else []
        parts += [f"{_RULE_LABEL[k]} “{t}”" for k, t in self.custom]
        return "  ·  ".join(parts)


def clean_rules(hidden, custom):
    """Build IgnoreRules from untrusted data (settings file, dialog): invalid or
    duplicate entries are dropped, nothing can raise."""
    out, seen = [], set()
    for item in (custom if isinstance(custom, (list, tuple)) else ()):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        kind, text = item
        if not isinstance(kind, str) or kind not in _RULE_LABEL or not isinstance(text, str):
            continue
        text = text.strip()
        if validate_rule_text(text):
            continue
        key = (kind, text.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, text))
        if len(out) >= MAX_RULES:
            break
    return IgnoreRules(bool(hidden), tuple(out))


# ── Folder structure ─────────────────────────────────────────────────────────

def get_folder_structure_with_paths(root_path, recursive=True,
                                    include_folders=True, include_files=True,
                                    ignore=None, ignored_out=None):
    """Return (display_lines, absolute_paths) — both lists have equal length.

    ignore: optional IgnoreRules. A matching FOLDER is left out completely,
    including everything inside it (files are never ignored by name).
    ignored_out: optional list that receives the relative paths of ignored folders.
    """
    display_lines, abs_paths = [], []
    if ignore is not None and not ignore.is_active():
        ignore = None
    if not recursive:
        try:
            entries = sorted(os.listdir(root_path))
        except PermissionError:
            return display_lines, abs_paths
        for name in entries:
            fp = os.path.join(root_path, name)
            if os.path.isdir(fp):
                if ignore is not None and ignore.matches(name):
                    if ignored_out is not None:
                        ignored_out.append(name)
                elif include_folders:
                    display_lines.append(name); abs_paths.append(fp)
            elif os.path.isfile(fp) and include_files:
                display_lines.append(name); abs_paths.append(fp)
        return display_lines, abs_paths

    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        if ignore is not None:
            keep = []
            for d in dirnames:
                if ignore.matches(d):
                    if ignored_out is not None:
                        ignored_out.append(os.path.relpath(os.path.join(dirpath, d), root_path))
                else:
                    keep.append(d)
            dirnames[:] = keep          # os.walk never enters the ignored folders
        dirnames.sort()
        rel = os.path.relpath(dirpath, root_path)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        indent = '  ' * (depth - 1) if depth > 0 else ''
        if rel != '.':
            if include_folders:
                display_lines.append(f"{indent}{os.path.basename(dirpath)}")
                abs_paths.append(dirpath)
            if include_files:
                for f in sorted(filenames):
                    display_lines.append(f"{'  ' * depth}{f}")
                    abs_paths.append(os.path.join(dirpath, f))
        elif include_files:
            for f in sorted(filenames):
                display_lines.append(f)
                abs_paths.append(os.path.join(dirpath, f))
    return display_lines, abs_paths


# ── Tree diagram ─────────────────────────────────────────────────────────────

def build_tree_diagram(lines, root_name="project"):
    items = []
    for line in lines:
        if not line.strip():
            continue
        items.append(((len(line) - len(line.lstrip())) // 2, line.strip()))
    if not items:
        return ""
    n = len(items)

    def is_file(name):
        return '.' in name and not name.startswith('.')

    # is_last[i]: item i has no later sibling (same parent)
    is_last = [True] * n
    has_later = {}
    for i in range(n - 1, -1, -1):
        d = items[i][0]
        is_last[i] = not has_later.get(d, False)
        has_later[d] = True
        for k in [k for k in has_later if k > d]:
            has_later[k] = False

    result = [f"{root_name}/", "│", "│"]
    anc = {}   # depth -> index of the latest item at that depth
    for i, (depth, name) in enumerate(items):
        anc[depth] = i
        hc = i + 1 < n and items[i + 1][0] > depth

        def bars(upto):
            return "".join("    " if is_last[anc[d]] else "│   " for d in range(upto))

        display = name + ("/" if (not is_file(name)) and hc else "")
        full = bars(depth) + ("└── " if is_last[i] else "├── ") + display
        result.append(full + " " * max(1, 52 - len(full)) + "# ← add description here")
        if (not is_file(name)) and hc:
            result.append(bars(items[i + 1][0]) + "│")
        if i + 1 < n and items[i + 1][0] == 0:
            result.append("│")
    return "\n".join(result)


# ── Safe renaming engine ─────────────────────────────────────────────────────

RENAME_TMP_PREFIX = "__structify_tmp_"
_WIN_RESERVED = ({"CON", "PRN", "AUX", "NUL"} |
                 {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)})


class RenameOp(NamedTuple):
    old_abs: str     # current absolute path
    old_name: str    # basename of old_abs
    new_name: str    # desired name (no path!)
    final_abs: str   # dirname(old_abs) / new_name


def _key(p):
    return os.path.normcase(os.path.normpath(p))


def _depth(p):
    return len([x for x in os.path.normpath(p).split(os.sep) if x])


def validate_new_name(name):
    """Return an error text if `name` is not a safe single file/folder name."""
    if not name:
        return "The new name is empty."
    if name in (".", ".."):
        return f'"{name}" is not a valid name.'
    if "/" in name or "\\" in name or "\x00" in name:
        return "A name must not contain / or \\ (that would move the item)."
    if len(name) > 255:
        return "The name is longer than 255 characters."
    if sys.platform == "win32":
        bad = sorted({c for c in name if c in '<>:"|?*' or ord(c) < 32})
        if bad:
            return "Not allowed in Windows names: " + " ".join(bad)
        if name[-1] in " .":
            return "Windows names must not end with a space or a dot."
        if name.split(".")[0].upper() in _WIN_RESERVED:
            return "This is a reserved Windows device name."
    return None


def plan_renames(ops):
    """Decide BEFORE touching the disk which renames are safe.

    Returns (clean, rejected, missing):
      clean    - ops that can be executed
      rejected - list of (op, reason): conflicts / invalid names
      missing  - ops whose source no longer exists
    Items renaming into each other (A->B, B->C, swaps) are fine; a name that is
    occupied by an item OUTSIDE the batch is a conflict (only that item is
    skipped, everything else still runs).
    """
    rejected, missing, live = [], [], []
    src_count = {}
    for op in ops:
        src_count[_key(op.old_abs)] = src_count.get(_key(op.old_abs), 0) + 1
    for op in ops:
        if src_count[_key(op.old_abs)] > 1:
            rejected.append((op, "The same item appears more than once in the list."))
        elif not os.path.lexists(op.old_abs):
            missing.append(op)
        else:
            err = validate_new_name(op.new_name)
            if err:
                rejected.append((op, err))
            else:
                live.append(op)

    blocked = {}
    while True:
        active = [op for op in live if _key(op.old_abs) not in blocked]
        vacated = {_key(op.old_abs) for op in active}
        newly = {}
        groups = {}
        for op in active:
            groups.setdefault(_key(op.final_abs), []).append(op)
        for grp in groups.values():
            if len(grp) > 1:
                for op in grp:
                    newly[_key(op.old_abs)] = (
                        f'Several items in the list want the same new name "{op.new_name}".')
        if not newly:
            for op in active:
                fk = _key(op.final_abs)
                if fk == _key(op.old_abs):
                    continue   # case-only rename on a case-insensitive disk
                if os.path.lexists(op.final_abs) and fk not in vacated:
                    newly[_key(op.old_abs)] = (
                        f'"{op.new_name}" already exists in this folder.')
        if not newly:
            break
        blocked.update(newly)

    clean = [op for op in live if _key(op.old_abs) not in blocked]
    rejected.extend((op, blocked[_key(op.old_abs)]) for op in live
                    if _key(op.old_abs) in blocked)
    return clean, rejected, missing


def execute_renames(clean):
    """Two-phase rename: everything -> unique temp name -> final name.

    Deepest items go first so nested renames (folder + its content) work.
    Every failure restores the original name. Returns (renamed, failed, conflicts).
    """
    renamed, failed, conflicts = [], [], []
    ordered = sorted(clean, key=lambda o: -_depth(o.old_abs))
    tmp_of, staged = {}, []

    for op in ordered:                                    # phase 1
        tmp = f"{RENAME_TMP_PREFIX}{uuid.uuid4().hex}"
        try:
            os.rename(op.old_abs, os.path.join(os.path.dirname(op.old_abs), tmp))
            tmp_of[_key(op.old_abs)] = tmp
            staged.append(op)
        except OSError as e:
            failed.append(f'FAILED  "{op.old_name}" could not be renamed '
                          f'(nothing was changed)\n    {e}')

    def where(p):
        """Location of an ORIGINAL path after phase 1."""
        parent = os.path.dirname(p)
        if parent == p:
            return p
        return os.path.join(where(parent), tmp_of.get(_key(p), os.path.basename(p)))

    def restore(cur, orig):
        try:
            os.rename(cur, orig)
            return "Original name restored - nothing lost."
        except OSError as e:
            return (f"WARNING: could not restore automatically. The item is currently "
                    f"named:\n    {cur}\n    Rename it back to: {os.path.basename(orig)}\n    {e}")

    for op in staged:                                     # phase 2
        parent_loc = where(os.path.dirname(op.old_abs))
        cur = os.path.join(parent_loc, tmp_of[_key(op.old_abs)])
        final = os.path.join(parent_loc, op.new_name)
        orig = os.path.join(parent_loc, op.old_name)
        if os.path.lexists(final):
            conflicts.append(f'CONFLICT  "{op.old_name}" -> "{op.new_name}"\n'
                             f'    The name became occupied.\n    {restore(cur, orig)}')
            continue
        try:
            os.rename(cur, final)
            renamed.append(f"{op.old_name}  →  {op.new_name}")
        except OSError as e:
            failed.append(f'FAILED  "{op.old_name}" -> "{op.new_name}"\n    {e}\n'
                          f'    {restore(cur, orig)}')
    return renamed, failed, conflicts


# ── Code editor ──────────────────────────────────────────────────────────────

FIXED_HEIGHT = QTextBlockFormat.LineHeightTypes.FixedHeight.value   # == 2


class _Gutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._ed = editor

    def sizeHint(self):
        return QSize(self._ed.gutter_width(), 0)

    def paintEvent(self, event):
        self._ed.paint_gutter(event)

    def mousePressEvent(self, event):
        self._ed.select_line_at(int(event.position().y()))


class _ColumnToggle(QWidget):
    """Small overlay icon (top-right corner of an editor) that switches the
    column-selection / multi-cursor mode on and off."""
    SIZE = 22

    def __init__(self, editor):
        super().__init__(editor.viewport())
        self._ed = editor
        self._hover = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setToolTip(
            "Column selection mode (multi-cursor)\n"
            "Toggle: Ctrl+Alt+Insert  or  Alt+Shift+Insert\n"
            "Alt+Shift+drag selects a block at any time \u00b7 Esc leaves the mode")

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._ed.set_column_mode(not self._ed.column_mode())
            self._ed.setFocus(Qt.FocusReason.OtherFocusReason)
            e.accept()
        else:
            e.ignore()

    def paintEvent(self, e):
        on = self._ed.column_mode()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        if on:
            bg, border, fg = QColor(THEME["selection"]), QColor("#5b8def"), QColor("#ffffff")
        else:
            bg = QColor("#2b2d30" if not self._hover else "#34373c")
            border = QColor(THEME["border"])
            fg = QColor("#c9ccd3" if self._hover else "#8b8f97")
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 4, 4)
        # icon: dashed block with three carets in one column
        pen = QPen(fg, 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(5.5, 5.5, 11.0, 11.0))
        p.setPen(QPen(fg, 1.6))
        cx = 11.0
        for y in (7.0, 11.0, 15.0):
            p.drawLine(QPoint(int(cx), int(y - 2)), QPoint(int(cx), int(y + 2)))
        p.end()


class LineNumberedEditor(QTextEdit):
    """PyCharm-style plain-text editor.

    * plain text only (rich text is refused) and every line has the SAME fixed
      height, no matter which glyphs it contains (CJK, emoji, symbols ...)
    * line numbers are taken from the real line positions -> they cannot overlap
    * paste is normalised (no foreign fonts, tabs, blank lines, NBSP ...)
    * Enter keeps the indentation and splits the line at the cursor
    * Tab / Shift+Tab indent, Shift+Alt+Up/Down (or Ctrl+Shift+Up/Down) move
      lines, Ctrl+D duplicates, Ctrl+wheel / Ctrl +/-/0 zoom
    * compare colours are painted with extra selections (text is never touched)
    * column (block) selection with several blinking carets, PyCharm style:
      toggle with Ctrl+Alt+Insert / Alt+Shift+Insert or the corner icon,
      Alt+Shift+drag (or middle-mouse drag) selects a block at any time
    """
    text_changed = pyqtSignal()
    zoom_requested = pyqtSignal(int)      # +1 / -1 / 0 (= reset)
    column_mode_changed = pyqtSignal(bool)

    def __init__(self, parent=None, strip_blank_lines=True):
        super().__init__(parent)
        self._strip_blank = strip_blank_lines
        # column mode state: _block = (anchor_line, anchor_col, head_line, head_col)
        self._col_mode = False
        self._block = None
        self._goal_col = 0
        self._col_busy = False        # True while WE move the native cursor / edit
        self._col_join = False        # next typed text joins the previous undo step
        self._dragging = False
        self._caret_on = True
        self._compare_selections = []
        self._line_h = 16.0
        self._ascent = 12
        self._gutter = _Gutter(self)
        self._fmt_timer = QTimer(self)
        self._fmt_timer.setSingleShot(True)
        self._fmt_timer.setInterval(120)
        self._fmt_timer.timeout.connect(self._ensure_line_format)

        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        opt = self.document().defaultTextOption()          # file lists always start at the
        opt.setTextDirection(Qt.LayoutDirection.LeftToRight)   # left, even for Arabic/Hebrew
        self.document().setDefaultTextOption(opt)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCursorWidth(2)
        self.setStyleSheet(EDITOR_QSS)
        self.document().blockCountChanged.connect(self._update_gutter_width)
        self.verticalScrollBar().valueChanged.connect(self._gutter.update)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.textChanged.connect(self._on_text_changed)
        self._blink = QTimer(self)
        flash = QApplication.cursorFlashTime()
        self._blink.setInterval(max(250, flash // 2) if flash > 1 else 500)
        self._blink.timeout.connect(self._blink_tick)
        self._toggle = _ColumnToggle(self)
        self.viewport().installEventFilter(self)
        self.setFont(make_editor_font())      # -> changeEvent -> _sync_metrics
        self._sync_metrics()
        self._on_cursor_moved()
        self._place_toggle()

    # ── fixed line height ────────────────────────────────────────────────────
    def _line_format(self):
        f = QTextBlockFormat()
        f.setLineHeight(self._line_h, FIXED_HEIGHT)
        f.setTopMargin(0)
        f.setBottomMargin(0)
        return f

    def _apply_line_format(self):
        """Give EVERY line the fixed height (load / font change).
        Formatting is never an undo step, so the history is cleared."""
        doc = self.document()
        doc.blockSignals(True)
        doc.setUndoRedoEnabled(False)
        try:
            c = QTextCursor(doc)
            c.select(QTextCursor.SelectionType.Document)
            c.mergeBlockFormat(self._line_format())
        finally:
            doc.setUndoRedoEnabled(True)
            doc.blockSignals(False)

    def _ensure_line_format(self):
        """Safety net: repair any line that lost the fixed height (normally none)."""
        doc, want = self.document(), self._line_h
        bad = []
        b = doc.firstBlock()
        while b.isValid():
            f = b.blockFormat()
            if f.lineHeightType() != FIXED_HEIGHT or abs(f.lineHeight() - want) > 0.01:
                bad.append(b.position())
            b = b.next()
        if not bad:
            return
        doc.blockSignals(True)
        ec = QTextCursor(doc)
        ec.joinPreviousEditBlock()
        for pos in bad:
            c = QTextCursor(doc)
            c.setPosition(pos)
            c.mergeBlockFormat(self._line_format())
        ec.endEditBlock()
        doc.blockSignals(False)
        self._gutter.update()

    def _sync_metrics(self):
        fm = QFontMetrics(self.font())
        new_h = float(fm.height())
        changed = abs(new_h - self._line_h) > 0.01
        self._line_h = new_h
        self._ascent = fm.ascent()
        self.setTabStopDistance(2 * fm.horizontalAdvance(" "))
        if changed:
            self._apply_line_format()
        self._update_gutter_width()
        self._place_gutter()
        self._gutter.update()

    # ── public API ───────────────────────────────────────────────────────────
    def setPlainText(self, text):
        """Load content (normalised). Resets scroll position and colours."""
        self._compare_selections = []
        self._col_join = False
        super().setPlainText(normalize_text(text, self._strip_blank))
        self._apply_line_format()
        if self._col_mode:
            self._block = (0, 0, 0, 0)
            self._goal_col = 0
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self._refresh_selections()

    def set_line_colors(self, colors):
        """colors[i] is a QColor (or None) for line i. Text is not modified."""
        sels = []
        block, i = self.document().firstBlock(), 0
        while block.isValid() and i < len(colors):
            c = colors[i]
            if c is not None:
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(c)
                s.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                cur = QTextCursor(block)
                cur.clearSelection()
                s.cursor = cur
                sels.append(s)
            block = block.next()
            i += 1
        self._compare_selections = sels
        self._refresh_selections()

    def clear_line_colors(self):
        self._compare_selections = []
        self._refresh_selections()

    # ── paste handling ───────────────────────────────────────────────────────
    def insertFromMimeData(self, source):
        if self.isReadOnly() or not source.hasText():
            return
        raw = source.text().replace("\r\n", "\n").replace("\r", "\n")
        if self._col_mode and self._block is not None:
            if self._column_paste(raw):
                return
        text = normalize_text(raw, self._strip_blank)
        if text and raw.endswith("\n"):
            text += "\n"            # pasting a whole line keeps its line break
        cur = self.textCursor()
        cur.insertText(text)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def createMimeDataFromSelection(self):
        """Copy / cut put PLAIN TEXT only on the clipboard (no fonts, no HTML)."""
        md = QMimeData()
        if self._col_mode and self._block is not None:
            md.setText(self._column_text())
        else:
            md.setText(self.textCursor().selection().toPlainText())
        return md

    # ── keyboard ─────────────────────────────────────────────────────────────
    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)

        if ctrl and not alt and key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_requested.emit(1); return
        if ctrl and not alt and key == Qt.Key.Key_Minus:
            self.zoom_requested.emit(-1); return
        if ctrl and not alt and not shift and key == Qt.Key.Key_0:
            self.zoom_requested.emit(0); return

        # column mode: Ctrl+Alt+Insert (as asked) and Alt+Shift+Insert (PyCharm)
        if key == Qt.Key.Key_Insert and alt and (ctrl or shift):
            self.set_column_mode(not self._col_mode)
            return
        if self._col_mode and self._block is not None and self._column_key(e):
            return

        if not self.isReadOnly():
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and shift and (alt or ctrl):
                self._move_lines(up=(key == Qt.Key.Key_Up)); return
            if ctrl and not shift and not alt and key == Qt.Key.Key_D:
                self._duplicate(); return
            if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and shift):
                self._dedent(); return
            if key == Qt.Key.Key_Tab and not ctrl and not alt:
                self._indent(); return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (ctrl or alt):
                self._newline(); return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            d = e.angleDelta().y()
            if d:
                self.zoom_requested.emit(1 if d > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    # ── editing helpers ──────────────────────────────────────────────────────
    def _block_range(self):
        cur = self.textCursor()
        doc = self.document()
        s, e = cur.selectionStart(), cur.selectionEnd()
        first = doc.findBlock(s).blockNumber()
        last_block = doc.findBlock(e)
        last = last_block.blockNumber()
        if cur.hasSelection() and e == last_block.position() and last > first:
            last -= 1               # selection ends at the start of the next line
        return first, last

    def _select_blocks(self, first_no, last_no):
        doc = self.document()
        fb, lb = doc.findBlockByNumber(first_no), doc.findBlockByNumber(last_no)
        c = QTextCursor(doc)
        c.setPosition(fb.position())
        c.setPosition(lb.position() + lb.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)

    def _newline(self):
        cur = self.textCursor()
        cur.beginEditBlock()
        if cur.hasSelection():
            cur.removeSelectedText()
        text = cur.block().text()
        col = cur.positionInBlock()
        lead = text[:len(text) - len(text.lstrip(" "))]
        cur.insertText("\n" + lead[:col])     # text after the cursor moves down
        cur.endEditBlock()
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def _indent(self):
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.insertText(" " * (2 - cur.positionInBlock() % 2))
            self.setTextCursor(cur)
            return
        first, last = self._block_range()
        doc = self.document()
        ec = QTextCursor(doc)
        ec.beginEditBlock()
        for n in range(first, last + 1):
            QTextCursor(doc.findBlockByNumber(n)).insertText("  ")
        ec.endEditBlock()
        self._select_blocks(first, last)

    def _dedent(self):
        first, last = self._block_range()
        had_sel = self.textCursor().hasSelection()
        doc = self.document()
        ec = QTextCursor(doc)
        ec.beginEditBlock()
        for n in range(first, last + 1):
            b = doc.findBlockByNumber(n)
            t = b.text()
            k = min(2, len(t) - len(t.lstrip(" ")))
            if k:
                c = QTextCursor(b)
                c.movePosition(QTextCursor.MoveOperation.NextCharacter,
                               QTextCursor.MoveMode.KeepAnchor, k)
                c.removeSelectedText()
        ec.endEditBlock()
        if had_sel:
            self._select_blocks(first, last)

    def _duplicate(self):
        cur = self.textCursor()
        doc = self.document()
        if cur.hasSelection():
            text = cur.selectedText().replace("\u2029", "\n")
            c = QTextCursor(doc)
            c.setPosition(cur.selectionEnd())
            c.insertText(text)
            return
        block = cur.block()
        col = cur.positionInBlock()
        text = block.text()
        c = QTextCursor(block)
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        c.insertText("\n" + text)
        nb = block.next()
        c2 = QTextCursor(nb)
        c2.setPosition(nb.position() + min(col, len(text)))
        self.setTextCursor(c2)

    def _move_lines(self, up):
        doc = self.document()
        cur = self.textCursor()
        had_sel, col = cur.hasSelection(), cur.positionInBlock()
        first, last = self._block_range()
        if up:
            if first == 0:
                return
            other = first - 1
        else:
            if last >= doc.blockCount() - 1:
                return
            other = last + 1
        r0, r1 = min(first, other), max(last, other)
        texts = [doc.findBlockByNumber(i).text() for i in range(r0, r1 + 1)]
        n = last - first + 1
        moved = texts[first - r0:first - r0 + n]
        other_text = texts[other - r0]
        new = moved + [other_text] if up else [other_text] + moved
        b0, b1 = doc.findBlockByNumber(r0), doc.findBlockByNumber(r1)
        ec = QTextCursor(doc)
        ec.beginEditBlock()
        ec.setPosition(b0.position())
        ec.setPosition(b1.position() + b1.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        ec.insertText("\n".join(new))
        ec.endEditBlock()
        nf = first - 1 if up else first + 1
        if had_sel:
            self._select_blocks(nf, nf + n - 1)
        else:
            b = doc.findBlockByNumber(nf)
            c = QTextCursor(b)
            c.setPosition(b.position() + min(col, len(b.text())))
            self.setTextCursor(c)
        self.ensureCursorVisible()

    def select_line_at(self, y):
        c = self.cursorForPosition(QPoint(0, y))
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        if not c.movePosition(QTextCursor.MoveOperation.NextBlock,
                              QTextCursor.MoveMode.KeepAnchor):
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                           QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)
        self.setFocus()

    # ── column selection / multi-cursor ──────────────────────────────────────
    def column_mode(self):
        return self._col_mode

    def set_column_mode(self, on, collapse=True):
        """Switch column mode on/off. Turning it off leaves ONE normal caret
        (at the head of the block) unless collapse=False (a real selection exists)."""
        on = bool(on)
        if on == self._col_mode:
            return
        doc = self.document()
        if on:
            cur = self.textCursor()
            ab = doc.findBlock(cur.anchor())
            self._col_mode = True
            self._block = (ab.blockNumber(), cur.anchor() - ab.position(),
                           cur.blockNumber(), cur.positionInBlock())
            self._goal_col = cur.positionInBlock()
            self.setCursorWidth(0)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self._sync_native()
            self._blink.start()
        else:
            head = self._block
            self._col_mode = False
            self._block = None
            self._dragging = False
            self._col_join = False
            self._blink.stop()
            self.setCursorWidth(2)
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            if collapse and head is not None:
                blk = doc.findBlockByNumber(min(head[2], doc.blockCount() - 1))
                c = QTextCursor(blk)
                c.setPosition(blk.position() + min(head[3], len(blk.text())))
                self.setTextCursor(c)
        self._caret_on = True
        self._toggle.update()
        self._refresh_selections()
        self._gutter.update()
        self.viewport().update()
        self.column_mode_changed.emit(self._col_mode)

    def _block_rect(self):
        al, ac, hl, hc = self._block
        return min(al, hl), max(al, hl), min(ac, hc), max(ac, hc)

    def _clamp_block(self):
        last = self.document().blockCount() - 1
        al, ac, hl, hc = self._block
        self._block = (max(0, min(al, last)), ac, max(0, min(hl, last)), hc)

    def _max_len(self, first, last):
        doc, m = self.document(), 0
        for n in range(first, last + 1):
            b = doc.findBlockByNumber(n)
            if b.isValid():
                m = max(m, len(b.text()))
        return m

    def _rows(self):
        """[(block, sel_start, sel_end)] for every line of the block that reaches
        the block's left column (shorter lines get no caret)."""
        l0, l1, a, b = self._block_rect()
        doc, rows = self.document(), []
        blk, n = doc.findBlockByNumber(l0), l0
        while blk.isValid() and n <= l1:
            ln = len(blk.text())
            if ln >= a:
                rows.append((blk, a, min(b, ln)))
            blk = blk.next()
            n += 1
        return rows

    def _column_text(self):
        l0, l1, a, b = self._block_rect()
        if a >= b:
            return ""
        doc, out = self.document(), []
        for n in range(l0, l1 + 1):
            out.append(doc.findBlockByNumber(n).text()[a:b])
        return "\n".join(out)

    def _column_selections(self):
        out = []
        l0, l1, a, b = self._block_rect()
        if a >= b:
            return out
        blk, n = self.document().findBlockByNumber(l0), l0
        fg = QColor("#ffffff")
        bg = QColor(THEME["selection"])
        while blk.isValid() and n <= l1:
            ln = len(blk.text())
            if ln > a:
                c = QTextCursor(blk)
                c.setPosition(blk.position() + a)
                c.setPosition(blk.position() + min(b, ln), QTextCursor.MoveMode.KeepAnchor)
                s = QTextEdit.ExtraSelection()
                s.cursor = c
                s.format.setBackground(bg)
                s.format.setForeground(fg)
                out.append(s)
            blk = blk.next()
            n += 1
        return out

    def _sync_native(self):
        """Park the real (hidden) cursor at the head of the block."""
        al, ac, hl, hc = self._block
        doc = self.document()
        blk = doc.findBlockByNumber(max(0, min(hl, doc.blockCount() - 1)))
        c = QTextCursor(blk)
        c.setPosition(blk.position() + min(hc, len(blk.text())))
        was = self._col_busy
        self._col_busy = True
        try:
            self.setTextCursor(c)
            self.ensureCursorVisible()
        finally:
            self._col_busy = was

    def _col_changed(self):
        self._caret_on = True
        self._blink.start()
        self._refresh_selections()
        self._gutter.update()
        self.viewport().update()

    def _blink_tick(self):
        if self._col_mode and self._block is not None:
            self._caret_on = not self._caret_on
            self.viewport().update()

    def _col_edit(self, kind, payload=None):
        """Apply one edit at every caret as ONE undo step.
        kind: 'insert' (payload: str or list of str per row) | 'back' | 'delete'.
        Returns True when the key was consumed."""
        if not self._col_mode or self._block is None:
            return False
        if self.isReadOnly():
            return True
        rows = self._rows()
        if not rows:
            return True
        al, ac, hl, hc = self._block
        l0, l1, a, b = self._block_rect()
        plan, newcol, collapse_row = [], a, None
        if kind == "insert":
            if isinstance(payload, str):
                payload = [payload] * len(rows)
            texts = payload
            if all(len(t) == len(texts[0]) for t in texts):
                newcol = a + len(texts[0])
            else:
                collapse_row = len(rows) - 1
            for (blk, f, t), txt in zip(rows, texts):
                plan.append((blk, f, t, txt))
        elif kind == "back":
            if a < b:
                plan = [(blk, f, t, "") for blk, f, t in rows]
            elif a > 0:
                plan = [(blk, f - 1, f, "") for blk, f, t in rows]
                newcol = a - 1
        elif kind == "delete":
            if a < b:
                plan = [(blk, f, t, "") for blk, f, t in rows]
            else:
                plan = [(blk, f, f + 1, "") for blk, f, t in rows
                        if f < len(blk.text())]
        plan = [x for x in plan if x[2] > x[1] or x[3]]
        if not plan:
            return True
        doc = self.document()
        self._col_busy = True
        try:
            ec = QTextCursor(doc)
            if kind == "insert" and self._col_join:
                ec.joinPreviousEditBlock()
            else:
                ec.beginEditBlock()
            try:
                for blk, f, t, ins in plan:
                    c = QTextCursor(doc)
                    c.setPosition(blk.position() + f)
                    if t > f:
                        c.setPosition(blk.position() + t, QTextCursor.MoveMode.KeepAnchor)
                    if ins:
                        c.insertText(ins)
                    elif t > f:
                        c.removeSelectedText()
            finally:
                ec.endEditBlock()
            if collapse_row is not None:
                blk, f, t = rows[collapse_row]
                col = f + len(texts[collapse_row])
                nl = blk.blockNumber()
                self._block = (nl, col, nl, col)
            else:
                self._block = (al, newcol, hl, newcol)
            self._goal_col = self._block[3]
            self._col_join = (kind == "insert" and collapse_row is None)
            self._sync_native()
        finally:
            self._col_busy = False
        self._col_changed()
        return True

    def _column_paste(self, raw):
        """Paste into the column block. Returns False if the normal paste should run."""
        if self.isReadOnly() or self._block is None:
            return True
        text = normalize_text(raw, False)
        lines = text.split("\n")
        if len(lines) > 1 and lines[-1] == "":
            lines.pop()
        if not lines or all(x == "" for x in lines):
            return True
        rows = self._rows()
        if len(lines) == 1 or len(lines) == len(rows):
            self._col_join = False
            if len(lines) == 1:
                self._col_edit("insert", lines[0])
            else:
                self._col_edit("insert", lines)
            self._col_join = False
            return True
        self.set_column_mode(False)           # shape does not fit -> ordinary paste
        return False

    def _column_copy(self, cut=False):
        txt = self._column_text()
        if txt:
            QApplication.clipboard().setText(txt)
            if cut and not self.isReadOnly():
                self._col_join = False
                self._col_edit("delete")

    def _column_arrow(self, key, shift):
        al, ac, hl, hc = self._block
        l0, l1, a, b = self._block_rect()
        last = self.document().blockCount() - 1
        K = Qt.Key
        if shift:
            if key == K.Key_Up:
                hl = max(0, hl - 1)
            elif key == K.Key_Down:
                hl = min(last, hl + 1)
            elif key == K.Key_Left:
                hc = max(0, hc - 1)
                self._goal_col = hc
            elif key == K.Key_Right:
                cap = self._max_len(min(al, hl), max(al, hl))
                hc = max(hc, min(hc + 1, cap))
                self._goal_col = hc
            self._block = (al, ac, hl, hc)
        elif key in (K.Key_Left, K.Key_Right):
            if a < b:
                col = a if key == K.Key_Left else b
            elif key == K.Key_Left:
                col = max(0, hc - 1)
            else:
                col = max(hc, min(hc + 1, self._max_len(l0, l1)))
            self._goal_col = col
            self._block = (al, col, hl, col)
        else:
            d = -1 if key == K.Key_Up else 1
            if l0 + d < 0 or l1 + d > last:
                return
            if al == hl and ac == hc:                       # single caret
                nl = al + d
                col = min(self._goal_col, len(self.document().findBlockByNumber(nl).text()))
                self._block = (nl, col, nl, col)
            else:
                self._block = (al + d, ac, hl + d, hc)
        self._sync_native()
        self._col_changed()

    def _column_key(self, e):
        """Key handling while column mode is on. True = consumed."""
        K = Qt.Key
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        plain = not (ctrl or shift or alt)

        if key == K.Key_Escape and plain:
            self.set_column_mode(False)
            return True
        if (ctrl and not alt and not shift and key in (K.Key_C, K.Key_Insert)):
            self._column_copy(False)
            return True
        if ((ctrl and not alt and not shift and key == K.Key_X)
                or (shift and not ctrl and not alt and key == K.Key_Delete)):
            self._column_copy(True)
            return True
        if key in (K.Key_Left, K.Key_Right, K.Key_Up, K.Key_Down):
            if (not ctrl and not alt) or (shift and key in (K.Key_Up, K.Key_Down)):
                self._column_arrow(key, shift)
                return True
            return False
        if shift and not ctrl and not alt and key in (K.Key_Home, K.Key_End):
            al, ac, hl, hc = self._block
            hc = 0 if key == K.Key_Home else self._max_len(min(al, hl), max(al, hl))
            self._block = (al, ac, hl, hc)
            self._goal_col = hc
            self._sync_native()
            self._col_changed()
            return True
        if key == K.Key_Backspace and not ctrl and not alt:
            self._col_join = False
            return self._col_edit("back")
        if key == K.Key_Delete and plain:
            self._col_join = False
            return self._col_edit("delete")
        if key == K.Key_Tab and plain:
            self._col_join = False
            a = self._block_rect()[2]
            return self._col_edit("insert", " " * (2 - a % 2))
        if key == K.Key_Backtab or (key == K.Key_Tab and shift):
            return True
        if key in (K.Key_Return, K.Key_Enter) and not (ctrl or alt):
            self.set_column_mode(False)
            if not self.isReadOnly():
                self._newline()
            return True
        txt = e.text()
        if txt and not (alt and not ctrl) and not (ctrl and not alt):
            if txt.isprintable():
                return self._col_edit("insert", txt)
            return True            # NBSP, zero-width, control characters: never inserted
        return False

    # mouse -----------------------------------------------------------------
    def _pos_to_lc(self, pos):
        """viewport point -> (line, column); the column may lie beyond the line end."""
        c = self.cursorForPosition(pos)
        blk = c.block()
        col = c.positionInBlock()
        if col >= len(blk.text()):
            sp = max(1, self.fontMetrics().horizontalAdvance(" "))
            extra = int(round((pos.x() - self.cursorRect(c).x()) / sp))
            col = len(blk.text()) + max(0, min(extra, 5000))
        return blk.blockNumber(), col

    def mousePressEvent(self, e):
        btn = e.button()
        mods = e.modifiers()
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        left = btn == Qt.MouseButton.LeftButton
        if not ((left and (self._col_mode or (alt and shift)))
                or btn == Qt.MouseButton.MiddleButton):
            super().mousePressEvent(e)
            return
        was_on = self._col_mode
        if not was_on:
            self.set_column_mode(True)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        l, c = self._pos_to_lc(e.position().toPoint())
        self._col_join = False
        if was_on and shift and not alt and self._block is not None:
            al, ac, _, _ = self._block
            self._block = (al, ac, l, c)                     # extend existing block
        else:
            self._block = (l, c, l, c)
            self._goal_col = c
        self._dragging = True
        self._sync_native()
        self._col_changed()
        e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging and self._col_mode and self._block is not None:
            if e.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.MiddleButton):
                l, c = self._pos_to_lc(e.position().toPoint())
                al, ac, hl, hc = self._block
                if (l, c) != (hl, hc):
                    self._block = (al, ac, l, c)
                    self._goal_col = c
                    self._sync_native()
                    self._col_changed()
                e.accept()
                return
            self._dragging = False
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self._col_mode:
            self.mousePressEvent(e)
            return
        super().mouseDoubleClickEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._caret_on = True
        if self._col_mode:
            self._blink.start()
            self.viewport().update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self._dragging = False
        self.viewport().update()

    def inputMethodEvent(self, e):
        if self._col_mode and self._block is not None:
            commit = e.commitString()
            if commit and commit.isprintable():
                self._col_edit("insert", commit)
            e.accept()
            return
        super().inputMethodEvent(e)

    def contextMenuEvent(self, e):
        if not (self._col_mode and self._block is not None):
            super().contextMenuEvent(e)
            return
        menu = QMenu(self)
        has = self._block_rect()[2] < self._block_rect()[3]
        ro = self.isReadOnly()
        a_cut = menu.addAction("Cut")
        a_cut.setEnabled(has and not ro)
        a_copy = menu.addAction("Copy")
        a_copy.setEnabled(has)
        a_paste = menu.addAction("Paste")
        md = QApplication.clipboard().mimeData()
        a_paste.setEnabled(not ro and md is not None and md.hasText())
        menu.addSeparator()
        a_exit = menu.addAction("Leave column mode")
        chosen = menu.exec(e.globalPos())
        if chosen is a_cut:
            self._column_copy(True)
        elif chosen is a_copy:
            self._column_copy(False)
        elif chosen is a_paste:
            if md is not None:
                self.insertFromMimeData(md)
        elif chosen is a_exit:
            self.set_column_mode(False)

    # painting --------------------------------------------------------------
    def paintEvent(self, e):
        super().paintEvent(e)
        if (self._col_mode and self._block is not None and self._caret_on
                and self.hasFocus()):
            self._paint_carets()

    def _paint_carets(self):
        l0, l1, a, b = self._block_rect()
        hc = self._block[3]
        vp = self.viewport()
        p = QPainter(vp)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(THEME["text"]))
        blk = self.cursorForPosition(QPoint(0, 0)).block()
        view_h = vp.height()
        while blk.isValid():
            n = blk.blockNumber()
            if n > l1:
                break
            if n >= l0:
                ln = len(blk.text())
                c = QTextCursor(blk)
                c.setPosition(blk.position() + min(hc, ln))
                r = self.cursorRect(c)
                if r.top() > view_h:
                    break
                if ln >= a:
                    p.drawRect(r.x(), r.y(), 2, max(1, r.height()))
            blk = blk.next()
        p.end()

    # toggle icon -----------------------------------------------------------
    def _place_toggle(self):
        if not hasattr(self, "_toggle"):
            return
        vp = self.viewport()
        t = self._toggle
        t.move(max(0, vp.width() - t.width() - 8), 6)
        t.raise_()

    def eventFilter(self, obj, ev):
        if obj is self.viewport() and ev.type() == QEvent.Type.Resize:
            self._place_toggle()
        return super().eventFilter(obj, ev)

    # ── gutter / highlight plumbing ──────────────────────────────────────────
    def gutter_width(self):
        digits = max(3, len(str(max(1, self.document().blockCount()))))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        self._place_gutter()

    def _place_gutter(self):
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_gutter()
        self._place_toggle()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.FontChange and hasattr(self, "_fmt_timer"):
            self._sync_metrics()

    def _on_text_changed(self):
        self._gutter.update()
        self._fmt_timer.start()
        if not self._col_busy:
            self._col_join = False
            if self._col_mode and self._block is not None:
                self._clamp_block()
                self._refresh_selections()
        self.text_changed.emit()

    def _on_cursor_moved(self):
        if self._col_mode and not self._col_busy:
            # the native cursor moved by itself (Home, PageUp, Ctrl+Left, undo ...)
            cur = self.textCursor()
            if cur.hasSelection():
                self.set_column_mode(False, collapse=False)   # keep the real selection
            else:
                col = cur.positionInBlock()
                self._block = (cur.blockNumber(), col, cur.blockNumber(), col)
                self._goal_col = col
                self._col_join = False
        self._refresh_selections()
        self._gutter.update()

    def _refresh_selections(self):
        sels = []
        if not self.textCursor().hasSelection():
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(THEME["current_line"]))
            s.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            s.cursor = self.textCursor()
            s.cursor.clearSelection()
            sels.append(s)
        sels.extend(self._compare_selections)
        if self._col_mode and self._block is not None:
            sels.extend(self._column_selections())
        self.setExtraSelections(sels)

    def paint_gutter(self, event):
        p = QPainter(self._gutter)
        w = self._gutter.width()
        p.fillRect(event.rect(), QColor(THEME["gutter_bg"]))
        p.setPen(QColor(THEME["border"]))
        p.drawLine(w - 1, event.rect().top(), w - 1, event.rect().bottom())
        p.setFont(self.font())
        fm = self.fontMetrics()
        layout = self.document().documentLayout()
        vscroll = self.verticalScrollBar().value()
        block = self.cursorForPosition(QPoint(0, 0)).block()      # first visible line
        cur_n = self.textCursor().blockNumber()
        while block.isValid():
            top = round(layout.blockBoundingRect(block).top()) - vscroll
            if top > event.rect().bottom():
                break
            if top + self._line_h >= event.rect().top():
                n = block.blockNumber()
                label = str(n + 1)
                p.setPen(QColor(THEME["gutter_fg_current"] if n == cur_n
                                else THEME["gutter_fg"]))
                p.drawText(w - 9 - fm.horizontalAdvance(label), top + self._ascent, label)
            block = block.next()
        p.end()


# ── Ignore-rules dialog ──────────────────────────────────────────────────────

class IgnoreRulesDialog(QDialog):
    """Edit the (global, remembered) rules for folders that are left out of scans."""
    PRESETS = ("__pycache__", "node_modules", "venv", "build", "dist", "target", "bin", "obj")

    def __init__(self, rules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ignore folders — rules")
        self.resize(580, 600)
        self._custom = list(clean_rules(rules.hidden, rules.custom).custom)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 12)
        v.setSpacing(8)
        info = QLabel("Folders that match <b>any</b> rule are left out of the scan completely — "
                      "together with everything inside them. Files are never ignored. "
                      "Upper / lower case does not matter. Your choice is remembered.")
        info.setWordWrap(True)
        v.addWidget(info)

        self.cb_hidden = QCheckBox("Folders that start with a dot   (.git  .idea  .vscode  .venv …)")
        self.cb_hidden.setChecked(bool(rules.hidden))
        self.cb_hidden.stateChanged.connect(self._update_test)
        v.addWidget(self.cb_hidden)

        v.addWidget(QLabel("<b>Your own rules</b>  (a folder is ignored if it matches any of them):"))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        v.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.kind = QComboBox()
        for key, label in RULE_KINDS:
            self.kind.addItem(label, key)
        row.addWidget(self.kind)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("text, e.g.   tmp_     _old     node_modules")
        self.edit.returnPressed.connect(self._add_from_fields)
        row.addWidget(self.edit, stretch=1)
        self.btn_add = QPushButton("Add")
        self.btn_add.clicked.connect(self._add_from_fields)
        row.addWidget(self.btn_add)
        v.addLayout(row)

        self.msg = QLabel("")
        self.msg.setStyleSheet("color:#e08030;font-size:11px;")
        v.addWidget(self.msg)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("Quick add:"))
        self.presets = QComboBox()
        self.presets.addItem("common folders …")
        for p in self.PRESETS:
            self.presets.addItem(p)
        self.presets.activated.connect(self._on_preset)
        row2.addWidget(self.presets)
        row2.addStretch()
        self.btn_remove = QPushButton("Remove selected")
        self.btn_remove.clicked.connect(self._remove_selected)
        row2.addWidget(self.btn_remove)
        self.btn_clear = QPushButton("Remove all")
        self.btn_clear.clicked.connect(self._remove_all)
        row2.addWidget(self.btn_clear)
        v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(6)
        row3.addWidget(QLabel("Try a folder name:"))
        self.test_edit = QLineEdit()
        self.test_edit.setPlaceholderText("e.g.  .git   or   build_old")
        self.test_edit.textChanged.connect(self._update_test)
        row3.addWidget(self.test_edit, stretch=1)
        self.test_result = QLabel("")
        self.test_result.setMinimumWidth(130)
        row3.addWidget(self.test_result)
        v.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        row4.addWidget(self.btn_cancel)
        self.btn_save = QPushButton("Save")
        self.btn_save.setStyleSheet("font-weight:bold;")
        self.btn_save.clicked.connect(self.accept)
        row4.addWidget(self.btn_save)
        v.addLayout(row4)

        # Enter inside the text field must ADD a rule, never close the dialog
        for b in (self.btn_add, self.btn_remove, self.btn_clear, self.btn_cancel, self.btn_save):
            b.setAutoDefault(False)
            b.setDefault(False)
        self._refresh_list()

    # ── logic ────────────────────────────────────────────────────────────────
    def rules(self):
        return clean_rules(self.cb_hidden.isChecked(), self._custom)

    def _refresh_list(self):
        self.list.clear()
        for kind, text in self._custom:
            self.list.addItem(f"{_RULE_LABEL[kind]}   “{text}”")
        self._update_test()

    def _add_rule(self, kind, text):
        text = text.strip()
        err = validate_rule_text(text)
        if err:
            self.msg.setText(err)
            return False
        if any(k == kind and t.casefold() == text.casefold() for k, t in self._custom):
            self.msg.setText("This rule is already in the list.")
            return False
        if len(self._custom) >= MAX_RULES:
            self.msg.setText(f"At most {MAX_RULES} rules are possible.")
            return False
        self._custom.append((kind, text))
        self.msg.setText("")
        self._refresh_list()
        return True

    def _add_from_fields(self):
        if not self.edit.text().strip():
            return
        if self._add_rule(self.kind.currentData(), self.edit.text()):
            self.edit.clear()
        self.edit.setFocus()

    def _on_preset(self, index):
        if index > 0:
            self._add_rule("equals", self.presets.itemText(index))
        self.presets.setCurrentIndex(0)

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.list.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self._custom):
                del self._custom[r]
        self._refresh_list()

    def _remove_all(self):
        self._custom.clear()
        self.msg.setText("")
        self._refresh_list()

    def _update_test(self, *_):
        name = self.test_edit.text().strip()
        if not name:
            self.test_result.setText("")
        elif self.rules().matches(name):
            self.test_result.setText("→ would be IGNORED")
            self.test_result.setStyleSheet("color:#e08030;font-weight:bold;")
        else:
            self.test_result.setText("→ would be kept")
            self.test_result.setStyleSheet("color:#66BB6A;font-weight:bold;")


# ── Main application ─────────────────────────────────────────────────────────

class FolderStructureApp(QMainWindow):

    LS = ("font-family:'Segoe UI','SF Pro Text','Helvetica Neue',Arial,sans-serif;"
          "font-size:11px;color:#e0e0e0;")
    C_BOTH = QColor(COLOR_BOTH)
    C_DIFF = QColor(COLOR_DIFF)
    C_ONLY = QColor(COLOR_ONLY)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Structify — Folder Structure Tool")
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = int(screen.width() * 0.60), int(screen.height() * 0.85)
        self.resize(w, h)
        self.setMinimumSize(QSize(880, 620))
        self.move(screen.x() + (screen.width() - w) // 2,
                  screen.y() + (screen.height() - h) // 2)
        if 'Fusion' in QStyleFactory.keys() and QApplication.style().objectName().lower() != 'fusion':
            QApplication.setStyle('Fusion')

        self._tab1_compare_active = False
        self._t2_compare_active = False
        self._sync_scroll_active = False
        self._syncing_scroll = False
        self._tab2_initialized = False
        self._tab3_initialized = False
        self._editor_font_size = EDITOR_FONT_SIZE
        self._editor_font_family = None
        # scan caches: key -> (nonblank_lines, absolute_paths, scanned_root)
        self._scan_cache = {}
        self._ignore_rules = IgnoreRules()       # global, remembered
        self._ignored_info = {}                  # panel prefix -> ignored folder paths

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

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
        self.tabs.addTab(self.tab1, "①  Compare && Explore")
        self.tabs.addTab(self.tab2, "②  Rename Files && Folders")
        self.tabs.addTab(self.tab3, "③  Generate Tree Diagram")

        for ed in self._all_editors():
            ed.zoom_requested.connect(self._on_zoom)

        self._load_last_paths()
        self._update_ignore_labels()
        self.left_preview.text_changed.connect(self._on_left_changed)

    def _all_editors(self):
        return [self.left_preview, self.right_preview, self.t2_left_preview,
                self.tab2_right_editor, self.t3_left_preview, self.tree_output]

    # ── shared widget helpers ────────────────────────────────────────────────
    def _hr(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#555;margin:1px 0;")
        return f

    def _legend_item(self, color_hex, text, prefix=""):
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(2, 1, 6, 1)
        hl.setSpacing(5)
        sw = QLabel(prefix)
        sw.setFixedSize(20, 18)
        sw.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sw.setStyleSheet(f"background-color:{color_hex};border:1px solid #888;"
                         f"border-radius:3px;font-weight:bold;color:#fff;font-size:10px;")
        lb = QLabel(text)
        lb.setStyleSheet(self.LS + "font-weight:600;font-size:10px;")
        hl.addWidget(sw)
        hl.addWidget(lb)
        return w

    @staticmethod
    def _btn_style(color, min_w=160):
        c = QColor(color)
        return (f"QPushButton{{background-color:{color};color:white;font-weight:bold;"
                f"min-width:{min_w}px;border-radius:5px;padding:3px 10px;}}"
                f"QPushButton:hover{{background-color:{c.lighter(115).name()};}}"
                f"QPushButton:pressed{{background-color:{c.darker(115).name()};}}")

    def _blue_btn(self):   return self._btn_style("#0066cc")
    def _green_btn(self):  return self._btn_style("#4CAF50")
    def _orange_btn(self): return self._btn_style("#e65c00", 180)

    def _make_btn(self, text, style, height=26, tooltip=""):
        b = QPushButton(text)
        b.setStyleSheet(style)
        b.setFixedHeight(height)
        if tooltip:
            b.setToolTip(tooltip)
        return b

    def _circle_btn(self, symbol, color, tooltip, size=48):
        b = QPushButton(symbol)
        b.setFixedSize(size, size)
        b.setToolTip(tooltip)
        c = QColor(color)
        b.setStyleSheet(
            f"QPushButton{{background-color:{color};color:white;font-size:20px;"
            f"font-weight:bold;border-radius:{size // 2}px;}}"
            f"QPushButton:hover{{background-color:{c.lighter(115).name()};}}"
            f"QPushButton:pressed{{background-color:{c.darker(115).name()};}}")
        return b

    # ── scan panel pieces ────────────────────────────────────────────────────
    def _make_controls(self, prefix, scan_cb, export_cb, import_cb, browse_cb):
        """Path row + scan options + Scan/Export/Import buttons (identical in all tabs)."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        pr = QHBoxLayout()
        pr.setSpacing(4)
        pl = QLabel("Source:")
        pl.setFixedWidth(52)
        pl.setStyleSheet(self.LS)
        pr.addWidget(pl)
        edit = QLineEdit()
        edit.setPlaceholderText("Select a folder …")
        edit.setFixedHeight(24)
        pr.addWidget(edit)
        bb = QPushButton("Browse")
        bb.setFixedWidth(68)
        bb.setFixedHeight(24)
        bb.clicked.connect(browse_cb)
        pr.addWidget(bb)
        v.addLayout(pr)
        setattr(self, f"{prefix}_path_edit", edit)

        orow = QHBoxLayout()
        orow.setSpacing(14)
        r_root = QRadioButton("Only root items")
        r_root.setChecked(True)
        r_rec = QRadioButton("All subfolders (recursive)")
        for r in (r_root, r_rec):
            r.setStyleSheet("font-size:11px;")
        grp = QButtonGroup(self)
        grp.addButton(r_root)
        grp.addButton(r_rec)
        orow.addWidget(r_root)
        orow.addWidget(r_rec)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#666;")
        orow.addWidget(sep)
        cb_fold = QCheckBox("Folders")
        cb_fold.setChecked(True)
        cb_file = QCheckBox("Files")
        cb_file.setChecked(False)
        for c in (cb_fold, cb_file):
            c.setStyleSheet("font-size:11px;")

        def make_guard(a, b):
            def g(_):
                if not a.isChecked() and not b.isChecked():
                    a.setChecked(True)
            return g
        cb_fold.stateChanged.connect(make_guard(cb_fold, cb_file))
        cb_file.stateChanged.connect(make_guard(cb_file, cb_fold))
        orow.addWidget(cb_fold)
        orow.addWidget(cb_file)
        orow.addStretch()
        v.addLayout(orow)
        setattr(self, f"{prefix}_radio_only_root", r_root)
        setattr(self, f"{prefix}_radio_recursive", r_rec)
        setattr(self, f"{prefix}_cb_folders", cb_fold)
        setattr(self, f"{prefix}_cb_files", cb_file)

        irow = QHBoxLayout()
        irow.setSpacing(8)
        cb_ign = QCheckBox("Ignore folders")
        cb_ign.setStyleSheet("font-size:11px;")
        cb_ign.setToolTip("Leave folders out of the scan completely (e.g. .git, .idea).\n"
                          "Which folders is defined under “Rules …”.\n"
                          "Switch off to load everything.")
        btn_rules = QPushButton("Rules …")
        btn_rules.setFixedSize(70, 22)
        btn_rules.setToolTip("Choose which folders are ignored (remembered).")
        lbl_rules = QLabel("")
        lbl_rules.setStyleSheet(self.LS + "font-size:10px;color:#9aa0a6;")
        lbl_rules.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        irow.addWidget(cb_ign)
        irow.addWidget(btn_rules)
        irow.addWidget(lbl_rules, stretch=1)
        v.addLayout(irow)
        setattr(self, f"{prefix}_cb_ignore", cb_ign)
        setattr(self, f"{prefix}_btn_rules", btn_rules)
        setattr(self, f"{prefix}_lbl_rules", lbl_rules)
        cb_ign.stateChanged.connect(lambda _=0, p=prefix: self._on_ignore_toggled(p))
        btn_rules.clicked.connect(lambda _=False, p=prefix: self._open_ignore_rules(p))

        br = QHBoxLayout()
        br.setSpacing(6)
        bs, be, bi = QPushButton("Scan"), QPushButton("Export TXT"), QPushButton("Import TXT")
        bs.setToolTip("Read the folder at Source and fill the preview.")
        be.setToolTip("Save the current preview as a .txt file inside the source folder.")
        bi.setToolTip("Load a .txt file into the preview.")
        bs.clicked.connect(scan_cb)
        be.clicked.connect(export_cb)
        bi.clicked.connect(import_cb)
        for b in (bs, be, bi):
            b.setFixedHeight(24)
            br.addWidget(b)
        v.addLayout(br)
        return w

    def _build_preview_panel(self, parent_layout, title, prefix,
                             scan_cb, export_cb, import_cb, browse_cb, stretch=1):
        col = QVBoxLayout()
        col.setSpacing(4)
        parent_layout.addLayout(col, stretch=stretch)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight:bold;font-size:12px;")
        col.addWidget(lbl)
        col.addWidget(self._make_controls(prefix, scan_cb, export_cb, import_cb, browse_cb))
        pl = QLabel("Structure Preview (editable)")
        pl.setStyleSheet("font-weight:bold;font-size:11px;")
        col.addWidget(pl)
        preview = LineNumberedEditor()
        col.addWidget(preview, stretch=1)
        setattr(self, f"{prefix}_preview", preview)

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 1 — Compare & Explore
    # ═════════════════════════════════════════════════════════════════════════
    def _build_tab1(self):
        self.tab1 = QWidget()
        lay = QVBoxLayout(self.tab1)
        lay.setContentsMargins(10, 8, 10, 6)
        lay.setSpacing(5)

        hint = QLabel(
            "Scan two folder structures and compare them directly in the previews.  "
            "Green = the same name exists in both (at the same depth).  "
            "Yellow = only on this side.  Order does not matter.  "
            "Editor: Shift+Alt+↑/↓ move line · Ctrl+D duplicate · Tab/Shift+Tab indent · "
            "Ctrl+Wheel zoom · Column mode: Alt+Shift+Insert / Ctrl+Alt+Insert or the corner icon.")
        hint.setStyleSheet(self.LS)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        panels = QHBoxLayout()
        panels.setSpacing(12)
        lay.addLayout(panels, stretch=1)
        self._build_preview_panel(panels, "Source Folder 1", "left",
                                  self.scan_left, self.export_left,
                                  self.import_txt_left, self.browse_left_source)
        self._build_preview_panel(panels, "Source Folder 2", "right",
                                  self.scan_right, self.export_right,
                                  self.import_txt_right, self.browse_right_source)

        bot = QHBoxLayout()
        bot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bot.setSpacing(20)
        lay.addLayout(bot)

        self.cb_sync_scroll = QCheckBox("Sync scroll — both previews scroll together")
        self.cb_sync_scroll.setStyleSheet(self.LS + "font-weight:500;")
        self.cb_sync_scroll.stateChanged.connect(self._on_sync_scroll_toggled)
        self.cb_sync_scroll.setChecked(True)          # ON by default
        bot.addWidget(self.cb_sync_scroll)

        self.btn_t1_compare = self._make_btn(
            "Compare Structures  (highlight differences)", self._green_btn(), 28,
            "Colour each line directly in the previews:\n"
            "Green = same name exists in both | Yellow = only on one side.\n"
            "Click again to clear the colours.")
        self.btn_t1_compare.clicked.connect(self._toggle_tab1_compare)
        bot.addWidget(self.btn_t1_compare)

        lay.addWidget(self._hr())
        leg = QHBoxLayout()
        leg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        leg.setSpacing(16)
        lay.addLayout(leg)
        lg = QLabel("Legend:")
        lg.setStyleSheet(self.LS + "font-weight:600;")
        leg.addWidget(lg)
        leg.addWidget(self._legend_item(COLOR_BOTH, "Same name found in both structures (at this depth)"))
        leg.addWidget(self._legend_item(COLOR_ONLY, "Only on this side — not found in the other structure"))
        leg.addStretch()

    def _toggle_tab1_compare(self):
        self._tab1_compare_active = not self._tab1_compare_active
        if self._tab1_compare_active:
            self.btn_t1_compare.setText("Clear Comparison  (click to remove colours)")
            self.btn_t1_compare.setStyleSheet(self._btn_style("#888888"))
            if not hasattr(self, "_t1_timer"):
                self._t1_timer = QTimer(self)
                self._t1_timer.setSingleShot(True)
                self._t1_timer.setInterval(200)
                self._t1_timer.timeout.connect(self._apply_tab1_colors)
                self.left_preview.text_changed.connect(self._schedule_t1)
                self.right_preview.text_changed.connect(self._schedule_t1)
            self._apply_tab1_colors()
        else:
            self.btn_t1_compare.setText("Compare Structures  (highlight differences)")
            self.btn_t1_compare.setStyleSheet(self._green_btn())
            if hasattr(self, "_t1_timer"):
                self._t1_timer.stop()
            self.left_preview.clear_line_colors()
            self.right_preview.clear_line_colors()

    def _schedule_t1(self):
        if self._tab1_compare_active:
            self._t1_timer.start()

    def _apply_tab1_colors(self):
        """Order-insensitive, level-by-level inline colouring."""
        if not self._tab1_compare_active:
            return

        def levels(ed):
            out = {}
            for line in ed.toPlainText().split("\n"):
                if line.strip():
                    out.setdefault((len(line) - len(line.lstrip())) // 2, set()).add(line.strip())
            return out

        def colors(ed, other):
            res = []
            for line in ed.toPlainText().split("\n"):
                if not line.strip():
                    res.append(None)
                    continue
                d = (len(line) - len(line.lstrip())) // 2
                res.append(self.C_BOTH if line.strip() in other.get(d, set()) else self.C_ONLY)
            return res

        lv_left, lv_right = levels(self.left_preview), levels(self.right_preview)
        self.left_preview.set_line_colors(colors(self.left_preview, lv_right))
        self.right_preview.set_line_colors(colors(self.right_preview, lv_left))

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 2 — Rename Files & Folders
    # ═════════════════════════════════════════════════════════════════════════
    def _build_tab2(self):
        self.tab2 = QWidget()
        outer = QVBoxLayout(self.tab2)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(10, 8, 10, 6)
        lay.setSpacing(5)

        hint = QLabel(
            "LEFT = current names on disk (scan a folder, or auto-loaded from Tab 1).  "
            "RIGHT = the desired new names, one per line, in the same order.  "
            "Use  →  to copy left to right, then edit.  "
            "Shift+Alt+↑/↓ moves lines · Ctrl+D duplicates a line · "
            "Column mode (multi-cursor): Alt+Shift+Insert / Ctrl+Alt+Insert or the corner icon.")
        hint.setStyleSheet(self.LS)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # A grid keeps both editors on exactly the same rows -> line N meets line N.
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        lay.addLayout(grid, stretch=1)

        t = QLabel("Current Names  (left = names that exist on disk right now)")
        t.setStyleSheet("font-weight:bold;font-size:12px;")
        grid.addWidget(t, 0, 0)
        grid.addWidget(self._make_controls("t2_left", self._scan_t2_left, self._export_t2_left,
                                           self._import_t2_left, self._browse_t2_left), 1, 0)
        pl = QLabel("Structure Preview (editable)")
        pl.setStyleSheet("font-weight:bold;font-size:11px;")
        grid.addWidget(pl, 2, 0)
        self.t2_left_preview = LineNumberedEditor()
        grid.addWidget(self.t2_left_preview, 3, 0)

        rt = QLabel("New Names  (right = desired names — edit here)")
        rt.setStyleSheet("font-weight:bold;font-size:12px;")
        grid.addWidget(rt, 0, 2)
        rh = QLabel("Type or paste the NEW names here, one per line.\n"
                    "Line N on this side renames line N on the left.")
        rh.setStyleSheet(self.LS)
        rh.setWordWrap(True)
        rh.setAlignment(Qt.AlignmentFlag.AlignTop)
        rh.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        grid.addWidget(rh, 1, 2)
        rpl = QLabel("New Names Preview (editable — one name per line)")
        rpl.setStyleSheet("font-weight:bold;font-size:11px;")
        grid.addWidget(rpl, 2, 2)
        self.tab2_right_editor = LineNumberedEditor()
        grid.addWidget(self.tab2_right_editor, 3, 2)

        cc = QVBoxLayout()
        cc.setSpacing(10)
        cc.setContentsMargins(4, 0, 4, 0)
        cc.addStretch()
        btn_copy = self._circle_btn(
            "→", "#4a90c4", "Copy Left preview → Right editor.\n"
                            "Then edit the right side to set the desired new names.")
        btn_copy.clicked.connect(self._copy_left_to_right_t2)
        cc.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignHCenter)
        lc = QLabel("Copy")
        lc.setStyleSheet(self.LS + "font-size:10px;font-weight:600;")
        lc.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cc.addWidget(lc)
        cc.addSpacing(10)

        self.btn_t2_compare = self._circle_btn(
            "≡?", "#707070", "Compare left and right names line by line.\n"
                             "Green = same, Red = different, Yellow = one side only.\n"
                             "Click again to clear.")
        self.btn_t2_compare.clicked.connect(self._toggle_tab2_compare)
        cc.addWidget(self.btn_t2_compare, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.lbl_t2_cmp = QLabel("Compare")
        self.lbl_t2_cmp.setStyleSheet(self.LS + "font-size:10px;font-weight:600;")
        self.lbl_t2_cmp.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cc.addWidget(self.lbl_t2_cmp)
        cc.addSpacing(10)

        btn_apply = self._circle_btn(
            "✓", "#e65c00", "Apply: rename on disk.\n"
                            "The item on Left line N is renamed to Right line N.\n"
                            "A confirmation is shown first. Safe two-phase rename "
                            "with automatic rollback.")
        btn_apply.clicked.connect(self.batch_rename)
        cc.addWidget(btn_apply, alignment=Qt.AlignmentFlag.AlignHCenter)
        la = QLabel("Apply")
        la.setStyleSheet(self.LS + "font-size:10px;font-weight:600;color:#ff8040;")
        la.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cc.addWidget(la)
        cc.addStretch()
        grid.addLayout(cc, 0, 1, 4, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(3, 1)

        lay.addWidget(self._hr())
        wf = QLabel(
            "<b>Workflow:</b>  <b>① Scan</b> a folder (left = current names).  "
            "<b>② →</b> copies them to the right.  "
            "<b>③ Edit</b> the right side.  "
            "<b>④ ✓ Apply</b> renames on disk: <i>Left line N</i> becomes <i>Right line N</i>.  "
            "Names that already exist are skipped (only those); everything else is renamed.  "
            "Confirmation required — it cannot be undone.")
        wf.setStyleSheet(self.LS + "font-size:10px;")
        wf.setWordWrap(True)
        lay.addWidget(wf)

        leg = QHBoxLayout()
        leg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        leg.setSpacing(12)
        lay.addLayout(leg)
        lg = QLabel("≡? colours:")
        lg.setStyleSheet(self.LS + "font-weight:600;font-size:10px;")
        leg.addWidget(lg)
        leg.addWidget(self._legend_item(COLOR_BOTH, "Same — no rename needed"))
        leg.addWidget(self._legend_item(COLOR_DIFF, "Different — will be renamed"))
        leg.addWidget(self._legend_item(COLOR_ONLY, "Line exists on one side only"))
        leg.addStretch()

        outer.addWidget(content, stretch=1)

    def _toggle_tab2_compare(self):
        left_ok = bool(self.t2_left_preview.toPlainText().strip())
        right_ok = bool(self.tab2_right_editor.toPlainText().strip())
        if not self._t2_compare_active and not (left_ok and right_ok):
            QMessageBox.information(
                self, "Compare Names",
                "Please load a structure into the Left preview\n"
                "and type new names into the Right preview first.")
            return
        self._t2_compare_active = not self._t2_compare_active
        if self._t2_compare_active:
            self.btn_t2_compare.setText("≡✔")
            self.btn_t2_compare.setStyleSheet(
                self._circle_btn("", "#4CAF50", "").styleSheet())
            self.lbl_t2_cmp.setText("ON")
            self.lbl_t2_cmp.setStyleSheet(self.LS + "font-size:10px;font-weight:600;color:#66BB6A;")
            if not hasattr(self, "_t2_timer"):
                self._t2_timer = QTimer(self)
                self._t2_timer.setSingleShot(True)
                self._t2_timer.setInterval(150)
                self._t2_timer.timeout.connect(self._apply_tab2_colors)
                self.t2_left_preview.text_changed.connect(self._schedule_t2)
                self.tab2_right_editor.text_changed.connect(self._schedule_t2)
            self._apply_tab2_colors()
        else:
            self.btn_t2_compare.setText("≡?")
            self.btn_t2_compare.setStyleSheet(
                self._circle_btn("", "#707070", "").styleSheet())
            self.lbl_t2_cmp.setText("Compare")
            self.lbl_t2_cmp.setStyleSheet(self.LS + "font-size:10px;font-weight:600;")
            if hasattr(self, "_t2_timer"):
                self._t2_timer.stop()
            self.t2_left_preview.clear_line_colors()
            self.tab2_right_editor.clear_line_colors()

    def _schedule_t2(self):
        if self._t2_compare_active:
            self._t2_timer.start()

    def _apply_tab2_colors(self):
        """Strict line-index comparison: line N left vs line N right."""
        if not self._t2_compare_active:
            return
        ll = self.t2_left_preview.toPlainText().split("\n")
        rl = self.tab2_right_editor.toPlainText().split("\n")

        def colors(lines, partner):
            out = []
            for i, ln in enumerate(lines):
                if i >= len(partner):
                    out.append(self.C_ONLY)
                elif ln.strip() == partner[i].strip():
                    out.append(self.C_BOTH)
                else:
                    out.append(self.C_DIFF)
            return out

        self.t2_left_preview.set_line_colors(colors(ll, rl))
        self.tab2_right_editor.set_line_colors(colors(rl, ll))

    # ── Tab 2 actions ────────────────────────────────────────────────────────
    def _copy_left_to_right_t2(self):
        text = self.t2_left_preview.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Copy Left → Right",
                                    "The Left preview is empty.\nPlease scan a folder first.")
            return
        self.tab2_right_editor.setPlainText(text)

    def _browse_t2_left(self):
        f = QFileDialog.getExistingDirectory(self, "Select Folder", self.t2_left_path_edit.text())
        if f:
            self.t2_left_path_edit.setText(f)

    def _scan_t2_left(self):
        self._scan_into("t2_left")

    def _export_t2_left(self):
        self._export_from("t2_left")

    def _import_t2_left(self):
        self._import_into("t2_left")

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 3 — Generate Tree Diagram
    # ═════════════════════════════════════════════════════════════════════════
    def _build_tab3(self):
        self.tab3 = QWidget()
        outer = QVBoxLayout(self.tab3)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(10, 8, 10, 6)
        lay.setSpacing(5)

        hint = QLabel(
            "Scan a folder (auto-loaded from Tab 1 on first use, or scan independently).  "
            "Click Generate Tree to build a ├── └── │ diagram with  # ← description  "
            "placeholders — you can write the descriptions straight into the result.  "
            "Export saves  directory_structure_explained.md  into the source folder.  "
            "Column mode (multi-cursor): Alt+Shift+Insert / Ctrl+Alt+Insert or the corner icon.")
        hint.setStyleSheet(self.LS)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        panels = QHBoxLayout()
        panels.setSpacing(12)
        lay.addLayout(panels, stretch=1)
        self._build_preview_panel(panels, "Source Structure  (scan a folder — edit before generating)",
                                  "t3_left", self._scan_t3, self._export_t3_left,
                                  self._import_t3_left, self._browse_t3)

        right = QVBoxLayout()
        right.setSpacing(4)
        panels.addLayout(right, stretch=1)
        rl = QLabel("Generated Tree Diagram  (editable — # ← add description here)")
        rl.setStyleSheet("font-weight:bold;font-size:12px;")
        right.addWidget(rl)
        right.addSpacing(0)
        self.tree_output = LineNumberedEditor(strip_blank_lines=False)
        right.addWidget(self.tree_output, stretch=1)

        lay.addWidget(self._hr())
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.setSpacing(16)
        lay.addLayout(row)
        b_gen = self._make_btn("▶  Generate Tree", self._green_btn(), 28,
                               "Build the │ ├── └── tree from the structure preview.")
        b_gen.clicked.connect(self._generate_tree)
        row.addWidget(b_gen)
        b_exp = self._make_btn("💾  Export as directory_structure_explained.md",
                               self._blue_btn(), 28,
                               "Save the tree as 'directory_structure_explained.md' "
                               "inside the source folder.")
        b_exp.clicked.connect(self._export_tree)
        row.addWidget(b_exp)
        outer.addWidget(content, stretch=1)

    def _browse_t3(self):
        f = QFileDialog.getExistingDirectory(self, "Select Folder", self.t3_left_path_edit.text())
        if f:
            self.t3_left_path_edit.setText(f)

    def _scan_t3(self):
        self._scan_into("t3_left")

    def _export_t3_left(self):
        self._export_from("t3_left")

    def _import_t3_left(self):
        self._import_into("t3_left")

    def _generate_tree(self):
        text = self.t3_left_preview.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Generate Tree",
                                "The structure preview is empty.\nPlease scan a folder first.")
            return
        src = self.t3_left_path_edit.text().strip()
        root_name = os.path.basename(os.path.normpath(src)) if src else "project"
        self.tree_output.setPlainText(
            build_tree_diagram([l for l in text.split("\n") if l.strip()], root_name or "project"))

    def _export_tree(self):
        tree = self.tree_output.toPlainText().strip()
        if not tree:
            QMessageBox.warning(self, "Export Tree", "Tree is empty. Click Generate Tree first.")
            return
        src = self.t3_left_path_edit.text().strip()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self, "Export Tree", "No valid source folder set.")
            return
        out = os.path.join(src, "directory_structure_explained.md")
        if os.path.exists(out):
            msg = QMessageBox(self)
            msg.setWindowTitle("File Already Exists")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setText(f"File already exists:\n{out}")
            msg.setInformativeText("What would you like to do?")
            ow = msg.addButton("Overwrite", QMessageBox.ButtonRole.YesRole)
            msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() != ow:
                return
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(tree + "\n")
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Export failed:\n{e}")
            return
        self._show_export_ok(out, "Tree diagram exported.")

    # ── Tab 1 → Tab 2/3: first load only, afterwards every tab is independent ─
    def _on_left_changed(self):
        text = self.left_preview.toPlainText()
        if not text.strip():
            return
        for flag, pfx in (("_tab2_initialized", "t2_left"), ("_tab3_initialized", "t3_left")):
            if getattr(self, flag):
                continue
            getattr(self, f"{pfx}_preview").setPlainText(text)
            getattr(self, f"{pfx}_path_edit").setText(self.left_path_edit.text())
            (getattr(self, f"{pfx}_radio_recursive") if self.left_radio_recursive.isChecked()
             else getattr(self, f"{pfx}_radio_only_root")).setChecked(True)
            cf, ci = getattr(self, f"{pfx}_cb_folders"), getattr(self, f"{pfx}_cb_files")
            cf.blockSignals(True); ci.blockSignals(True)
            cf.setChecked(self.left_cb_folders.isChecked())
            ci.setChecked(self.left_cb_files.isChecked())
            cf.blockSignals(False); ci.blockSignals(False)
            cg = getattr(self, f"{pfx}_cb_ignore")
            cg.blockSignals(True)
            cg.setChecked(self.left_cb_ignore.isChecked())
            cg.blockSignals(False)
            self._ignored_info[pfx] = list(self._ignored_info.get("left", []))
            setattr(self, flag, True)
        self._update_ignore_labels()

    # ── Zoom (all editors share one font) ────────────────────────────────────
    def _on_zoom(self, delta):
        size = EDITOR_FONT_SIZE if delta == 0 else self._editor_font_size + delta
        self._apply_editor_font(size, self._editor_font_family)

    def _apply_editor_font(self, size, family=None):
        self._editor_font_size = max(EDITOR_FONT_MIN, min(EDITOR_FONT_MAX, int(size)))
        self._editor_font_family = family
        font = make_editor_font(self._editor_font_size, family)
        for ed in self._all_editors():
            ed.setFont(font)

    # ── Persistence ──────────────────────────────────────────────────────────
    def _load_last_paths(self):
        try:
            with open(LAST_PATHS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for part in (self._restore_paths, self._restore_options,
                     self._restore_ignore, self._restore_font):
            try:
                part(data)
            except Exception:
                pass            # one damaged entry must never stop the others

    def _restore_paths(self, data):
        for prefix in ("left", "right"):
            p = data.get(prefix)
            if isinstance(p, str) and os.path.isdir(p):
                getattr(self, f"{prefix}_path_edit").setText(p)

    def _restore_options(self, data):
        for prefix in ("left", "right"):
            if f"{prefix}_recursive" in data:
                (getattr(self, f"{prefix}_radio_recursive") if data[f"{prefix}_recursive"]
                 else getattr(self, f"{prefix}_radio_only_root")).setChecked(True)
            kf, ki = f"{prefix}_folders", f"{prefix}_files"
            if kf in data and ki in data:
                lf, li = bool(data[kf]), bool(data[ki])
                cbf = getattr(self, f"{prefix}_cb_folders")
                cbi = getattr(self, f"{prefix}_cb_files")
                cbf.blockSignals(True); cbi.blockSignals(True)
                cbf.setChecked(lf or not li)
                cbi.setChecked(li)
                cbf.blockSignals(False); cbi.blockSignals(False)

    def _restore_ignore(self, data):
        hidden = data.get("ignore_hidden", True)
        self._ignore_rules = clean_rules(hidden if isinstance(hidden, bool) else True,
                                         data.get("ignore_custom", []))
        for prefix in ("left", "right"):
            v = data.get(f"{prefix}_ignore")
            if isinstance(v, bool):
                cb = getattr(self, f"{prefix}_cb_ignore")
                cb.blockSignals(True)
                cb.setChecked(v)
                cb.blockSignals(False)

    def _restore_font(self, data):
        fam = data.get("font_family")
        if not isinstance(fam, str) or not (fam in QFontDatabase.families()
                                            and QFontDatabase.isFixedPitch(fam)):
            fam = None            # never restore a missing / proportional font
        self._apply_editor_font(int(data.get("font_size", EDITOR_FONT_SIZE)), fam)

    def _save_settings(self, report_errors=False):
        """Write all remembered settings (atomically). Returns True on success."""
        r = self._ignore_rules
        data = {
            "left": self.left_path_edit.text().strip(),
            "right": self.right_path_edit.text().strip(),
            "left_recursive": self.left_radio_recursive.isChecked(),
            "left_folders": self.left_cb_folders.isChecked(),
            "left_files": self.left_cb_files.isChecked(),
            "left_ignore": self.left_cb_ignore.isChecked(),
            "right_recursive": self.right_radio_recursive.isChecked(),
            "right_folders": self.right_cb_folders.isChecked(),
            "right_files": self.right_cb_files.isChecked(),
            "right_ignore": self.right_cb_ignore.isChecked(),
            "ignore_hidden": r.hidden,
            "ignore_custom": [list(x) for x in r.custom],
            "font_family": QFontInfo(self.left_preview.font()).family(),
            "font_size": self._editor_font_size,
        }
        tmp = LAST_PATHS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, LAST_PATHS_FILE)
            return True
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            if report_errors:
                QMessageBox.warning(self, "Settings",
                                    f"Your settings could not be saved to\n"
                                    f"{os.path.abspath(LAST_PATHS_FILE)}\n\n{e}")
            return False

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    # ── Ignore folders ───────────────────────────────────────────────────────
    def _active_ignore(self, prefix):
        cb = getattr(self, f"{prefix}_cb_ignore")
        return self._ignore_rules if cb.isChecked() and self._ignore_rules.is_active() else None

    def _update_ignore_labels(self):
        rules = self._ignore_rules
        base = rules.describe() if rules.is_active() else "no rules — click “Rules …”"
        for prefix in IGNORE_PANELS:
            on = getattr(self, f"{prefix}_cb_ignore").isChecked()
            names = self._ignored_info.get(prefix, []) if on else []
            lbl = getattr(self, f"{prefix}_lbl_rules")
            lbl.setText((f"{len(names)} ignored  ·  " if names else "") + base)
            tip = "Ignored folders: " + base
            if names:
                tip += f"\n\nLeft out of the last scan ({len(names)}):\n" + "\n".join(names[:40])
                if len(names) > 40:
                    tip += "\n…"
            lbl.setToolTip(tip)

    def _refresh_after_ignore_change(self, prefix, prev_rules):
        """Re-scan a panel right away — but ONLY if its text is still exactly the
        result of a scan with the previous settings. Text you edited or imported,
        or options you changed without scanning, are never overwritten."""
        path = getattr(self, f"{prefix}_path_edit").text().strip()
        ed = getattr(self, f"{prefix}_preview")
        shown = nonblank_lines(ed.toPlainText())
        if not shown or not os.path.isdir(path):
            return
        rec = getattr(self, f"{prefix}_radio_recursive").isChecked()
        incf = getattr(self, f"{prefix}_cb_folders").isChecked()
        inci = getattr(self, f"{prefix}_cb_files").isChecked()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            prev_lines, _ = get_folder_structure_with_paths(path, rec, incf, inci, prev_rules)
        except OSError:
            return
        finally:
            QApplication.restoreOverrideCursor()
        if shown != nonblank_lines(normalize_text("\n".join(prev_lines), True)):
            return
        if prefix == "t2_left" and nonblank_lines(self.tab2_right_editor.toPlainText()):
            QMessageBox.information(
                self, "Ignore folders",
                "The ignore setting changed.\n\nThe list on the left was NOT reloaded, because "
                "you already have new names on the right and the line numbers would no longer "
                "match.\nClick Scan to reload the left list, then check the right side again.")
            return
        self._scan_into(prefix)

    def _on_ignore_toggled(self, prefix):
        self._ignored_info.pop(prefix, None)
        rules = self._ignore_rules
        if rules.is_active():
            checked = getattr(self, f"{prefix}_cb_ignore").isChecked()
            self._refresh_after_ignore_change(prefix, None if checked else rules)
        self._update_ignore_labels()

    def _open_ignore_rules(self, prefix=None):
        dlg = IgnoreRulesDialog(self._ignore_rules, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new, old = dlg.rules(), self._ignore_rules
        if new == old:
            return
        self._ignore_rules = new
        self._save_settings(report_errors=True)
        for p in IGNORE_PANELS:
            if getattr(self, f"{p}_cb_ignore").isChecked():
                self._ignored_info.pop(p, None)
                self._refresh_after_ignore_change(p, old if old.is_active() else None)
        self._update_ignore_labels()

    # ── Sync scroll (Tab 1): the SAME first visible line in both previews ────
    def _on_sync_scroll_toggled(self, state):
        self._sync_scroll_active = bool(state)
        lb = self.left_preview.verticalScrollBar()
        rb = self.right_preview.verticalScrollBar()
        if self._sync_scroll_active:
            lb.valueChanged.connect(self._sync_l2r)
            rb.valueChanged.connect(self._sync_r2l)
            self._sync_l2r(lb.value())
        else:
            for bar, slot in ((lb, self._sync_l2r), (rb, self._sync_r2l)):
                try:
                    bar.valueChanged.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass

    def _sync_l2r(self, v):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            self.right_preview.verticalScrollBar().setValue(v)
        finally:
            self._syncing_scroll = False

    def _sync_r2l(self, v):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            self.left_preview.verticalScrollBar().setValue(v)
        finally:
            self._syncing_scroll = False

    # ── Generic scan / export / import (all three tabs) ──────────────────────
    def _scan_into(self, prefix):
        path = getattr(self, f"{prefix}_path_edit").text().strip()
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Error", "Source path is not a valid folder.")
            return
        rec = getattr(self, f"{prefix}_radio_recursive").isChecked()
        incf = getattr(self, f"{prefix}_cb_folders").isChecked()
        inci = getattr(self, f"{prefix}_cb_files").isChecked()
        ignored, err = [], None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lines, abs_paths = get_folder_structure_with_paths(
                path, rec, incf, inci, self._active_ignore(prefix), ignored)
        except OSError as e:
            err = e
        finally:
            QApplication.restoreOverrideCursor()
        if err is not None:
            QMessageBox.critical(self, "Error", f"Cannot read structure:\n{err}")
            return
        self._ignored_info[prefix] = ignored        # before setPlainText: Tab 1 -> 2/3 copies it
        ed = getattr(self, f"{prefix}_preview")
        ed.setPlainText("\n".join(lines))
        shown = nonblank_lines(ed.toPlainText())
        if len(shown) == len(abs_paths):
            self._scan_cache[prefix] = (shown, list(abs_paths), path)
        else:
            self._scan_cache.pop(prefix, None)
        self._update_ignore_labels()

    def _export_from(self, prefix):
        p = getattr(self, f"{prefix}_path_edit").text().strip()
        if not os.path.isdir(p):
            QMessageBox.warning(self, "Error", "Invalid source folder.")
            return
        self._safe_export(p, getattr(self, f"{prefix}_preview").toPlainText().rstrip())

    def _import_into(self, prefix):
        txt, _ = QFileDialog.getOpenFileName(self, "Select .txt", "",
                                             "Text files (*.txt);;All files (*.*)")
        if not txt:
            return
        try:
            with open(txt, encoding="utf-8-sig") as f:
                lines = [l.rstrip() for l in f
                         if l.strip() and not l.strip().startswith('#')]
        except (OSError, UnicodeDecodeError) as e:
            QMessageBox.critical(self, "Error", f"Cannot load TXT file:\n{e}")
            return
        getattr(self, f"{prefix}_preview").setPlainText("\n".join(lines))
        self._scan_cache.pop(prefix, None)
        self._ignored_info.pop(prefix, None)
        self._update_ignore_labels()

    def scan_left(self):   self._scan_into("left")
    def scan_right(self):  self._scan_into("right")
    def export_left(self): self._export_from("left")
    def export_right(self): self._export_from("right")
    def import_txt_left(self):  self._import_into("left")
    def import_txt_right(self): self._import_into("right")

    def browse_left_source(self):
        f = QFileDialog.getExistingDirectory(self, "Select Folder", self.left_path_edit.text())
        if f:
            self.left_path_edit.setText(f)

    def browse_right_source(self):
        f = QFileDialog.getExistingDirectory(self, "Select Folder", self.right_path_edit.text())
        if f:
            self.right_path_edit.setText(f)

    # ── Export ───────────────────────────────────────────────────────────────
    def _safe_export(self, source_path, content):
        if not content.strip():
            QMessageBox.warning(self, "Nothing to export", "The preview is empty.")
            return
        today = date.today().strftime("%Y.%m.%d")
        safe = "".join(c if c.isalnum() or c in " -_" else "_"
                       for c in os.path.basename(os.path.normpath(source_path))).strip("_")
        txt_path = os.path.join(source_path, f"{today}_folder-structure_{safe}.txt")

        def write(p):
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content + "\n")
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Export failed:\n{e}")
                return
            self._show_export_ok(p, "Preview exported")

        if not os.path.exists(txt_path):
            write(txt_path)
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("File Already Exists")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(f"File already exists:\n{txt_path}")
        msg.setInformativeText("What would you like to do?")
        ow = msg.addButton("Overwrite", QMessageBox.ButtonRole.YesRole)
        nc = msg.addButton("Create numbered copy", QMessageBox.ButtonRole.NoRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == ow:
            write(txt_path)
        elif msg.clickedButton() == nc:
            i = 1
            while True:
                np_ = os.path.join(source_path, f"{today}_folder-structure_{safe}_{i:02d}.txt")
                if not os.path.exists(np_):
                    write(np_)
                    break
                i += 1

    def _show_export_ok(self, path, title):
        msg = QMessageBox(self)
        msg.setWindowTitle("Export Successful")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(title)
        msg.setInformativeText(f"Location:\n{path}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        ob = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        msg.exec()
        if msg.clickedButton() == ob:
            self._open_folder(os.path.dirname(path))

    # ── Batch rename (Tab 2) ─────────────────────────────────────────────────
    def _valid_cached_paths(self, key, editor, root_text):
        """Cached absolute paths of the last scan — only if they still describe
        EXACTLY what the editor shows and the Source field still matches."""
        e = self._scan_cache.get(key)
        if not e or not root_text:
            return None
        lines, paths, root = e
        if _key(root) != _key(root_text):
            return None
        if nonblank_lines(editor.toPlainText()) != lines:
            return None
        return list(paths)

    def batch_rename(self):
        left_text = self.t2_left_preview.toPlainText()
        right_text = self.tab2_right_editor.toPlainText()
        left_lines, right_lines = nonblank_lines(left_text), nonblank_lines(right_text)
        if not left_lines or not right_lines:
            QMessageBox.warning(self, "Batch Rename", "Both previews must contain names.")
            return

        # Blank lines in the middle would shift the line-by-line pairing.
        for side, text in (("Left", left_text), ("Right", right_text)):
            blanks = interior_blank_line_numbers(text)
            if blanks:
                shown = ", ".join(map(str, blanks[:10])) + (" …" if len(blanks) > 10 else "")
                QMessageBox.warning(
                    self, "Batch Rename",
                    f"The {side} preview contains empty line(s) in the middle "
                    f"(line {shown}).\nThey would shift the line-by-line pairing.\n\n"
                    "Please delete the empty line(s) and try again. Nothing was changed.")
                return

        if len(left_lines) != len(right_lines):
            QMessageBox.warning(
                self, "Batch Rename",
                f"Line count mismatch!\nLeft: {len(left_lines)}  |  Right: {len(right_lines)}\n"
                "Both sides must have the same number of non-empty lines.\nNothing was changed.")
            return

        root = self.t2_left_path_edit.text().strip()
        if not os.path.isdir(root):
            QMessageBox.warning(self, "Batch Rename",
                                "Please set a valid Left source folder path.")
            return

        left_abs = (self._valid_cached_paths("t2_left", self.t2_left_preview, root)
                    or self._valid_cached_paths("left", self.t2_left_preview, root))
        if left_abs is None:                       # rebuild paths from indentation
            stack, left_abs = [root], []
            for line in left_lines:
                level = (len(line) - len(line.lstrip())) // 2
                while len(stack) > level + 1:
                    stack.pop()
                ap = os.path.join(stack[-1], line.strip())
                left_abs.append(ap)
                stack.append(ap)

        ops = []
        for old_abs, right_line in zip(left_abs, right_lines):
            old_name, new_name = os.path.basename(old_abs), right_line.strip()
            if new_name == old_name:
                continue
            ops.append(RenameOp(old_abs, old_name, new_name,
                                os.path.join(os.path.dirname(old_abs), new_name)))
        if not ops:
            QMessageBox.information(self, "Batch Rename", "No differences — nothing to rename.")
            return

        clean, rejected, missing = plan_renames(ops)

        def pre_text():
            parts = []
            if rejected:
                parts.append(f"NOT renamed — conflict / invalid name ({len(rejected)}):")
                parts += [f'  "{o.old_name}" → "{o.new_name}"\n      {why}' for o, why in rejected]
            if missing:
                parts.append(f"NOT found on disk ({len(missing)}):")
                parts += [f'  "{o.old_name}"  ({o.old_abs})' for o in missing]
            return "\n".join(parts)

        if not clean:
            QMessageBox.warning(self, "Batch Rename",
                                "Nothing can be renamed.\n\n" + pre_text())
            return

        # ── confirmation ──
        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm Batch Rename")
        dlg.resize(760, 500)
        cl = QVBoxLayout(dlg)
        cl.setContentsMargins(16, 16, 16, 12)
        cl.setSpacing(8)
        hdr = QLabel(f"About to rename <b>{len(clean)}</b> item(s) inside:<br><code>{root}</code>")
        hdr.setWordWrap(True)
        cl.addWidget(hdr)
        wi = QLabel("⚠  This cannot be undone. Close other programs that use these "
                    "files or folders before you continue.")
        wi.setWordWrap(True)
        wi.setStyleSheet("color:#e08030;font-weight:bold;")
        cl.addWidget(wi)
        body = "\n".join(f"  {o.old_name}  →  {o.new_name}" for o in clean)
        if rejected or missing:
            body += "\n\n" + "─" * 60 + "\n" + pre_text()
        sc = QPlainTextEdit()
        sc.setReadOnly(True)
        sc.setFont(make_editor_font(10))
        sc.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        sc.setPlainText(body)
        cl.addWidget(sc, stretch=1)
        br = QHBoxLayout()
        br.setSpacing(10)
        br.addStretch()
        cn = QPushButton("Cancel")
        cn.setFixedSize(110, 30)
        cn.clicked.connect(dlg.reject)
        br.addWidget(cn)
        co = QPushButton("Rename")
        co.setFixedSize(110, 30)
        co.setStyleSheet("background-color:#e65c00;color:white;font-weight:bold;border-radius:4px;")
        co.clicked.connect(dlg.accept)
        br.addWidget(co)
        cl.addLayout(br)
        cn.setDefault(True)     # Enter = Cancel, a rename needs a deliberate click
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        renamed, failed, late_conflicts = execute_renames(clean)
        self._scan_cache.pop("t2_left", None)
        self._scan_cache.pop("left", None)

        sl = []
        if renamed:
            sl.append(f"✅  Renamed {len(renamed)} item(s) successfully.\n")
            sl += [f"  {r}" for r in renamed]
        conflicts = [f'CONFLICT  "{o.old_name}" -> "{o.new_name}"\n    {why}' for o, why in rejected]
        conflicts += late_conflicts
        if conflicts:
            sl += ["", f"⚠️  {len(conflicts)} item(s) NOT renamed — originals untouched:", ""]
            for c in conflicts:
                sl += [f"  {c}", ""]
        if missing:
            sl += ["", f"⚠️  {len(missing)} item(s) not found on disk:", ""]
            sl += [f"  {o.old_name}   ({o.old_abs})" for o in missing]
        if failed:
            sl += ["", f"❌  {len(failed)} error(s):", ""]
            for fm in failed:
                sl += [f"  {fm}", ""]
        full = "\n".join(sl)

        rd = QDialog(self)
        rd.setWindowTitle("Batch Rename Complete")
        rd.resize(780, 480)
        rl = QVBoxLayout(rd)
        rl.setContentsMargins(16, 16, 16, 12)
        rl.setSpacing(8)
        se = QPlainTextEdit()
        se.setReadOnly(True)
        se.setFont(make_editor_font(10))
        se.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        se.setPlainText(full)
        rl.addWidget(se, stretch=1)
        rb = QHBoxLayout()
        rb.setSpacing(10)
        cb2 = QPushButton("Copy to Clipboard")
        cb2.setFixedHeight(30)
        cb2.clicked.connect(lambda: QApplication.clipboard().setText(full))
        rb.addWidget(cb2)
        rb.addStretch()
        ob2 = QPushButton("Open Folder")
        ob2.setFixedHeight(30)
        ob2.clicked.connect(lambda: self._open_folder(root))
        rb.addWidget(ob2)
        ok2 = QPushButton("OK")
        ok2.setFixedHeight(30)
        ok2.setDefault(True)
        ok2.clicked.connect(rd.accept)
        rb.addWidget(ok2)
        rl.addLayout(rb)
        rd.exec()

    # ── Replicate (kept; not wired to a button in the current layout) ────────
    def _replicate(self, prefix):
        lines = nonblank_lines(getattr(self, f"{prefix}_preview").toPlainText())
        if not lines:
            QMessageBox.warning(self, "Error", "No structure in preview.")
            return
        dest = QFileDialog.getExistingDirectory(self, "Select destination folder")
        if not dest or not os.path.isdir(dest):
            return
        try:
            self.create_from_lines(dest, lines)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Error", f"Failed:\n{e}")
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Replication Successful")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("Folder structure replicated.")
        msg.setInformativeText(f"Created in:\n{dest}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        ob = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        msg.exec()
        if msg.clickedButton() == ob:
            self._open_folder(dest)

    def replicate_left(self):  self._replicate("left")
    def replicate_right(self): self._replicate("right")

    def create_from_lines(self, path, lines):
        stack = [path]
        for line in lines:
            level = (len(line) - len(line.lstrip())) // 2
            name = line.strip()
            err = validate_new_name(name)
            if err:
                raise ValueError(f'"{name}": {err}')
            while len(stack) > level + 1:
                stack.pop()
            cur = os.path.join(stack[-1], name)
            os.makedirs(cur, exist_ok=True)
            stack.append(cur)

    def _open_folder(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as e:
            QMessageBox.warning(self, "Open Folder", f"Cannot open the folder:\n{e}")


def apply_dark_palette_if_needed(app):
    """The UI is designed dark. If the system theme is light, use a dark palette so
    every label stays readable; a dark system theme is left exactly as it is."""
    if app.palette().color(QPalette.ColorRole.Window).lightness() <= 128:
        return
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    p = QPalette()
    for role, col in ((R.Window, "#2b2d30"), (R.WindowText, "#e0e0e0"), (R.Base, "#1e1f22"),
                      (R.AlternateBase, "#25262a"), (R.ToolTipBase, "#3c3f41"),
                      (R.ToolTipText, "#e0e0e0"), (R.Text, "#e6e8eb"), (R.Button, "#3c3f41"),
                      (R.ButtonText, "#e0e0e0"), (R.BrightText, "#ffffff"), (R.Link, "#589df6"),
                      (R.Highlight, "#2f65ca"), (R.HighlightedText, "#ffffff"),
                      (R.PlaceholderText, "#7a7e85")):
        p.setColor(role, QColor(col))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, role, QColor("#6f737a"))
    app.setPalette(p)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_dark_palette_if_needed(app)
    window = FolderStructureApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
"""Design tokens and stylesheet for Simple APK.

Identity: the warm workbench. A warm near-charcoal bench, off-white ink,
and one amber work-lamp accent for the thing that matters most (the
Build button, the status light). Token inspiration comes from the Warp
design file (warm canvas, off-white ink, tight radii, Inter-like system
type, mono for the log), but this is its own look: amber is ours, and
the voice is plain words, not developer chrome.

Techniques pulled from the BNB UI Design Source File Library (each
passed the Part 3 filter in design-rules.md: simpler, toy test, cheap
on his PC, feels like itself):
- 012 Progressive disclosure: the main window shows three steps only;
  everything else lives one menu tap away in its own window.
- 003 Calm technology: one status light plus one status line; the log
  stays in its own window and the app never pops up to say it worked.
- 008 Delight, done right: the finish moment only. A check that fades
  in over 200 ms when the APK is ready, nowhere else.

Motion budget: functional animation under 300 ms, opacity only, no
layout animation, no blur. Cheap on an 8 GB PC with no GPU.
"""
from __future__ import annotations

# Tokens (single source; no ad-hoc hex in the windows).
CANVAS = "#2b2622"
CANVAS_SOFT = "#383330"
CARD = "#332e2a"
HAIRLINE = "#4a443e"
INK = "#f7f5f0"
BODY = "#c9c0ad"
MUTE = "#aea69c"
ACCENT = "#e8a33d"
ACCENT_DARK = "#c07f1f"
ON_ACCENT = "#2b2622"
SUCCESS = "#7fb069"
ERROR = "#e0655a"

FONT_TITLE = 20
FONT_STEP = 17
FONT_BODY = 14
FONT_SMALL = 12
FONT_LOG = 13

BUTTON_MIN_HEIGHT = 44


def stylesheet() -> str:
    """One stylesheet for the whole app (U15: one system)."""
    return f"""
    QMainWindow, QWidget {{
        background: {CANVAS};
        color: {INK};
        font-size: {FONT_BODY}px;
    }}
    QLabel, QCheckBox {{
        background: transparent;
    }}
    QMenuBar {{
        background: {CANVAS};
        color: {INK};
        padding: 4px 8px;
    }}
    QMenuBar::item:selected {{
        background: {CANVAS_SOFT};
    }}
    QMenu {{
        background: {CANVAS_SOFT};
        color: {INK};
        border: 1px solid {HAIRLINE};
        padding: 4px;
    }}
    QMenu::item:selected {{
        background: {ACCENT};
        color: {ON_ACCENT};
    }}
    QPushButton {{
        background: {CANVAS_SOFT};
        color: {INK};
        border: 1px solid {HAIRLINE};
        border-radius: 4px;
        padding: 10px 18px;
        min-height: {BUTTON_MIN_HEIGHT - 22}px;
    }}
    QPushButton:hover {{
        border-color: {ACCENT};
    }}
    QPushButton:pressed {{
        background: {CARD};
    }}
    QPushButton:disabled {{
        color: {MUTE};
        border-color: {HAIRLINE};
    }}
    QPushButton:focus {{
        border: 2px solid {ACCENT};
    }}
    QPushButton#primary {{
        background: {ACCENT};
        color: {ON_ACCENT};
        border: 1px solid {ACCENT};
        font-weight: 600;
        font-size: 16px;
    }}
    QPushButton#primary:hover {{
        background: {ACCENT_DARK};
        border-color: {ACCENT_DARK};
        color: {INK};
    }}
    QPushButton#primary:disabled {{
        background: {CANVAS_SOFT};
        color: {MUTE};
        border-color: {HAIRLINE};
    }}
    QProgressBar {{
        background: {CANVAS_SOFT};
        border: 1px solid {HAIRLINE};
        border-radius: 4px;
        height: 18px;
        text-align: center;
        color: {INK};
    }}
    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: 3px;
    }}
    QLineEdit, QPlainTextEdit, QTextEdit {{
        background: {CANVAS_SOFT};
        color: {INK};
        border: 1px solid {HAIRLINE};
        border-radius: 4px;
        padding: 8px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border: 2px solid {ACCENT};
    }}
    QCheckBox {{
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
    }}
    QListWidget {{
        background: {CANVAS_SOFT};
        color: {INK};
        border: 1px solid {HAIRLINE};
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background: {ACCENT};
        color: {ON_ACCENT};
    }}
    QStatusBar {{
        background: {CANVAS};
        color: {BODY};
    }}
    QFrame#card {{
        background: {CARD};
        border: 1px solid {HAIRLINE};
        border-radius: 6px;
    }}
    QFrame#cardActive {{
        background: {CARD};
        border: 2px solid {ACCENT};
        border-radius: 6px;
    }}
    QLabel#title {{
        font-size: {FONT_TITLE}px;
        font-weight: 600;
    }}
    QLabel#stepTitle {{
        font-size: {FONT_STEP}px;
        font-weight: 600;
    }}
    QLabel#body {{
        color: {BODY};
    }}
    QLabel#small {{
        color: {MUTE};
        font-size: {FONT_SMALL}px;
    }}
    QLabel#success {{
        color: {SUCCESS};
        font-weight: 600;
    }}
    QLabel#error {{
        color: {ERROR};
    }}
    """

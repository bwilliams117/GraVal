"""Centralised design tokens: colours, fonts, and ttk widget styles."""

import tkinter.ttk as ttk

# ── Accent ────────────────────────────────────────────────────────────────────
ACCENT          = "#78D68B"
ACCENT_HOVER    = "#5fc476"

# ── Surface / structural ──────────────────────────────────────────────────────
SURFACE_0       = "#121212"   # root window / PanedWindow bg
SURFACE_1       = "#1c1c1c"   # card / panel frames
SURFACE_2       = "#272727"   # entry / textbox inset

# ── Borders ───────────────────────────────────────────────────────────────────
BORDER_SUBTLE   = "#2a2a2a"
BORDER_STRONG   = "#3a3a3a"

# ── Text ──────────────────────────────────────────────────────────────────────
TEXT_PRIMARY    = "#ffffff"
TEXT_MUTED      = "#9aa0a6"
TEXT_DISABLED   = "#555555"
TEXT_STATUS     = "#ffffff"

# ── Status semantics ──────────────────────────────────────────────────────────
STATUS_PASS     = "#78D68B"
STATUS_PASS_HVR = "#5fc476"
STATUS_WARN     = "#f59e0b"
STATUS_FAIL     = "#ef4444"
STATUS_FAIL_HVR = "#dc2626"

# ── Special purpose ───────────────────────────────────────────────────────────
LINK            = "#78D68B"
LINK_HOVER      = "#a8e6b4"
THUMB_MISSING   = "#555555"
SCROLLBAR_BTN   = "#3a3a3a"
SCROLLBAR_HVR   = "#4a4a4a"

# ── Font tuples ───────────────────────────────────────────────────────────────
FONT_TITLE      = ("Helvetica", 26, "bold")
FONT_H1         = ("Helvetica", 22, "bold")
FONT_H2         = ("Helvetica", 20, "bold")
FONT_H3         = ("Helvetica", 18, "bold")
FONT_H4         = ("Helvetica", 15, "bold")
FONT_SUBHEAD    = ("Helvetica", 13)
FONT_BODY       = ("Helvetica", 12)
FONT_BODY_BOLD  = ("Helvetica", 12, "bold")
FONT_SMALL      = ("Helvetica", 11)
FONT_TINY       = ("Helvetica", 10)
FONT_CAPTION    = ("Helvetica", 9)
FONT_MONO       = ("Courier", 11)
FONT_MONO_SMALL = ("Courier", 10)


def setup_ttk_style() -> None:
    """Apply the dark-theme styles to ttk.Treeview and Vertical.TScrollbar."""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "Treeview",
        background=SURFACE_1,
        foreground=TEXT_PRIMARY,
        fieldbackground=SURFACE_1,
        bordercolor=BORDER_SUBTLE,
        borderwidth=0,
        rowheight=26,
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#121212")],
    )

    style.configure(
        "Treeview.Heading",
        background=SURFACE_0,
        foreground=TEXT_MUTED,
        bordercolor=BORDER_SUBTLE,
        relief="flat",
        font=("Helvetica", 10, "bold"),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", SURFACE_1)],
    )

    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE_1,
        troughcolor=SURFACE_0,
        bordercolor=SURFACE_0,
        arrowcolor=SCROLLBAR_BTN,
        relief="flat",
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", SCROLLBAR_HVR), ("!disabled", SCROLLBAR_BTN)],
    )

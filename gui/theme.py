# ── Accent (cyan-steel, mission-control) ─────────────────────────────────────
ACCENT          = "#00b4d8"
ACCENT_HOVER    = "#0096c7"

# ── Surface / structural ──────────────────────────────────────────────────────
SURFACE_0       = "#1a1c1e"   # root window / PanedWindow bg
SURFACE_1       = "#22262a"   # card / panel frames
SURFACE_2       = "#2b2f33"   # entry / textbox inset

# ── Borders ───────────────────────────────────────────────────────────────────
BORDER_SUBTLE   = "#2e3338"
BORDER_STRONG   = "#3d4450"

# ── Text ──────────────────────────────────────────────────────────────────────
TEXT_PRIMARY    = "#e2e8f0"
TEXT_MUTED      = "#8a9bb0"
TEXT_DISABLED   = "#4a5568"
TEXT_STATUS     = "#e2e8f0"

# ── Status semantics ──────────────────────────────────────────────────────────
STATUS_PASS     = "#22c55e"
STATUS_PASS_HVR = "#16a34a"
STATUS_WARN     = "#f59e0b"
STATUS_FAIL     = "#ef4444"
STATUS_FAIL_HVR = "#dc2626"

# ── Special purpose ───────────────────────────────────────────────────────────
LINK            = "#38bdf8"
LINK_HOVER      = "#7dd3fc"
THUMB_MISSING   = "#4a5568"
SCROLLBAR_BTN   = "#3d4450"
SCROLLBAR_HVR   = "#546070"

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
    import tkinter.ttk as ttk

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
        foreground=[("selected", "#ffffff")],
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

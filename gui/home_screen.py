import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme


def _Frame(parent, **kw):
    if _HAS_CTK:
        return ctk.CTkFrame(parent, **kw)
    kw.pop("fg_color", None)
    return tk.Frame(parent, **kw)

def _Label(parent, text, font=None, text_color=None, **kw):
    if _HAS_CTK:
        kw2 = {"text": text}
        if font:
            kw2["font"] = font
        if text_color:
            kw2["text_color"] = text_color
        kw2.update(kw)
        return ctk.CTkLabel(parent, **kw2)
    else:
        return tk.Label(parent, text=text, **kw)

def _Button(parent, text, command, **kw):
    if _HAS_CTK:
        return ctk.CTkButton(parent, text=text, command=command, **kw)
    else:
        kw.pop("fg_color", None)
        kw.pop("hover_color", None)
        kw.pop("corner_radius", None)
        return tk.Button(parent, text=text, command=command, **kw)


_TOOLS = [
    (
        "Granule Validator",
        "Spot-check a NASA Earthdata collection by sampling granules and running "
        "schema, spatial, temporal, and URL health checks against the UMM metadata.",
        "show_search",
    ),
]


class HomeScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self):
        # ── header bar ────────────────────────────────────────────────────────
        hdr = _Frame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))

        _Label(hdr, text="Vernier", font=("Helvetica", 22, "bold")).pack(side="left")

        _Button(
            hdr, text="Sign Out", command=self._on_signout,
            width=90,
        ).pack(side="right")

        # ── sub-header ────────────────────────────────────────────────────────
        sub = _Frame(self, fg_color="transparent")
        sub.pack(fill="x", padx=24, pady=(6, 20))

        _Label(
            sub,
            text="Select a tool to get started",
            font=("Helvetica", 13),
            text_color=theme.TEXT_MUTED,
        ).pack(side="left")

        tk.Frame(self, height=1, bg=theme.BORDER_STRONG).pack(fill="x")

        # ── card area ─────────────────────────────────────────────────────────
        if _HAS_CTK:
            card_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        else:
            card_area = tk.Frame(self)
        card_area.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        num_cols = 3
        for i in range(num_cols):
            card_area.grid_columnconfigure(i, weight=1, uniform="card")

        for i, (title, desc, action_key) in enumerate(_TOOLS):
            row = i // num_cols
            col = i % num_cols
            card_area.grid_rowconfigure(row, weight=0)
            self._make_card(card_area, title, desc, action_key, row, col)

    def _make_card(self, container, title, desc, action_key, row, col):
        if _HAS_CTK:
            card = ctk.CTkFrame(container, corner_radius=10, border_width=1, border_color=theme.BORDER_SUBTLE)
        else:
            card = tk.LabelFrame(container, relief="groove", bd=2)

        card.grid(row=row, column=col, padx=12, pady=12, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        # Title
        _Label(
            card,
            text=title,
            font=("Helvetica", 15, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))

        # Description
        _Label(
            card,
            text=desc,
            font=("Helvetica", 11),
            text_color=theme.TEXT_MUTED,
            wraplength=280,
            justify="left",
        ).grid(row=1, column=0, sticky="nw", padx=16, pady=(0, 12))

        # Launch button
        _Button(
            card,
            text="Launch",
            command=lambda ak=action_key: getattr(self.app, ak)(),
            fg_color=theme.STATUS_PASS,
            hover_color=theme.STATUS_PASS_HVR,
            width=120,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 16))

    def _on_signout(self):
        self.app.auth = None
        self.app.selected_collection = None
        self.app.last_validation_run = None
        self.app.show_login()

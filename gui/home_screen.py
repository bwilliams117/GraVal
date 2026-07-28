"""Home screen: card-based tool dashboard shown after a successful login."""

import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme


def _Frame(parent, **kw):
    """Return a CTkFrame or plain tk.Frame, stripping CTk-only kwargs for Tk."""
    if _HAS_CTK:
        return ctk.CTkFrame(parent, **kw)
    kw.pop("fg_color", None)
    return tk.Frame(parent, **kw)


def _Label(parent, text, font=None, text_color=None, **kw):
    """Return a CTkLabel or plain tk.Label."""
    if _HAS_CTK:
        kw2 = {"text": text}
        if font:
            kw2["font"] = font
        if text_color:
            kw2["text_color"] = text_color
        kw2.update(kw)
        return ctk.CTkLabel(parent, **kw2)
    return tk.Label(parent, text=text, **kw)


def _Button(parent, text, command, **kw):
    """Return a CTkButton or plain tk.Button, stripping CTk-only kwargs for Tk."""
    if _HAS_CTK:
        return ctk.CTkButton(parent, text=text, command=command, **kw)
    for key in ("fg_color", "hover_color", "corner_radius"):
        kw.pop(key, None)
    return tk.Button(parent, text=text, command=command, **kw)


# Each entry is (title, description, app_method_name).
_TOOLS = [
    (
        "Granule Validator",
        "Spot-check a NASA Earthdata collection by sampling granules and running "
        "schema, spatial, temporal, and URL health checks against the UMM metadata.",
        "show_search",
    ),
]


class HomeScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    """Card grid offering entry points to each available tool."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self):
        hdr = _Frame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 0))

        _Label(hdr, text="GraVal", font=("Helvetica", 22, "bold")).pack(side="left")
        _Button(
            hdr, text="Sign Out", command=self._on_signout, width=90
        ).pack(side="right")

        sub = _Frame(self, fg_color="transparent")
        sub.pack(fill="x", padx=24, pady=(6, 20))
        _Label(
            sub,
            text="Select a tool to get started",
            font=("Helvetica", 13),
            text_color=theme.TEXT_MUTED,
        ).pack(side="left")

        tk.Frame(self, height=1, bg=theme.BORDER_STRONG).pack(fill="x")

        if _HAS_CTK:
            card_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        else:
            card_area = tk.Frame(self)
        card_area.pack(fill="both", expand=True, padx=24, pady=(0, 24))

        num_cols = 3
        for i in range(num_cols):
            card_area.grid_columnconfigure(i, weight=1, uniform="card")

        for i, (title, desc, action_key) in enumerate(_TOOLS):
            row, col = divmod(i, num_cols)
            card_area.grid_rowconfigure(row, weight=0)
            self._make_card(card_area, title, desc, action_key, row, col)

    def _make_card(self, container, title, desc, action_key, row, col):
        """Build a single tool card and place it in the grid."""
        if _HAS_CTK:
            card = ctk.CTkFrame(
                container, corner_radius=10, border_width=0,
                fg_color=theme.SURFACE_2, width=300,
            )
        else:
            card = tk.LabelFrame(container, relief="groove", bd=2)

        card.grid(row=row, column=col, padx=14, pady=14, sticky="nw")
        card.grid_columnconfigure(0, weight=1)

        if _HAS_CTK:
            strip = ctk.CTkFrame(card, height=5, fg_color=theme.ACCENT, corner_radius=0)
            strip.grid(row=0, column=0, sticky="ew")
            strip.grid_propagate(False)

        _Label(
            card, text=title, font=theme.FONT_H4, text_color=theme.TEXT_PRIMARY,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(14, 4))

        tk.Frame(card, height=1, bg=theme.BORDER_STRONG).grid(
            row=2, column=0, sticky="ew", padx=18, pady=(4, 0),
        )

        _Label(
            card, text=desc,
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=250, justify="left",
        ).grid(row=3, column=0, sticky="nw", padx=18, pady=(10, 4))

        _Button(
            card, text="Launch",
            command=lambda ak=action_key: getattr(self.app, ak)(),
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color=theme.SURFACE_0,
            width=100,
        ).grid(row=4, column=0, sticky="w", padx=18, pady=(10, 18))

    def _on_signout(self):
        self.app.auth = None
        self.app.selected_collection = None
        self.app.last_validation_run = None
        self.app.show_login()

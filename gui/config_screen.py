"""Config screen: sample size, optional date range, and check-toggle controls."""

import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme
from validator.runner import ALL_CHECK_IDS, CHECKS


_CHECK_LABELS = {
    "schema":     "Schema Completeness — required UMM fields present",
    "temporal":   "Temporal Validity — date range is logical",
    "spatial":    "Spatial Validity — coordinate ranges are valid",
    "daynight":   "Day/Night Consistency — flag vs. sun position",
    "url_health": "URL Health — download URLs exist and are reachable",
    "file_size":  "File Size Sanity — no zero-byte or suspiciously tiny files",
    "prod_date":  "Production Date Sanity — produced after acquisition",
    "collection": "Collection Reference — granule belongs to selected collection",
    "duplicates": "Duplicate Detection — no repeated granule IDs in sample",
}


class ConfigScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    """Validation configuration form: sample size, date range, and check toggles."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._check_vars: dict[str, tk.BooleanVar] = {}
        self._build()

    def _build(self):
        col = self.app.selected_collection
        umm = col.get("umm", {}) if col else {}
        short_name = umm.get("ShortName", "Unknown")
        version = umm.get("Version", "?")
        cid = col.get("meta", {}).get("concept-id", "") if col else ""

        # ── header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        hdr.pack(fill="x", padx=16, pady=(16, 2))

        title_text = f"Configure Validation — {short_name} v{version}"
        if _HAS_CTK:
            ctk.CTkLabel(
                hdr, text=title_text, font=theme.FONT_H3,
            ).pack(side="left")
        else:
            tk.Label(hdr, text=title_text, font=theme.FONT_H3).pack(side="left")

        sub = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        sub.pack(fill="x", padx=16, pady=(0, 10))
        if _HAS_CTK:
            ctk.CTkLabel(
                sub, text=f"Concept ID: {cid}",
                font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
            ).pack(side="left")
        else:
            tk.Label(sub, text=f"Concept ID: {cid}", font=theme.FONT_CAPTION).pack(
                side="left"
            )

        # ── single card ───────────────────────────────────────────────────────
        if _HAS_CTK:
            self._card = ctk.CTkFrame(
                self, fg_color=theme.SURFACE_1, corner_radius=12
            )
        else:
            self._card = tk.Frame(self, bg=theme.SURFACE_1)
        self._card.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._build_sample_section()
        self._build_date_section()
        self._build_checks_section()
        self._build_bottom_bar()

    # ── layout helpers ────────────────────────────────────────────────────────

    def _section_heading(self, text: str):
        """Render a small uppercase section label inside the card."""
        if _HAS_CTK:
            ctk.CTkLabel(
                self._card, text=text, font=theme.FONT_CAPTION,
                text_color=theme.TEXT_MUTED,
            ).pack(anchor="w", padx=20, pady=(16, 4))
        else:
            tk.Label(
                self._card, text=text, font=theme.FONT_CAPTION,
                fg=theme.TEXT_MUTED, bg=theme.SURFACE_1,
            ).pack(anchor="w", padx=20, pady=(16, 4))

    def _divider(self):
        """Render a 1px horizontal rule inside the card."""
        tk.Frame(
            self._card, height=1, bg=theme.BORDER_SUBTLE
        ).pack(fill="x", padx=20, pady=(12, 0))

    # ── sections ──────────────────────────────────────────────────────────────

    def _build_sample_section(self):
        """Slider that controls how many granules are sampled."""
        self._section_heading("SAMPLE SIZE")

        row = (
            ctk.CTkFrame(self._card, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self._card, bg=theme.SURFACE_1)
        )
        row.pack(fill="x", padx=20, pady=(0, 4))

        self._sample_var = tk.IntVar(value=5)
        self._sample_label_var = tk.StringVar(value="5")

        if _HAS_CTK:
            ctk.CTkSlider(
                row, from_=1, to=50, number_of_steps=49,
                variable=self._sample_var, command=self._on_slider, width=260,
            ).pack(side="left", padx=(0, 12))
            ctk.CTkLabel(
                row, textvariable=self._sample_label_var,
                width=28, font=theme.FONT_BODY_BOLD,
            ).pack(side="left")
            ctk.CTkLabel(
                row, text="granules", font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
            ).pack(side="left", padx=(6, 0))
        else:
            tk.Scale(
                row, from_=1, to=50, orient="horizontal",
                variable=self._sample_var,
                command=lambda v: self._sample_label_var.set(str(int(float(v)))),
                length=240,
            ).pack(side="left", padx=(0, 8))
            tk.Label(row, textvariable=self._sample_label_var,
                     bg=theme.SURFACE_1).pack(side="left")
            tk.Label(row, text="granules", bg=theme.SURFACE_1,
                     fg=theme.TEXT_MUTED).pack(side="left", padx=(4, 0))

        self._divider()

    def _build_date_section(self):
        """Optional start/end date entries for narrowing the CMR search."""
        self._section_heading("DATE RANGE")

        row = (
            ctk.CTkFrame(self._card, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self._card, bg=theme.SURFACE_1)
        )
        row.pack(fill="x", padx=20, pady=(0, 4))

        self._start_var = tk.StringVar()
        self._end_var = tk.StringVar()

        if _HAS_CTK:
            ctk.CTkEntry(
                row, textvariable=self._start_var,
                placeholder_text="Start (YYYY-MM-DD)", width=160,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                row, text="to", font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkEntry(
                row, textvariable=self._end_var,
                placeholder_text="End (YYYY-MM-DD)", width=160,
            ).pack(side="left")
            ctk.CTkLabel(
                row, text="optional", font=theme.FONT_CAPTION,
                text_color=theme.TEXT_DISABLED,
            ).pack(side="left", padx=(12, 0))
        else:
            tk.Entry(row, textvariable=self._start_var, width=18).pack(
                side="left", padx=(0, 4)
            )
            tk.Label(row, text="to", bg=theme.SURFACE_1,
                     fg=theme.TEXT_MUTED).pack(side="left", padx=4)
            tk.Entry(row, textvariable=self._end_var, width=18).pack(side="left")

        self._divider()

    def _build_checks_section(self):
        """Two-column grid of check toggle checkboxes."""
        self._section_heading("CHECKS")

        grid = (
            ctk.CTkFrame(self._card, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self._card, bg=theme.SURFACE_1)
        )
        grid.pack(fill="x", padx=20, pady=(0, 16))

        for i, check_id in enumerate(ALL_CHECK_IDS):
            var = tk.BooleanVar(value=True)
            self._check_vars[check_id] = var
            row_idx = i // 2
            col_idx = i % 2
            label = _CHECK_LABELS.get(check_id, check_id)
            if _HAS_CTK:
                ctk.CTkCheckBox(
                    grid, text=label, variable=var, font=theme.FONT_SMALL,
                ).grid(row=row_idx, column=col_idx, sticky="w",
                       padx=(0, 20), pady=3)
            else:
                tk.Checkbutton(grid, text=label, variable=var).grid(
                    row=row_idx, column=col_idx, sticky="w",
                    padx=(0, 16), pady=2,
                )

    # ── bottom bar ────────────────────────────────────────────────────────────

    def _build_bottom_bar(self):
        """Back, Home, and Run Validation navigation buttons."""
        btm = (
            ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self)
        )
        btm.pack(fill="x", padx=16, pady=(0, 16))

        if _HAS_CTK:
            ctk.CTkButton(
                btm, text="← Back to Search",
                command=self.app.show_search, width=140,
            ).pack(side="left")
            ctk.CTkButton(
                btm, text="Home", command=self.app.show_home, width=80,
                fg_color=theme.SURFACE_2, hover_color=theme.BORDER_STRONG,
                text_color=theme.TEXT_MUTED,
            ).pack(side="left", padx=(8, 0))
            ctk.CTkButton(
                btm, text="Run Validation", command=self._on_run, width=180,
                fg_color=theme.STATUS_PASS, hover_color=theme.STATUS_PASS_HVR,
            ).pack(side="right")
        else:
            tk.Button(btm, text="← Back to Search",
                      command=self.app.show_search).pack(side="left")
            tk.Button(btm, text="Home", command=self.app.show_home).pack(
                side="left", padx=(6, 0)
            )
            tk.Button(btm, text="Run Validation",
                      command=self._on_run).pack(side="right")

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_slider(self, value):
        self._sample_label_var.set(str(int(float(value))))

    def _on_run(self):
        enabled = {cid for cid, var in self._check_vars.items() if var.get()}
        start = self._start_var.get().strip() or None
        end = self._end_var.get().strip() or None
        temporal = (start, end) if start or end else None
        col = self.app.selected_collection
        self.app.show_results({
            "sample_size": int(self._sample_var.get()),
            "temporal": temporal,
            "enabled_checks": enabled,
            "env": getattr(self.app, "env", "OPS"),
            "uat_token": getattr(self.app, "uat_token", None),
            "concept_id": col.get("meta", {}).get("concept-id", "") if col else "",
        })

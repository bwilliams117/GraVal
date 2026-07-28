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

        hdr = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        hdr.pack(fill="x", padx=16, pady=(16, 4))

        title_text = f"Configure Validation — {short_name} v{version}"
        if _HAS_CTK:
            ctk.CTkLabel(
                hdr, text=title_text, font=("Helvetica", 18, "bold")
            ).pack(side="left")
        else:
            tk.Label(hdr, text=title_text, font=("Helvetica", 14, "bold")).pack(
                side="left"
            )

        sub = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        sub.pack(fill="x", padx=16, pady=(0, 12))
        if _HAS_CTK:
            ctk.CTkLabel(
                sub, text=f"Concept ID: {cid}",
                font=("Helvetica", 10), text_color=theme.TEXT_MUTED,
            ).pack(side="left")
        else:
            tk.Label(sub, text=f"Concept ID: {cid}", font=("Helvetica", 9)).pack(
                side="left"
            )

        self._build_sample_section()
        self._build_date_section()
        self._build_checks_section()
        self._build_bottom_bar()

    def _build_sample_section(self):
        """Slider that controls how many granules are sampled."""
        frame = (
            ctk.CTkFrame(self) if _HAS_CTK
            else tk.LabelFrame(self, text="Sample Size")
        )
        frame.pack(fill="x", padx=16, pady=(0, 10))

        if _HAS_CTK:
            ctk.CTkLabel(
                frame,
                text="Sample Size  (granules to check):",
                font=("Helvetica", 12),
            ).pack(side="left", padx=(12, 8), pady=10)
        else:
            tk.Label(frame, text="Sample Size:").pack(side="left", padx=8)

        self._sample_var = tk.IntVar(value=5)
        self._sample_label_var = tk.StringVar(value="5")

        if _HAS_CTK:
            ctk.CTkSlider(
                frame, from_=1, to=50, number_of_steps=49,
                variable=self._sample_var, command=self._on_slider, width=220,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                frame, textvariable=self._sample_label_var,
                width=28, font=("Helvetica", 12, "bold"),
            ).pack(side="left")
        else:
            tk.Scale(
                frame, from_=1, to=50, orient="horizontal",
                variable=self._sample_var,
                command=lambda v: self._sample_label_var.set(str(int(float(v)))),
                length=200,
            ).pack(side="left", padx=8)
            tk.Label(frame, textvariable=self._sample_label_var).pack(side="left")

    def _build_date_section(self):
        """Optional start/end date entries for narrowing the CMR search."""
        frame = (
            ctk.CTkFrame(self) if _HAS_CTK
            else tk.LabelFrame(self, text="Date Range (optional)")
        )
        frame.pack(fill="x", padx=16, pady=(0, 10))

        if _HAS_CTK:
            ctk.CTkLabel(
                frame,
                text="Date Range  (optional, YYYY-MM-DD):",
                font=("Helvetica", 12),
            ).pack(side="left", padx=(12, 8), pady=10)
        else:
            tk.Label(frame, text="Date Range:").pack(side="left", padx=8)

        self._start_var = tk.StringVar()
        self._end_var = tk.StringVar()

        if _HAS_CTK:
            ctk.CTkEntry(
                frame, textvariable=self._start_var,
                placeholder_text="Start (YYYY-MM-DD)", width=160,
            ).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(frame, text="to", font=("Helvetica", 11)).pack(
                side="left", padx=4
            )
            ctk.CTkEntry(
                frame, textvariable=self._end_var,
                placeholder_text="End (YYYY-MM-DD)", width=160,
            ).pack(side="left", padx=(6, 0))
        else:
            tk.Entry(frame, textvariable=self._start_var, width=18).pack(
                side="left", padx=4
            )
            tk.Label(frame, text="to").pack(side="left")
            tk.Entry(frame, textvariable=self._end_var, width=18).pack(
                side="left", padx=4
            )

    def _build_checks_section(self):
        """Two-column grid of check toggle checkboxes."""
        frame = (
            ctk.CTkFrame(self) if _HAS_CTK
            else tk.LabelFrame(self, text="Validation Checks")
        )
        frame.pack(fill="x", padx=16, pady=(0, 10))

        if _HAS_CTK:
            ctk.CTkLabel(
                frame, text="Validation Checks", font=("Helvetica", 13, "bold")
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4))

        for i, check_id in enumerate(ALL_CHECK_IDS):
            var = tk.BooleanVar(value=True)
            self._check_vars[check_id] = var
            row = (i // 2) + 1
            col_idx = i % 2
            label = _CHECK_LABELS.get(check_id, check_id)
            if _HAS_CTK:
                ctk.CTkCheckBox(
                    frame, text=label, variable=var, font=("Helvetica", 11)
                ).grid(row=row, column=col_idx, sticky="w", padx=16, pady=3)
            else:
                tk.Checkbutton(frame, text=label, variable=var).grid(
                    row=row, column=col_idx, sticky="w", padx=8, pady=2
                )

    def _build_bottom_bar(self):
        """Back and Run Validation navigation buttons."""
        btm = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        btm.pack(fill="x", padx=16, pady=(4, 16))

        if _HAS_CTK:
            ctk.CTkButton(
                btm, text="← Back", command=self.app.show_search, width=100
            ).pack(side="left")
            ctk.CTkButton(
                btm, text="Run Validation →", command=self._on_run, width=180,
                fg_color=theme.STATUS_PASS, hover_color=theme.STATUS_PASS_HVR,
            ).pack(side="right")
        else:
            tk.Button(btm, text="← Back", command=self.app.show_search).pack(
                side="left"
            )
            tk.Button(btm, text="Run Validation →", command=self._on_run).pack(
                side="right"
            )

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_slider(self, value):
        self._sample_label_var.set(str(int(float(value))))

    def _on_run(self):
        enabled = {cid for cid, var in self._check_vars.items() if var.get()}
        start = self._start_var.get().strip() or None
        end = self._end_var.get().strip() or None
        temporal = (start, end) if start or end else None
        self.app.show_results({
            "sample_size": int(self._sample_var.get()),
            "temporal": temporal,
            "enabled_checks": enabled,
        })

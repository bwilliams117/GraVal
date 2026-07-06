import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from validator.runner import ALL_CHECK_IDS, CHECKS


class ConfigScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
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

        # ── header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        hdr.pack(fill="x", padx=16, pady=(16, 4))

        title_text = f"Configure Validation — {short_name} v{version}"
        if _HAS_CTK:
            ctk.CTkLabel(hdr, text=title_text, font=("Helvetica", 18, "bold")).pack(side="left")
        else:
            tk.Label(hdr, text=title_text, font=("Helvetica", 14, "bold")).pack(side="left")

        # concept id sub-label
        cid = col.get("meta", {}).get("concept-id", "") if col else ""
        sub = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        sub.pack(fill="x", padx=16, pady=(0, 12))
        if _HAS_CTK:
            ctk.CTkLabel(sub, text=f"Concept ID: {cid}", font=("Helvetica", 10), text_color="#aaaaaa").pack(side="left")
        else:
            tk.Label(sub, text=f"Concept ID: {cid}", font=("Helvetica", 9)).pack(side="left")

        # ── sample size ───────────────────────────────────────────────────────
        sample_frame = ctk.CTkFrame(self) if _HAS_CTK else tk.LabelFrame(self, text="Sample Size")
        sample_frame.pack(fill="x", padx=16, pady=(0, 10))

        if _HAS_CTK:
            ctk.CTkLabel(sample_frame, text="Sample Size  (granules to check):", font=("Helvetica", 12)).pack(side="left", padx=(12, 8), pady=10)
        else:
            tk.Label(sample_frame, text="Sample Size:").pack(side="left", padx=8)

        self._sample_var = tk.IntVar(value=5)
        self._sample_label_var = tk.StringVar(value="5")

        if _HAS_CTK:
            slider = ctk.CTkSlider(
                sample_frame, from_=1, to=50, number_of_steps=49,
                variable=self._sample_var, command=self._on_slider,
                width=220,
            )
            slider.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(sample_frame, textvariable=self._sample_label_var, width=28, font=("Helvetica", 12, "bold")).pack(side="left")
        else:
            slider = tk.Scale(sample_frame, from_=1, to=50, orient="horizontal", variable=self._sample_var,
                              command=lambda v: self._sample_label_var.set(str(int(float(v)))), length=200)
            slider.pack(side="left", padx=8)
            tk.Label(sample_frame, textvariable=self._sample_label_var).pack(side="left")

        # ── date range (optional) ─────────────────────────────────────────────
        date_frame = ctk.CTkFrame(self) if _HAS_CTK else tk.LabelFrame(self, text="Date Range (optional)")
        date_frame.pack(fill="x", padx=16, pady=(0, 10))

        if _HAS_CTK:
            ctk.CTkLabel(date_frame, text="Date Range  (optional, YYYY-MM-DD):", font=("Helvetica", 12)).pack(side="left", padx=(12, 8), pady=10)
        else:
            tk.Label(date_frame, text="Date Range:").pack(side="left", padx=8)

        self._start_var = tk.StringVar()
        self._end_var = tk.StringVar()
        if _HAS_CTK:
            ctk.CTkEntry(date_frame, textvariable=self._start_var, placeholder_text="Start (YYYY-MM-DD)", width=160).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(date_frame, text="to", font=("Helvetica", 11)).pack(side="left", padx=4)
            ctk.CTkEntry(date_frame, textvariable=self._end_var, placeholder_text="End (YYYY-MM-DD)", width=160).pack(side="left", padx=(6, 0))
        else:
            tk.Entry(date_frame, textvariable=self._start_var, width=18).pack(side="left", padx=4)
            tk.Label(date_frame, text="to").pack(side="left")
            tk.Entry(date_frame, textvariable=self._end_var, width=18).pack(side="left", padx=4)

        # ── check toggles ─────────────────────────────────────────────────────
        checks_outer = ctk.CTkFrame(self) if _HAS_CTK else tk.LabelFrame(self, text="Validation Checks")
        checks_outer.pack(fill="x", padx=16, pady=(0, 10))

        if _HAS_CTK:
            ctk.CTkLabel(checks_outer, text="Validation Checks", font=("Helvetica", 13, "bold")).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4))

        check_labels = {
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

        for i, check_id in enumerate(ALL_CHECK_IDS):
            var = tk.BooleanVar(value=True)
            self._check_vars[check_id] = var
            row = (i // 2) + 1
            col_idx = i % 2
            label = check_labels.get(check_id, check_id)
            if _HAS_CTK:
                cb = ctk.CTkCheckBox(checks_outer, text=label, variable=var, font=("Helvetica", 11))
                cb.grid(row=row, column=col_idx, sticky="w", padx=16, pady=3)
            else:
                cb = tk.Checkbutton(checks_outer, text=label, variable=var)
                cb.grid(row=row, column=col_idx, sticky="w", padx=8, pady=2)

        # ── bottom buttons ────────────────────────────────────────────────────
        btm = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        btm.pack(fill="x", padx=16, pady=(4, 16))

        if _HAS_CTK:
            ctk.CTkButton(btm, text="← Back", command=self.app.show_search, width=100).pack(side="left")
            ctk.CTkButton(btm, text="Run Validation →", command=self._on_run, width=180, fg_color="#2d9e5e", hover_color="#25854f").pack(side="right")
        else:
            tk.Button(btm, text="← Back", command=self.app.show_search).pack(side="left")
            tk.Button(btm, text="Run Validation →", command=self._on_run).pack(side="right")

    def _on_slider(self, value):
        self._sample_label_var.set(str(int(float(value))))

    def _on_run(self):
        enabled = {cid for cid, var in self._check_vars.items() if var.get()}
        start = self._start_var.get().strip() or None
        end = self._end_var.get().strip() or None
        temporal = (start, end) if start or end else None

        config = {
            "sample_size": int(self._sample_var.get()),
            "temporal": temporal,
            "enabled_checks": enabled,
        }
        self.app.show_results(config)

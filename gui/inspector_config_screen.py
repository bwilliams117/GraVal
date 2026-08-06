"""Inspector config screen: file-format selection, check toggles, and run controls."""

import tkinter as tk
from pathlib import Path

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

try:
    import h5py as _h5py  # noqa: F401
    _HAS_H5PY = True
except ImportError:
    _HAS_H5PY = False

try:
    import rasterio as _rasterio  # noqa: F401
    _HAS_RASTERIO = True
except ImportError:
    _HAS_RASTERIO = False

try:
    import netCDF4 as _netCDF4  # noqa: F401
    _HAS_NETCDF4 = True
except ImportError:
    _HAS_NETCDF4 = False

try:
    import pyhdf as _pyhdf  # noqa: F401
    _HAS_PYHDF = True
except ImportError:
    _HAS_PYHDF = False

from . import theme

_FILE_FORMATS = ["AUTO", "HDF5", "COG", "HDF4", "NetCDF"]

# (check_id, label, available, install_hint)
_METADATA_CHECKS = [
    ("schema",     "Schema Completeness",          True,  ""),
    ("temporal",   "Temporal Validity",             True,  ""),
    ("spatial",    "Spatial Validity",              True,  ""),
    ("daynight",   "Day/Night Consistency",         True,  ""),
    ("url_health", "URL Health",                    True,  ""),
    ("prod_date",  "Production Date Sanity",        True,  ""),
    ("collection", "Collection Reference",          True,  ""),
    ("duplicates", "Duplicate Detection",           True,  ""),
]

_FILE_CHECKS = [
    ("hdf5_sm",        "HDF5 Standard Metadata",
     _HAS_H5PY,      "pip install h5py"),
    ("cog_compliance", "COG Compliance (tile/ovr/CRS/NoData)",
     _HAS_RASTERIO, "pip install rasterio"),
    ("hdf4_core",      "HDF4 Core Metadata",
     _HAS_PYHDF,     "pip install pyhdf"),
    ("netcdf_struct",  "NetCDF Structure",
     _HAS_NETCDF4,   "pip install netCDF4"),
    ("file_size",      "File Size Accuracy",            True,  ""),
    ("prod_readiness", "PROD Readiness (UAT string scan)", True, ""),
    ("coll_xref",
     "Collection Cross-Check (platforms/instruments/format)", True, ""),
]


def _download_root() -> Path:
    return Path.home() / "Documents" / "GraVal" / "downloads"


class InspectorConfigScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    """Configuration form for the Granule Inspector tool."""

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
        env = getattr(self.app, "env", "UAT")

        # ── header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        hdr.pack(fill="x", padx=16, pady=(16, 2))

        title_text = f"Configure Inspection — {short_name} v{version}  [{env}]"
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
            tk.Label(sub, text=f"Concept ID: {cid}",
                     font=theme.FONT_CAPTION).pack(side="left")

        # ── single card ───────────────────────────────────────────────────────
        if _HAS_CTK:
            self._card = ctk.CTkFrame(
                self, fg_color=theme.SURFACE_1, corner_radius=12
            )
        else:
            self._card = tk.Frame(self, bg=theme.SURFACE_1)
        self._card.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._build_format_section()
        self._build_granules_section()
        self._build_checks_section()
        self._build_download_section()
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

    def _build_format_section(self):
        self._section_heading("FILE FORMAT")

        row = (
            ctk.CTkFrame(self._card, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self._card, bg=theme.SURFACE_1)
        )
        row.pack(fill="x", padx=20, pady=(0, 4))

        self._format_var = tk.StringVar(value="AUTO")

        if _HAS_CTK:
            ctk.CTkOptionMenu(
                row, variable=self._format_var, values=_FILE_FORMATS, width=120,
            ).pack(side="left", padx=(0, 12))
            ctk.CTkLabel(
                row, text="AUTO works for most LP DAAC products.",
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            ).pack(side="left")
        else:
            tk.OptionMenu(row, self._format_var, *_FILE_FORMATS).pack(
                side="left", padx=(0, 8)
            )

        self._divider()

    def _build_granules_section(self):
        self._section_heading("GRANULES")

        row = (
            ctk.CTkFrame(self._card, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self._card, bg=theme.SURFACE_1)
        )
        row.pack(fill="x", padx=20, pady=(0, 4))

        self._max_granules_var = tk.IntVar(value=1)
        self._max_granules_label_var = tk.StringVar(value="1")

        if _HAS_CTK:
            ctk.CTkSlider(
                row, from_=1, to=3, number_of_steps=2,
                variable=self._max_granules_var,
                command=self._on_granules_slider, width=140,
            ).pack(side="left", padx=(0, 12))
            ctk.CTkLabel(
                row, textvariable=self._max_granules_label_var,
                width=28, font=theme.FONT_BODY_BOLD,
            ).pack(side="left")
            ctk.CTkLabel(
                row, text="files to download and inspect",
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            ).pack(side="left", padx=(6, 0))
        else:
            tk.Scale(
                row, from_=1, to=3, orient="horizontal",
                variable=self._max_granules_var,
                command=lambda v: self._max_granules_label_var.set(
                    str(int(float(v)))
                ),
                length=140,
            ).pack(side="left", padx=(0, 8))
            tk.Label(row, textvariable=self._max_granules_label_var,
                     bg=theme.SURFACE_1).pack(side="left")

        self._divider()

    def _build_checks_section(self):
        env = getattr(self.app, "env", "OPS")
        self._section_heading("CHECKS")

        cols_frame = (
            ctk.CTkFrame(self._card, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self._card, bg=theme.SURFACE_1)
        )
        cols_frame.pack(fill="x", padx=20, pady=(0, 4))
        cols_frame.grid_columnconfigure(0, weight=1)
        cols_frame.grid_columnconfigure(1, weight=1)

        # ── UMM Metadata group (left) ──────────────────────────────────────────
        meta_group = (
            ctk.CTkFrame(cols_frame, fg_color=theme.SURFACE_2)
            if _HAS_CTK
            else tk.LabelFrame(cols_frame, text="UMM Metadata")
        )
        meta_group.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        if _HAS_CTK:
            ctk.CTkLabel(
                meta_group, text="UMM Metadata", font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
            ).pack(anchor="w", padx=10, pady=(8, 4))

        for check_id, label, available, _ in _METADATA_CHECKS:
            var = tk.BooleanVar(value=True)
            self._check_vars[check_id] = var
            state = "normal" if available else "disabled"
            if _HAS_CTK:
                ctk.CTkCheckBox(
                    meta_group, text=label, variable=var,
                    font=theme.FONT_SMALL, state=state,
                ).pack(anchor="w", padx=10, pady=3)
            else:
                tk.Checkbutton(
                    meta_group, text=label, variable=var, state=state
                ).pack(anchor="w", padx=8, pady=2)

        # ── File-Level group (right) ───────────────────────────────────────────
        file_group = (
            ctk.CTkFrame(cols_frame, fg_color=theme.SURFACE_2)
            if _HAS_CTK
            else tk.LabelFrame(cols_frame, text="File-Level")
        )
        file_group.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        if _HAS_CTK:
            ctk.CTkLabel(
                file_group, text="File-Level", font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
            ).pack(anchor="w", padx=10, pady=(8, 4))

        for check_id, label, available, hint in _FILE_CHECKS:
            # PROD Readiness only applies when inspecting UAT granules — the
            # check scans for UAT endpoint strings that must be absent in OPS.
            if check_id == "prod_readiness" and env == "OPS":
                available = False
                hint = "UAT sessions only — not applicable in OPS"

            var = tk.BooleanVar(value=available)
            self._check_vars[check_id] = var
            state = "normal" if available else "disabled"
            display = label if available else f"{label}  ⚠"
            if _HAS_CTK:
                ctk.CTkCheckBox(
                    file_group, text=display, variable=var,
                    font=theme.FONT_SMALL, state=state,
                ).pack(anchor="w", padx=10, pady=3)
                if not available and hint:
                    ctk.CTkLabel(
                        file_group,
                        text=f"  {hint}",
                        font=theme.FONT_CAPTION, text_color=theme.TEXT_DISABLED,
                    ).pack(anchor="w", padx=22, pady=(0, 2))
            else:
                tk.Checkbutton(
                    file_group, text=display, variable=var, state=state
                ).pack(anchor="w", padx=8, pady=2)

        self._divider()

    def _build_download_section(self):
        """Read-only display of the managed download path for this run."""
        col = self.app.selected_collection
        umm = col.get("umm", {}) if col else {}
        short_name = umm.get("ShortName", "unknown")
        version = umm.get("Version", "?")
        env = getattr(self.app, "env", "UAT")
        cid = col.get("meta", {}).get("concept-id", "unknown") if col else "unknown"

        dl_path = _download_root() / env / f"{short_name}_v{version}" / cid

        self._section_heading("DOWNLOAD LOCATION")

        if _HAS_CTK:
            ctk.CTkLabel(
                self._card, text=str(dl_path),
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
            ).pack(anchor="w", padx=20, pady=(0, 16))
        else:
            tk.Label(
                self._card, text=str(dl_path),
                font=theme.FONT_CAPTION, fg=theme.TEXT_MUTED,
                bg=theme.SURFACE_1, anchor="w",
            ).pack(anchor="w", padx=20, pady=(0, 16))

    # ── bottom bar ────────────────────────────────────────────────────────────

    def _build_bottom_bar(self):
        btm = (
            ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK
            else tk.Frame(self)
        )
        btm.pack(fill="x", padx=16, pady=(0, 16))

        if _HAS_CTK:
            ctk.CTkButton(
                btm, text="Back to Search",
                command=self.app.show_inspector_search, width=140,
            ).pack(side="left")
            ctk.CTkButton(
                btm, text="Home", command=self.app.show_home, width=80,
                fg_color=theme.SURFACE_2, hover_color=theme.BORDER_STRONG,
                text_color=theme.TEXT_MUTED,
            ).pack(side="left", padx=(8, 0))
            ctk.CTkButton(
                btm, text="Run Inspection", command=self._on_run, width=200,
                fg_color=theme.STATUS_PASS, hover_color=theme.STATUS_PASS_HVR,
            ).pack(side="right")
        else:
            tk.Button(
                btm, text="Back to Search",
                command=self.app.show_inspector_search,
            ).pack(side="left")
            tk.Button(btm, text="Home", command=self.app.show_home).pack(
                side="left", padx=(6, 0)
            )
            tk.Button(btm, text="Run Inspection",
                      command=self._on_run).pack(side="right")

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_granules_slider(self, value):
        self._max_granules_label_var.set(str(int(float(value))))

    def _on_run(self):
        enabled_metadata = {
            cid for cid in [c[0] for c in _METADATA_CHECKS]
            if self._check_vars.get(cid, tk.BooleanVar(value=False)).get()
        }
        enabled_file = {
            cid for cid in [c[0] for c in _FILE_CHECKS]
            if self._check_vars.get(cid, tk.BooleanVar(value=False)).get()
        }

        col = self.app.selected_collection
        umm = col.get("umm", {}) if col else {}
        short_name = umm.get("ShortName", "")
        version = umm.get("Version", "")
        cid = col.get("meta", {}).get("concept-id", "") if col else ""
        env = getattr(self.app, "env", "UAT")

        check_config = {
            "short_name": short_name,
            "version": version,
            "concept_id": cid,
            "env": env,
            "uat_token": getattr(self.app, "uat_token", None),
            "file_format": self._format_var.get(),
            "max_granules": int(self._max_granules_var.get()),
            "enabled_metadata_checks": enabled_metadata,
            "enabled_file_checks": enabled_file,
        }
        self.app.show_inspector_results(check_config)

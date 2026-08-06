"""Inspector results screen: per-granule download progress, then a split-pane report."""

import io
import json
import os
import platform
import queue
import subprocess
import threading
import tkinter as tk
import tkinter.ttk as ttk
import webbrowser
from pathlib import Path
from tkinter import filedialog

import requests
import urllib3
from PIL import Image, ImageTk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme
from validator.checks import Status
from validator.report import default_report_path, export_csv
from validator.deep_runner import DeepValidationRun, DeepValidationRunner

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_STATUS_COLORS = {
    "PASS": theme.STATUS_PASS,
    "WARN": theme.STATUS_WARN,
    "FAIL": theme.STATUS_FAIL,
}

_STATUS_SYMBOLS = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}

_ROW_STATUS_LABELS = {
    "waiting":     "Waiting",
    "starting":    "Starting...",
    "downloading": "Downloading",
    "inspecting":  "Inspecting...",
    "done":        "Done",
    "failed":      "Failed",
}

_STATE_DOT_COLORS = {
    "waiting":     theme.TEXT_DISABLED,
    "starting":    theme.ACCENT,
    "downloading": theme.ACCENT,
    "inspecting":  theme.ACCENT,
    "done":        theme.STATUS_PASS,
    "failed":      theme.STATUS_FAIL,
}


def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


class InspectorResultsScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    """Downloads granules and runs checks; shows live progress then a report."""

    def __init__(self, parent, app, check_config: dict):
        super().__init__(parent)
        self.app = app
        self._check_config = check_config
        self._runner = DeepValidationRunner()
        self._run: DeepValidationRun | None = None
        self._thumb_cache: dict[str, Image.Image] = {}
        self._thumb_photo = None
        self._granule_rows: list[dict] = []    # per-row widget references
        self._build_progress_view()
        self._start_inspection()

    # ── progress phase ────────────────────────────────────────────────────────

    def _build_progress_view(self):
        cfg = self._check_config
        col = self.app.selected_collection
        short_name = col.get("umm", {}).get("ShortName", "?") if col else "?"
        max_granules = cfg.get("max_granules", 1)

        self._progress_frame = (
            ctk.CTkFrame(self, fg_color=theme.SURFACE_1, corner_radius=12)
            if _HAS_CTK else tk.Frame(self, bg=theme.SURFACE_1)
        )
        self._progress_frame.place(relx=0.5, rely=0.5, anchor="center")

        inner = (
            ctk.CTkFrame(self._progress_frame, fg_color="transparent")
            if _HAS_CTK else tk.Frame(self._progress_frame, bg=theme.SURFACE_1)
        )
        inner.pack(padx=40, pady=28)

        if _HAS_CTK:
            ctk.CTkLabel(
                inner,
                text=f"Inspecting: {short_name}",
                font=theme.FONT_H3,
            ).pack(pady=(0, 4))
            ctk.CTkLabel(
                inner,
                text="Downloading and inspecting granules…",
                font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
            ).pack(pady=(0, 16))
        else:
            tk.Label(
                inner,
                text=f"Inspecting: {short_name}",
                font=theme.FONT_H3,
                bg=theme.SURFACE_1, fg=theme.TEXT_PRIMARY,
            ).pack(pady=(0, 4))
            tk.Label(
                inner,
                text="Downloading and inspecting granules…",
                font=("Helvetica", 10),
                bg=theme.SURFACE_1, fg=theme.TEXT_MUTED,
            ).pack(pady=(0, 16))

        # Per-granule rows.
        rows_container = (
            ctk.CTkFrame(inner, fg_color="transparent")
            if _HAS_CTK else tk.Frame(inner, bg=theme.SURFACE_1)
        )
        rows_container.pack(fill="x", padx=4, pady=(0, 12))

        for i in range(max_granules):
            row = self._build_granule_row(rows_container, i)
            self._granule_rows.append(row)

        # Separator above overall progress.
        tk.Frame(inner, height=1, bg=theme.BORDER_SUBTLE).pack(
            fill="x", pady=(0, 12)
        )

        # Overall progress bar.
        if _HAS_CTK:
            self._overall_bar = ctk.CTkProgressBar(inner, width=480)
            self._overall_bar.set(0)
            self._overall_bar.pack(pady=(0, 6))
            self._overall_label = ctk.CTkLabel(
                inner,
                text="0 / 0 granules complete",
                font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
            )
            self._overall_label.pack(pady=(0, 16))
            self._cancel_btn = ctk.CTkButton(
                inner, text="Cancel",
                command=self._cancel, width=100,
                fg_color=theme.STATUS_FAIL, hover_color=theme.STATUS_FAIL_HVR,
            )
            self._cancel_btn.pack()
        else:
            self._overall_bar = ttk.Progressbar(
                inner, length=480, mode="determinate"
            )
            self._overall_bar.pack(pady=(0, 6))
            self._overall_label = tk.Label(
                inner, text="0 / 0 granules complete",
                bg=theme.SURFACE_1, fg=theme.TEXT_MUTED,
            )
            self._overall_label.pack(pady=(0, 16))
            self._cancel_btn = tk.Button(
                inner, text="Cancel", command=self._cancel
            )
            self._cancel_btn.pack()

    def _build_granule_row(self, parent, idx: int) -> dict:
        """Build one granule progress row and return widget references."""
        row_frame = (
            ctk.CTkFrame(parent, fg_color=theme.SURFACE_2)
            if _HAS_CTK
            else tk.Frame(parent, bg=theme.SURFACE_2, relief="flat", bd=1)
        )
        row_frame.pack(fill="x", padx=8, pady=4, ipady=4)

        name_var = tk.StringVar(value=f"Granule {idx + 1}")
        bytes_var = tk.StringVar(value="")
        status_var = tk.StringVar(value="Waiting")

        if _HAS_CTK:
            dot_label = ctk.CTkLabel(
                row_frame, text="●",
                font=theme.FONT_CAPTION, text_color=theme.TEXT_DISABLED, width=16,
            )
            dot_label.pack(side="left", padx=(10, 4))

            ctk.CTkLabel(
                row_frame, textvariable=name_var,
                font=theme.FONT_SMALL, width=260, anchor="w",
            ).pack(side="left", padx=(0, 6))

            bar = ctk.CTkProgressBar(row_frame, width=180, height=8)
            bar.set(0)
            bar.pack(side="left", padx=(0, 6))

            ctk.CTkLabel(
                row_frame, textvariable=bytes_var,
                font=theme.FONT_CAPTION, text_color=theme.TEXT_MUTED, width=100,
            ).pack(side="left", padx=(0, 6))

            ctk.CTkLabel(
                row_frame, textvariable=status_var,
                font=theme.FONT_CAPTION, text_color=theme.TEXT_MUTED, width=90,
            ).pack(side="left", padx=(0, 10))
        else:
            dot_label = tk.Label(
                row_frame, text="●",
                bg=theme.SURFACE_2, fg=theme.TEXT_DISABLED,
            )
            dot_label.pack(side="left", padx=(8, 4))

            tk.Label(
                row_frame, textvariable=name_var, width=32, anchor="w",
                bg=theme.SURFACE_2,
            ).pack(side="left", padx=(0, 4))
            bar = ttk.Progressbar(row_frame, length=180, mode="determinate")
            bar.pack(side="left", padx=(0, 4))
            tk.Label(
                row_frame, textvariable=bytes_var, width=14,
                bg=theme.SURFACE_2,
            ).pack(side="left", padx=(0, 4))
            tk.Label(
                row_frame, textvariable=status_var, width=12,
                bg=theme.SURFACE_2,
            ).pack(side="left", padx=(0, 8))

        return {
            "name_var": name_var,
            "bytes_var": bytes_var,
            "status_var": status_var,
            "bar": bar,
            "dot_label": dot_label,
            "_has_ctk": _HAS_CTK,
        }

    def _update_row_progress(
        self, idx: int, granule_ur: str,
        bytes_so_far: int, total_bytes: int, state: str,
    ):
        if idx >= len(self._granule_rows):
            return
        row = self._granule_rows[idx]

        short_ur = granule_ur[:42] + "…" if len(granule_ur) > 42 else granule_ur
        row["name_var"].set(short_ur)
        row["status_var"].set(_ROW_STATUS_LABELS.get(state, state))

        dot_color = _STATE_DOT_COLORS.get(state, theme.TEXT_DISABLED)
        if row["_has_ctk"]:
            row["dot_label"].configure(text_color=dot_color)
        else:
            row["dot_label"].configure(fg=dot_color)

        if state == "downloading" and total_bytes > 0:
            pct = bytes_so_far / total_bytes
            row["bytes_var"].set(f"{_fmt_bytes(bytes_so_far)} / {_fmt_bytes(total_bytes)}")
        elif state == "downloading":
            pct = 0
            row["bytes_var"].set(_fmt_bytes(bytes_so_far))
        elif state == "done":
            pct = 1.0
            row["bytes_var"].set("")
        else:
            pct = 0
            row["bytes_var"].set("")

        if row["_has_ctk"]:
            row["bar"].set(pct)
        else:
            row["bar"]["value"] = pct * 100

    # ── runner lifecycle ──────────────────────────────────────────────────────

    def _start_inspection(self):
        self._runner.run_async(self._check_config)
        self._poll()

    def _poll(self):
        """Drain the runner queue every 100ms until the run completes."""
        q = self._runner.result_queue
        try:
            while True:
                item = q.get_nowait()
                msg_type = item[0]
                payload = item[1] if len(item) > 1 else None

                if msg_type == "progress":
                    current, total, message = payload
                    pct = current / total if total > 0 else 0
                    if _HAS_CTK:
                        self._overall_bar.set(pct)
                    else:
                        self._overall_bar["value"] = pct * 100
                    self._overall_label.configure(
                        text=f"{current} / {total}  — {message}"
                    )

                elif msg_type == "download_progress":
                    idx, granule_ur, bytes_so_far, total_bytes, state = payload
                    self._update_row_progress(
                        idx, granule_ur, bytes_so_far, total_bytes, state
                    )

                elif msg_type == "done":
                    self._on_done(payload)
                    return

                elif msg_type == "error":
                    self._on_error(payload)
                    return

                elif msg_type == "cancelled":
                    self._on_cancelled()
                    return

        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _cancel(self):
        self._runner.cancel()

    def _on_cancelled(self):
        self.app.show_inspector_config()

    def _on_error(self, message: str):
        try:
            parsed = json.loads(message)
            errors = parsed.get("errors") or parsed.get("error")
            if errors:
                message = errors[0] if isinstance(errors, list) else str(errors)
        except Exception:
            pass
        if _HAS_CTK:
            self._overall_label.configure(
                text=f"Error: {message}", text_color=theme.STATUS_FAIL
            )
        else:
            self._overall_label.configure(text=f"Error: {message}")

    # ── results phase ─────────────────────────────────────────────────────────

    def _on_done(self, run: DeepValidationRun):
        self._run = run
        self._progress_frame.place_forget()
        self._build_results_view(run)
        theme.place_env_badge(self, getattr(self.app, "env", "OPS"))

    def _build_results_view(self, run: DeepValidationRun):
        theme.setup_ttk_style()

        summary_frame = (
            ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        )
        summary_frame.pack(fill="x", padx=16, pady=(16, 8))

        if _HAS_CTK:
            ctk.CTkLabel(
                summary_frame,
                text=f"{len(run.granule_reports)} granule(s) inspected",
                font=theme.FONT_H4,
            ).pack(side="left", padx=(8, 16))
            for symbol, count, color in [
                ("✓", run.pass_count, theme.STATUS_PASS),
                ("!", run.warn_count, theme.STATUS_WARN),
                ("✗", run.fail_count, theme.STATUS_FAIL),
            ]:
                ctk.CTkLabel(
                    summary_frame,
                    text=f"  {symbol}  {count}  ",
                    font=theme.FONT_BODY_BOLD,
                    text_color=color,
                    fg_color=theme.SURFACE_2,
                    corner_radius=6,
                ).pack(side="left", padx=(0, 6), ipady=2)
        else:
            tk.Label(
                summary_frame,
                text=f"{len(run.granule_reports)} granule(s) inspected",
                font=("Helvetica", 11, "bold"),
            ).pack(side="left", padx=(0, 16))
            for symbol, count, color in [
                ("✓", run.pass_count, theme.STATUS_PASS),
                ("!", run.warn_count, theme.STATUS_WARN),
                ("✗", run.fail_count, theme.STATUS_FAIL),
            ]:
                tk.Label(
                    summary_frame,
                    text=f"  {symbol}  {count}  ",
                    bg=theme.SURFACE_2, fg=color,
                ).pack(side="left", padx=(0, 6), ipadx=8, ipady=2)

        if run.errors:
            err_text = "Errors: " + "; ".join(run.errors)
            if _HAS_CTK:
                ctk.CTkLabel(
                    summary_frame, text=err_text, font=theme.FONT_SMALL,
                    text_color=theme.STATUS_FAIL,
                ).pack(side="left", padx=16)
            else:
                tk.Label(summary_frame, text=err_text).pack(side="left", padx=8)

        paned = tk.PanedWindow(
            self, orient="horizontal", sashwidth=6,
            bg=theme.SURFACE_0, sashrelief="flat",
        )
        paned.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        left = tk.Frame(paned, bg=theme.SURFACE_0)
        paned.add(left, minsize=300)

        cols = ("status", "granule_ur", "checks")
        self._tree = ttk.Treeview(
            left, columns=cols, show="headings", selectmode="browse"
        )
        self._tree.heading("status", text="")
        self._tree.heading("granule_ur", text="Granule UR")
        self._tree.heading("checks", text="Checks")
        self._tree.column("status", width=44, minwidth=36, stretch=False)
        self._tree.column("granule_ur", width=260, minwidth=100)
        self._tree.column("checks", width=80, minwidth=60, stretch=False)

        self._tree.tag_configure("row_WARN", foreground=theme.STATUS_WARN)
        self._tree.tag_configure("row_FAIL", foreground=theme.STATUS_FAIL)

        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        for report in run.granule_reports:
            total = len(report.checks)
            passed = sum(1 for c in report.checks if c.status == Status.PASS)
            status = report.overall_status.value
            tag = () if status == "PASS" else (f"row_{status}",)
            self._tree.insert("", "end", values=(
                _STATUS_SYMBOLS.get(status, status),
                report.granule_ur,
                f"{passed}/{total}",
            ), tags=tag)

        self._tree.bind("<<TreeviewSelect>>", self._on_granule_select)

        right = tk.Frame(paned, bg=theme.SURFACE_0)
        paned.add(right, minsize=260)

        right_paned = tk.PanedWindow(
            right, orient="vertical", sashwidth=6,
            bg=theme.SURFACE_0, sashrelief="flat",
        )
        right_paned.pack(fill="both", expand=True)

        self._thumb_frame = tk.Frame(right_paned, bg=theme.SURFACE_0)
        right_paned.add(self._thumb_frame, minsize=50)
        self._thumb_label = tk.Label(
            self._thumb_frame,
            text="No browse image available",
            font=("Helvetica", 9),
            fg=theme.THUMB_MISSING,
            bg=theme.SURFACE_0,
            anchor="center",
        )
        self._thumb_label.place(relx=0.5, rely=0.5, anchor="center")

        right_paned.after(
            100,
            lambda: right_paned.sash_place(
                0, 0, int(right_paned.winfo_height() * 0.35)
            ),
        )

        text_frame = tk.Frame(right_paned, bg=theme.SURFACE_0)
        right_paned.add(text_frame, minsize=100)

        if _HAS_CTK:
            self._detail_text = ctk.CTkTextbox(
                text_frame, font=theme.FONT_SMALL, wrap="word"
            )
            self._detail_text.pack(fill="both", expand=True)
            self._detail_text.insert("end", "Select a granule to see check details.")
            self._detail_text.configure(state="disabled")
        else:
            self._detail_text = tk.Text(
                text_frame, font=theme.FONT_SMALL, wrap="word", state="disabled"
            )
            vsb2 = ttk.Scrollbar(
                text_frame, orient="vertical", command=self._detail_text.yview
            )
            self._detail_text.configure(yscrollcommand=vsb2.set)
            self._detail_text.pack(side="left", fill="both", expand=True)
            vsb2.pack(side="right", fill="y")

        tk.Frame(self, height=1, bg=theme.BORDER_SUBTLE).pack(fill="x", padx=16)

        btm = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        btm.pack(fill="x", padx=16, pady=(0, 16))

        if _HAS_CTK:
            ctk.CTkButton(
                btm, text="← New Inspection",
                command=self.app.show_inspector_config, width=160,
            ).pack(side="left")
            ctk.CTkButton(
                btm, text="Export CSV",
                command=self._export_csv, width=120,
            ).pack(side="right")
        else:
            tk.Button(
                btm, text="← New Inspection",
                command=self.app.show_inspector_config,
            ).pack(side="left")
            tk.Button(btm, text="Export CSV", command=self._export_csv).pack(
                side="right"
            )

        children = self._tree.get_children()
        if children:
            self._tree.selection_set(children[0])
            self._tree.focus(children[0])
            self._show_detail(self._run.granule_reports[0])

    # ── detail panel ──────────────────────────────────────────────────────────

    def _on_granule_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._tree.index(sel[0])
        if self._run and idx < len(self._run.granule_reports):
            self._show_detail(self._run.granule_reports[idx])

    def _load_thumbnail(self, report):
        self._thumb_label.configure(image="", text="Loading preview...")
        self._thumb_photo = None

        if not report.browse_url:
            self._thumb_label.configure(text="No browse image available")
            return

        if report.browse_url in self._thumb_cache:
            self._render_thumbnail(self._thumb_cache[report.browse_url])
            return

        def _fetch():
            try:
                try:
                    resp = requests.get(report.browse_url, timeout=15, stream=True)
                except requests.exceptions.SSLError:
                    resp = requests.get(
                        report.browse_url, timeout=15, stream=True, verify=False
                    )
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content))
                img.load()
                self._thumb_cache[report.browse_url] = img
                self.after(0, lambda: self._render_thumbnail(img))
            except Exception:
                self.after(
                    0,
                    lambda: self._thumb_label.configure(image="", text="Preview unavailable"),
                )

        threading.Thread(target=_fetch, daemon=True).start()

    def _render_thumbnail(self, img: Image.Image):
        frame_w = self._thumb_frame.winfo_width() or img.width
        frame_h = self._thumb_frame.winfo_height() or img.height
        display = img.copy()
        display.thumbnail((frame_w, frame_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(display)
        self._thumb_photo = photo
        self._thumb_label.configure(image=photo, text="")

    def _show_detail(self, report):
        """Populate the text pane with check results for the selected granule."""
        self._load_thumbnail(report)

        if _HAS_CTK:
            self._detail_text.configure(state="normal")
            self._detail_text.delete("1.0", "end")
            textbox = self._detail_text._textbox
        else:
            self._detail_text.configure(state="normal")
            self._detail_text.delete("1.0", "end")
            textbox = self._detail_text

        textbox.tag_configure("header_label", foreground=theme.TEXT_MUTED)
        textbox.tag_configure("header_value", foreground=theme.TEXT_PRIMARY)
        textbox.tag_configure("divider", foreground=theme.TEXT_DISABLED)
        textbox.tag_configure("link", foreground=theme.LINK, underline=True)
        textbox.tag_configure("link_hover", foreground=theme.LINK_HOVER, underline=True)

        textbox.insert("end", "Granule: ", "header_label")
        textbox.insert("end", f"{report.granule_ur}\n", "header_value")
        textbox.insert("end", "Concept ID: ", "header_label")
        textbox.insert("end", f"{report.concept_id}\n", "header_value")

        # Earthdata Search link (OPS only; concept IDs differ in UAT).
        env = self._check_config.get("env", "OPS")
        if env == "OPS":
            eds_url = (
                f"https://search.earthdata.nasa.gov/search/granules"
                f"?p={report.concept_id}"
            )
            textbox.insert("end", "View in Earthdata Search", "link")
            textbox.insert("end", "\n")
            textbox.tag_bind(
                "link", "<Button-1>",
                lambda _e, u=eds_url: webbrowser.open(u),
            )
            textbox.tag_bind("link", "<Enter>", lambda _e: [
                textbox.tag_configure("link", foreground=theme.LINK_HOVER),
                textbox.config(cursor="hand2"),
            ])
            textbox.tag_bind("link", "<Leave>", lambda _e: [
                textbox.tag_configure("link", foreground=theme.LINK),
                textbox.config(cursor=""),
            ])

        # Local download folder link.
        if report.local_folder and report.local_folder.exists():
            folder_path = str(report.local_folder)
            tag = "folder_link"
            textbox.tag_configure(tag, foreground=theme.LINK, underline=True)
            textbox.insert("end", "Open download folder", tag)
            textbox.insert("end", f"\n  {folder_path}\n")
            textbox.tag_bind(
                tag, "<Button-1>",
                lambda _e, p=report.local_folder: self._open_folder(p),
            )
            textbox.tag_bind(tag, "<Enter>", lambda _e: [
                textbox.tag_configure(tag, foreground=theme.LINK_HOVER),
                textbox.config(cursor="hand2"),
            ])
            textbox.tag_bind(tag, "<Leave>", lambda _e: [
                textbox.tag_configure(tag, foreground=theme.LINK),
                textbox.config(cursor=""),
            ])

        textbox.insert(
            "end",
            "  ──────────"
            "──────────"
            "────\n\n",
            "divider",
        )

        for status, color in _STATUS_COLORS.items():
            textbox.tag_configure(f"status_{status}", foreground=color)

        _uid = [0]

        def _make_toggle(tb, tag_closed, tag_open, tag_items):
            is_open = [False]

            def _toggle(_e):
                tb.configure(state="normal")
                if is_open[0]:
                    tb.tag_configure(tag_items, elide=True)
                    tb.tag_configure(tag_closed, elide=False)
                    tb.tag_configure(tag_open, elide=True)
                    is_open[0] = False
                else:
                    tb.tag_configure(tag_items, elide=False)
                    tb.tag_configure(tag_closed, elide=True)
                    tb.tag_configure(tag_open, elide=False)
                    is_open[0] = True
                tb.configure(state="disabled")

            return _toggle

        for check in report.checks:
            symbol = {
                "PASS": "✓", "WARN": "!", "FAIL": "✗"
            }.get(check.status.value, "?")
            status_tag = f"status_{check.status.value}"
            textbox.insert("end", f"[{check.status.value}] {symbol} ", status_tag)
            textbox.insert("end", f"{check.check_name}\n")
            textbox.insert("end", f"       {check.message}\n")

            if check.details:
                for k, v in check.details.items():
                    if isinstance(v, list):
                        _uid[0] += 1
                        uid = _uid[0]
                        tc = f"tc_{uid}"
                        to = f"to_{uid}"
                        th = f"th_{uid}"
                        ti = f"ti_{uid}"

                        textbox.tag_configure(tc, foreground=theme.LINK)
                        textbox.tag_configure(to, foreground=theme.LINK, elide=True)
                        textbox.tag_configure(th, foreground=theme.LINK)
                        textbox.tag_configure(ti, elide=True)

                        textbox.insert("end", "       ")
                        textbox.insert("end", "▶", tc)
                        textbox.insert("end", "▼", to)
                        textbox.insert("end", f" {k}: ({len(v)})\n", th)
                        textbox.insert(
                            "end",
                            "".join(f"           {item}\n" for item in v),
                            ti,
                        )

                        toggle_fn = _make_toggle(textbox, tc, to, ti)
                        for t in (tc, to, th):
                            textbox.tag_bind(t, "<Button-1>", toggle_fn)
                            textbox.tag_bind(
                                t, "<Enter>",
                                lambda _e: textbox.config(cursor="hand2"),
                            )
                            textbox.tag_bind(
                                t, "<Leave>",
                                lambda _e: textbox.config(cursor=""),
                            )
                    else:
                        textbox.insert("end", f"       {k}: {v}\n")

            textbox.insert("end", "\n")

        self._detail_text.configure(state="disabled")

    def _open_folder(self, path: Path):
        """Open *path* in the OS file manager."""
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", str(path)])
            elif system == "Windows":
                os.startfile(str(path))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    # ── export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._run:
            return
        col = self.app.selected_collection
        short_name = (
            col.get("umm", {}).get("ShortName", "unknown") if col else "unknown"
        )
        default_path = default_report_path(short_name, self._run)
        path_str = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_path.name,
            initialdir=str(default_path.parent),
        )
        if path_str:
            export_csv(self._run, Path(path_str))

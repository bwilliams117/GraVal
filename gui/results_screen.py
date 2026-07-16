import io
import json
import queue
import threading
import tkinter as tk
import tkinter.ttk as ttk
import webbrowser
from pathlib import Path
from tkinter import filedialog

import urllib3
import earthaccess
import requests
from PIL import Image, ImageTk

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme
from validator.runner import ValidationRunner, ValidationRun
from validator.checks import Status
from validator.report import export_csv, default_report_path

_STATUS_COLORS = {
    "PASS": theme.STATUS_PASS,
    "WARN": theme.STATUS_WARN,
    "FAIL": theme.STATUS_FAIL,
}


class ResultsScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    def __init__(self, parent, app, config: dict):
        super().__init__(parent)
        self.app = app
        self._config = config
        self._runner = ValidationRunner()
        self._run: ValidationRun | None = None
        self._build_running_view()
        self._start_validation()

    # ── running phase ─────────────────────────────────────────────────────────

    def _build_running_view(self):
        self._running_frame = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        self._running_frame.place(relx=0.5, rely=0.5, anchor="center")

        col = self.app.selected_collection
        short_name = col.get("umm", {}).get("ShortName", "?") if col else "?"

        if _HAS_CTK:
            ctk.CTkLabel(self._running_frame, text=f"Validating: {short_name}", font=("Helvetica", 18, "bold")).pack(pady=(0, 16))
            self._progress_bar = ctk.CTkProgressBar(self._running_frame, width=420)
            self._progress_bar.set(0)
            self._progress_bar.pack(pady=(0, 8))
            self._progress_label = ctk.CTkLabel(self._running_frame, text="Starting...", font=("Helvetica", 11))
            self._progress_label.pack(pady=(0, 16))
            ctk.CTkButton(self._running_frame, text="Cancel", command=self._cancel, width=100, fg_color=theme.STATUS_FAIL, hover_color=theme.STATUS_FAIL_HVR).pack()
        else:
            tk.Label(self._running_frame, text=f"Validating: {short_name}", font=("Helvetica", 14, "bold")).pack(pady=(0, 16))
            self._progress_bar = ttk.Progressbar(self._running_frame, length=420, mode="determinate")
            self._progress_bar.pack(pady=(0, 8))
            self._progress_label = tk.Label(self._running_frame, text="Starting...")
            self._progress_label.pack(pady=(0, 16))
            tk.Button(self._running_frame, text="Cancel", command=self._cancel).pack()

    def _start_validation(self):
        col = self.app.selected_collection
        umm = col.get("umm", {}) if col else {}
        short_name = umm.get("ShortName", "")
        entry_title = umm.get("EntryTitle", "")
        self._runner.run_async(
            short_name=short_name,
            sample_size=self._config["sample_size"],
            temporal=self._config.get("temporal"),
            enabled_checks=self._config["enabled_checks"],
            entry_title=entry_title,
        )
        self._poll()

    def _poll(self):
        q = self._runner.result_queue
        try:
            while True:
                msg_type, payload = q.get_nowait()
                if msg_type == "progress":
                    current, total, message = payload
                    pct = current / total if total > 0 else 0
                    if _HAS_CTK:
                        self._progress_bar.set(pct)
                        self._progress_label.configure(text=f"{message}  ({current}/{total})")
                    else:
                        self._progress_bar["value"] = pct * 100
                        self._progress_label.configure(text=f"{message}  ({current}/{total})")
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
        # Navigate back immediately — don't wait for the worker to ack
        self.app.show_config()

    def _on_cancelled(self):
        self.app.show_config()

    def _on_error(self, message: str):
        # earthaccess sometimes surfaces raw CMR JSON error bodies — unwrap them
        try:
            parsed = json.loads(message)
            errors = parsed.get("errors") or parsed.get("error")
            if errors:
                message = errors[0] if isinstance(errors, list) else str(errors)
        except Exception:
            pass
        if _HAS_CTK:
            self._progress_label.configure(text=f"Error: {message}", text_color=theme.STATUS_FAIL)
        else:
            self._progress_label.configure(text=f"Error: {message}")

    # ── results phase ─────────────────────────────────────────────────────────

    def _on_done(self, run: ValidationRun):
        self._run = run
        self.app.last_validation_run = run
        self._running_frame.place_forget()
        self._build_results_view(run)

    def _build_results_view(self, run: ValidationRun):
        theme.setup_ttk_style()
        # summary bar
        summary_frame = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        summary_frame.pack(fill="x", padx=16, pady=(16, 8))

        summary_text = (
            f"{len(run.granule_reports)} granule(s) checked  ·  "
            f"PASS: {run.pass_count}  ·  WARN: {run.warn_count}  ·  FAIL: {run.fail_count}"
        )
        if _HAS_CTK:
            ctk.CTkLabel(summary_frame, text=summary_text, font=("Helvetica", 14, "bold")).pack(side="left", padx=8)
        else:
            tk.Label(summary_frame, text=summary_text, font=("Helvetica", 11, "bold")).pack(side="left")

        # paned view: tree on left, detail on right
        paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bg=theme.SURFACE_0, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # ── left: granule table ───────────────────────────────────────────────
        left = tk.Frame(paned, bg=theme.SURFACE_0)
        paned.add(left, minsize=300)

        cols = ("status", "granule_ur", "checks")
        self._tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("status", text="Status")
        self._tree.heading("granule_ur", text="Granule UR")
        self._tree.heading("checks", text="Checks")
        self._tree.column("status", width=60, minwidth=50, stretch=False)
        self._tree.column("granule_ur", width=260, minwidth=100)
        self._tree.column("checks", width=80, minwidth=60, stretch=False)

        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        for report in run.granule_reports:
            total = len(report.checks)
            passed = sum(1 for c in report.checks if c.status == Status.PASS)
            status_str = report.overall_status.value
            self._tree.insert("", "end", values=(status_str, report.granule_ur, f"{passed}/{total}"))

        self._tree.bind("<<TreeviewSelect>>", self._on_granule_select)

        # ── right: detail panel ───────────────────────────────────────────────
        right = tk.Frame(paned, bg=theme.SURFACE_0)
        paned.add(right, minsize=260)

        right_paned = tk.PanedWindow(right, orient="vertical", sashwidth=6, bg=theme.SURFACE_0, sashrelief="flat")
        right_paned.pack(fill="both", expand=True)

        # Image pane
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
        self._thumb_photo = None  # keep reference to prevent GC
        self._thumb_cache: dict[str, ImageTk.PhotoImage] = {}

        # Give the image pane ~40% of the right panel height after layout settles
        right_paned.after(100, lambda: right_paned.sash_place(0, 0, int(right_paned.winfo_height() * 0.4)))

        # Text pane
        text_frame = tk.Frame(right_paned, bg=theme.SURFACE_0)
        right_paned.add(text_frame, minsize=100)

        if _HAS_CTK:
            self._detail_text = ctk.CTkTextbox(text_frame, font=("Courier", 11), wrap="word")
            self._detail_text.pack(fill="both", expand=True)
            self._detail_text.insert("end", "Select a granule to see check details.")
            self._detail_text.configure(state="disabled")
        else:
            self._detail_text = tk.Text(text_frame, font=("Courier", 10), wrap="word", state="disabled")
            vsb2 = ttk.Scrollbar(text_frame, orient="vertical", command=self._detail_text.yview)
            self._detail_text.configure(yscrollcommand=vsb2.set)
            self._detail_text.pack(side="left", fill="both", expand=True)
            vsb2.pack(side="right", fill="y")

        # ── bottom bar ────────────────────────────────────────────────────────
        btm = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        btm.pack(fill="x", padx=16, pady=(0, 16))

        if _HAS_CTK:
            ctk.CTkButton(btm, text="← New Validation", command=self.app.show_config, width=160).pack(side="left")
            ctk.CTkButton(btm, text="Export CSV", command=self._export_csv, width=120).pack(side="right")
        else:
            tk.Button(btm, text="← New Validation", command=self.app.show_config).pack(side="left")
            tk.Button(btm, text="Export CSV", command=self._export_csv).pack(side="right")

        # Select first row
        children = self._tree.get_children()
        if children:
            self._tree.selection_set(children[0])
            self._tree.focus(children[0])
            self._show_detail(self._run.granule_reports[0])

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

        # Serve from cache immediately if already fetched
        if report.browse_url in self._thumb_cache:
            self._render_thumbnail(self._thumb_cache[report.browse_url])
            return

        def _fetch():
            try:
                session = earthaccess.get_requests_https_session()
                try:
                    resp = session.get(report.browse_url, timeout=15, stream=True)
                except requests.exceptions.SSLError:
                    resp = session.get(report.browse_url, timeout=15, stream=True, verify=False)

                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content))
                img.load()  # fully decode before leaving the thread
                self._thumb_cache[report.browse_url] = img
                self.after(0, lambda: self._render_thumbnail(img))
            except Exception:
                self.after(0, lambda: self._thumb_label.configure(image="", text="Preview unavailable"))

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
        self._load_thumbnail(report)
        url = f"https://search.earthdata.nasa.gov/search/granules?p={report.concept_id}"

        # Resolve the underlying tk.Text widget regardless of CTk vs plain Tk
        if _HAS_CTK:
            self._detail_text.configure(state="normal")
            self._detail_text.delete("1.0", "end")
            textbox = self._detail_text._textbox
        else:
            self._detail_text.configure(state="normal")
            self._detail_text.delete("1.0", "end")
            textbox = self._detail_text

        textbox.tag_configure("link", foreground=theme.LINK, underline=True)
        textbox.tag_configure("link_hover", foreground=theme.LINK_HOVER, underline=True)

        textbox.insert("end", f"Granule: {report.granule_ur}\n")
        textbox.insert("end", f"Concept ID: {report.concept_id}\n")
        textbox.insert("end", "View in Earthdata Search", "link")
        textbox.insert("end", "\n")

        # Wire up click and hover on the link tag
        textbox.tag_bind("link", "<Button-1>", lambda _e, u=url: self._open_url(u))
        textbox.tag_bind("link", "<Enter>", lambda _e: [
            textbox.tag_configure("link", foreground=theme.LINK_HOVER),
            textbox.config(cursor="hand2"),
        ])
        textbox.tag_bind("link", "<Leave>", lambda _e: [
            textbox.tag_configure("link", foreground=theme.LINK),
            textbox.config(cursor=""),
        ])

        textbox.insert("end", "\n")

        for status, color in _STATUS_COLORS.items():
            textbox.tag_configure(f"status_{status}", foreground=color)

        _uid = [0]

        def _make_toggle(tb, tag_closed, tag_open, tag_items):
            is_open = [False]
            def _toggle(_e):
                tb.configure(state="normal")
                if is_open[0]:
                    tb.tag_configure(tag_items,  elide=True)
                    tb.tag_configure(tag_closed, elide=False)
                    tb.tag_configure(tag_open,   elide=True)
                    is_open[0] = False
                else:
                    tb.tag_configure(tag_items,  elide=False)
                    tb.tag_configure(tag_closed, elide=True)
                    tb.tag_configure(tag_open,   elide=False)
                    is_open[0] = True
                tb.configure(state="disabled")
            return _toggle

        for check in report.checks:
            symbol = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}.get(check.status.value, "?")
            status_tag = f"status_{check.status.value}"
            textbox.insert("end", f"[{check.status.value}] {symbol} ", status_tag)
            textbox.insert("end", f"{check.check_name}\n")
            textbox.insert("end", f"       {check.message}\n")
            if check.details:
                for k, v in check.details.items():
                    if isinstance(v, list):
                        _uid[0] += 1
                        uid = _uid[0]
                        tc = f"tc_{uid}"  # closed arrow tag
                        to = f"to_{uid}"  # open arrow tag
                        th = f"th_{uid}"  # header label tag
                        ti = f"ti_{uid}"  # items tag

                        textbox.tag_configure(tc, foreground=theme.LINK)
                        textbox.tag_configure(to, foreground=theme.LINK, elide=True)
                        textbox.tag_configure(th, foreground=theme.LINK)
                        textbox.tag_configure(ti, elide=True)

                        textbox.insert("end", "       ")
                        textbox.insert("end", "▶", tc)
                        textbox.insert("end", "▼", to)
                        textbox.insert("end", f" {k}: ({len(v)})\n", th)
                        textbox.insert("end", "".join(f"           {item}\n" for item in v), ti)

                        toggle_fn = _make_toggle(textbox, tc, to, ti)
                        for t in (tc, to, th):
                            textbox.tag_bind(t, "<Button-1>", toggle_fn)
                            textbox.tag_bind(t, "<Enter>", lambda _e: textbox.config(cursor="hand2"))
                            textbox.tag_bind(t, "<Leave>", lambda _e: textbox.config(cursor=""))
                    else:
                        textbox.insert("end", f"       {k}: {v}\n")
            textbox.insert("end", "\n")

        self._detail_text.configure(state="disabled")

    def _open_url(self, url: str):
        webbrowser.open(url)

    def _export_csv(self):
        if not self._run:
            return
        col = self.app.selected_collection
        short_name = col.get("umm", {}).get("ShortName", "unknown") if col else "unknown"
        default_path = default_report_path(short_name, self._run)
        path_str = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_path.name,
            initialdir=str(default_path.parent),
        )
        if path_str:
            export_csv(self._run, Path(path_str))

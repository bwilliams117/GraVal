import math
import os
import threading
import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme


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

def _Button(parent, text, command, state="normal", **kw):
    if _HAS_CTK:
        return ctk.CTkButton(parent, text=text, command=command, state=state, **kw)
    else:
        return tk.Button(parent, text=text, command=command, state=state, **kw)

def _ProgressBar(parent, mode="indeterminate"):
    if _HAS_CTK:
        return ctk.CTkProgressBar(parent, mode=mode)
    else:
        import tkinter.ttk as ttk
        return ttk.Progressbar(parent, mode=mode)


_ENV_LABEL    = "Use .env file"
_MANUAL_LABEL = "Enter credentials"


class LoginScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._manual = False
        self._build()

    def _build(self):
        # Two-column full-bleed layout
        self.grid_columnconfigure(0, weight=0, minsize=460)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── left: form panel ─────────────────────────────────────────────────
        if _HAS_CTK:
            left = ctk.CTkFrame(self, corner_radius=0, fg_color=theme.SURFACE_1)
        else:
            left = tk.Frame(self, bg=theme.SURFACE_1)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(0, weight=0)   # logo strip
        left.grid_rowconfigure(1, weight=1)   # form area
        left.grid_rowconfigure(2, weight=0)   # footer
        left.grid_columnconfigure(0, weight=1)

        # logo strip
        logo_bar = tk.Frame(left, bg=theme.SURFACE_1)
        logo_bar.grid(row=0, column=0, sticky="w", padx=28, pady=(28, 0))

        badge = tk.Canvas(logo_bar, width=26, height=26,
                          bg=theme.SURFACE_1, highlightthickness=0)
        badge.create_oval(2, 2, 24, 24, fill=theme.ACCENT, outline="")
        badge.create_text(13, 13, text="V", fill="#ffffff",
                          font=("Helvetica", 11, "bold"))
        badge.pack(side="left", padx=(0, 8))

        if _HAS_CTK:
            ctk.CTkLabel(logo_bar, text="Vernier",
                         font=("Helvetica", 14, "bold"),
                         text_color=theme.TEXT_PRIMARY).pack(side="left")
        else:
            tk.Label(logo_bar, text="Vernier",
                     font=("Helvetica", 14, "bold"),
                     bg=theme.SURFACE_1, fg=theme.TEXT_PRIMARY).pack(side="left")

        # form area — centered vertically via place inside a fill frame
        form_outer = tk.Frame(left, bg=theme.SURFACE_1)
        form_outer.grid(row=1, column=0, sticky="nsew")

        container = tk.Frame(form_outer, bg=theme.SURFACE_1)
        container.place(relx=0.5, rely=0.5, anchor="center")

        if _HAS_CTK:
            ctk.CTkLabel(container, text="Sign in to Vernier",
                         font=("Helvetica", 24, "bold"),
                         text_color=theme.TEXT_PRIMARY).pack(pady=(0, 6))
            ctk.CTkLabel(container,
                         text="Precision metadata validation for NASA Earthdata collections",
                         font=("Helvetica", 11),
                         text_color=theme.TEXT_MUTED).pack(pady=(0, 24))
        else:
            tk.Label(container, text="Sign in to Vernier",
                     font=("Helvetica", 20, "bold"),
                     bg=theme.SURFACE_1, fg=theme.TEXT_PRIMARY).pack(pady=(0, 6))
            tk.Label(container,
                     text="Precision metadata validation for NASA Earthdata collections",
                     font=("Helvetica", 10),
                     bg=theme.SURFACE_1, fg=theme.TEXT_MUTED).pack(pady=(0, 20))

        # mode selector
        if _HAS_CTK:
            self._mode_widget = ctk.CTkSegmentedButton(
                container,
                values=[_ENV_LABEL, _MANUAL_LABEL],
                command=self._on_mode_change,
                width=300,
            )
            self._mode_widget.set(_ENV_LABEL)
            self._mode_widget.pack(pady=(0, 12))
        else:
            self._mode_widget = tk.Frame(container, bg=theme.SURFACE_1)
            self._mode_widget.pack(pady=(0, 8))
            self._mode_tk_var = tk.StringVar(value="env")
            tk.Radiobutton(
                self._mode_widget, text=_ENV_LABEL,
                variable=self._mode_tk_var, value="env",
                command=lambda: self._on_mode_change("env"),
                bg=theme.SURFACE_1, fg=theme.TEXT_PRIMARY,
            ).pack(side="left", padx=8)
            tk.Radiobutton(
                self._mode_widget, text=_MANUAL_LABEL,
                variable=self._mode_tk_var, value="manual",
                command=lambda: self._on_mode_change("manual"),
                bg=theme.SURFACE_1, fg=theme.TEXT_PRIMARY,
            ).pack(side="left", padx=8)

        # credentials frame
        if _HAS_CTK:
            self._creds_frame = ctk.CTkFrame(container, fg_color="transparent")
            ctk.CTkLabel(self._creds_frame, text="Username",
                         font=("Helvetica", 11)).pack(anchor="w", padx=4)
            self._user_entry = ctk.CTkEntry(
                self._creds_frame, placeholder_text="Earthdata username", width=280)
            self._user_entry.pack(pady=(2, 8))
            ctk.CTkLabel(self._creds_frame, text="Password",
                         font=("Helvetica", 11)).pack(anchor="w", padx=4)
            self._pass_entry = ctk.CTkEntry(
                self._creds_frame, placeholder_text="Earthdata password",
                show="•", width=280)
            self._pass_entry.pack(pady=(2, 0))
        else:
            self._creds_frame = tk.Frame(container, bg=theme.SURFACE_1)
            tk.Label(self._creds_frame, text="Username",
                     bg=theme.SURFACE_1, fg=theme.TEXT_PRIMARY).pack(anchor="w")
            self._user_entry = tk.Entry(self._creds_frame, width=34)
            self._user_entry.pack(pady=(0, 6))
            tk.Label(self._creds_frame, text="Password",
                     bg=theme.SURFACE_1, fg=theme.TEXT_PRIMARY).pack(anchor="w")
            self._pass_entry = tk.Entry(self._creds_frame, show="•", width=34)
            self._pass_entry.pack()
        # not packed yet — _on_mode_change controls visibility

        # status + progress
        self._status_label = _Label(container, text="", font=("Helvetica", 11))
        self._status_label.pack(pady=(12, 4))

        self._progress = _ProgressBar(container, mode="indeterminate")
        self._progress.pack(fill="x", padx=20, pady=(0, 16))
        if _HAS_CTK:
            self._progress.set(0)
        else:
            self._progress.stop()

        self._btn = _Button(container, text="Login with Earthdata",
                            command=self._on_login, width=300)
        self._btn.pack()

        # footer (sits at the bottom of left panel, outside the form container)
        footer_text = "Credentials are loaded from your .env file (EARTHDATA_USERNAME / EARTHDATA_PASSWORD)"
        self._footer = _Label(left, text=footer_text, font=("Helvetica", 9),
                              text_color=theme.TEXT_DISABLED)
        self._footer.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 24))

        # ── right: decorative canvas ─────────────────────────────────────────
        self._canvas = tk.Canvas(self, bg=theme.SURFACE_0, highlightthickness=0)
        self._canvas.grid(row=0, column=1, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_resize)

    # ── mode toggle ───────────────────────────────────────────────────────────

    def _on_mode_change(self, value):
        self._manual = value in (_MANUAL_LABEL, "manual")
        if self._manual:
            self._creds_frame.pack(after=self._mode_widget, fill="x", padx=20, pady=(0, 4))
            footer = "Your credentials are used only for this session and are not stored."
        else:
            self._creds_frame.pack_forget()
            footer = "Credentials are loaded from your .env file (EARTHDATA_USERNAME / EARTHDATA_PASSWORD)"
        self._footer.configure(text=footer)
        self._set_status("")

    # ── canvas art ────────────────────────────────────────────────────────────

    def _on_canvas_resize(self, event):
        self._draw_decoration(event.width, event.height)

    def _draw_decoration(self, w, h):
        c = self._canvas
        c.delete("all")
        if w < 10 or h < 10:
            return

        cx = w / 2
        cy = h / 2
        r = min(w, h) * 0.38

        # background grid lines — very subtle
        grid_color = "#161e24"
        step = max(w, h) // 12
        for x in range(0, w + step, step):
            c.create_line(x, 0, x, h, fill=grid_color, width=1)
        for y in range(0, h + step, step):
            c.create_line(0, y, w, y, fill=grid_color, width=1)

        # crosshair through center
        c.create_line(cx, 0, cx, h, fill="#1a2830", width=1)
        c.create_line(0, cy, w, cy, fill="#1a2830", width=1)

        # concentric rings
        ring_color = "#1c2c36"
        for scale in (0.3, 0.5, 0.7, 0.9, 1.1):
            rr = r * scale
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                          outline=ring_color, width=1)

        # main dial ring
        c.create_oval(cx - r, cy - r, cx + r, cy + r,
                      outline="#1e3040", width=2)

        # tick marks around the outer ring (60 total, every 6°)
        for i in range(60):
            angle_deg = i * 6 - 90
            angle = math.radians(angle_deg)
            is_major = (i % 5 == 0)
            is_cardinal = (i % 15 == 0)

            if is_cardinal:
                inner_r = r * 0.82
                tick_color = theme.ACCENT
                width = 2
            elif is_major:
                inner_r = r * 0.88
                tick_color = "#223a4a"
                width = 1
            else:
                inner_r = r * 0.93
                tick_color = "#1c2e3c"
                width = 1

            x0 = cx + inner_r * math.cos(angle)
            y0 = cy + inner_r * math.sin(angle)
            x1 = cx + r * math.cos(angle)
            y1 = cy + r * math.sin(angle)
            c.create_line(x0, y0, x1, y1, fill=tick_color, width=width)

        # inner detail ring with arc segments — gives a multi-ring instrument look
        ir = r * 0.62
        seg_color = "#1e3040"
        for i in range(12):
            start = i * 30
            c.create_arc(cx - ir, cy - ir, cx + ir, cy + ir,
                         start=start, extent=24,
                         outline=seg_color, style="arc", width=1)

        # accent arc — partial ring highlight in cyan
        arc_r = r * 0.78
        c.create_arc(cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r,
                     start=200, extent=140,
                     outline=theme.ACCENT, style="arc", width=1)

        # center crosshair dot
        dot = 5
        c.create_oval(cx - dot, cy - dot, cx + dot, cy + dot,
                      fill=theme.ACCENT, outline="")

        # wordmark at bottom
        c.create_text(cx, h - 58, text="VERNIER",
                      fill=theme.TEXT_MUTED,
                      font=("Helvetica", 13, "bold"))
        c.create_text(cx, h - 36, text="Precision Metadata Validation",
                      fill=theme.TEXT_DISABLED,
                      font=("Helvetica", 9))

    # ── login flow ────────────────────────────────────────────────────────────

    def _on_login(self):
        if self._manual:
            username = self._user_entry.get().strip()
            password = self._pass_entry.get()
            if not username or not password:
                self._on_failure("Please enter both username and password")
                return
        else:
            username = password = None

        if _HAS_CTK:
            self._btn.configure(state="disabled")
            self._progress.configure(mode="indeterminate")
            self._progress.start()
        else:
            self._btn.configure(state="disabled")
            self._progress.start()
        self._set_status("Authenticating with NASA Earthdata Login...")
        threading.Thread(target=self._login_worker, args=(username, password), daemon=True).start()

    def _login_worker(self, username, password):
        try:
            import earthaccess

            if username and password:
                saved = {k: os.environ.get(k) for k in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD")}
                os.environ["EARTHDATA_USERNAME"] = username
                os.environ["EARTHDATA_PASSWORD"] = password
                try:
                    auth = earthaccess.login(strategy="environment")
                finally:
                    for k, v in saved.items():
                        if v is None:
                            os.environ.pop(k, None)
                        else:
                            os.environ[k] = v
            else:
                auth = earthaccess.login(strategy="environment")

            if auth.authenticated:
                self.app.auth = auth
                self.after(0, self.app.show_home)
            else:
                self.after(0, lambda: self._on_failure("Authentication failed — check your credentials"))
        except Exception as exc:
            self.after(0, lambda msg=str(exc): self._on_failure(msg))

    def _set_status(self, text, color=None):
        if _HAS_CTK:
            self._status_label.configure(text=text, text_color=color or theme.TEXT_STATUS)
        else:
            self._status_label.configure(text=text)

    def _on_failure(self, message: str):
        if _HAS_CTK:
            self._progress.stop()
            self._progress.set(0)
            self._btn.configure(state="normal")
        else:
            self._progress.stop()
            self._btn.configure(state="normal")
        self._set_status(f"Error: {message}", color=theme.STATUS_FAIL)

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
        kw.pop("fg_color", None)
        kw.pop("hover_color", None)
        kw.pop("corner_radius", None)
        return tk.Button(parent, text=text, command=command, state=state, **kw)

def _ProgressBar(parent, mode="indeterminate"):
    if _HAS_CTK:
        return ctk.CTkProgressBar(parent, mode=mode)
    else:
        import tkinter.ttk as ttk
        return ttk.Progressbar(parent, mode=mode)


_ENV_LABEL    = "Use .env file"
_MANUAL_LABEL = "Enter credentials"

# Fixed pixel width of the sign-in panel — never changes on toggle
_PANEL_WIDTH  = 700


class LoginScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._manual = False
        self._build()

    def _build(self):
        # Left panel fixed width, right panel takes remaining space
        self.grid_columnconfigure(0, weight=0, minsize=_PANEL_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── left: form panel ─────────────────────────────────────────────────
        if _HAS_CTK:
            left = ctk.CTkFrame(self, corner_radius=0, fg_color=theme.SURFACE_0,
                                width=_PANEL_WIDTH)
        else:
            left = tk.Frame(self, bg=theme.SURFACE_0, width=_PANEL_WIDTH)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_propagate(False)   # hold fixed width regardless of content
        left.grid_rowconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=0)
        left.grid_columnconfigure(0, weight=1)

        # form area — centered via place
        form_outer = tk.Frame(left, bg=theme.SURFACE_0)
        form_outer.grid(row=0, column=0, sticky="nsew")

        container = tk.Frame(form_outer, bg=theme.SURFACE_0)
        container.place(relx=0.5, rely=0.5, anchor="center")

        # Title + subtitle
        if _HAS_CTK:
            ctk.CTkLabel(container, text="Sign into Vernier",
                         font=("Helvetica", 26, "bold"),
                         text_color=theme.TEXT_PRIMARY).pack(pady=(0, 4))
            ctk.CTkLabel(container,
                         text="use your earthdata login",
                         font=("Helvetica", 11),
                         text_color=theme.TEXT_MUTED).pack(pady=(0, 20))
        else:
            tk.Label(container, text="Sign into Vernier",
                     font=("Helvetica", 22, "bold"),
                     bg=theme.SURFACE_0, fg=theme.TEXT_PRIMARY).pack(pady=(0, 4))
            tk.Label(container,
                     text="use your earthdata login",
                     font=("Helvetica", 10),
                     bg=theme.SURFACE_0, fg=theme.TEXT_MUTED).pack(pady=(0, 16))

        # Mode selector
        if _HAS_CTK:
            self._mode_widget = ctk.CTkSegmentedButton(
                container,
                values=[_ENV_LABEL, _MANUAL_LABEL],
                command=self._on_mode_change,
                width=300,
            )
            self._mode_widget.set(_ENV_LABEL)
            self._mode_widget.pack(pady=(0, 0))
        else:
            self._mode_widget = tk.Frame(container, bg=theme.SURFACE_0)
            self._mode_widget.pack(pady=(0, 0))
            self._mode_tk_var = tk.StringVar(value="env")
            tk.Radiobutton(
                self._mode_widget, text=_ENV_LABEL,
                variable=self._mode_tk_var, value="env",
                command=lambda: self._on_mode_change("env"),
                bg=theme.SURFACE_0, fg=theme.TEXT_PRIMARY,
            ).pack(side="left", padx=8)
            tk.Radiobutton(
                self._mode_widget, text=_MANUAL_LABEL,
                variable=self._mode_tk_var, value="manual",
                command=lambda: self._on_mode_change("manual"),
                bg=theme.SURFACE_0, fg=theme.TEXT_PRIMARY,
            ).pack(side="left", padx=8)

        # Fixed-height credentials area — always occupies space, preventing layout shift
        creds_area = tk.Frame(container, bg=theme.SURFACE_0, width=300, height=130)
        creds_area.pack(pady=(4, 0))
        creds_area.pack_propagate(False)

        if _HAS_CTK:
            self._creds_frame = ctk.CTkFrame(creds_area, fg_color="transparent")
            ctk.CTkLabel(self._creds_frame, text="Username",
                         font=("Helvetica", 11)).pack(anchor="w", padx=4)
            self._user_entry = ctk.CTkEntry(
                self._creds_frame, placeholder_text="Earthdata username", width=300)
            self._user_entry.pack(pady=(2, 8))
            ctk.CTkLabel(self._creds_frame, text="Password",
                         font=("Helvetica", 11)).pack(anchor="w", padx=4)
            self._pass_entry = ctk.CTkEntry(
                self._creds_frame, placeholder_text="Earthdata password",
                show="•", width=300)
            self._pass_entry.pack(pady=(2, 0))
        else:
            self._creds_frame = tk.Frame(creds_area, bg=theme.SURFACE_0)
            tk.Label(self._creds_frame, text="Username",
                     bg=theme.SURFACE_0, fg=theme.TEXT_PRIMARY).pack(anchor="w")
            self._user_entry = tk.Entry(self._creds_frame, width=36)
            self._user_entry.pack(pady=(0, 6))
            tk.Label(self._creds_frame, text="Password",
                     bg=theme.SURFACE_0, fg=theme.TEXT_PRIMARY).pack(anchor="w")
            self._pass_entry = tk.Entry(self._creds_frame, show="•", width=36)
            self._pass_entry.pack()
        # hidden by default; shown via place() in _on_mode_change

        # Status + progress
        self._status_label = _Label(container, text="", font=("Helvetica", 11))
        self._status_label.pack(pady=(8, 4))

        self._progress = _ProgressBar(container, mode="indeterminate")
        self._progress.pack(fill="x", padx=4, pady=(0, 12))
        if _HAS_CTK:
            self._progress.set(0)
        else:
            self._progress.stop()

        # Login button
        self._btn = _Button(
            container, text="Login",
            command=self._on_login,
            width=300,
            fg_color=theme.STATUS_PASS,
            hover_color=theme.STATUS_PASS_HVR,
        )
        self._btn.pack()

        # Footer pinned to bottom of left panel
        footer_text = "Credentials are loaded from your .env file (EARTHDATA_USERNAME / EARTHDATA_PASSWORD)"
        self._footer = _Label(left, text=footer_text, font=("Helvetica", 9),
                              text_color=theme.TEXT_DISABLED,
                              wraplength=_PANEL_WIDTH - 56)
        self._footer.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 20))

        # ── right: image panel ───────────────────────────────────────────────
        from PIL import Image as _PilImage
        _assets = os.path.join(os.path.dirname(__file__), "assets")
        self._source_img = _PilImage.open(
            os.path.join(_assets, "image_section_login_screen.png"))
        self._resize_job = None

        if _HAS_CTK:
            self._right = ctk.CTkLabel(self, text="", corner_radius=0,
                                       fg_color=theme.SURFACE_0)
            self._right.grid(row=0, column=1, sticky="nsew")
            self._right.bind("<Configure>", self._on_canvas_resize)
        else:
            self._right = tk.Canvas(self, bg=theme.SURFACE_0, highlightthickness=0)
            self._right.grid(row=0, column=1, sticky="nsew")
            self._right.bind("<Configure>", self._on_canvas_resize)

    # ── mode toggle ───────────────────────────────────────────────────────────

    def _on_mode_change(self, value):
        self._manual = value in (_MANUAL_LABEL, "manual")
        if self._manual:
            self._creds_frame.place(x=0, y=0, relwidth=1)
            self._footer.configure(
                text="Your credentials are used only for this session and are not stored.")
        else:
            self._creds_frame.place_forget()
            self._footer.configure(
                text="Credentials are loaded from your .env file (EARTHDATA_USERNAME / EARTHDATA_PASSWORD)")
        self._set_status("")

    # ── image panel ───────────────────────────────────────────────────────────

    def _on_canvas_resize(self, event):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, lambda w=event.width, h=event.height:
                                      self._draw_decoration(w, h))

    def _draw_decoration(self, w, h):
        self._resize_job = None
        if w < 10 or h < 10:
            return

        if _HAS_CTK:
            from PIL import Image as _Pil, ImageOps
            import customtkinter as _ctk
            resample = getattr(_Pil.Resampling, "LANCZOS", _Pil.LANCZOS)
            cropped = ImageOps.fit(self._source_img, (w, h), resample)
            self._ctk_image = _ctk.CTkImage(light_image=cropped,
                                            dark_image=cropped,
                                            size=(w, h))
            self._right.configure(image=self._ctk_image)
        else:
            from PIL import Image as _Pil, ImageOps, ImageTk
            resample = getattr(_Pil.Resampling, "LANCZOS", _Pil.LANCZOS)
            cropped = ImageOps.fit(self._source_img, (w, h), resample)
            self._bg_photo = ImageTk.PhotoImage(cropped)
            self._right.delete("all")
            self._right.create_image(0, 0, anchor="nw", image=self._bg_photo)

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

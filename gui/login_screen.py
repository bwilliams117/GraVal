import os
import threading
import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None


def _Frame(parent, **kw):
    return ctk.CTkFrame(parent, **kw) if _HAS_CTK else tk.Frame(parent)

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
        self._manual = False  # True when "Enter credentials" mode is active
        self._build()

    def _build(self):
        container = _Frame(self)
        container.place(relx=0.5, rely=0.5, anchor="center")

        _Label(
            container,
            text="NASA Granule Validator",
            font=("Helvetica", 26, "bold"),
        ).pack(pady=(0, 6))

        _Label(
            container,
            text="Automated collection spot-checking powered by earthaccess",
            font=("Helvetica", 12),
        ).pack(pady=(0, 20))

        # ── mode selector ─────────────────────────────────────────────────────
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
            self._mode_widget = tk.Frame(container)
            self._mode_widget.pack(pady=(0, 8))
            self._mode_tk_var = tk.StringVar(value="env")
            tk.Radiobutton(
                self._mode_widget, text=_ENV_LABEL,
                variable=self._mode_tk_var, value="env",
                command=lambda: self._on_mode_change("env"),
            ).pack(side="left", padx=8)
            tk.Radiobutton(
                self._mode_widget, text=_MANUAL_LABEL,
                variable=self._mode_tk_var, value="manual",
                command=lambda: self._on_mode_change("manual"),
            ).pack(side="left", padx=8)

        # ── credentials fields (shown only in manual mode) ────────────────────
        if _HAS_CTK:
            self._creds_frame = ctk.CTkFrame(container, fg_color="transparent")
            ctk.CTkLabel(self._creds_frame, text="Username", font=("Helvetica", 11)).pack(anchor="w", padx=4)
            self._user_entry = ctk.CTkEntry(
                self._creds_frame, placeholder_text="Earthdata username", width=280,
            )
            self._user_entry.pack(pady=(2, 8))
            ctk.CTkLabel(self._creds_frame, text="Password", font=("Helvetica", 11)).pack(anchor="w", padx=4)
            self._pass_entry = ctk.CTkEntry(
                self._creds_frame, placeholder_text="Earthdata password", show="•", width=280,
            )
            self._pass_entry.pack(pady=(2, 0))
        else:
            self._creds_frame = tk.Frame(container)
            tk.Label(self._creds_frame, text="Username").pack(anchor="w")
            self._user_entry = tk.Entry(self._creds_frame, width=34)
            self._user_entry.pack(pady=(0, 6))
            tk.Label(self._creds_frame, text="Password").pack(anchor="w")
            self._pass_entry = tk.Entry(self._creds_frame, show="•", width=34)
            self._pass_entry.pack()
        # not packed yet — _on_mode_change controls visibility

        # ── status + progress ─────────────────────────────────────────────────
        self._status_label = _Label(container, text="", font=("Helvetica", 11))
        self._status_label.pack(pady=(12, 4))

        self._progress = _ProgressBar(container, mode="indeterminate")
        self._progress.pack(fill="x", padx=20, pady=(0, 16))
        if _HAS_CTK:
            self._progress.set(0)
        else:
            self._progress.stop()

        self._btn = _Button(container, text="Login with Earthdata", command=self._on_login, width=220)
        self._btn.pack()

        self._footer = _Label(
            container,
            text="Credentials are read from your .env file (EARTHDATA_USERNAME / EARTHDATA_PASSWORD)",
            font=("Helvetica", 9),
        )
        self._footer.pack(pady=(14, 0))

    # ── mode toggle ───────────────────────────────────────────────────────────

    def _on_mode_change(self, value):
        self._manual = value in (_MANUAL_LABEL, "manual")
        if self._manual:
            self._creds_frame.pack(after=self._mode_widget, fill="x", padx=20, pady=(0, 4))
            footer = "Your credentials are used only for this session and are not stored."
        else:
            self._creds_frame.pack_forget()
            footer = "Credentials are read from your .env file (EARTHDATA_USERNAME / EARTHDATA_PASSWORD)"
        self._footer.configure(text=footer)
        self._set_status("")

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
                # Temporarily inject credentials so strategy="environment" picks them up.
                # Restores original env state in the finally block regardless of outcome.
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
                self.after(0, self.app.show_search)
            else:
                self.after(0, lambda: self._on_failure("Authentication failed — check your credentials"))
        except Exception as exc:
            self.after(0, lambda msg=str(exc): self._on_failure(msg))

    def _set_status(self, text, color=None):
        if _HAS_CTK:
            self._status_label.configure(text=text, text_color=color or "white")
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
        self._set_status(f"Error: {message}", color="#d94040")

"""Login screen: split-pane layout with a form on the left and a cover image on the right."""

import base64
import os
import threading
import tkinter as tk

import earthaccess
import requests
from PIL import Image as PilImage, ImageOps, ImageTk

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme


def _Button(parent, text, command, state="normal", **kw):
    """Return a CTkButton or plain tk.Button, stripping CTk-only kwargs for Tk."""
    if _HAS_CTK:
        return ctk.CTkButton(parent, text=text, command=command, state=state, **kw)
    for key in ("fg_color", "hover_color", "corner_radius", "text_color",
                "border_color", "border_width", "height"):
        kw.pop(key, None)
    return tk.Button(parent, text=text, command=command, state=state, **kw)


def _ProgressBar(parent, mode="indeterminate"):
    """Return a CTkProgressBar or ttk.Progressbar."""
    if _HAS_CTK:
        return ctk.CTkProgressBar(parent, mode=mode)
    import tkinter.ttk as ttk
    return ttk.Progressbar(parent, mode=mode)


_PANEL_WIDTH = 700
_ENTRY_W     = 340
_ENTRY_H     = 44

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


class LoginScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    """Authentication screen shown on startup."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._source_img = PilImage.open(
            os.path.join(_ASSETS_DIR, "login_screen_right_pane.webp")
        )
        self._resize_job = None
        self._ctk_image = None   # prevent GC on CTkImage
        self._bg_photo = None    # prevent GC on ImageTk.PhotoImage
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=0, minsize=_PANEL_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_form_panel()
        self._build_image_panel()

    def _build_form_panel(self):
        """Construct the left credential-entry panel."""
        if _HAS_CTK:
            left = ctk.CTkFrame(
                self, corner_radius=0, fg_color=theme.SURFACE_0, width=_PANEL_WIDTH
            )
        else:
            left = tk.Frame(self, bg=theme.SURFACE_0, width=_PANEL_WIDTH)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_propagate(False)
        left.grid_rowconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=0)
        left.grid_columnconfigure(0, weight=1)

        if _HAS_CTK:
            form_outer = ctk.CTkFrame(left, corner_radius=0, fg_color=theme.SURFACE_0)
            container = ctk.CTkFrame(form_outer, corner_radius=0, fg_color=theme.SURFACE_0)
        else:
            form_outer = tk.Frame(left, bg=theme.SURFACE_0)
            container = tk.Frame(form_outer, bg=theme.SURFACE_0)
        form_outer.grid(row=0, column=0, sticky="nsew")
        container.place(relx=0.5, rely=0.5, anchor="center")

        # tk.Label prevents descender clipping that CTkLabel exhibits at large sizes.
        tk.Label(
            container, text="Sign in",
            font=("Helvetica", 32, "bold"),
            bg=theme.SURFACE_0, fg=theme.TEXT_PRIMARY,
        ).pack(pady=(0, 6))
        tk.Label(
            container, text="use your Earthdata login",
            font=("Helvetica", 13),
            bg=theme.SURFACE_0, fg=theme.TEXT_MUTED,
        ).pack(pady=(0, 20))

        self._build_env_toggle(container)

        self._build_entry(container, "Username", "Earthdata username", show=None)
        self._build_entry(container, "Password", "Earthdata password", show="•")

        self._status_label = (
            ctk.CTkLabel(
                container, text="", font=("Helvetica", 11),
                width=_ENTRY_W, wraplength=_ENTRY_W, justify="center",
            )
            if _HAS_CTK
            else tk.Label(
                container, text="",
                wraplength=_ENTRY_W, justify="center",
            )
        )
        self._status_label.pack(pady=(14, 4))

        self._progress = _ProgressBar(container, mode="indeterminate")
        self._progress.pack(fill="x", padx=2, pady=(0, 14))
        self._progress.pack_forget()
        if _HAS_CTK:
            self._progress.set(0)
        else:
            self._progress.stop()

        self._btn = _Button(
            container, text="Login",
            command=self._on_login,
            width=_ENTRY_W, height=_ENTRY_H,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#121212",
            font=("Helvetica", 13, "bold"),
        )
        self._btn.pack()

        footer = tk.Frame(left, bg=theme.SURFACE_0)
        footer.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 22))

        if _HAS_CTK:
            ctk.CTkLabel(
                footer, text="GraVal",
                font=("Helvetica", 20, "bold"),
                text_color=theme.ACCENT,
                anchor="center",
            ).pack(anchor="center", pady=(0, 5))
            ctk.CTkLabel(
                footer,
                text="Your credentials are never stored.",
                font=("Helvetica", 9),
                text_color=theme.TEXT_DISABLED,
                anchor="center",
                justify="center",
                wraplength=_PANEL_WIDTH - 56,
            ).pack(anchor="center")
        else:
            tk.Label(
                footer, text="GraVal",
                font=("Helvetica", 14, "bold"),
                bg=theme.SURFACE_0, fg=theme.ACCENT,
            ).pack(anchor="center", pady=(0, 5))
            tk.Label(
                footer,
                text="Your credentials are never stored.",
                font=("Helvetica", 9),
                bg=theme.SURFACE_0, fg=theme.TEXT_DISABLED,
                justify="center",
                wraplength=_PANEL_WIDTH - 56,
            ).pack(anchor="center")

    def _build_env_toggle(self, container):
        """UAT / OPS environment selector shown above the credential fields."""
        env_frame = (
            ctk.CTkFrame(container, fg_color="transparent")
            if _HAS_CTK
            else tk.Frame(container, bg=theme.SURFACE_0)
        )
        env_frame.pack(pady=(0, 20))

        self._env_var = tk.StringVar(value="UAT")

        if _HAS_CTK:
            self._env_toggle = ctk.CTkSegmentedButton(
                env_frame,
                values=["UAT", "OPS"],
                variable=self._env_var,
                width=200,
                height=36,
                font=theme.FONT_BODY_BOLD,
                selected_color=theme.STATUS_WARN,
                unselected_color=theme.SURFACE_2,
                unselected_hover_color=theme.BORDER_STRONG,
                text_color=theme.SURFACE_0,
                text_color_disabled=theme.TEXT_MUTED,
                command=self._on_env_change,
            )
            self._env_toggle.pack()
        else:
            btn_frame = tk.Frame(env_frame, bg=theme.SURFACE_0)
            btn_frame.pack()
            for val in ("UAT", "OPS"):
                tk.Radiobutton(
                    btn_frame, text=val, variable=self._env_var, value=val,
                    bg=theme.SURFACE_0, fg=theme.TEXT_PRIMARY,
                    selectcolor=theme.SURFACE_2,
                ).pack(side="left", padx=8)

    def _build_entry(self, container, label_text, placeholder, show):
        """Add a labelled text entry (username or password) to *container*."""
        if _HAS_CTK:
            ctk.CTkLabel(
                container, text=label_text,
                font=("Helvetica", 12),
                text_color=theme.TEXT_MUTED,
                anchor="w",
            ).pack(anchor="w", padx=2, pady=(0, 5))
            entry = ctk.CTkEntry(
                container,
                placeholder_text=placeholder,
                show=show or "",
                width=_ENTRY_W, height=_ENTRY_H,
                font=("Helvetica", 13),
            )
            entry.pack(pady=(0, 18))
        else:
            tk.Label(
                container, text=label_text,
                font=("Helvetica", 12),
                bg=theme.SURFACE_0, fg=theme.TEXT_MUTED,
            ).pack(anchor="w", padx=2)
            entry = tk.Entry(container, width=36, font=("Helvetica", 13),
                             show=show or "")
            entry.pack(pady=(5, 18))

        if label_text == "Username":
            self._user_entry = entry
        else:
            self._pass_entry = entry

    def _build_image_panel(self):
        """Construct the right decorative image panel."""
        if _HAS_CTK:
            self._right = ctk.CTkLabel(
                self, text="", corner_radius=0, fg_color=theme.SURFACE_0
            )
        else:
            self._right = tk.Canvas(
                self, bg=theme.SURFACE_0, highlightthickness=0
            )
        self._right.grid(row=0, column=1, sticky="nsew")
        self._right.bind("<Configure>", self._on_canvas_resize)

    # ── image panel ───────────────────────────────────────────────────────────

    def _on_canvas_resize(self, event):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(
            80,
            lambda w=event.width, h=event.height: self._draw_decoration(w, h),
        )

    def _draw_decoration(self, w, h):
        self._resize_job = None
        if w < 10 or h < 10:
            return
        resample = getattr(PilImage.Resampling, "LANCZOS", PilImage.LANCZOS)
        cropped = ImageOps.fit(self._source_img, (w, h), resample)
        if _HAS_CTK:
            self._ctk_image = ctk.CTkImage(
                light_image=cropped, dark_image=cropped, size=(w, h)
            )
            self._right.configure(image=self._ctk_image)
        else:
            self._bg_photo = ImageTk.PhotoImage(cropped)
            self._right.delete("all")
            self._right.create_image(0, 0, anchor="nw", image=self._bg_photo)

    # ── login flow ────────────────────────────────────────────────────────────

    def _on_login(self):
        username = self._user_entry.get().strip()
        password = self._pass_entry.get()
        if not username or not password:
            self._on_failure("Please enter both username and password")
            return
        self._start_login(username, password)

    def _start_login(self, username, password):
        self._btn.configure(state="disabled")
        self._progress.pack(fill="x", padx=2, pady=(0, 14))
        if _HAS_CTK:
            self._progress.configure(mode="indeterminate")
        self._progress.start()
        self._set_status("Authenticating with NASA Earthdata Login...")
        threading.Thread(
            target=self._login_worker, args=(username, password), daemon=True
        ).start()

    def _login_worker(self, username, password):
        try:
            env = self._env_var.get()

            if env == "UAT":
                # UAT URS is completely separate from OPS URS — earthaccess only
                # knows about OPS, so we skip it entirely for UAT.  The Bearer
                # token from uat.urs.earthdata.nasa.gov is sufficient for all
                # UAT CMR operations.
                if not username or not password:
                    # .env path: pull credentials that were loaded at startup.
                    username = os.environ.get("EARTHDATA_USERNAME", "")
                    password = os.environ.get("EARTHDATA_PASSWORD", "")
                    if not username or not password:
                        self.after(
                            0,
                            lambda: self._on_failure(
                                "No credentials found. Please enter your "
                                "Earthdata username and password above."
                            ),
                        )
                        return

                self.after(
                    0,
                    lambda: self._set_status(
                        "Authenticating with UAT Earthdata Login..."
                    ),
                )
                creds = base64.b64encode(
                    f"{username}:{password}".encode()
                ).decode()
                auth_header = {"Authorization": f"Basic {creds}"}
                _uat_base = "https://uat.urs.earthdata.nasa.gov"

                # Retrieve existing tokens first — this endpoint only needs Basic
                # auth and avoids the application-registration requirement that
                # the POST /api/users/token endpoint enforces.
                list_resp = requests.get(
                    f"{_uat_base}/api/users/tokens",
                    headers=auth_header,
                    timeout=15,
                )
                uat_token = ""
                if list_resp.status_code == 200:
                    tokens = list_resp.json()
                    if tokens:
                        uat_token = (
                            tokens[0].get("access_token")
                            or tokens[0].get("token", {}).get("access_token")
                            or ""
                        )

                if not uat_token:
                    # No existing tokens — create one.
                    create_resp = requests.post(
                        f"{_uat_base}/api/users/token",
                        headers=auth_header,
                        timeout=15,
                    )
                    if create_resp.status_code not in (200, 201):
                        self.after(
                            0,
                            lambda: self._on_failure(
                                "Incorrect username or password. "
                                "Please check your UAT Earthdata credentials "
                                "and try again."
                            ),
                        )
                        return
                    data = create_resp.json()
                    uat_token = (
                        data.get("access_token")
                        or data.get("token", {}).get("access_token")
                        or ""
                    )

                if not uat_token:
                    self.after(
                        0,
                        lambda: self._on_failure(
                            "Login succeeded but no access token was returned. "
                            "Try again or contact your system administrator."
                        ),
                    )
                    return

                self.app.auth = None   # earthaccess auth not used in UAT sessions
                self.app.env = env
                self.app.uat_token = uat_token
                self.after(0, self.app.show_home)
                return

            # ── OPS path ──────────────────────────────────────────────────────
            if username and password:
                saved = {
                    k: os.environ.get(k)
                    for k in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD")
                }
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

            if not auth.authenticated:
                self.after(
                    0,
                    lambda: self._on_failure(
                        "Incorrect username or password. "
                        "Please check your Earthdata credentials and try again."
                    ),
                )
                return

            self.app.auth = auth
            self.app.env = env
            self.app.uat_token = None
            self.after(0, self.app.show_home)

        except Exception as exc:
            self.after(0, lambda msg=str(exc): self._on_failure(msg))

    def _set_status(self, text, color=None):
        if _HAS_CTK:
            self._status_label.configure(
                text=text, text_color=color or theme.TEXT_STATUS
            )
        else:
            self._status_label.configure(text=text)

    def _on_env_change(self, value: str):
        color = theme.STATUS_WARN if value == "UAT" else theme.ACCENT
        self._env_toggle.configure(selected_color=color)

    def _on_failure(self, message: str):
        self._progress.stop()
        if _HAS_CTK:
            self._progress.set(0)
        self._progress.pack_forget()
        self._btn.configure(state="normal")
        self._set_status(f"Error: {message}", color=theme.STATUS_FAIL)

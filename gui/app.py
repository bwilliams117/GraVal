"""Root application window and screen-transition controller."""

import os
import sys
import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
    _BASE = ctk.CTk
except ImportError:
    _HAS_CTK = False
    _BASE = tk.Tk


class ValidatorApp(_BASE):
    """Top-level window that owns shared state and drives screen transitions."""

    def __init__(self):
        super().__init__()
        self.title("GraVal")
        self.geometry("1600x900")
        self.minsize(800, 560)

        if _HAS_CTK:
            ctk.set_appearance_mode("dark")
            # Support both frozen (PyInstaller) and normal execution paths.
            _base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
            theme_path = (
                os.path.join(_base, "gui", "theme.json")
                if hasattr(sys, "_MEIPASS")
                else os.path.join(os.path.dirname(__file__), "theme.json")
            )
            ctk.set_default_color_theme(theme_path)

        # Shared state passed between screens.
        self.auth = None
        self.uat_token = None          # Bearer token for UAT CMR/download calls
        self.env = "UAT"               # "UAT" or "OPS"; set by login screen
        self.selected_collection = None
        self.last_validation_run = None
        self._inspector_entry = False  # True when SearchScreen was entered via Inspector
        self._current_screen = None

        self.show_login()

    # ── screen transitions ────────────────────────────────────────────────────

    def _replace_screen(self, screen, show_badge: bool = True):
        """Destroy the current screen and pack the new one."""
        if self._current_screen is not None:
            self._current_screen.destroy()
        self._current_screen = screen
        screen.pack(fill="both", expand=True)
        if show_badge:
            from .theme import place_env_badge
            place_env_badge(screen, getattr(self, "env", "OPS"))

    def show_login(self):
        from .login_screen import LoginScreen
        self._replace_screen(LoginScreen(self, self), show_badge=False)

    def show_home(self):
        from .home_screen import HomeScreen
        self._replace_screen(HomeScreen(self, self))

    def show_search(self):
        self._inspector_entry = False
        from .search_screen import SearchScreen
        self._replace_screen(SearchScreen(self, self))

    def show_config(self):
        from .config_screen import ConfigScreen
        self._replace_screen(ConfigScreen(self, self))

    def show_results(self, config: dict):
        from .results_screen import ResultsScreen
        self._replace_screen(ResultsScreen(self, self, config))

    def show_inspector_search(self):
        self._inspector_entry = True
        from .search_screen import SearchScreen
        self._replace_screen(SearchScreen(self, self))

    def show_inspector_config(self):
        from .inspector_config_screen import InspectorConfigScreen
        self._replace_screen(InspectorConfigScreen(self, self))

    def show_inspector_results(self, check_config: dict):
        from .inspector_results_screen import InspectorResultsScreen
        self._replace_screen(InspectorResultsScreen(self, self, check_config))

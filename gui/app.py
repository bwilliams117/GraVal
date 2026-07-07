import tkinter as tk

try:
    import customtkinter as ctk
    _HAS_CTK = True
    _BASE = ctk.CTk
    _FRAME = ctk.CTkFrame
except ImportError:
    _HAS_CTK = False
    _BASE = tk.Tk
    _FRAME = tk.Frame

class ValidatorApp(_BASE):
    def __init__(self):
        super().__init__()
        self.title("NASA Granule Validator")
        self.geometry("960x680")
        self.minsize(800, 560)

        if _HAS_CTK:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")

        # Shared state
        self.auth = None
        self.selected_collection = None
        self.last_validation_run = None
        self._current_screen = None

        self.show_login()

    # ── navigation ────────────────────────────────────────────────────────────

    def _replace_screen(self, screen):
        if self._current_screen is not None:
            self._current_screen.destroy()
        self._current_screen = screen
        screen.pack(fill="both", expand=True)

    def show_login(self):
        from .login_screen import LoginScreen
        self._replace_screen(LoginScreen(self, self))

    def show_search(self):
        from .search_screen import SearchScreen
        self._replace_screen(SearchScreen(self, self))

    def show_config(self):
        from .config_screen import ConfigScreen
        self._replace_screen(ConfigScreen(self, self))

    def show_results(self, config: dict):
        from .results_screen import ResultsScreen
        self._replace_screen(ResultsScreen(self, self, config))

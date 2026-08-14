#!/usr/bin/env python3
"""Entry point for GraVal — load environment credentials and launch the GUI."""

import warnings

from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=FutureWarning, module="earthaccess")


def main():
    """Launch the GraVal application."""
    from gui.app import ValidatorApp
    app = ValidatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()

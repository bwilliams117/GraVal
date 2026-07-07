#!/usr/bin/env python3
import warnings

from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=FutureWarning, module="earthaccess")


def main():
    from gui.app import ValidatorApp
    app = ValidatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()

"""PyInstaller entry point. Build a standalone exe with:

    py -3.12 -m PyInstaller --onefile --noconsole --name CultistAdviser launcher.py
"""
from cultist_adviser.gui import main

if __name__ == "__main__":
    main()

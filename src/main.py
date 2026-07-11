import sys
import os

# Resolve imports when executing directly or as a module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from src.utils.logger import get_logger

logger = get_logger("Main")


def main():
    logger.info("Starting Desktop Pet AI Application...")

    # 1. QApplication FIRST — Qt objects (pixmaps, timers, the event bus)
    #    may only be created after this exists, and only on this thread.
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(True)

    # 2. Build the full object graph on the GUI thread.
    from src.core.composition import CompositionRoot
    root = CompositionRoot()

    # 3. Start subsystems and show the pet.
    root.start()

    # 4. Enter main PyQt event loop
    exit_code = qapp.exec()

    # 5. Safe cleanup of background resources
    logger.info("PyQt loop exited. Performing cleanup...")
    root.shutdown()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

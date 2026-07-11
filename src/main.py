import sys
import os

# Resolve imports when executing directly or as a module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication
from src.core.application import Application
from src.ui.window import PetWindow
from src.utils.logger import get_logger

logger = get_logger("Main")

def main():
    logger.info("Starting Desktop Pet AI Application...")
    
    # 1. Start the asynchronous background event loop thread
    app_engine = Application.get_instance()
    app_engine.start()
    
    # 2. Create the GUI application
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(True)
    
    # 3. Instantiate and show main pet UI
    pet = PetWindow()
    pet.show()
    
    # 4. Enter main PyQt event loop
    exit_code = qapp.exec()
    
    # 5. Safe cleanup of background resources
    logger.info("PyQt loop exited. Performing cleanup...")
    app_engine.shutdown()
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()

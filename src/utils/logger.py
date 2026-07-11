import logging
import sys
import os

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if logger is already initialized
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File Handler (logs to storage/logs/app.log)
        try:
            log_dir = os.path.join("storage", "logs")
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.FileHandler(
                os.path.join(log_dir, "app.log"), encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            # Fallback if logs directory cannot be created
            print(f"Warning: Could not create log file: {e}")
            
    return logger

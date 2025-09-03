# c:\Users\XC\Desktop\Projects\ConnectHear\CHDatasetManager\logger_config.py
import logging
import os # Added for path.join
from .constants import APP_LOG_FILENAME # Use relative import if in the same package
from .file_system_operations import get_app_base_path # Import the helper

def setup_logging():
    """Configures the application-wide logger."""
    log_file_path = os.path.join(get_app_base_path(), APP_LOG_FILENAME)
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(threadName)s - %(module)s - %(funcName)s - %(message)s',
        filename=log_file_path,
        filemode='a'
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging configured via logger_config.py.")
    return logger

# Initialize logger when this module is imported
logger = setup_logging()

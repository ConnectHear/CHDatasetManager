# c:\Users\XC\Desktop\Projects\ConnectHear\CHDatasetManager\file_system_operations.py
import os
import shutil
import re
import csv
import datetime
import logging
import sys # Added for get_app_base_path

# Assuming constants are in a sibling file or accessible via package structure
from .constants import VERIFICATION_LOG_FILE

logger = logging.getLogger(__name__)

# NEW helper function
def get_app_base_path():
    """
    Returns the base path for the application.
    For a frozen app (PyInstaller), it's the directory of the executable.
    For a script, it's the directory of the main script (sys.argv[0]).
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running in a PyInstaller bundle
        return os.path.dirname(sys.executable)
    else:
        # Running as a normal Python script
        return os.path.dirname(os.path.abspath(sys.argv[0]))

def get_directory_structure(base_dir_path):
    """Scans the base directory and returns a_dict of categories and their words."""
    structure = {}
    if not base_dir_path or not os.path.isdir(base_dir_path):
        logger.warning(f"Invalid base directory for structure scan: {base_dir_path}")
        return structure
    try:
        categories = sorted([d for d in os.listdir(base_dir_path) if os.path.isdir(os.path.join(base_dir_path, d))])
        for category_name in categories:
            category_path = os.path.join(base_dir_path, category_name)
            words = sorted([w for w in os.listdir(category_path) if os.path.isdir(os.path.join(category_path, w))])
            structure[category_name] = words
        logger.debug(f"Directory structure scanned for {base_dir_path}: {len(structure)} categories.")
    except Exception as e:
        logger.error(f"Error scanning directory structure {base_dir_path}: {e}", exc_info=True)
    return structure

def determine_next_take_number(target_dir_path, interpreter_id_str):
    """Determines the next available take number in the target directory."""
    highest_take = 0
    if os.path.isdir(target_dir_path):
        try:
            pattern = re.compile(re.escape(f"{interpreter_id_str}_") + r"([1-4])\..+$", re.IGNORECASE)
            for filename in os.listdir(target_dir_path):
                match = pattern.match(filename)
                if match:
                    try:
                        take_number = int(match.group(1))
                        highest_take = max(highest_take, take_number)
                    except ValueError:
                        logger.warning(f"Non-integer take in {filename} for pattern {pattern.pattern}")
            logger.debug(f"Highest take in {target_dir_path} for ID {interpreter_id_str} is {highest_take}.")
            return highest_take + 1
        except Exception as e:
            logger.error(f"Error determining next take in {target_dir_path}: {e}", exc_info=True)
            return -1 # Indicate error
    return 1 # Default if directory doesn't exist

def move_and_rename_video(source_path, target_folder_path, new_filename):
    """Moves and renames a video file. Creates target_folder_path if it doesn't exist."""
    if not os.path.isfile(source_path):
        logger.error(f"Source file not found for move: {source_path}")
        return False, f"Source file not found: {os.path.basename(source_path)}"
    
    try:
        if not os.path.isdir(target_folder_path):
            os.makedirs(target_folder_path)
            logger.info(f"Created target directory: {target_folder_path}")
        
        final_destination_path = os.path.join(target_folder_path, new_filename)
        if os.path.exists(final_destination_path):
            logger.error(f"Destination file already exists: {final_destination_path}")
            return False, f"Destination file already exists: {new_filename}"
            
        shutil.move(source_path, final_destination_path)
        logger.info(f"Moved '{os.path.basename(source_path)}' to '{final_destination_path}'")
        return True, None
    except Exception as e:
        logger.error(f"Error moving file {source_path} to {target_folder_path}/{new_filename}: {e}", exc_info=True)
        return False, f"Failed to move {os.path.basename(source_path)}: {e}"

def log_verification_to_csv(log_entry_data):
    """Logs verification data to the CSV file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry_data["Timestamp"] = timestamp # Add/overwrite timestamp

    log_file_path = os.path.join(get_app_base_path(), VERIFICATION_LOG_FILE)
    try:
        file_exists = os.path.isfile(log_file_path)
        # Ensure fieldnames are derived from the provided dict to maintain order and completeness
        fieldnames = list(log_entry_data.keys()) 

        with open(log_file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists or os.path.getsize(VERIFICATION_LOG_FILE) == 0:
                writer.writeheader()
            writer.writerow(log_entry_data)
        logger.info(f"Successfully logged verification data to {VERIFICATION_LOG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error logging data to CSV '{log_file_path}': {e}", exc_info=True)
        return False

# c:\Users\XC\Desktop\Projects\ConnectHear\CHDatasetManager\constants.py
import numpy as np

# --- GUI and Display Constants ---
THUMBNAIL_WIDTH = 160  # Width for the animation display area
THUMBNAIL_HEIGHT = 90   # Height for the animation display area
MAX_VIDEOS = 4
PREVIEW_ANIMATION_DELAY = 250  # Milliseconds between preview frames

# --- Logging Constants ---
APP_LOG_FILENAME = 'video_placer_app.log' # Renamed to avoid conflict
VERIFICATION_LOG_FILE = "verification_log.csv"

# --- Video Processing Constants ---
# SSIM Keyframes
SSIM_KEYFRAME_PERCENTAGES = [0.25, 0.33, 0.5, 0.66, 0.75]
NUM_SSIM_KEYFRAMES = len(SSIM_KEYFRAME_PERCENTAGES)
SSIM_RESIZE_WIDTH = 160
SSIM_RESIZE_HEIGHT = 90

# Preview Frames
NUM_PREVIEW_FRAMES = 5
PREVIEW_START_PERC = 0.25  # Start preview sampling at 25%
PREVIEW_END_PERC = 0.75    # End preview sampling at 75%
PREVIEW_FRAME_PERCENTAGES = np.linspace(PREVIEW_START_PERC, PREVIEW_END_PERC, NUM_PREVIEW_FRAMES)

# --- Scoring and Marking Constants ---
PRE_MARKING_SD_FACTOR = 0.5  # Factor for SD-based pre-marking
PRE_MARKING_SCORE_THRESHOLD = 0.85

# --- File System Constants ---
VALID_VIDEO_EXTENSIONS = ('.mp4', '.avi', '.mov', '.wmv', '.mkv', '.flv')
INTERPRETER_ID_RANGE = range(0, 10000) # Allow 4-digit numbers from 0000-9999

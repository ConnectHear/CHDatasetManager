
# c:\Users\XC\Desktop\Projects\ConnectHear\CHDatasetManager\VideoPlacerv2.py
import os
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
import csv
import datetime
import threading
import queue
import concurrent.futures # Added for parallel processing
import sys # Added for sys.exit
import os # Added for path manipulation

# --- Adjust sys.path to allow running script directly within a package structure ---
# This allows imports like 'from CHDatasetManager.module import ...'
# Get the directory of the current script
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory of the script's directory (this should be the directory containing the CHDatasetManager package)
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)

# Add the project root to sys.path so that 'CHDatasetManager' can be found as a package
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# --- Local Project Imports ---
# Assuming 'CHDatasetManager' is the name of the package directory
from CHDatasetManager.logger_config import logger
from CHDatasetManager.constants import (
    MAX_VIDEOS, INTERPRETER_ID_RANGE, VALID_VIDEO_EXTENSIONS,
    PRE_MARKING_SD_FACTOR, PRE_MARKING_SCORE_THRESHOLD,
    PREVIEW_ANIMATION_DELAY, VERIFICATION_LOG_FILE
)
from CHDatasetManager.video_processing_operations import VideoProcessor
from CHDatasetManager.file_system_operations import (
    get_directory_structure, determine_next_take_number,
    move_and_rename_video, log_verification_to_csv
)

# --- Try importing required libraries and provide guidance if missing ---
try:
    logger.debug("Attempting to import dependencies: cv2, PIL, skimage, numpy")
    import cv2
    from PIL import Image, ImageTk
    from skimage.metrics import structural_similarity as ssim
    import numpy as np
    logger.debug("Core dependencies (cv2, PIL, skimage, numpy) imported successfully.")

except ImportError as e:
    logger.critical(f"Missing required library: {e.name}. Please install dependencies.", exc_info=True)
    messagebox.showerror(
        "Missing Dependencies",
        f"Error: Required library not found: {e.name}\n\n"
        "Please install required libraries using pip:\n"
        "pip install opencv-python Pillow scikit-image numpy"
    )
    # Exit if dependencies are missing, otherwise the app will crash later
    sys.exit(1)
except Exception as e:
     logger.critical(f"An unexpected error occurred during dependency import: {e}", exc_info=True)
     messagebox.showerror("Critical Error", f"An unexpected error occurred during startup:\n{e}")
     sys.exit(1)

# --- Global Constants for the GUI ---
VIDEO_TYPES_FILTER = [("Video Files", "*.mp4 *.avi *.mov *.wmv *.mkv *.flv"), ("All Files", "*.*")]


class VideoPlacerApp:
    """
    GUI application to place up to 4 video takes into a folder structure.
    Base Directory and Interpreter ID are set once per session.
    Includes automatic similarity scoring (Per-Video Multi-Frame SSIM),
    displays an animated preview using sampled frames, pre-marks videos
    close to the max score, allows manual per-video approval, and logs
    initial/final states. Processes only approved videos.
    Renames files as InterpreterID_TakeNumber.ext.
    """
    def __init__(self, master):
        logger.info("Initializing VideoPlacerApp GUI.")
        self.master = master
        master.title("Video Placement Helper (Animated Preview)") # Updated title

        # --- Center the window ---
        master.update_idletasks() # Ensure window dimensions are calculated
        width = 650 # Adjusted width for better layout
        height = 750 # Adjusted height for more content
        screen_width = master.winfo_screenwidth()
        screen_height = master.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        master.geometry(f'{width}x{height}+{x}+{y}')
        master.minsize(width, height) # Set minimum size
        logger.debug(f"Window size set to {width}x{height}, centered at ({x},{y}) on screen {screen_width}x{screen_height}.")


        # --- State Variables ---
        self.initial_setup_done = False
        logger.debug("State variable 'initial_setup_done' initialized to False.")

        # --- Tkinter Variables ---
        self.base_directory = tk.StringVar()
        self.selected_interpreter_id = tk.StringVar()
        self.selected_category = tk.StringVar() # Replaces selected_col_a
        self.selected_word = tk.StringVar()     # Replaces selected_col_b
        self.selected_file_paths_tuple = ()
        self.selected_files_info = tk.StringVar(value="No files selected")
        self.status_message = tk.StringVar(value="Step 1: Select Base Directory")
        self.take_assignment_display = tk.StringVar(value="Takes: -")
        # Analysis/verification variables
        self.per_video_similarity_scores = [None] * MAX_VIDEOS
        self.score_display_vars = [tk.StringVar(value="Score: -") for _ in range(MAX_VIDEOS)]
        self.per_video_confirmed_vars = [tk.BooleanVar(value=False) for _ in range(MAX_VIDEOS)]
        self.initial_confirmation_state = [False] * MAX_VIDEOS # Stores state *after* analysis pre-marking
        # Store references to the multiple preview PhotoImage objects (list of lists)
        self.preview_photo_images = [[] for _ in range(MAX_VIDEOS)]
        # Store current animation frame index for each slot
        self.preview_animation_index = [0] * MAX_VIDEOS
        # Store IDs returned by master.after for cancellation
        self.preview_after_ids = [None] * MAX_VIDEOS
        self.analysis_queue = queue.Queue()
        self.is_analysis_running = False
        logger.debug("Tkinter variables and state variables initialized.")

        # --- Initialize Helper Classes ---
        self.video_processor = VideoProcessor(self.analysis_queue.put)


        # --- Style ---
        style = ttk.Style()
        style.configure("TLabel", padding=5, font=('Helvetica', 10))
        style.configure("TButton", padding=5, font=('Helvetica', 10))
        style.configure("TCombobox", padding=5, font=('Helvetica', 10))
        style.configure("TEntry", padding=5, font=('Helvetica', 10))
        style.configure("Status.TLabel", font=('Helvetica', 9), foreground="grey")
        style.configure("TakeAssign.TLabel", font=('Helvetica', 10, 'bold'), foreground="blue")
        style.configure("Score.TLabel", font=('Helvetica', 9, 'bold'), foreground="green")
        style.configure("Confirm.TCheckbutton", font=('Helvetica', 9))
        logger.debug("Configured ttk styles.")


        # --- GUI Layout ---
        main_frame = ttk.Frame(master, padding="15 15 15 15") # Increased padding
        main_frame.pack(expand=True, fill=tk.BOTH)
        logger.debug("Main frame created and packed.")

        row_basedir = 0; row_id = 1; row_treeview = 2 # Category/Word Tree
        row_fileselect = 3; row_verification_area = 4; row_analysis_info = 5
        row_processbtn = 6; row_status = 7
        logger.debug(f"Defined grid row assignments: basedir={row_basedir}, id={row_id}, treeview={row_treeview}, fileselect={row_fileselect}, verification={row_verification_area}, analysis_info={row_analysis_info}, process_btn={row_processbtn}, status={row_status}")

        # --- Widgets ---
        ttk.Label(main_frame, text="Base Directory:").grid(row=row_basedir, column=0, sticky=tk.W, padx=10, pady=(10, 5))
        self.base_dir_entry = ttk.Entry(main_frame, textvariable=self.base_directory, width=45, state='readonly')
        self.base_dir_entry.grid(row=row_basedir, column=1, columnspan=2, padx=5, pady=(10, 5))
        self.base_dir_button = ttk.Button(main_frame, text="Browse...", command=self.select_base_dir)
        self.base_dir_button.grid(row=row_basedir, column=3, padx=10, pady=(10, 5))
        logger.debug("Base directory widgets placed.")

        ttk.Label(main_frame, text="Interpreter ID:").grid(row=row_id, column=0, sticky=tk.W, padx=10, pady=5)
        self.interpreter_id_entry = ttk.Entry(main_frame, textvariable=self.selected_interpreter_id, width=40, state='disabled') # Adjusted width
        self.interpreter_id_entry.grid(row=row_id, column=1, sticky=tk.EW, padx=5, pady=5)
        self.interpreter_id_entry.bind("<FocusOut>", self.on_id_select) # Trigger validation when focus leaves
        self.interpreter_id_entry.bind("<Return>", self.on_id_select) # Trigger validation when Enter is pressed
        logger.debug("Interpreter ID widgets placed.")

        # --- Category/Word TreeView ---
        ttk.Label(main_frame, text="Category / Word:").grid(row=row_treeview, column=0, sticky=tk.NW, padx=10, pady=(10,5))
        self.category_word_tree = ttk.Treeview(main_frame, selectmode="browse", height=7, show="tree headings") # height is number of rows
        self.category_word_tree.heading("#0", text="Select a Word")
        self.category_word_tree.column("#0", width=250) # Adjust width as needed
        self.tree_scroll = ttk.Scrollbar(main_frame, orient="vertical", command=self.category_word_tree.yview)
        self.category_word_tree.configure(yscrollcommand=self.tree_scroll.set)
        self.category_word_tree.grid(row=row_treeview, column=1, sticky="nsew", padx=(5,0), pady=5)
        self.tree_scroll.grid(row=row_treeview, column=2, sticky="nsw", padx=(0,10), pady=5) # Adjusted padx
        self.category_word_tree.bind("<<TreeviewSelect>>", self.on_tree_item_select)
        logger.debug("Category/Word TreeView placed.")

        ttk.Label(main_frame, text="Selected Files:").grid(row=row_fileselect, column=0, sticky=tk.W, padx=10, pady=5)
        self.files_info_entry = ttk.Entry(main_frame, textvariable=self.selected_files_info, width=40, state='readonly') # Adjusted width
        self.files_info_entry.grid(row=row_fileselect, column=1, sticky=tk.EW, padx=5, pady=5)
        self.select_files_button = ttk.Button(main_frame, text="Select Files...", command=self.select_video_files, state='disabled')
        self.select_files_button.grid(row=row_fileselect, column=3, padx=10, pady=5)
        logger.debug("File selection widgets placed.")


        # --- Verification Area (Animated Preview, Scores, Checkboxes) ---
        ttk.Label(main_frame, text="Review & Approve Takes:").grid(row=row_verification_area, column=0, sticky="nw", padx=10, pady=(15, 0))
        self.verification_frame = ttk.Frame(main_frame, borderwidth=1, relief="sunken")
        self.verification_frame.grid(row=row_verification_area, column=1, columnspan=3, sticky="nsew", padx=5, pady=(10,5)) # Adjusted padx
        logger.debug("Verification area frame placed.")

        # Use single label per slot for animation
        self.preview_labels = []
        self.score_labels = []
        self.confirm_checkboxes = []

        for i in range(MAX_VIDEOS):
            item_frame = ttk.Frame(self.verification_frame)
            item_frame.grid(row=0, column=i, padx=5, pady=5, sticky="n")
            self.verification_frame.columnconfigure(i, weight=1) # Ensure columns expand equally

            # Single Label for Animated Preview
            preview_label = ttk.Label(item_frame) # Size determined by image
            preview_label.pack(pady=(0,2))
            self.preview_labels.append(preview_label)

            # Score Label
            score_label = ttk.Label(item_frame, textvariable=self.score_display_vars[i], style="Score.TLabel")
            score_label.pack(pady=(0,2))
            self.score_labels.append(score_label)

            # Checkbox
            confirm_cb = ttk.Checkbutton(item_frame, text="Approve", variable=self.per_video_confirmed_vars[i], onvalue=True, offvalue=False, command=self.check_button_state, style="Confirm.TCheckbutton", state='disabled')
            confirm_cb.pack(pady=(0,5))
            self.confirm_checkboxes.append(confirm_cb)
        logger.debug(f"Created {MAX_VIDEOS} slots in verification frame (preview labels, score labels, checkboxes).")

        # Take Assignment Display
        ttk.Label(main_frame, textvariable=self.take_assignment_display, style="TakeAssign.TLabel").grid(row=row_analysis_info, column=1, columnspan=2, sticky="w", padx=5, pady=(5, 0)) # Adjusted columnspan and padx
        logger.debug("Take assignment display label placed.")

        # Process Button
        self.process_button = ttk.Button(main_frame, text="Place Approved Files", command=self.process_selected_videos, state='disabled')
        self.process_button.grid(row=row_processbtn, column=1, sticky=tk.EW, pady=20, padx=5)
        logger.debug("Process button placed.")

        # Status Label
        ttk.Label(main_frame, textvariable=self.status_message, style="Status.TLabel").grid(row=row_status, column=0, columnspan=4, sticky="ew", padx=5, pady=(10, 15)) # Adjusted padx
        logger.debug("Status label placed.")

        # --- Configure Grid (within main_frame) ---
        main_frame.columnconfigure(1, weight=1)
        main_frame.columnconfigure(2, weight=0) # Column for scrollbar / some buttons
        main_frame.columnconfigure(3, weight=0) # Column for some buttons
        main_frame.rowconfigure(row_verification_area, weight=1)
        logger.debug("Main frame grid configured for expansion.")

        # --- Start Queue Checker & Bind Closing ---
        self.master.after(100, self.check_analysis_queue) # Start queue checker
        logger.debug("Started check_analysis_queue loop via master.after.")
        # Bind closing event
        logger.debug("Bound on_closing method to window close event.")



    # --- Helper Functions ---
    def clear_analysis_results(self):
        """Clears previous analysis results from GUI and stops animations."""
        logger.info("Clearing previous analysis results and stopping animations.")
        # Stop any running animations
        for i in range(MAX_VIDEOS):
            if self.preview_after_ids[i] is not None:
                try:
                    self.master.after_cancel(self.preview_after_ids[i])
                    logger.debug(f"Cancelled animation 'after' job for slot {i}.")
                except tk.TclError:
                    logger.debug(f"Could not cancel animation 'after' job for slot {i} (job may have already run/cancelled).")
                    pass # Job might have already run or been cancelled
                self.preview_after_ids[i] = None

        self.per_video_similarity_scores = [None] * MAX_VIDEOS
        logger.debug("Similarity scores reset.")
        for var in self.score_display_vars:
            var.set("Score: -")
        logger.debug("Score display labels reset.")
        self.take_assignment_display.set("Takes: -")
        logger.debug("Take assignment display reset.")
        self.initial_confirmation_state = [False] * MAX_VIDEOS # Reset initial state tracking
        logger.debug("Initial confirmation state tracking reset.")
        for i in range(MAX_VIDEOS):
            self.per_video_confirmed_vars[i].set(False)
            if i < len(self.confirm_checkboxes):
                 # Keep checkboxes disabled until analysis results are ready
                 self.confirm_checkboxes[i].config(state='disabled')
        logger.debug("Approval checkboxes reset and disabled.")

        # Clear preview images and labels
        self.preview_photo_images = [[] for _ in range(MAX_VIDEOS)] # Reset list of lists
        logger.debug("Preview photo image list reset.")
        for i, label in enumerate(self.preview_labels): # Use the single preview labels now
             try:
                label.config(image='') # Clear the displayed image
                logger.debug(f"Cleared preview image for slot {i}.")
             except Exception as e:
                 logger.warning(f"Failed to clear image for preview label {i}: {e}") # Should not happen
        self.preview_animation_index = [0] * MAX_VIDEOS # Reset animation index
        logger.debug("Preview animation indices reset.")

        logger.debug("Finished clearing analysis results.")

    def select_base_dir(self):
        logger.debug("select_base_dir called.")
        if self.initial_setup_done:
            logger.debug("select_base_dir: Initial setup already done, returning.")
            return

        directory = filedialog.askdirectory(title="Select Base Directory (Set Once)")
        if directory:
            self.base_directory.set(directory)
            self.status_message.set("Step 2: Select your Interpreter ID")
            logger.info(f"Base directory selected: {directory}")
            # Enable next step and disable this one
            self.interpreter_id_entry.config(state='normal') # Changed to 'normal' for entry
            self.interpreter_id_entry.focus()
            self.base_dir_button.config(state='disabled')
            self.category_word_tree.unbind("<<TreeviewSelect>>")
            logger.debug("Treeview unbind <<TreeviewSelect>> in select_base_dir")
            self.select_files_button.config(state='disabled')
            self.process_button.config(state='disabled') # Process button should also be disabled
            logger.debug("Enabled Interpreter ID combobox, disabled Base Dir button.")
        else:
            logger.info("Base directory selection cancelled.")
            self.status_message.set("Base directory selection cancelled. Please select Base Directory.")
            logger.debug("Base directory selection cancelled, status message updated.")

    def _validate_interpreter_id(self, interpreter_id_str):
        """Validates the interpreter ID input."""
        logger.debug(f"Validating interpreter ID: '{interpreter_id_str}'")
        if not interpreter_id_str:
            messagebox.showerror("Validation Error", "Interpreter ID cannot be empty.")
            logger.warning("Interpreter ID validation failed: empty.")
            return False
        if not re.fullmatch(r"^\d{4}$", interpreter_id_str):
            messagebox.showerror("Validation Error", "Interpreter ID must be a 4-digit number (e.g., 0001, 1234).")
            logger.warning(f"Interpreter ID validation failed: '{interpreter_id_str}' is not a 4-digit number.")
            return False
        
        interpreter_id_int = int(interpreter_id_str)
        if interpreter_id_int < INTERPRETER_ID_RANGE.start or interpreter_id_int >= INTERPRETER_ID_RANGE.stop:
            messagebox.showerror("Validation Error", f"Interpreter ID must be between {INTERPRETER_ID_RANGE.start:04d} and {INTERPRETER_ID_RANGE.stop-1:04d}.")
            logger.warning(f"Interpreter ID validation failed: {interpreter_id_int} is out of range.")
            return False
        
        logger.debug(f"Interpreter ID '{interpreter_id_str}' validated successfully.")
        return True

    def on_id_select(self, event=None):
        logger.debug(f"on_id_select called. Event: {event}")
        selected_id = self.selected_interpreter_id.get()

        if self.initial_setup_done:
            logger.debug("on_id_select: Initial setup already done. Returning.")
            return

        if not self._validate_interpreter_id(selected_id):
            self.interpreter_id_entry.focus_set() # Keep focus on the entry for correction
            self.status_message.set("Please enter a valid 4-digit Interpreter ID.")
            logger.debug("Interpreter ID validation failed in on_id_select. Not proceeding with setup.")
            return

        logger.info(f"Interpreter ID selected: {selected_id}. Initial setup now complete.")
        self.initial_setup_done = True
        # self.interpreter_id_entry.config(state='disabled') # Keep editable as per user feedback
        self.status_message.set("Step 3: Select a Word from the tree below.")
        logger.debug("Calling populate_category_word_tree.")
        self.populate_category_word_tree()
        # populate_category_word_tree itself will set state to 'normal' if successful
        # or 'disabled' if not.
        self.category_word_tree.focus_set() # Set focus to the tree

        # Clear subsequent selections and states
        self.selected_category.set("")
        self.selected_word.set("")
        self.category_word_tree.selection_set(()) # Clear tree selection
        logger.debug("Category and Word selections (StringVar) cleared. Tree selection cleared.")

        self.selected_file_paths_tuple = ()
        self.selected_files_info.set("No files selected")
        logger.debug("Word selection and file selection cleared.")

        self.clear_analysis_results()
        logger.debug("Analysis results cleared.")

        # Status message is handled by populate_category_word_tree or on_tree_item_select

        # Select Files button should be disabled until Word is selected
        self.select_files_button.config(state='disabled')
        logger.debug("File select button disabled.")

        self.check_button_state() # Re-evaluate process button state
        logger.debug("check_button_state called after Category selection.")
        logger.debug("on_id_select finished processing.")

    def populate_category_word_tree(self):
        """Populates the TreeView with categories and words from the base directory."""
        logger.debug("populate_category_word_tree called.")
        for i in self.category_word_tree.get_children():
            self.category_word_tree.delete(i)
        logger.debug("Cleared existing items from category_word_tree.")

        base_dir = self.base_directory.get()
        if not base_dir or not os.path.isdir(base_dir):
            logger.warning(f"Base directory '{base_dir}' not set or not a directory. Tree not populated.")
            self.category_word_tree.insert("", "end", text="Base directory not set or invalid.", open=False)
            self.category_word_tree.unbind("<<TreeviewSelect>>")
            logger.debug("Treeview unbind <<TreeviewSelect>> in populate_category_word_tree (base_dir invalid)")
            self.status_message.set("Error: Base directory invalid. Cannot load categories.")
            return

        dir_structure = get_directory_structure(base_dir)

        if not dir_structure:
            logger.info(f"No category subdirectories found or error scanning {base_dir}.")
            self.category_word_tree.insert("", "end", text="No categories found or error.", open=False)
            self.category_word_tree.unbind("<<TreeviewSelect>>")
            self.status_message.set("No categories found or error. Check base directory.")
            return

        for category_name, words in dir_structure.items():
                category_id = self.category_word_tree.insert("", "end", text=category_name, open=False, tags=('category',))
                if words:
                    for word_name in words:
                        self.category_word_tree.insert(category_id, "end", text=word_name, tags=('word',))
                else:
                    self.category_word_tree.insert(category_id, "end", text=" (No words)", tags=('empty_category_info',))
            
        self.category_word_tree.bind("<<TreeviewSelect>>", self.on_tree_item_select)
        logger.debug("Treeview bind <<TreeviewSelect>> in populate_category_word_tree (success)")
        self.status_message.set("Select a Category, then a Word from the tree.")
        # logger.info(f"Populated category/word tree with {len(categories)} categories from {base_dir}.") # categories not defined here
        logger.info(f"Populated category/word tree with {len(dir_structure)} categories from {base_dir}.")


    def on_tree_item_select(self, event=None):
        """Handles selection changes in the category/word TreeView."""
        logger.debug("on_tree_item_select called.")
        selected_item_id = self.category_word_tree.focus() # Get the ID of the focused/selected item

        if not selected_item_id: # No item selected (e.g., selection cleared)
            self.selected_category.set("")
            self.selected_word.set("")
            logger.debug("Tree selection cleared. Category and Word reset.")
        else:
            item = self.category_word_tree.item(selected_item_id)
            item_text = item['text']
            item_tags = item['tags']

            if 'word' in item_tags:
                parent_id = self.category_word_tree.parent(selected_item_id)
                self.selected_category.set(self.category_word_tree.item(parent_id, "text"))
                self.selected_word.set(item_text)
                logger.info(f"Word selected: '{item_text}' under Category: '{self.selected_category.get()}'")
            elif 'category' in item_tags:
                self.selected_category.set(item_text)
                self.selected_word.set("") # Clear word if only category is selected
                logger.info(f"Category selected: '{item_text}'. Word cleared.")
            else: # Should not happen if tags are set correctly
                self.selected_category.set("")
                self.selected_word.set("")
                logger.warning(f"Selected tree item '{item_text}' has no 'category' or 'word' tag.")

        # Common actions for any selection change
        self.selected_file_paths_tuple = ()
        self.selected_files_info.set("No files selected")
        self.clear_analysis_results() # Clears scores, previews, and disables checkboxes

        if self.selected_word.get():
            self.status_message.set(f"Step 4: Select video files for Word '{self.selected_word.get()}'")
            self.calculate_and_display_take_assignment() # Update take info if a word is selected
        elif self.selected_category.get():
            self.status_message.set(f"Select a Word under Category '{self.selected_category.get()}'")
            self.take_assignment_display.set("Takes: -") # Clear take info if only category
        else:
            self.status_message.set("Select a Category, then a Word.")
            self.take_assignment_display.set("Takes: -")

        self.check_button_state()
        logger.debug("on_tree_item_select finished processing.")

    # --- Centralized File Processing Logic ---
    def _process_filepaths_for_analysis(self, filepaths):
        """Common logic to handle a list of filepaths for analysis."""
        if not filepaths:
            logger.debug("_process_filepaths_for_analysis called with no filepaths.")
            return

        num_selected = len(filepaths)
        logger.info(f"Processing {num_selected} file(s) for analysis via _process_filepaths_for_analysis.")

        if num_selected > MAX_VIDEOS:
            messagebox.showwarning("Too Many Files", f"Please select a maximum of {MAX_VIDEOS} files. {num_selected} were provided.")
            logger.warning(f"User provided {num_selected} files, exceeding the maximum of {MAX_VIDEOS}.")
            return

        # Validate file extensions (basic check)
        validated_filepaths = []
        for fp in filepaths:
            if os.path.splitext(fp)[1].lower() in VALID_VIDEO_EXTENSIONS:
                validated_filepaths.append(fp)
            else:
                logger.warning(f"Skipping non-video file (based on extension): {fp}")
        
        if not validated_filepaths:
            messagebox.showwarning("No Valid Video Files", "No files with recognized video extensions were found among the provided files.")
            logger.warning("No valid video files after extension check from provided list.")
            # Clear selections if all provided files were invalid
            self.selected_file_paths_tuple = ()
            self.selected_files_info.set("No files selected")
            self.clear_analysis_results() # Clean up UI
            self.status_message.set("No valid video files found.")
            self.check_button_state()
            return

        filepaths_to_process = tuple(validated_filepaths)
        num_to_process = len(filepaths_to_process)

        self.clear_analysis_results() # Clears previous results and animations
        logger.debug("Cleared previous analysis results and animations before new analysis.")

        self.selected_file_paths_tuple = filepaths_to_process
        self.selected_files_info.set(f"{num_to_process} file(s) selected")
        self.status_message.set("Analyzing videos...")
        logger.info(f"Selected {num_to_process} video files for analysis: {'; '.join(map(os.path.basename, filepaths_to_process))}")

        self.check_button_state() # Update button states (e.g., disable process button)
        self.is_analysis_running = True
        logger.info("Analysis started. Setting is_analysis_running to True.")

        # Use the VideoProcessor instance to run analysis
        analysis_thread = threading.Thread(
            target=self.video_processor.run_analysis_in_thread,
            args=(filepaths_to_process,),
            daemon=True)
        analysis_thread.start()
        logger.debug(f"Analysis thread started: {analysis_thread.name}")

    # --- Video File Selection and Analysis Trigger ---
    def select_video_files(self):
        """Opens dialog to select multiple video files and starts analysis thread."""
        logger.debug("select_video_files called.")
        if not self.selected_word.get(): # Corrected from selected_col_b
            messagebox.showwarning("Selection Missing", "Please select Word first.")
            logger.warning("Attempted to select files before selecting Word.")
            return

        if self.is_analysis_running:
            messagebox.showwarning("Busy", "Analysis is already in progress.")
            logger.warning("Attempted to select files while analysis is already running.")
            return

        logger.debug(f"Opening file dialog to select up to {MAX_VIDEOS} video files.")
        filepaths_from_dialog = filedialog.askopenfilenames(title=f"Select up to {MAX_VIDEOS} Video Files", filetypes=VIDEO_TYPES_FILTER)

        if filepaths_from_dialog:
            self._process_filepaths_for_analysis(filepaths_from_dialog)
        else:
            self.selected_file_paths_tuple = ()
            self.selected_files_info.set("No files selected")
            self.clear_analysis_results() # Ensure display is clean on cancel
            self.status_message.set("Video file selection cancelled.")
            logger.info("Video file selection cancelled by user.")
            self.check_button_state() # Update button states after cancellation


    # --- MODIFIED Queue Checking (Runs in Main Thread) ---
    def check_analysis_queue(self):
        """Checks the queue for results, displays scores, starts animations, pre-marks."""
        try:
            # logger.debug("Checking analysis queue...") # Too noisy for debug unless needed
            result = self.analysis_queue.get_nowait()
            logger.info("Received message from analysis queue.")

            # Check the type of message from the queue
            if result.get('type') == 'analysis_complete':
                logger.info("Processing 'analysis_complete' message.")
                self.is_analysis_running = False
                logger.debug("is_analysis_running set to False.")

                # Retrieve results using the new keys
                list_of_preview_pil_list = result.get("previews", [])
                self.per_video_similarity_scores = result.get("scores", [None] * MAX_VIDEOS)
                errors = result.get("errors", [])
                filepaths = result.get("filepaths", []) # Get filepaths for context
                num_selected = len(filepaths) # Use the actual number of files selected

                logger.debug(f"Received scores: {self.per_video_similarity_scores}")
                logger.debug(f"Received errors: {errors}")
                logger.debug(f"Received previews list structure: {len(list_of_preview_pil_list)} lists of previews.")


                # --- Update Score Display ---
                logger.debug("Updating score display labels.")
                valid_scores = [s for s in self.per_video_similarity_scores[:num_selected] if s is not None]
                max_score = 0.0
                if valid_scores: max_score = max(valid_scores)
                logger.debug(f"Valid scores for pre-marking: {valid_scores}, Max Score: {max_score:.3f}")


                for i in range(MAX_VIDEOS):
                    if i < num_selected:
                         current_score = self.per_video_similarity_scores[i]
                         if current_score is not None:
                             self.score_display_vars[i].set(f"Score: {current_score:.3f}")
                             logger.debug(f"Set score for slot {i}: {current_score:.3f}")
                         else:
                             self.score_display_vars[i].set("Score: N/A")
                             logger.debug(f"Set score for slot {i}: N/A (score was None)")
                    else:
                        self.score_display_vars[i].set("Score: -")
                        logger.debug(f"Set score for slot {i}: - (index out of bounds for selected files)")


                # --- Create PhotoImage objects for previews and enable/disable checkboxes ---
                logger.debug("Creating PhotoImage objects and configuring checkboxes.")
                self.preview_photo_images = [[] for _ in range(MAX_VIDEOS)] # Reset list of lists
                checkbox_states_after_load = {} # Map index to state ('normal', 'disabled')
                num_videos_with_valid_previews = 0 # Count videos that successfully loaded at least one preview

                for video_idx in range(MAX_VIDEOS):
                    photo_images_for_video = []
                    preview_success = False # Track if at least one preview frame loaded for this video

                    if video_idx < num_selected and video_idx < len(list_of_preview_pil_list):
                        pil_images_for_video = list_of_preview_pil_list[video_idx]
                        logger.debug(f"Processing preview images for slot {video_idx}. Found {len(pil_images_for_video)} potential PIL images (orig+flow).")

                        # Iterate through all images provided for this video (original and flow frames)
                        for img_list_idx, pil_image in enumerate(pil_images_for_video):
                            if pil_image is not None:
                                try:
                                    photo_img = ImageTk.PhotoImage(pil_image)
                                    photo_images_for_video.append(photo_img)
                                    preview_success = True
                                    # Determine if it's an original or flow frame for logging
                                    logger.debug(f"Successfully created PhotoImage for original frame {img_list_idx +1} (list index {img_list_idx}) in slot {video_idx}.")
                                except Exception as e:
                                    logger.error(f"Error creating PhotoImage for image at list index {img_list_idx} in slot {video_idx}: {e}", exc_info=True)
                                    photo_images_for_video.append(None) # Add placeholder on error
                            else:
                                photo_images_for_video.append(None) # Add placeholder if no PIL image was provided
                                # This case might indicate an issue upstream if a PIL image was expected
                                logger.warning(f"PIL image was None for image at list index {img_list_idx} in slot {video_idx}.")
                    self.preview_photo_images[video_idx] = photo_images_for_video # Store list of PhotoImages

                    # Determine checkbox state based on whether *any* preview frames loaded for this video
                    checkbox_state = 'normal' if preview_success else 'disabled'
                    checkbox_states_after_load[video_idx] = checkbox_state

                    if video_idx < len(self.confirm_checkboxes):
                        self.confirm_checkboxes[video_idx].config(state=checkbox_state)
                        logger.debug(f"Checkbox for slot {video_idx} set to state '{checkbox_state}'.")
                        if checkbox_state == 'disabled':
                            # If disabled, ensure the checkbox is unchecked
                            if self.per_video_confirmed_vars[video_idx].get():
                                self.per_video_confirmed_vars[video_idx].set(False)
                                logger.debug(f"Checkbox for slot {video_idx} was disabled and unchecked.")
                            else:
                                logger.debug(f"Checkbox for slot {video_idx} was disabled.")

                    if preview_success:
                        num_videos_with_valid_previews += 1
                        # --- Start Animation for this slot ---
                        logger.debug(f"Starting preview animation for slot {video_idx}.")
                        self.start_preview_animation(video_idx)
                    else:
                         logger.debug(f"No valid previews loaded for slot {video_idx}. Animation not started.")
                         # Ensure label is empty if no previews loaded
                         if video_idx < len(self.preview_labels):
                            self.preview_labels[video_idx].config(image='')


                # --- Pre-mark Checkbox(es) based on Standard Deviation ---
                logger.debug("Starting pre-marking process.")
                # Reset all checkboxes first (already done in clear_analysis_results, but good to re-iterate intention)
                # for i in range(MAX_VIDEOS): self.per_video_confirmed_vars[i].set(False) # Already reset

                # Pre-marking logic applies only if there's more than one video and at least two have valid scores
                if num_selected > 1 and len(valid_scores) >= 2:
                    std_dev = np.std(valid_scores)
                    score_threshold = max_score - PRE_MARKING_SD_FACTOR * std_dev
                    logger.info(f"Pre-marking logic: {num_selected} videos selected, {len(valid_scores)} valid scores. MaxScore={max_score:.3f}, SD={std_dev:.3f}, Threshold={score_threshold:.3f}")

                    # Iterate through the indices of the *selected* files
                    for i in range(num_selected):
                        current_score = self.per_video_similarity_scores[i]
                        # Check if the checkbox for this slot was successfully enabled
                        is_enabled = checkbox_states_after_load.get(i) == 'normal'

                        # Check score vs threshold AND ensure the checkbox is enabled
                        if is_enabled and current_score is not None and (current_score >= score_threshold or current_score >= PRE_MARKING_SCORE_THRESHOLD):
                            logger.info(f"Pre-marking video index {i} ('{os.path.basename(filepaths[i])}') - Score {current_score:.3f} >= Threshold {score_threshold:.3f} or {PRE_MARKING_SCORE_THRESHOLD}. Checkbox state was '{checkbox_states_after_load.get(i)}'.")
                            self.per_video_confirmed_vars[i].set(True)
                        elif is_enabled:
                             logger.debug(f"Video index {i} ('{os.path.basename(filepaths[i])}') not pre-marked. Score {current_score} (is None={current_score is None}). Threshold check: {current_score >= score_threshold if current_score is not None else 'N/A'} | {current_score >= PRE_MARKING_SCORE_THRESHOLD if current_score is not None else 'N/A'}. Checkbox state was '{checkbox_states_after_load.get(i)}'.")
                        else:
                            logger.debug(f"Video index {i} ('{os.path.basename(filepaths[i])}') not pre-marked because checkbox was disabled (state: '{checkbox_states_after_load.get(i)}'). Score: {current_score}.")


                # --- Store Initial Confirmation State for Logging ---
                # This state reflects the checkboxes AFTER analysis and pre-marking
                self.initial_confirmation_state = [self.per_video_confirmed_vars[i].get() if i < MAX_VIDEOS else False for i in range(num_selected)]
                logger.debug(f"Stored initial confirmation state after pre-marking: {self.initial_confirmation_state[:num_selected]}")


                # Report errors from thread
                if errors:
                    messagebox.showwarning("Analysis Issues", "Encountered issues during analysis:\n- " + "\n- ".join(errors))
                    logger.warning(f"Analysis completed with {len(errors)} reported issues.")

                # Calculate take assignment ONLY if analysis produced results (at least one valid preview)
                if num_videos_with_valid_previews > 0:
                    logger.debug("Valid previews found. Calculating take assignment.")
                    self.calculate_and_display_take_assignment()
                    # Status message updated in calculate_and_display_take_assignment if successful
                else:
                    self.take_assignment_display.set("Takes: Error")
                    self.status_message.set("Analysis failed for all videos. Cannot assign takes.")
                    logger.error("Analysis failed for all selected videos. No valid previews/results to assign takes.")


                self.check_button_state() # Update process button state based on confirmation checkboxes
                logger.debug("check_button_state called after analysis results processed.")
            # else: Handle other message types if needed in the future

        except queue.Empty:
            # logger.debug("Analysis queue empty.") # Too noisy
            pass # No item in the queue, just continue
        except Exception as e:
            logger.error(f"Unexpected error in check_analysis_queue: {e}", exc_info=True)
            # Potentially show a user error messagebox if this is a critical failure in the main loop

        finally:
             # Schedule the next check regardless of whether an item was processed or an error occurred
             self.master.after(100, self.check_analysis_queue)


    # --- Animation Functions ---
    def start_preview_animation(self, video_idx):
        """Starts or restarts the animation loop for a specific video slot."""
        logger.debug(f"Attempting to start/restart animation for slot {video_idx}.")
        # Cancel any previous loop for this slot
        if self.preview_after_ids[video_idx] is not None:
            try:
                self.master.after_cancel(self.preview_after_ids[video_idx])
                logger.debug(f"Cancelled existing animation 'after' job {self.preview_after_ids[video_idx]} for slot {video_idx}.")
            except tk.TclError:
                 logger.debug(f"Existing animation 'after' job for slot {video_idx} was already cancelled or finished.")
                 pass # Ignore if job doesn't exist
            self.preview_after_ids[video_idx] = None
            logger.debug(f"Cleared preview_after_ids[{video_idx}].")


        # Reset index and start the update cycle
        self.preview_animation_index[video_idx] = 0
        logger.debug(f"Reset animation index for slot {video_idx} to 0.")

        # Check if the preview label exists before trying to configure it
        if video_idx < len(self.preview_labels):
            # Check if there are any valid PhotoImages for this slot before starting
            valid_photo_list = [img for img in self.preview_photo_images[video_idx] if img is not None]
            if valid_photo_list:
                 logger.debug(f"Starting animation update cycle for slot {video_idx} with {len(valid_photo_list)} valid frames.")
                 self.update_preview_animation(video_idx)
            else:
                 logger.debug(f"No valid PhotoImages found for slot {video_idx}. Not starting animation.")
                 # Ensure label is clear if no animation starts
                 self.preview_labels[video_idx].config(image='')

        else:
            logger.warning(f"Preview label list size mismatch. Preview label for index {video_idx} not found.")


    def update_preview_animation(self, video_idx):
        """Updates the preview label with the next frame and schedules the next update."""
        # Basic check if core lists exist
        if not all(hasattr(self, attr) for attr in ['preview_photo_images', 'preview_labels', 'preview_animation_index', 'preview_after_ids']):
             logger.error(f"Animation components missing during update_preview_animation for slot {video_idx}. Stopping.")
             return # Cannot proceed

        # Check if video_idx is within expected bounds
        if video_idx >= MAX_VIDEOS or video_idx >= len(self.preview_photo_images) or \
           video_idx >= len(self.preview_labels) or video_idx >= len(self.preview_animation_index) or \
           video_idx >= len(self.preview_after_ids):
             logger.error(f"Invalid video_idx {video_idx} during update_preview_animation. Index out of bounds for component lists. Stopping.")
             if video_idx < MAX_VIDEOS and video_idx < len(self.preview_after_ids): # Check bounds before trying to stop
                self.preview_after_ids[video_idx] = None # Attempt to stop recurrence if possible
             return


        photo_list = self.preview_photo_images[video_idx]
        # Filter out None placeholders
        valid_photo_list = [img for img in photo_list if img is not None]

        if not valid_photo_list: # No valid images loaded for this slot
            logger.debug(f"No valid photo list for slot {video_idx} during update. Stopping animation.")
            self.preview_labels[video_idx].config(image='') # Ensure label is clear
            self.preview_after_ids[video_idx] = None # Stop loop
            return

        # Cycle through only the valid images
        num_valid_frames = len(valid_photo_list)
        current_frame_idx = self.preview_animation_index[video_idx] % num_valid_frames
        photo_to_display = valid_photo_list[current_frame_idx]

        # Update the corresponding preview label
        try:
            self.preview_labels[video_idx].config(image=photo_to_display)
            # logger.debug(f"Updated preview label {video_idx} with frame {current_frame_idx}.") # Too noisy
        except tk.TclError as e:
            logger.error(f"Error updating preview label {video_idx} with image: {e}", exc_info=True)
            self.preview_after_ids[video_idx] = None # Stop loop on error
            return


        # Increment index for the next cycle
        self.preview_animation_index[video_idx] = (self.preview_animation_index[video_idx] + 1)

        # Schedule the next update
        # Store the ID returned by after for later cancellation
        self.preview_after_ids[video_idx] = self.master.after(
            PREVIEW_ANIMATION_DELAY, self.update_preview_animation, video_idx
        )


    # --- Take Calculation ---
    def calculate_and_display_take_assignment(self):
        """Calculates the available take range based on existing files and number selected."""
        logger.debug("calculate_and_display_take_assignment called.")
        base_dir = self.base_directory.get() # Correct
        category = self.selected_category.get() # Updated
        word = self.selected_word.get()         # Updated
        interpreter_id = self.selected_interpreter_id.get()
        num_selected = len(self.selected_file_paths_tuple)

        if num_selected == 0:
            self.take_assignment_display.set("Takes: -")
            logger.debug("No files selected, take assignment set to '-'.")
            return

        if not all([base_dir, category, word, interpreter_id]): # Updated
            self.take_assignment_display.set("Takes: Error")
            self.status_message.set("Error: Prerequisite selection missing for take calculation.")
            logger.error(f"Missing prerequisites for take calculation: BaseDir='{base_dir}', Category='{category}', Word='{word}', InterpreterID='{interpreter_id}'.")
            return

        target_folder_path = os.path.join(base_dir, category, word, interpreter_id) # Updated
        logger.debug(f"Checking existing takes in target folder: {target_folder_path}")

        start_take = determine_next_take_number(target_folder_path, interpreter_id)
        if start_take == -1: # Error occurred
            self.take_assignment_display.set("Takes: Error")
            self.status_message.set(f"Error checking existing takes in target folder.")
            return

        logger.debug(f"Calculated starting take: {start_take}.")


        if start_take > 4:
            self.take_assignment_display.set("Takes: FULL (4/4)")
            self.status_message.set("Error: Maximum 4 takes already exist for this Word/Interpreter.")
            logger.warning(f"Target folder '{target_folder_path}' already contains 4 takes or more. Cannot add new files.")
        else:
            end_take = start_take + num_selected - 1
            available_slots = 4 - start_take + 1

            if end_take > 4:
                self.take_assignment_display.set(f"Takes: Error (Need {num_selected}, Avail: {available_slots})")
                self.status_message.set(f"Error: Too many files selected ({num_selected}) for available takes ({available_slots} starting from {start_take}). Approve carefully.")
                logger.warning(f"Number of selected files ({num_selected}) exceeds available slots ({available_slots}) starting from take {start_take}. End take would be {end_take}.")
            else:
                if num_selected == 1:
                    self.take_assignment_display.set(f"Potential Take: {start_take}")
                    logger.info(f"Calculated potential take: {start_take} for 1 selected file.")
                else:
                    self.take_assignment_display.set(f"Potential Takes: {start_take}-{end_take}")
                    logger.info(f"Calculated potential takes: {start_take}-{end_take} for {num_selected} selected files.")

                # Update status message only if analysis didn't report errors and isn't still running
                current_status = self.status_message.get()
                if "Analyzing" not in current_status and "Error" not in current_status:
                    self.status_message.set(f"Ready for approval. Review videos and approve below.")
                    logger.debug("Status message updated to 'Ready for approval'.")

        logger.debug("Finished take assignment calculation.")


    # --- Button State Check ---
    def check_button_state(self):
        """Enables or disables widgets based on the application state (Set-Once Workflow)."""
        logger.debug("check_button_state called.")

        # Initial Setup Phase
        if not self.initial_setup_done:
            logger.debug("Initial setup phase.")
            # Base directory button enabled only if no base dir is set yet
            self.base_dir_button.config(state='normal' if not self.base_directory.get() else 'disabled')
            # Interpreter ID enabled only after base dir is set
            self.interpreter_id_entry.config(state='normal' if self.base_directory.get() and not self.initial_setup_done else 'disabled')
            self.select_files_button.config(state='disabled')
            self.process_button.config(state='disabled')
            # Checkboxes disabled in clear_analysis_results, which is called during initial setup
            # for cb in self.confirm_checkboxes: cb.config(state='disabled') # Redundant if clear_analysis_results is called appropriately
            logger.debug("Widget states updated for initial setup phase.")
            return

        # Post-Initial Setup Phase
        logger.debug("Post-initial setup phase.")
        # Base dir and ID are disabled after initial setup
        self.base_dir_button.config(state='disabled')
        # self.interpreter_id_entry.config(state='disabled') # Keep editable as per user feedback
        logger.debug("Base dir and ID widgets disabled.")

        # Category/Word TreeView enabled if initial setup is done and base_directory is set
        # (its population logic handles if base_dir is invalid)
        if self.initial_setup_done and self.base_directory.get():
            # Check if already bound to avoid duplicate bindings if check_button_state is called multiple times
            # However, ttk.Treeview doesn't have a simple way to check existing bindings for a specific event sequence directly.
            # For simplicity, we'll re-bind; Tkinter usually handles duplicate binds by replacing.
            self.category_word_tree.bind("<<TreeviewSelect>>", self.on_tree_item_select)
            logger.debug("Treeview bind <<TreeviewSelect>> in check_button_state (enabled)")
            tree_state_log = "bound"
        else:
            self.category_word_tree.unbind("<<TreeviewSelect>>")
            logger.debug("Treeview unbind <<TreeviewSelect>> in check_button_state (disabled)")
            tree_state_log = "unbound"
        logger.debug(f"Category/Word TreeView event <<TreeviewSelect>> is {tree_state_log}")

        # File Select enabled if Word is selected
        word_selected = bool(self.selected_word.get())
        self.select_files_button.config(state='normal' if word_selected else 'disabled')
        logger.debug(f"File select button state set to {'normal' if word_selected else 'disabled'}.")

        # Process button requires specific conditions:
        # 1. Files must be selected.
        files_selected = len(self.selected_file_paths_tuple) > 0
        # 2. Take assignment must be valid (not FULL, not Error, not '-').
        take_info = self.take_assignment_display.get()
        valid_take_assignment = not take_info.startswith("Takes: FULL") and not take_info.startswith("Takes: Error") and take_info != "Takes: -"
        # 3. At least one file must be confirmed via checkbox.
        # Only check checkboxes for files that were actually selected
        num_selected_actual = len(self.selected_file_paths_tuple)
        at_least_one_confirmed = any(var.get() for i, var in enumerate(self.per_video_confirmed_vars) if i < num_selected_actual)
        # 4. Analysis must NOT be running.
        can_process = not self.is_analysis_running

        # Enable process button if all conditions met
        enable_process = (files_selected and valid_take_assignment and at_least_one_confirmed and can_process)
        self.process_button.config(state='normal' if enable_process else 'disabled')
        logger.debug(f"Process button state set to {'normal' if enable_process else 'disabled'}. Conditions: FilesSelected={files_selected}, ValidTakes={valid_take_assignment}, Approved={at_least_one_confirmed}, AnalysisRunning={self.is_analysis_running}.")

        # Checkboxes states are handled during analysis completion in check_analysis_queue
        # or cleared in clear_analysis_results. No need to manage their state here based on workflow steps.

        logger.debug("Finished check_button_state.")


    def process_selected_videos(self):
        """Processes the selected and approved video files."""
        logger.info("Process Selected Videos button clicked.")
        messagebox.showinfo("Processing", "Processing of approved videos will start now.")
        # Placeholder for actual processing logic
        # This method will contain the logic to move and rename files
        # based on approved checkboxes and calculated take numbers.
        # For now, it just shows a message.
        self.status_message.set("Processing complete (placeholder).")
        self.clear_analysis_results()
        self.selected_file_paths_tuple = ()
        self.selected_files_info.set("No files selected")
        self.check_button_state()
    # --- Logging Function (for CSV) ---
    def _trigger_csv_logging(self, processed_indices, assigned_take_numbers):
        """Logs verification details including pre-marked and final confirmation status to CSV."""
        logger.info(f"Preparing data for CSV logging to: {VERIFICATION_LOG_FILE}")
        num_selected = len(self.selected_file_paths_tuple)

        # Get final confirmation states for the selected files
        final_confirmation_states = [self.per_video_confirmed_vars[i].get() for i in range(num_selected)]
        final_confirmation_str = "; ".join(map(str, final_confirmation_states))
        logger.debug(f"Final confirmation states: {final_confirmation_states}")

        # Get initial confirmation states (after pre-marking) for the selected files
        # self.initial_confirmation_state was stored after check_analysis_queue processed results
        initial_confirmation_str = "; ".join(map(str, self.initial_confirmation_state[:num_selected])) # Ensure we only log for selected files
        logger.debug(f"Initial (pre-marked) confirmation states: {self.initial_confirmation_state[:num_selected]}")


        # Get scores for the selected files
        scores_str = "; ".join([f"{s:.4f}" if s is not None else "N/A" for s in self.per_video_similarity_scores[:num_selected]])


if __name__ == "__main__":
    root = tk.Tk()
    app = VideoPlacerApp(root)
    root.mainloop()

# c:\Users\XC\Desktop\Projects\ConnectHear\CHDatasetManager\video_processing_operations.py
import cv2
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
import os # For basename
import logging
import threading
import concurrent.futures

# Assuming constants are in a sibling file or accessible via package structure
from .constants import (
    NUM_SSIM_KEYFRAMES, SSIM_KEYFRAME_PERCENTAGES, SSIM_RESIZE_WIDTH, SSIM_RESIZE_HEIGHT,
    NUM_PREVIEW_FRAMES, PREVIEW_FRAME_PERCENTAGES, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT, MAX_VIDEOS
)

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, analysis_queue_put_callback):
        self.analysis_queue_put = analysis_queue_put_callback

    def _extract_frames_for_video(self, video_path):
        video_filename = os.path.basename(video_path)
        logger.debug(f"Extracting frames from: {video_filename}")
        keyframes_for_ssim = [None] * NUM_SSIM_KEYFRAMES
        preview_pil_images = []
        error_messages = []
        cap = None
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                error_messages.append(f"Error opening: {video_filename}")
                return keyframes_for_ssim, preview_pil_images, error_messages
            
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) # Still needed for percentages
            
            # Extract SSIM Keyframes
            for kf_idx, percentage in enumerate(SSIM_KEYFRAME_PERCENTAGES):
                frame_idx = max(0, min(int(frame_count * percentage), frame_count - 1))
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret_key, frame_key = cap.read()
                if ret_key and frame_key is not None:
                    height, width, _ = frame_key.shape
                    start_col, end_col = width // 3, 2 * width // 3
                    cropped_frame_key = frame_key[:, start_col:end_col]
                    if cropped_frame_key.shape[0] > 0 and cropped_frame_key.shape[1] > 0:
                        gray_frame = cv2.cvtColor(cropped_frame_key, cv2.COLOR_BGR2GRAY)
                        keyframes_for_ssim[kf_idx] = cv2.resize(gray_frame, (SSIM_RESIZE_WIDTH, SSIM_RESIZE_HEIGHT), interpolation=cv2.INTER_AREA)
                    else: error_messages.append(f"Invalid crop for SSIM {kf_idx+1}: {video_filename}")
                else: error_messages.append(f"Error reading SSIM keyframe {kf_idx+1}: {video_filename}")

            # Extract Preview Frames (Original only)
            for pv_idx, percentage in enumerate(PREVIEW_FRAME_PERCENTAGES):
                frame_num_current = max(0, min(int(frame_count * percentage), frame_count - 1))
                pil_img_orig_processed = None
                final_w_disp, final_h_disp = THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT

                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num_current)
                ret_curr, frame_curr_raw = cap.read()

                if ret_curr and frame_curr_raw is not None:
                    h_c, w_c, _ = frame_curr_raw.shape
                    crop_c = frame_curr_raw[:, w_c // 3 : 2 * w_c // 3]
                    ch_c, cw_c, _ = crop_c.shape

                    if ch_c > 0 and cw_c > 0:
                        aspect_ratio_c = cw_c / ch_c
                        if THUMBNAIL_WIDTH / aspect_ratio_c <= THUMBNAIL_HEIGHT:
                            final_w_disp, final_h_disp = THUMBNAIL_WIDTH, int(THUMBNAIL_WIDTH / aspect_ratio_c)
                        else:
                            final_h_disp, final_w_disp = THUMBNAIL_HEIGHT, int(THUMBNAIL_HEIGHT * aspect_ratio_c)
                        
                        final_w_disp, final_h_disp = max(1, final_w_disp), max(1, final_h_disp)
                        resized_display = cv2.resize(crop_c, (final_w_disp, final_h_disp), interpolation=cv2.INTER_AREA)
                        pil_img_orig_processed = Image.fromarray(cv2.cvtColor(resized_display, cv2.COLOR_BGR2RGB))
                    else: error_messages.append(f"Invalid crop_c for preview {pv_idx+1}: {video_filename}")
                else: error_messages.append(f"Error reading preview frame {pv_idx+1}: {video_filename}")
                
                preview_pil_images.append(pil_img_orig_processed)

        except Exception as e:
            error_messages.append(f"Unexpected error processing {video_filename}: {e}")
            logger.error(f"Unexpected error in _extract_frames_for_video for {video_filename}", exc_info=True)
        finally:
            if cap: cap.release()
        return keyframes_for_ssim, preview_pil_images, error_messages

    def _calculate_ssim_scores_for_videos(self, all_keyframes, filepaths):
        num_videos = len(all_keyframes)
        per_video_avg_scores = [None] * num_videos
        error_messages = []
        valid_indices = [i for i, kf_list in enumerate(all_keyframes) if kf_list and all(kf is not None for kf in kf_list)]

        if len(valid_indices) > 1:
            sums = {idx: 0.0 for idx in valid_indices}
            counts = {idx: 0 for idx in valid_indices}
            for i in range(len(valid_indices)):
                idx_i = valid_indices[i]
                for j in range(i + 1, len(valid_indices)):
                    idx_j = valid_indices[j]
                    pair_scores = []
                    for kf_idx in range(NUM_SSIM_KEYFRAMES):
                        f_i, f_j = all_keyframes[idx_i][kf_idx], all_keyframes[idx_j][kf_idx]
                        try:
                            score = ssim(f_i, f_j, data_range=f_i.max() - f_i.min())
                            pair_scores.append(score)
                        except ValueError as ve: error_messages.append(f"SSIM error pair ({idx_i},{idx_j}) kf {kf_idx+1}: {ve}")
                    if pair_scores:
                        avg_pair = np.mean(pair_scores)
                        sums[idx_i] += avg_pair; sums[idx_j] += avg_pair
                        counts[idx_i] += 1; counts[idx_j] += 1
            for idx in valid_indices:
                if counts[idx] > 0: per_video_avg_scores[idx] = sums[idx] / counts[idx]
        elif len(valid_indices) == 1:
            per_video_avg_scores[valid_indices[0]] = 1.0
        return per_video_avg_scores, error_messages

    def run_analysis_in_thread(self, filepaths):
        logger.info(f"Analysis thread started for {len(filepaths)} videos.")
        num_videos = len(filepaths)
        all_previews = [[] for _ in range(num_videos)]
        all_ssim_kf = [[] for _ in range(num_videos)]
        all_errors = []
        results_from_extraction = [None] * num_videos

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_VIDEOS, os.cpu_count() or 1)) as executor:
            future_to_idx = {executor.submit(self._extract_frames_for_video, path): i for i, path in enumerate(filepaths)}
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    kf, prev, err = future.result()
                    results_from_extraction[idx] = (kf, prev, err)
                    if err: all_errors.extend(err)
                except Exception as exc:
                    all_errors.append(f"Extraction failed for {os.path.basename(filepaths[idx])}: {exc}")
        
        for idx in range(num_videos):
            if results_from_extraction[idx]:
                all_ssim_kf[idx], all_previews[idx], _ = results_from_extraction[idx]
            else: # Placeholder if extraction failed catastrophically
                all_ssim_kf[idx] = [None] * NUM_SSIM_KEYFRAMES
                all_previews[idx] = [None] * NUM_PREVIEW_FRAMES

        scores, ssim_errs = self._calculate_ssim_scores_for_videos(all_ssim_kf, filepaths)
        if ssim_errs: all_errors.extend(ssim_errs)

        self.analysis_queue_put({
            'type': 'analysis_complete',
            'scores': scores,
            'previews': all_previews,
            'errors': all_errors,
            'filepaths': filepaths
        })
        logger.info("Analysis thread finished.")

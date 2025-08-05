import os
import logging
import time
from pathlib import Path
from typing import List, Tuple
from open_webui.config import UPLOAD_DIR, GCS_BUCKET_NAME, RAG_FILE_MAX_SIZE

log = logging.getLogger(__name__)


def cleanup_uploads_folder() -> dict:
    """
    Clean up uploads folder when it exceeds RAG_FILE_MAX_SIZE * 2.
    Only runs when GCS is enabled since we want to keep files in GCS but manage local storage.
    
    Returns:
        dict: Summary of cleanup operation
    """
    # Only run cleanup if GCS is enabled
    if not GCS_BUCKET_NAME:
        log.debug("GCS not enabled, skipping uploads folder cleanup")
        return {
            "enabled": False,
            "reason": "GCS not enabled",
            "files_deleted": 0,
            "space_freed": 0,
            "total_size_before": 0,
            "total_size_after": 0
        }
    
    max_folder_size = (RAG_FILE_MAX_SIZE.value * 1024 * 1024 * 2) if RAG_FILE_MAX_SIZE.value else 40 * 1024 * 1024  # Convert MB to bytes, then multiply by 2
    min_file_age_hours = 0  # Don't delete files newer than 1 hour
    
    try:
        if not UPLOAD_DIR.exists():
            log.debug(f"Uploads directory {UPLOAD_DIR} does not exist")
            return {
                "enabled": True,
                "reason": "Directory does not exist",
                "files_deleted": 0,
                "space_freed": 0,
                "total_size_before": 0,
                "total_size_after": 0
            }
        
        # Get all files in uploads directory with their sizes and modification times
        files_info: List[Tuple[Path, int, float]] = []
        total_size = 0
        
        for file_path in UPLOAD_DIR.iterdir():
            if file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                    mod_time = file_path.stat().st_mtime
                    files_info.append((file_path, file_size, mod_time))
                    total_size += file_size
                except OSError as e:
                    log.warning(f"Could not get info for {file_path}: {e}")
                    continue
        
        log.info(f"Uploads folder size: {total_size / (1024*1024):.2f}MB (limit: {max_folder_size / (1024*1024):.2f}MB)")
        
        if total_size <= max_folder_size:
            log.debug("Uploads folder size is within limits, no cleanup needed")
            return {
                "enabled": True,
                "reason": "Size within limits",
                "files_deleted": 0,
                "space_freed": 0,
                "total_size_before": total_size,
                "total_size_after": total_size
            }
        
        # Sort files by modification time (oldest first)
        files_info.sort(key=lambda x: x[2])
        
        # Calculate cutoff time (files older than this can be deleted)
        cutoff_time = time.time() - (min_file_age_hours * 3600)
        
        files_deleted = 0
        space_freed = 0
        current_time = time.time()
        
        for file_path, file_size, mod_time in files_info:
            # Stop if we've freed enough space
            if total_size - space_freed <= max_folder_size:
                break
            
            # Only delete files older than the minimum age
            if mod_time < cutoff_time:
                try:
                    # Get base name for related files
                    base_name = file_path.stem
                    
                    # Delete the main file
                    file_path.unlink()
                    files_deleted += 1
                    space_freed += file_size
                    log.info(f"Deleted file: {file_path.name} (size: {file_size / (1024*1024):.2f}MB)")
                    
                    # Delete related files (.mp3, .json) if they exist
                    for ext in ['.mp3', '.json']:
                        related_file = file_path.parent / f"{base_name}{ext}"
                        if related_file.exists():
                            try:
                                related_size = related_file.stat().st_size
                                related_file.unlink()
                                space_freed += related_size
                                log.info(f"Deleted related file: {related_file.name} (size: {related_size / (1024*1024):.2f}MB)")
                            except OSError as e:
                                log.warning(f"Could not delete related file {related_file}: {e}")
                    
                except OSError as e:
                    log.warning(f"Could not delete file {file_path}: {e}")
                    continue
            else:
                # File is too new, skip it
                age_hours = (current_time - mod_time) / 3600
                log.debug(f"Skipping file {file_path.name} (age: {age_hours:.2f} hours)")
        
        final_size = total_size - space_freed
        log.info(f"Cleanup completed: deleted {files_deleted} files, freed {space_freed / (1024*1024):.2f}MB")
        log.info(f"Final folder size: {final_size / (1024*1024):.2f}MB")
        
        return {
            "enabled": True,
            "reason": "Cleanup completed",
            "files_deleted": files_deleted,
            "space_freed": space_freed,
            "total_size_before": total_size,
            "total_size_after": final_size
        }
        
    except Exception as e:
        log.error(f"Error during uploads folder cleanup: {e}")
        return {
            "enabled": True,
            "reason": f"Error: {str(e)}",
            "files_deleted": 0,
            "space_freed": 0,
            "total_size_before": 0,
            "total_size_after": 0
        } 
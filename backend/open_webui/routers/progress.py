import asyncio
import json
import time
import logging
from typing import Dict, Optional
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from open_webui.utils.auth import get_verified_user
from open_webui.models.users import Users
from open_webui.models.knowledge import Knowledges

log = logging.getLogger(__name__)

router = APIRouter(tags=["progress"])

def update_progress(session_id: str, progress_data: dict):
    """Update progress for a session in the database"""
    try:
        # Extract knowledge_id from session_id (assuming format: knowledge_id_session_uuid)
        # For now, we'll store progress in a special knowledge entry with id = session_id
        knowledge_id = session_id
        
        # Get or create knowledge entry for this session
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        
        if not knowledge:
            log.warning(f"Knowledge base {knowledge_id} not found for progress tracking")
            return
        
        # Update the meta field with progress information
        meta = knowledge.meta or {}
        meta["processing_progress"] = {
            "session_id": session_id,
            "status": progress_data.get("status", "processing"),
            "total_files": progress_data.get("total_files", 1),
            "processed_files": 1 if progress_data.get("status") == "completed" else 0,
            "current_file": progress_data.get("file_list", [""])[0] if progress_data.get("file_list") else "",
            "file_list": progress_data.get("file_list", []),
            "progress": progress_data.get("progress", 0),
            "message": progress_data.get("message", ""),
            "last_updated": int(time.time()),
            "error": progress_data.get("error")
        }
        
        # Update the knowledge entry
        Knowledges.update_knowledge_by_id(
            id=knowledge_id,
            form_data=type('obj', (object,), {
                'name': knowledge.name,
                'description': knowledge.description,
                'data': knowledge.data,
                'access_control': knowledge.access_control
            })(),
            overwrite=True
        )
        
        # Also update the meta field specifically
        Knowledges.update_knowledge_meta_by_id(knowledge_id, meta)
        
        log.info(f"Progress updated for session {session_id}: {progress_data}")
        
    except Exception as e:
        log.error(f"Error updating progress for session {session_id}: {e}")

def get_progress(session_id: str) -> Optional[Dict]:
    """Get current progress for a session from the database"""
    try:
        knowledge_id = session_id
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        
        if not knowledge or not knowledge.meta:
            return None
        
        progress_data = knowledge.meta.get("processing_progress")
        if not progress_data:
            return None
        
        # Check if progress is stale (older than 5 minutes)
        last_updated = progress_data.get("last_updated", 0)
        if time.time() - last_updated > 300:  # 5 minutes
            log.info(f"Progress for session {session_id} is stale, removing")
            # Remove stale progress
            meta = knowledge.meta.copy()
            meta.pop("processing_progress", None)
            Knowledges.update_knowledge_meta_by_id(knowledge_id, meta)
            return None
        
        return progress_data
        
    except Exception as e:
        log.error(f"Error getting progress for session {session_id}: {e}")
        return None

def mark_session_complete(session_id: str):
    """Mark a session as complete in the database"""
    try:
        knowledge_id = session_id
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        
        if not knowledge:
            log.warning(f"Knowledge base {knowledge_id} not found for marking session complete")
            return
        
        meta = knowledge.meta or {}
        if "processing_progress" in meta:
            # Force completion state
            pp = meta["processing_progress"]
            pp["status"] = "completed"
            pp["progress"] = 100
            pp["processed_files"] = pp.get("total_files", 1)
            pp["last_updated"] = int(time.time())
            pp["message"] = "Processing completed successfully"
            
            Knowledges.update_knowledge_meta_by_id(knowledge_id, meta)
            log.info(f"Session {session_id} marked as complete")
        
    except Exception as e:
        log.error(f"Error marking session {session_id} as complete: {e}")

def mark_session_error(session_id: str, error: str):
    """Mark a session as error in the database"""
    try:
        knowledge_id = session_id
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        
        if not knowledge:
            log.warning(f"Knowledge base {knowledge_id} not found for marking session error")
            return
        
        meta = knowledge.meta or {}
        if "processing_progress" in meta:
            meta["processing_progress"]["status"] = "error"
            meta["processing_progress"]["error"] = error
            meta["processing_progress"]["last_updated"] = int(time.time())
            meta["processing_progress"]["message"] = f"Error: {error}"
            
            Knowledges.update_knowledge_meta_by_id(knowledge_id, meta)
            log.info(f"Session {session_id} marked as error: {error}")
        
    except Exception as e:
        log.error(f"Error marking session {session_id} as error: {e}")

def update_file_progress(session_id: str, file_progress: dict):
    """Update progress for a specific file in the session"""
    try:
        knowledge_id = session_id
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        
        if not knowledge:
            log.warning(f"Knowledge base {knowledge_id} not found for file progress update")
            return
        
        meta = knowledge.meta or {}
        if "processing_progress" not in meta:
            meta["processing_progress"] = {
                "session_id": session_id,
                "status": "processing",
                "total_files": file_progress.get("total_files", 1),
                "processed_files": file_progress.get("processed_files", 0),
                "current_file": file_progress.get("current_file", ""),
                "file_list": file_progress.get("file_list", []),
                "progress": 0,
                "message": "",
                "last_updated": int(time.time()),
                "error": None
            }
        
        # Update file-specific progress
        progress = meta["processing_progress"]
        # Determine session-level status, avoiding premature 'completed'
        incoming_status = file_progress.get("status", progress.get("status", "processing"))
        if incoming_status == "completed":
            # Only set completed when all files are done; otherwise keep processing
            total = progress.get("total_files") or file_progress.get("total_files") or 1
            processed = progress.get("processed_files", 0)
            # If this completion will not finish the whole batch, keep session status as processing
            session_status = "completed" if (processed + 1) >= total else "processing"
        else:
            session_status = incoming_status

        progress.update({
            "status": session_status,
            "progress": file_progress.get("progress", progress.get("progress", 0)),
            "message": file_progress.get("message", progress.get("message", "")),
            "last_updated": int(time.time()),
            "error": file_progress.get("error")
        })
        
        # Update additional fields if provided
        if "total_files" in file_progress:
            progress["total_files"] = file_progress["total_files"]
        if "processed_files" in file_progress:
            progress["processed_files"] = file_progress["processed_files"]
        if "current_file" in file_progress:
            progress["current_file"] = file_progress["current_file"]
        if "file_list" in file_progress:
            progress["file_list"] = file_progress["file_list"]
        
        # Update processed files count if completed
        if file_progress.get("status") == "completed":
            current_processed = progress.get("processed_files", 0)
            total = progress.get("total_files", 1)
            progress["processed_files"] = min(current_processed + 1, total)
        
        Knowledges.update_knowledge_meta_by_id(knowledge_id, meta)
        log.info(f"File progress updated for session {session_id}: {file_progress}")
        
    except Exception as e:
        log.error(f"Error updating file progress for session {session_id}: {e}")

@router.get("/{session_id}")
async def progress_stream(session_id: str, request: Request):
    """Legacy SSE endpoint - now returns a message to use polling instead"""
    log.info(f"SSE request received for session: {session_id} - redirecting to polling")
    
    async def event_generator():
        yield f"data: {json.dumps({'status': 'deprecated', 'message': 'SSE deprecated, use polling endpoint /progress/{session_id}/status instead'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
            "Access-Control-Allow-Credentials": "true",
            "X-Accel-Buffering": "no",
        }
    )

@router.get("/{session_id}/status")
async def get_session_status(session_id: str, user=Depends(get_verified_user)):
    """Get current status of a session (for polling)"""
    progress_data = get_progress(session_id)
    
    if not progress_data:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    return progress_data

@router.delete("/{session_id}")
async def clear_session_progress(session_id: str, user=Depends(get_verified_user)):
    """Clear progress data for a session"""
    try:
        knowledge_id = session_id
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        
        if not knowledge:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # Remove progress data from meta
        meta = knowledge.meta or {}
        meta.pop("processing_progress", None)
        
        Knowledges.update_knowledge_meta_by_id(knowledge_id, meta)
        
        return {"message": "Progress data cleared successfully"}
        
    except Exception as e:
        log.error(f"Error clearing progress for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear progress data")

# Export functions for use in other modules
__all__ = ["update_progress", "get_progress", "mark_session_complete", "mark_session_error", "update_file_progress"] 
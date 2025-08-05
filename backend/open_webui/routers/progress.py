import asyncio
import json
import time
import logging
from typing import Dict, Optional
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from open_webui.utils.auth import get_verified_user
from open_webui.models.users import Users

log = logging.getLogger(__name__)

router = APIRouter(tags=["progress"])

# In-memory storage for progress tracking
# In production, this should be moved to Redis or database
progress_store: Dict[str, Dict] = {}

def update_progress(session_id: str, progress_data: dict):
    """Update progress for a session"""
    progress_store[session_id] = {
        **progress_data,
        "last_updated": time.time(),
        "active": True
    }
    log.info(f"Progress updated for session {session_id}: {progress_data}")

def get_progress(session_id: str) -> Optional[Dict]:
    """Get current progress for a session"""
    return progress_store.get(session_id)

def mark_session_complete(session_id: str):
    """Mark a session as complete"""
    if session_id in progress_store:
        progress_store[session_id]["active"] = False
        progress_store[session_id]["status"] = "completed"
        log.info(f"Session {session_id} marked as complete")

def mark_session_error(session_id: str, error: str):
    """Mark a session as error"""
    if session_id in progress_store:
        progress_store[session_id]["active"] = False
        progress_store[session_id]["status"] = "error"
        progress_store[session_id]["error"] = error
        log.info(f"Session {session_id} marked as error: {error}")

@router.get("/{session_id}")
async def progress_stream(session_id: str, request: Request):
    log.info(f"SSE request received for session: {session_id}")
    
    # Handle token authentication from URL parameter for SSE
    token = request.query_params.get("token")
    if token:
        log.info(f"Authenticating with token for session: {session_id}")
        # Verify token manually for SSE
        try:
            from open_webui.utils.auth import decode_token
            user_data = decode_token(token)
            if not user_data:
                log.warning(f"Invalid token for session: {session_id}")
                raise HTTPException(status_code=401, detail="Invalid token")
            log.info(f"Token validated for user: {user_data.get('id', 'unknown')}")
            # Token is valid, continue with SSE logic
        except Exception as e:
            log.error(f"Token validation error for session {session_id}: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        log.info(f"No token provided, skipping auth for SSE session: {session_id}")
        # For SSE, we'll skip authentication if no token is provided
        # This allows the connection to establish immediately
        pass
    
    """Stream progress updates for a session using Server-Sent Events"""
    
    async def event_generator():
        try:
            log.info(f"Starting event generator for session: {session_id}")
            # Send immediate response to establish connection
            connecting_data = f"data: {json.dumps({'status': 'connecting', 'message': 'Connecting to progress stream...'})}\n\n"
            log.info(f"Sending connecting message for session {session_id}: {connecting_data.strip()}")
            yield connecting_data
            log.info(f"Sent connecting message for session {session_id}")
            
            # Wait for session to be created if it doesn't exist yet
            wait_count = 0
            while session_id not in progress_store and wait_count < 30:  # Wait up to 30 seconds
                log.info(f"Session {session_id} not found, waiting... (attempt {wait_count + 1}/30)")
                yield f"data: {json.dumps({'status': 'waiting', 'message': 'Waiting for session to be created...'})}\n\n"
                await asyncio.sleep(1)
                wait_count += 1
            
            # Send current progress immediately when client connects
            if session_id in progress_store:
                current_progress = progress_store[session_id]
                initial_data = f"data: {json.dumps(current_progress)}\n\n"
                log.info(f"Sending initial SSE data for session {session_id}: {initial_data.strip()}")
                yield initial_data
                log.info(f"Sent initial progress for session {session_id}")
                
                # If session is already completed or has error, stop immediately
                if current_progress.get("status") in ["completed", "error"] or not current_progress.get("active", False):
                    log.info(f"Session {session_id} already finished, stopping stream immediately")
                    return
            else:
                # Session not found after waiting
                yield f"data: {json.dumps({'status': 'not_found', 'message': 'Session not found after waiting'})}\n\n"
                log.warning(f"Session {session_id} not found after waiting")
                return
            
            # Continue monitoring for updates only if session is still active
            last_progress = None
            while True:
                if session_id in progress_store:
                    progress = progress_store[session_id]
                    
                    # Only send if progress has changed
                    if last_progress is None or progress.get("progress") != last_progress.get("progress") or progress.get("status") != last_progress.get("status") or progress.get("message") != last_progress.get("message"):
                        sse_data = f"data: {json.dumps(progress)}\n\n"
                        log.info(f"Sending SSE data for session {session_id}: {sse_data.strip()}")
                        yield sse_data
                        last_progress = progress.copy()
                        log.info(f"Sent progress update for session {session_id}: {progress.get('status')} - {progress.get('progress')}% - {progress.get('message')}")
                    
                    # Check if session is still active
                    if not progress.get("active", False):
                        log.info(f"Session {session_id} completed, stopping stream")
                        break
                        
                    if progress.get("status") in ["completed", "error"]:
                        log.info(f"Session {session_id} finished with status: {progress.get('status')}")
                        break
                else:
                    # Session was removed
                    yield f"data: {json.dumps({'status': 'not_found', 'message': 'Session was removed'})}\n\n"
                    log.warning(f"Session {session_id} was removed during streaming")
                    break
                    
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            log.info(f"SSE stream cancelled for session {session_id}")
        except Exception as e:
            log.error(f"Error in SSE stream for session {session_id}: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
    
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
    """Get current status of a session (for polling fallback)"""
    if session_id not in progress_store:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return progress_store[session_id]

# Export functions for use in other modules
__all__ = ["update_progress", "get_progress", "mark_session_complete", "mark_session_error"] 
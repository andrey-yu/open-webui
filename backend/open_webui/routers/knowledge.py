from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
import logging

from open_webui.models.knowledge import (
    Knowledges,
    KnowledgeForm,
    KnowledgeResponse,
    KnowledgeUserResponse,
)
from open_webui.models.files import Files, FileModel, FileMetadataResponse
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.routers.retrieval import (
    process_file,
    ProcessFileForm,
    process_files_batch,
    BatchProcessFilesForm,
)
from open_webui.routers.audio import transcribe
from open_webui.storage.provider import Storage
from open_webui.utils.google_drive import google_drive_service
from fnmatch import fnmatch

from open_webui.constants import ERROR_MESSAGES
from open_webui.utils.auth import get_verified_user
from open_webui.utils.access_control import has_access, has_permission


from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.models import Models, ModelForm


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

############################
# getKnowledgeBases
############################


@router.get("/", response_model=list[KnowledgeUserResponse])
async def get_knowledge(user=Depends(get_verified_user)):
    knowledge_bases = []

    if user.role == "admin":
        knowledge_bases = Knowledges.get_knowledge_bases()
    else:
        knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(user.id, "read")

    log.info(f"get_knowledge: Retrieved {len(knowledge_bases)} knowledge bases")
    for kb in knowledge_bases:
        log.info(f"get_knowledge: Knowledge base {kb.id} meta: {kb.meta}")

    # Get files for each knowledge base
    knowledge_with_files = []
    for knowledge_base in knowledge_bases:
        files = []
        if knowledge_base.data:
            files = Files.get_file_metadatas_by_ids(
                knowledge_base.data.get("file_ids", [])
            )

            # Check if all files exist
            if len(files) != len(knowledge_base.data.get("file_ids", [])):
                missing_files = list(
                    set(knowledge_base.data.get("file_ids", []))
                    - set([file.id for file in files])
                )
                if missing_files:
                    data = knowledge_base.data or {}
                    file_ids = data.get("file_ids", [])

                    for missing_file in missing_files:
                        file_ids.remove(missing_file)

                    data["file_ids"] = file_ids
                    Knowledges.update_knowledge_data_by_id(
                        id=knowledge_base.id, data=data
                    )

                    files = Files.get_file_metadatas_by_ids(file_ids)

        knowledge_with_files.append(
            KnowledgeUserResponse(
                **knowledge_base.model_dump(),
                files=files,
            )
        )

    return knowledge_with_files


@router.get("/list", response_model=list[KnowledgeUserResponse])
async def get_knowledge_list(user=Depends(get_verified_user)):
    knowledge_bases = []

    if user.role == "admin":
        knowledge_bases = Knowledges.get_knowledge_bases()
    else:
        knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(user.id, "write")

    # Get files for each knowledge base
    knowledge_with_files = []
    for knowledge_base in knowledge_bases:
        files = []
        if knowledge_base.data:
            files = Files.get_file_metadatas_by_ids(
                knowledge_base.data.get("file_ids", [])
            )

            # Check if all files exist
            if len(files) != len(knowledge_base.data.get("file_ids", [])):
                missing_files = list(
                    set(knowledge_base.data.get("file_ids", []))
                    - set([file.id for file in files])
                )
                if missing_files:
                    data = knowledge_base.data or {}
                    file_ids = data.get("file_ids", [])

                    for missing_file in missing_files:
                        file_ids.remove(missing_file)

                    data["file_ids"] = file_ids
                    Knowledges.update_knowledge_data_by_id(
                        id=knowledge_base.id, data=data
                    )

                    files = Files.get_file_metadatas_by_ids(file_ids)

        knowledge_with_files.append(
            KnowledgeUserResponse(
                **knowledge_base.model_dump(),
                files=files,
            )
        )
    return knowledge_with_files


############################
# CreateNewKnowledge
############################


@router.post("/create", response_model=Optional[KnowledgeResponse])
async def create_new_knowledge(
    request: Request, form_data: KnowledgeForm, user=Depends(get_verified_user)
):
    if user.role != "admin" and not has_permission(
        user.id, "workspace.knowledge", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    knowledge = Knowledges.insert_new_knowledge(user.id, form_data)

    if knowledge:
        return knowledge
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.FILE_EXISTS,
        )


############################
# ReindexKnowledgeFiles
############################


@router.post("/reindex", response_model=bool)
async def reindex_knowledge_files(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    knowledge_bases = Knowledges.get_knowledge_bases()

    log.info(f"Starting reindexing for {len(knowledge_bases)} knowledge bases")

    deleted_knowledge_bases = []

    for knowledge_base in knowledge_bases:
        # -- Robust error handling for missing or invalid data
        if not knowledge_base.data or not isinstance(knowledge_base.data, dict):
            log.warning(
                f"Knowledge base {knowledge_base.id} has no data or invalid data ({knowledge_base.data!r}). Deleting."
            )
            try:
                Knowledges.delete_knowledge_by_id(id=knowledge_base.id)
                deleted_knowledge_bases.append(knowledge_base.id)
            except Exception as e:
                log.error(
                    f"Failed to delete invalid knowledge base {knowledge_base.id}: {e}"
                )
            continue

        try:
            file_ids = knowledge_base.data.get("file_ids", [])
            files = Files.get_files_by_ids(file_ids)
            try:
                if VECTOR_DB_CLIENT.has_collection(collection_name=knowledge_base.id):
                    VECTOR_DB_CLIENT.delete_collection(
                        collection_name=knowledge_base.id
                    )
            except Exception as e:
                log.error(f"Error deleting collection {knowledge_base.id}: {str(e)}")
                continue  # Skip, don't raise

            failed_files = []
            for file in files:
                try:
                    process_file(
                        request,
                        ProcessFileForm(
                            file_id=file.id, collection_name=knowledge_base.id
                        ),
                        user=user,
                    )
                except Exception as e:
                    log.error(
                        f"Error processing file {file.filename} (ID: {file.id}): {str(e)}"
                    )
                    failed_files.append({"file_id": file.id, "error": str(e)})
                    continue

        except Exception as e:
            log.error(f"Error processing knowledge base {knowledge_base.id}: {str(e)}")
            # Don't raise, just continue
            continue

        if failed_files:
            log.warning(
                f"Failed to process {len(failed_files)} files in knowledge base {knowledge_base.id}"
            )
            for failed in failed_files:
                log.warning(f"File ID: {failed['file_id']}, Error: {failed['error']}")

    log.info(
        f"Reindexing completed. Deleted {len(deleted_knowledge_bases)} invalid knowledge bases: {deleted_knowledge_bases}"
    )
    return True


############################
# GetKnowledgeById
############################


class KnowledgeFilesResponse(KnowledgeResponse):
    files: list[FileMetadataResponse]
    warnings: Optional[dict] = None

class KnowledgeFilesResponseWithSession(KnowledgeFilesResponse):
    session_id: Optional[str] = None
# Background worker for Google Drive folder processing
async def process_google_drive_folder_complete(
    request: Request,
    knowledge_id: str,
    session_id: str,
    user_id: str,
    files: list[dict],
    oauth_token: str,
):
    """Process a Google Drive folder end-to-end in the background."""
    from open_webui.routers.progress import update_file_progress, mark_session_complete, mark_session_error
    from open_webui.models.files import Files, FileForm
    try:
        # Minimal user object for downstream calls that only require user.id
        class MockUser:
            def __init__(self, uid: str):
                self.id = uid

        mock_user = MockUser(user_id)

        successful_files: list[str] = []
        failed_files: list[dict] = []

        batch_size = 5
        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            for file_info in batch:
                import uuid
                storage_file_id = str(uuid.uuid4())
                filename = file_info.get("name", "unknown")

                try:
                    update_file_progress(session_id, {
                        "status": "processing",
                        "progress": 10,
                        "message": f"Downloading {filename}",
                        "current_file": filename
                    })

                    file_content, filename, mime_type = google_drive_service.download_file(
                        file_info["id"], oauth_token
                    )

                    update_file_progress(session_id, {
                        "status": "processing",
                        "progress": 30,
                        "message": f"Uploading {filename}",
                        "current_file": filename
                    })

                    from io import BytesIO
                    file_obj = BytesIO(file_content)
                    file_obj.name = filename

                    tags = {
                        "OpenWebUI-User-Id": user_id,
                        "OpenWebUI-File-Id": storage_file_id,
                        "OpenWebUI-Source": "google-drive",
                    }
                    contents, file_path = Storage.upload_file(file_obj, f"{storage_file_id}_{filename}", tags)

                    update_file_progress(session_id, {
                        "status": "processing",
                        "progress": 50,
                        "message": f"Creating file record for {filename}",
                        "current_file": filename
                    })

                    file_item = Files.insert_new_file(
                        user_id,
                        FileForm(
                            **{
                                "id": storage_file_id,
                                "filename": filename,
                                "path": file_path,
                                "meta": {
                                    "name": filename,
                                    "content_type": mime_type,
                                    "size": len(contents),
                                    "data": {"source": "google-drive", "file_id": file_info["id"]},
                                },
                            }
                        ),
                    )

                    # Dedup checks
                    existing_docs = VECTOR_DB_CLIENT.query(
                        collection_name=knowledge_id,
                        filter={"file_id": storage_file_id},
                    )
                    if existing_docs is not None and existing_docs.ids[0]:
                        update_file_progress(session_id, {
                            "status": "completed",
                            "progress": 100,
                            "message": f"Skipped {filename} (already exists)",
                            "current_file": filename
                        })
                        successful_files.append(storage_file_id)
                        continue

                    existing_docs_by_name = VECTOR_DB_CLIENT.query(
                        collection_name=knowledge_id,
                        filter={"name": filename},
                    )
                    if existing_docs_by_name is not None and existing_docs_by_name.ids[0]:
                        update_file_progress(session_id, {
                            "status": "completed",
                            "progress": 100,
                            "message": f"Skipped {filename} (already exists)",
                            "current_file": filename
                        })
                        successful_files.append(storage_file_id)
                        continue

                    # Transcribe or process
                    if mime_type and mime_type.startswith(("video/", "audio/")):
                        update_file_progress(session_id, {
                            "status": "transcribing",
                            "progress": 70,
                            "message": f"Transcribing {filename}",
                            "current_file": filename
                        })

                        actual_path = Storage.get_file(file_path)
                        # Run sync transcription in thread to allow async progress loop
                        import threading, time
                        transcription_result = None
                        transcription_error = None
                        def run_transcription():
                            nonlocal transcription_result, transcription_error
                            try:
                                transcription_result = transcribe(request, actual_path, {"source": "google-drive"})
                            except Exception as e:
                                transcription_error = e
                        t = threading.Thread(target=run_transcription)
                        t.start()

                        start_time = time.time()
                        while t.is_alive():
                            elapsed = time.time() - start_time
                            est = min(75 + int((elapsed / 30) * 10), 95)
                            update_file_progress(session_id, {
                                "status": "transcribing",
                                "progress": est,
                                "message": f"Transcribing {filename}... ({int(elapsed)}s elapsed)",
                                "current_file": filename
                            })
                            import asyncio
                            await asyncio.sleep(2)

                        if transcription_error:
                            raise ValueError(f"Failed to transcribe audio/video file: {transcription_error}")

                        result = transcription_result or {}
                        update_file_progress(session_id, {
                            "status": "transcribing",
                            "progress": 78,
                            "message": f"Transcription completed for {filename}",
                            "current_file": filename
                        })

                        update_file_progress(session_id, {
                            "status": "processing",
                            "progress": 90,
                            "message": f"Processing {filename}",
                            "current_file": filename
                        })

                        transcription_text = result.get("text", "").strip()
                        if not transcription_text:
                            raise ValueError("Transcription resulted in empty content")

                        segments = result.get("segments", [])
                        from langchain_core.documents import Document
                        from open_webui.routers.retrieval import save_docs_to_vector_db
                        doc = Document(
                            page_content=transcription_text,
                            metadata={
                                "name": filename,
                                "file_id": storage_file_id,
                                "source": filename,
                                "segments": segments,
                                "content_type": mime_type,
                                "transcription_source": "google_drive",
                            },
                        )
                        save_docs_to_vector_db(
                            request=request,
                            docs=[doc],
                            collection_name=knowledge_id,
                            metadata={
                                "file_id": storage_file_id,
                                "name": filename,
                                "content_type": mime_type,
                                "transcription_source": "google_drive",
                            },
                            add=True,
                            user=mock_user,
                        )

                        file_rec = Files.get_file_by_id(storage_file_id)
                        if file_rec:
                            data = file_rec.data or {}
                            data["content"] = transcription_text
                            Files.update_file_data_by_id(storage_file_id, data)
                    else:
                        update_file_progress(session_id, {
                            "status": "processing",
                            "progress": 70,
                            "message": f"Processing {filename}",
                            "current_file": filename
                        })
                        process_file(
                            request,
                            ProcessFileForm(file_id=storage_file_id, collection_name=knowledge_id),
                            user=mock_user,
                        )

                    update_file_progress(session_id, {
                        "status": "completed",
                        "progress": 100,
                        "message": f"Completed {filename}",
                        "current_file": filename
                    })

                    successful_files.append(storage_file_id)
                except Exception as e:
                    update_file_progress(session_id, {
                        "status": "error",
                        "progress": 0,
                        "message": None,
                        "error": str(e),
                        "current_file": filename
                    })
                    failed_files.append({"name": filename, "error": str(e)})

        # Complete session and update knowledge
        mark_session_complete(session_id)
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])
        for fid in successful_files:
            if fid not in file_ids:
                file_ids.append(fid)
        data["file_ids"] = file_ids
        Knowledges.update_knowledge_data_by_id(id=knowledge_id, data=data)
    except Exception as e:
        log.error(f"Error in process_google_drive_folder_complete: {e}")
        try:
            mark_session_error(session_id, str(e))
        except Exception:
            pass


@router.get("/{id}", response_model=Optional[KnowledgeFilesResponse])
async def get_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    
    log.info(f"get_knowledge_by_id: Retrieved knowledge for ID {id}")
    if knowledge:
        log.info(f"get_knowledge_by_id: Knowledge meta field: {knowledge.meta}")
        log.info(f"get_knowledge_by_id: Knowledge data field: {knowledge.data}")

        if (
            user.role == "admin"
            or knowledge.user_id == user.id
            or has_access(user.id, "read", knowledge.access_control)
        ):

            file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
            files = Files.get_file_metadatas_by_ids(file_ids)

            response = KnowledgeFilesResponse(
                **knowledge.model_dump(),
                files=files,
            )
            log.info(f"get_knowledge_by_id: Returning response with meta: {response.meta}")
            return response
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# UpdateKnowledgeById
############################


@router.post("/{id}/update", response_model=Optional[KnowledgeFilesResponse])
async def update_knowledge_by_id(
    id: str,
    form_data: KnowledgeForm,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    # Is the user the original creator, in a group with write access, or an admin
    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    knowledge = Knowledges.update_knowledge_by_id(id=id, form_data=form_data)
    if knowledge:
        file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
        files = Files.get_files_by_ids(file_ids)

        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=files,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ID_TAKEN,
        )


############################
# AddFileToKnowledge
############################


class KnowledgeFileIdForm(BaseModel):
    file_id: str


class GoogleDriveFileForm(BaseModel):
    file_id: str
    oauth_token: str


class GoogleDriveFolderForm(BaseModel):
    folder_id: str
    oauth_token: str
    recursive: bool = True


@router.post("/{id}/file/add", response_model=Optional[KnowledgeFilesResponse])
def add_file_to_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    log.info(f"=== FILE ADDITION START === Knowledge ID: {id}, File ID: {form_data.file_id}")
    
    knowledge = Knowledges.get_knowledge_by_id(id=id)

    if not knowledge:
        log.error(f"Knowledge base not found: {id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    log.info(f"Knowledge base found: {knowledge.name} (user_id: {knowledge.user_id})")

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        log.error(f"Access denied for user {user.id} to knowledge base {id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        log.error(f"File not found: {form_data.file_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    log.info(f"File found: {file.filename} (path: {file.path})")
    
    if not file.data:
        log.error(f"File {form_data.file_id} has no data (not processed)")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.FILE_NOT_PROCESSED,
        )

    log.info(f"File data exists, content length: {len(file.data.get('content', ''))}")

    # Add content to the vector database
    log.info(f"Calling process_file with collection_name={id}")
    try:
        process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
        )
        log.info(f"Successfully processed file {form_data.file_id} for collection {id}")
    except Exception as e:
        log.error(f"Error processing file {form_data.file_id}: {str(e)}")
        log.debug(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if knowledge:
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])
        log.info(f"Current file_ids in knowledge base: {file_ids}")

        if form_data.file_id not in file_ids:
            file_ids.append(form_data.file_id)
            data["file_ids"] = file_ids
            log.info(f"Updated file_ids after addition: {file_ids}")

            knowledge = Knowledges.update_knowledge_data_by_id(id=id, data=data)
            log.info(f"Successfully updated knowledge base data")

            if knowledge:
                files = Files.get_file_metadatas_by_ids(file_ids)
                log.info(f"Retrieved {len(files)} files for knowledge base")

                log.info(f"=== FILE ADDITION COMPLETE === Knowledge ID: {id}, File ID: {form_data.file_id}")
                return KnowledgeFilesResponse(
                    **knowledge.model_dump(),
                    files=files,
                )
            else:
                log.error(f"Failed to update knowledge base: {id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("knowledge"),
                )
        else:
            log.warning(f"File ID {form_data.file_id} already exists in knowledge base file_ids: {file_ids}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("file_id"),
            )
    else:
        log.error(f"Knowledge base not found after update: {id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.post("/{id}/file/update", response_model=Optional[KnowledgeFilesResponse])
def update_file_from_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Remove content from the vector database
    VECTOR_DB_CLIENT.delete(
        collection_name=knowledge.id, filter={"file_id": form_data.file_id}
    )

    # Add content to the vector database
    try:
        process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if knowledge:
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])

        files = Files.get_file_metadatas_by_ids(file_ids)

        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=files,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# RemoveFileFromKnowledge
############################


@router.post("/{id}/file/remove", response_model=Optional[KnowledgeFilesResponse])
def remove_file_from_knowledge_by_id(
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    log.info(f"=== FILE REMOVAL START === Knowledge ID: {id}, File ID: {form_data.file_id}")
    
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        log.error(f"Knowledge base not found: {id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    log.info(f"Knowledge base found: {knowledge.name} (user_id: {knowledge.user_id})")

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        log.error(f"Access denied for user {user.id} to knowledge base {id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        log.error(f"File not found: {form_data.file_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    log.info(f"File found: {file.filename} (path: {file.path})")

    # Remove content from the vector database
    log.info(f"Attempting to delete vector DB entries for file {form_data.file_id} from collection {knowledge.id}")
    try:
        VECTOR_DB_CLIENT.delete(
            collection_name=knowledge.id, filter={"file_id": form_data.file_id}
        )
        log.info(f"Successfully deleted vector DB entries for file {form_data.file_id} from collection {knowledge.id}")
    except Exception as e:
        log.debug("This was most likely caused by bypassing embedding processing")
        log.debug(e)
        pass

    try:
        # Remove the file's collection from vector database
        file_collection = f"file-{form_data.file_id}"
        log.info(f"Checking if file collection exists: {file_collection}")
        if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
            log.info(f"Deleting file collection: {file_collection}")
            VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
            log.info(f"Successfully deleted file collection: {file_collection}")
        else:
            log.info(f"File collection does not exist: {file_collection}")
    except Exception as e:
        log.debug("This was most likely caused by bypassing embedding processing")
        log.debug(e)
        pass

    # Delete file from storage and database
    log.info(f"Deleting file from storage: {file.path}")
    try:
        Storage.delete_file_and_related(file.path)
        log.info(f"Successfully deleted file from storage: {file.path}")
    except Exception as e:
        log.warning(f"Failed to delete file and related files from storage: {e}")
    
    log.info(f"Deleting file record from database: {form_data.file_id}")
    Files.delete_file_by_id(form_data.file_id)
    log.info(f"Successfully deleted file record from database: {form_data.file_id}")

    if knowledge:
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])
        log.info(f"Current file_ids in knowledge base: {file_ids}")

        if form_data.file_id in file_ids:
            file_ids.remove(form_data.file_id)
            data["file_ids"] = file_ids
            log.info(f"Updated file_ids after removal: {file_ids}")

            knowledge = Knowledges.update_knowledge_data_by_id(id=id, data=data)
            log.info(f"Successfully updated knowledge base data")

            if knowledge:
                files = Files.get_file_metadatas_by_ids(file_ids)
                log.info(f"Retrieved {len(files)} remaining files for knowledge base")

                log.info(f"=== FILE REMOVAL COMPLETE === Knowledge ID: {id}, File ID: {form_data.file_id}")
                return KnowledgeFilesResponse(
                    **knowledge.model_dump(),
                    files=files,
                )
            else:
                log.error(f"Failed to update knowledge base: {id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("knowledge"),
                )
        else:
            log.error(f"File ID {form_data.file_id} not found in knowledge base file_ids: {file_ids}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("file_id"),
            )
    else:
        log.error(f"Knowledge base not found after update: {id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# DeleteKnowledgeById
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f"Deleting knowledge base: {id} (name: {knowledge.name})")

    # Get all models
    models = Models.get_all_models()
    log.info(f"Found {len(models)} models to check for knowledge base {id}")

    # Update models that reference this knowledge base
    for model in models:
        if model.meta and hasattr(model.meta, "knowledge"):
            knowledge_list = model.meta.knowledge or []
            # Filter out the deleted knowledge base
            updated_knowledge = [k for k in knowledge_list if k.get("id") != id]

            # If the knowledge list changed, update the model
            if len(updated_knowledge) != len(knowledge_list):
                log.info(f"Updating model {model.id} to remove knowledge base {id}")
                model.meta.knowledge = updated_knowledge
                # Create a ModelForm for the update
                model_form = ModelForm(
                    id=model.id,
                    name=model.name,
                    base_model_id=model.base_model_id,
                    meta=model.meta,
                    params=model.params,
                    access_control=model.access_control,
                    is_active=model.is_active,
                )
                Models.update_model_by_id(model.id, model_form)

    # Get all file IDs from the knowledge base
    file_ids = []
    if knowledge.data and knowledge.data.get("file_ids"):
        file_ids = knowledge.data.get("file_ids", [])
    
    log.info(f"Found {len(file_ids)} files in knowledge base {id}")

    # Clean up vector DB
    try:
        VECTOR_DB_CLIENT.delete_collection(collection_name=id)
    except Exception as e:
        log.debug(e)
        pass

    # Check which files are used by other knowledge bases and delete orphaned files
    if file_ids:
        # Get all knowledge bases to check file usage
        all_knowledge_bases = Knowledges.get_knowledge_bases()
        
        # Collect all file IDs used by other knowledge bases
        files_used_by_others = set()
        for kb in all_knowledge_bases:
            if kb.id != id and kb.data and kb.data.get("file_ids"):
                files_used_by_others.update(kb.data.get("file_ids", []))
        
        # Find orphaned files (files only used by this knowledge base)
        orphaned_file_ids = [file_id for file_id in file_ids if file_id not in files_used_by_others]
        
        log.info(f"Found {len(orphaned_file_ids)} orphaned files to delete")
        
        # Delete orphaned files from storage and database
        for file_id in orphaned_file_ids:
            try:
                file = Files.get_file_by_id(file_id)
                if file:
                    # Delete from storage
                    try:
                        Storage.delete_file_and_related(file.path)
                        log.info(f"Deleted orphaned file from storage: {file.filename}")
                    except Exception as e:
                        log.warning(f"Failed to delete orphaned file from storage {file.filename}: {e}")
                    
                    # Delete from vector database
                    try:
                        file_collection = f"file-{file_id}"
                        if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
                            VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
                            log.info(f"Deleted orphaned file collection from vector DB: {file_collection}")
                    except Exception as e:
                        log.debug(f"Failed to delete orphaned file collection {file_collection}: {e}")
                    
                    # Delete from database
                    Files.delete_file_by_id(file_id)
                    log.info(f"Deleted orphaned file from database: {file.filename}")
                else:
                    log.warning(f"Orphaned file {file_id} not found in database")
            except Exception as e:
                log.error(f"Error deleting orphaned file {file_id}: {e}")

    result = Knowledges.delete_knowledge_by_id(id=id)
    return result


############################
# ResetKnowledgeById
############################


@router.post("/{id}/reset", response_model=Optional[KnowledgeResponse])
async def reset_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        VECTOR_DB_CLIENT.delete_collection(collection_name=id)
    except Exception as e:
        log.debug(e)
        pass

    knowledge = Knowledges.update_knowledge_data_by_id(id=id, data={"file_ids": []})

    return knowledge


############################
# AddFilesToKnowledge
############################


@router.post("/{id}/files/batch/add", response_model=Optional[KnowledgeFilesResponse])
def add_files_to_knowledge_batch(
    request: Request,
    id: str,
    form_data: list[KnowledgeFileIdForm],
    user=Depends(get_verified_user),
):
    """
    Add multiple files to a knowledge base
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Get files content
    log.info(f"files/batch/add - {len(form_data)} files")
    files: List[FileModel] = []
    for form in form_data:
        file = Files.get_file_by_id(form.file_id)
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {form.file_id} not found",
            )
        files.append(file)

    # Process files
    try:
        result = process_files_batch(
            request=request,
            form_data=BatchProcessFilesForm(files=files, collection_name=id),
            user=user,
        )
    except Exception as e:
        log.error(
            f"add_files_to_knowledge_batch: Exception occurred: {e}", exc_info=True
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Add successful files to knowledge base
    data = knowledge.data or {}
    existing_file_ids = data.get("file_ids", [])

    # Only add files that were successfully processed
    successful_file_ids = [r.file_id for r in result.results if r.status == "completed"]
    skipped_file_ids = [r.file_id for r in result.results if r.status == "skipped"]
    
    for file_id in successful_file_ids:
        if file_id not in existing_file_ids:
            existing_file_ids.append(file_id)

    data["file_ids"] = existing_file_ids
    knowledge = Knowledges.update_knowledge_data_by_id(id=id, data=data)

    # Prepare response with appropriate warnings
    warnings = {}
    if result.errors:
        error_details = [f"{err.file_id}: {err.error}" for err in result.errors]
        warnings["message"] = "Some files failed to process"
        warnings["errors"] = error_details
    
    if skipped_file_ids:
        skipped_details = [f"{file_id}: File already exists in collection" for file_id in skipped_file_ids]
        if warnings:
            warnings["message"] = "Some files failed to process and some were skipped"
            warnings["skipped"] = skipped_details
        else:
            warnings["message"] = "Some files were skipped (already exist in collection)"
            warnings["skipped"] = skipped_details

    if warnings:
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=Files.get_file_metadatas_by_ids(existing_file_ids),
            warnings=warnings,
        )

    return KnowledgeFilesResponse(
        **knowledge.model_dump(),
        files=Files.get_file_metadatas_by_ids(existing_file_ids),
    )


############################
# Background Tasks
############################

async def process_google_drive_file_complete(
    request: Request,
    knowledge_id: str,
    session_id: str,
    progress_file_id: str,
    user_id: str,
    form_data_file_id: str,
    oauth_token: str
):
    """Process a Google Drive file completely in the background"""
    from open_webui.routers.progress import update_file_progress, mark_session_complete, mark_session_error
    from open_webui.routers.retrieval import process_file, ProcessFileForm
    from open_webui.models.users import Users
    from open_webui.models.files import Files, FileForm
    from open_webui.models.knowledge import Knowledges
    from open_webui.storage.provider import Storage
    import uuid
    
    try:
        # Create a mock user object for the background task
        class MockUser:
            def __init__(self, user_id):
                self.id = user_id
        
        mock_user = MockUser(user_id)
        
        # Update progress to show starting
        update_file_progress(session_id, {
            "status": "processing",
            "progress": 0,
            "message": "Starting file processing"
        })
        
        # Download file from Google Drive
        update_file_progress(session_id, {
            "status": "processing",
            "progress": 20,
            "message": "Downloading file from Google Drive"
        })
        
        file_content, filename, mime_type = google_drive_service.download_file(
            form_data_file_id, oauth_token
        )

        update_file_progress(session_id, {
            "status": "processing",
            "progress": 40,
            "message": "Uploading file to storage"
        })

        # Create a temporary file-like object
        from io import BytesIO
        file_obj = BytesIO(file_content)
        file_obj.name = filename

        # Upload file using existing storage provider
        storage_file_id = str(uuid.uuid4())
        tags = {
            "OpenWebUI-User-Email": "background_task",  # We don't have user email in background
            "OpenWebUI-User-Id": user_id,
            "OpenWebUI-User-Name": "background_task",  # We don't have user name in background
            "OpenWebUI-File-Id": progress_file_id,
            "OpenWebUI-Source": "google-drive",
        }

        contents, file_path = Storage.upload_file(file_obj, f"{storage_file_id}_{filename}", tags)

        update_file_progress(session_id, {
            "status": "processing",
            "progress": 60,
            "message": "Creating file record"
        })

        # Create file record
        file_form = FileForm(
            id=storage_file_id,
            filename=filename,
            path=file_path,
            meta={"content_type": mime_type, "size": len(file_content), "name": filename},
        )
        file = Files.insert_new_file(user_id, file_form)

        # Handle different file types
        if mime_type:
            stt_supported_content_types = getattr(
                request.app.state.config, "STT_SUPPORTED_CONTENT_TYPES", []
            )

            # Check if file is video/audio
            is_video_audio = mime_type.startswith(("video/", "audio/"))

            if is_video_audio:
                # For video/audio files, start transcription
                log.info(f"Starting transcription for file {file.id} with mime_type {mime_type}")
                
                # Get the actual file path for transcription
                actual_file_path = Storage.get_file(file_path)
                log.info(f"File path for transcription: {actual_file_path}")
                
                # Start transcription in background
                await process_transcription_completion(
                    request=request,
                    knowledge_id=knowledge_id,
                    file_id=file.id,
                    file_path=actual_file_path,
                    session_id=session_id,
                    progress_file_id=progress_file_id,
                    user_id=user_id,
                    mime_type=mime_type,
                    filename=filename,
                    form_data_file_id=form_data_file_id
                )
                
            elif (not mime_type.startswith(("image/", "video/"))) or (
                request.app.state.config.CONTENT_EXTRACTION_ENGINE == "external"
            ):
                # For other files, process normally
                log.info(f"Processing regular file {file.id} with mime_type {mime_type}")
                
                # Check if it's a PDF and provide helpful information
                if mime_type == "application/pdf":
                    log.info(f"Processing PDF file {file.id} ({filename})")
                
                # Update progress to show processing starting
                update_file_progress(session_id, {
                    "status": "processing",
                    "progress": 80,
                    "message": "Processing file content"
                })
                
                # Process the file
                process_file(
                    request,
                    ProcessFileForm(file_id=file.id, collection_name=knowledge_id),
                    user=mock_user,
                )
                
                # Clean up local files after successful processing
                # Keep GCS files and DB entries, remove only local files
                try:
                    from open_webui.storage.provider import LocalStorageProvider
                    LocalStorageProvider.delete_file_and_related(file_path)
                    log.info(f"Cleaned up local files for {file.id} after successful processing")
                except Exception as cleanup_error:
                    log.warning(f"Failed to clean up local files for {file.id}: {cleanup_error}")
                
                # Update progress to show completion
                update_file_progress(session_id, {
                    "status": "completed",
                    "progress": 100,
                    "message": "File processed successfully"
                })
                
            else:
                # For unsupported video/image files, skip processing
                log.info(f"File type {mime_type} is not supported for processing")
                
                update_file_progress(session_id, {
                    "status": "completed",
                    "progress": 100,
                    "message": "File type not supported for processing"
                })
        else:
            # If no content type, try to process anyway
            log.info(f"File type {mime_type} is not provided, but trying to process anyway")
            
            update_file_progress(session_id, {
                "status": "processing",
                "progress": 80,
                "message": "Processing file content"
            })
            
            # Process the file
            process_file(
                request,
                ProcessFileForm(file_id=file.id, collection_name=knowledge_id),
                user=mock_user,
            )
            
            # Clean up local files after successful processing
            # Keep GCS files and DB entries, remove only local files
            try:
                from open_webui.storage.provider import LocalStorageProvider
                LocalStorageProvider.delete_file_and_related(file_path)
                log.info(f"Cleaned up local files for {file.id} after successful processing")
            except Exception as cleanup_error:
                log.warning(f"Failed to clean up local files for {file.id}: {cleanup_error}")
            
            update_file_progress(session_id, {
                "status": "completed",
                "progress": 100,
                "message": "File processed successfully"
            })

        # Add file to knowledge base
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])
        
        if file.id not in file_ids:
            file_ids.append(file.id)
            data["file_ids"] = file_ids
            Knowledges.update_knowledge_data_by_id(id=knowledge_id, data=data)
        
        mark_session_complete(session_id)
        log.info(f"Google Drive file processing completed for file {file.id}")
        
    except Exception as e:
        log.error(f"Error processing Google Drive file: {e}")
        mark_session_error(session_id, str(e))
        raise

async def process_regular_file_completion(
    request: Request,
    knowledge_id: str,
    file_id: str,
    session_id: str,
    progress_file_id: str,
    user_id: str,
    mime_type: str,
    filename: str,
    form_data_file_id: str
):
    """Process a regular file (non-video/audio) in the background"""
    from open_webui.routers.progress import update_file_progress, mark_session_complete, mark_session_error
    from open_webui.routers.retrieval import process_file, ProcessFileForm
    from open_webui.models.users import Users
    
    try:
        # Create a mock user object for the background task
        class MockUser:
            def __init__(self, user_id):
                self.id = user_id
        
        mock_user = MockUser(user_id)
        
        # Update progress to show processing starting
        update_file_progress(session_id, {
            "status": "processing",
            "progress": 80,
            "message": "Processing file content"
        })
        
        # Process the file
        process_file(
            request,
            ProcessFileForm(file_id=file_id, collection_name=knowledge_id),
            user=mock_user,
        )
        
        # Update progress to show completion
        update_file_progress(session_id, {
            "status": "completed",
            "progress": 100,
            "message": "File processed successfully"
        })
        
        mark_session_complete(session_id)
        log.info(f"Regular file processing completed for file {file_id}")
        
    except Exception as e:
        log.error(f"Error processing regular file {file_id}: {e}")
        mark_session_error(session_id, str(e))
        raise

async def process_transcription_completion(
    request: Request,
    knowledge_id: str,
    file_id: str,
    file_path: str,
    session_id: str,
    progress_file_id: str,
    user_id: str,
    mime_type: str,
    filename: str,
    form_data_file_id: str
):
    """
    Background task to handle transcription completion and file processing
    """
    from open_webui.routers.progress import update_file_progress, mark_session_complete, mark_session_error
    
    try:
        log.info(f"Starting transcription for file {file_id} with mime_type {mime_type}")
        
        # Update progress to show transcription starting
        update_file_progress(session_id, {
            "status": "transcribing",
            "progress": 80,
            "message": "Transcribing audio/video file"
        })
        
        log.info(f"File path for transcription: {file_path}")
        
        # Start transcription in a background task to allow progress updates
        import asyncio
        import threading
        import time
        
        # Create a future to hold the transcription result
        transcription_future = None
        
        def run_transcription():
            nonlocal transcription_future
            try:
                transcription_future = transcribe(request, file_path, {"source": "google-drive"})
            except Exception as e:
                transcription_future = {"error": str(e)}
        
        # Start transcription in a thread
        transcription_thread = threading.Thread(target=run_transcription)
        transcription_thread.start()
        
        # Send periodic progress updates during transcription
        start_time = time.time()
        while transcription_thread.is_alive():
            elapsed = time.time() - start_time
            # Estimate progress based on elapsed time (assuming 30 seconds for transcription)
            estimated_progress = min(85 + int((elapsed / 30) * 10), 95)
            
            update_progress(session_id, {
                "session_id": session_id,
                "file_id": progress_file_id,
                "status": "transcribing",
                "progress": estimated_progress,
                "message": f"Transcribing audio... ({int(elapsed)}s elapsed)",
                "total_files": 1,
                "file_list": [form_data_file_id]
            })
            
            # Use non-blocking sleep to avoid blocking the event loop
            import asyncio
            await asyncio.sleep(2)  # Update every 2 seconds
        
        # Get the transcription result
        if transcription_future and "error" in transcription_future:
            raise ValueError(transcription_future["error"])
        
        result = transcription_future
        log.info(f"Transcription completed for file {file_id}")
        
        # Update progress to show transcription completed
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "transcribing",
            "progress": 88,
            "message": "Transcription completed",
            "total_files": 1,
            "file_list": [form_data_file_id]
        })

        
        # Process the transcribed content
        log.info(f"Starting processing for transcribed file {file_id}")
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "processing",
            "progress": 90,
            "message": "Processing transcribed content",
            "total_files": 1,
            "file_list": [form_data_file_id]
        })

        
        # Check if transcription result has content
        transcription_text = result.get("text", "").strip()
        if not transcription_text:
            raise ValueError("Transcription resulted in empty content")
        
        # Get timestamp segments if available
        segments = result.get("segments", [])
        
        # Process the file with transcribed content
        # Create a mock user object for the background task
        class MockUser:
            def __init__(self, user_id):
                self.id = user_id
        
        mock_user = MockUser(user_id)
        
        # Create document with timestamp information
        from langchain_core.documents import Document
        from open_webui.routers.retrieval import save_docs_to_vector_db
        
        doc = Document(
            page_content=transcription_text,
            metadata={
                "name": filename,
                "file_id": file_id,
                "source": filename,
                "segments": segments,  # Include timestamp segments
                "content_type": mime_type,
                "transcription_source": "audio_video"
            }
        )
        
        # Save document to vector database with timestamp information
        # Check for duplicates before saving
        log.info(f"Checking for existing document with file_id: {file_id} in collection {knowledge_id}")
        existing_docs = VECTOR_DB_CLIENT.query(
            collection_name=knowledge_id,
            filter={"file_id": file_id},
        )

        if existing_docs is not None and existing_docs.ids[0]:
            log.info(f"Document with file_id {file_id} already exists in collection {knowledge_id}, skipping file")
            # Skip this file but continue
            return

        # Fallback: Check by filename for files added before file_id metadata was consistent
        log.info(f"Checking for existing document with filename: {filename} in collection {knowledge_id}")
        existing_docs_by_name = VECTOR_DB_CLIENT.query(
            collection_name=knowledge_id,
            filter={"name": filename},
        )

        if existing_docs_by_name is not None and existing_docs_by_name.ids[0]:
            log.info(f"Document with filename {filename} already exists in collection {knowledge_id}, skipping file")
            # Skip this file but continue
            return

        save_docs_to_vector_db(
            request=request,
            docs=[doc],
            collection_name=knowledge_id,
            metadata={
                "file_id": file_id,
                "name": filename,
                "content_type": mime_type,
                "transcription_source": "audio_video"
            },
            add=True,
            user=mock_user
        )
        
        # Update the file's content field with the transcribed text
        from open_webui.models.files import Files
        file = Files.get_file_by_id(file_id)
        if file:
            data = file.data or {}
            data["content"] = transcription_text
            Files.update_file_data_by_id(file_id, data)
            log.info(f"Updated file content for {file_id}")
        
        log.info(f"Processing completed for file {file_id}")
        
        # Clean up local files after successful processing
        # Keep GCS files and DB entries, remove only local files
        try:
            from open_webui.storage.provider import LocalStorageProvider
            LocalStorageProvider.delete_file_and_related(file_path)
            log.info(f"Cleaned up local files for {file_id} after successful processing")
        except Exception as cleanup_error:
            log.warning(f"Failed to clean up local files for {file_id}: {cleanup_error}")
        
        # Update progress to show completion
        update_file_progress(session_id, {
            "status": "completed",
            "progress": 100,
            "message": "File processed successfully"
        })

        
        # Complete progress tracking session
        mark_session_complete(session_id)
        
        # Add file to knowledge base
        knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
        if knowledge:
            data = knowledge.data or {}
            file_ids = data.get("file_ids", [])
            
            if file_id not in file_ids:
                file_ids.append(file_id)
                data["file_ids"] = file_ids
                Knowledges.update_knowledge_data_by_id(id=knowledge_id, data=data)
        
        log.info(f"Background transcription processing completed for file {file_id}")
        
    except Exception as e:
        log.error(f"Error in background transcription processing for file {file_id}: {str(e)}")
        
        # Update progress to show error
        update_file_progress(session_id, {
            "status": "error",
            "progress": 0,
            "message": None,
            "error": str(e)
        })
        
        mark_session_error(session_id, str(e))


############################
# Google Drive Integration
############################


@router.post("/{id}/google-drive/file", response_model=Optional[KnowledgeFilesResponseWithSession])
async def add_google_drive_file_to_knowledge(
    request: Request,
    background_tasks: BackgroundTasks,
    id: str,
    form_data: GoogleDriveFileForm,
    user=Depends(get_verified_user),
):
    """
    Add a single file from Google Drive to a knowledge base
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        # Clean up uploads folder before downloading from Google Drive
        from open_webui.utils.upload_cleanup import cleanup_uploads_folder
        cleanup_result = cleanup_uploads_folder()
        log.info(f"Uploads cleanup before Google Drive download: {cleanup_result}")
        
        # Import progress tracking functions
        from open_webui.routers.progress import update_file_progress, mark_session_complete, mark_session_error
        
        # Start progress tracking session for single file
        import uuid
        session_id = str(uuid.uuid4())
        file_id = str(uuid.uuid4())  # Generate file ID for progress tracking
        
        # Initialize progress tracking for the session
        update_file_progress(session_id, {
            "status": "processing",
            "progress": 0,
            "message": "Starting file processing"
        })
        
        # Add comprehensive background task for all file processing
        # Use a thread pool to ensure it doesn't block the event loop
        import threading
        
        def run_in_thread():
            # Create a new event loop for this thread
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(process_google_drive_file_complete(
                    request=request,
                    knowledge_id=id,
                    session_id=session_id,
                    progress_file_id=file_id,
                    user_id=user.id,
                    form_data_file_id=form_data.file_id,
                    oauth_token=form_data.oauth_token
                ))
            finally:
                loop.close()
        
        # Start the background task in a separate thread
        thread = threading.Thread(target=run_in_thread)
        thread.daemon = True
        thread.start()
        
        # Return immediately with session ID for progress tracking
        # All file processing will happen in the background
        return KnowledgeFilesResponseWithSession(
            **knowledge.model_dump(),
            files=[],
            session_id=session_id
        )

    except Exception as e:
        # Handle exceptions
        if 'session_id' in locals() and 'file_id' in locals():
            update_file_progress(session_id, {
                "status": "error",
                "progress": 0,
                "message": None,
                "error": str(e)
            })
            mark_session_error(session_id, str(e))
        
        # Log the actual error for debugging
        log.error(f"Error in add_google_drive_file_to_knowledge for user {user.id}: {str(e)}")
        raise ValueError(f"Failed to add Google Drive file: {str(e)}")


@router.post("/{id}/google-drive/folder", response_model=Optional[KnowledgeFilesResponseWithSession])
async def add_google_drive_folder_to_knowledge(
    request: Request,
    id: str,
    form_data: GoogleDriveFolderForm,
    user=Depends(get_verified_user),
):
    """
    Add all files from a Google Drive folder to a knowledge base
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        # Clean up uploads folder before downloading from Google Drive folder
        from open_webui.utils.upload_cleanup import cleanup_uploads_folder
        cleanup_result = cleanup_uploads_folder()
        log.info(f"Uploads cleanup before Google Drive folder download: {cleanup_result}")

        # List all files in the folder (quick call to size progress)
        files = google_drive_service.list_folder_files(
            form_data.folder_id, form_data.oauth_token, form_data.recursive
        )

        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No supported files found in the selected folder",
            )

        log.info(f"Found {len(files)} files in Google Drive folder")

        # Start progress tracking session - use knowledge base ID as session ID
        from open_webui.routers.progress import update_file_progress, update_progress
        session_id = id  # Use the knowledge base ID as the session ID
        file_list = [file_info.get("name", "unknown") for file_info in files]

        # Initialize progress tracking for the session, including the full file list once
        update_progress(session_id, {
            "status": "processing",
            "progress": 0,
            "message": f"Starting to process {len(files)} files",
            "total_files": len(files),
            "processed_files": 0,
            "file_list": file_list,
        })

        # Process the folder in a background thread similar to single-file flow
        def run_in_thread():
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(process_google_drive_folder_complete(
                    request=request,
                    knowledge_id=id,
                    session_id=session_id,
                    user_id=user.id,
                    files=files,
                    oauth_token=form_data.oauth_token
                ))
            finally:
                loop.close()

        import threading
        thread = threading.Thread(target=run_in_thread)
        thread.daemon = True
        thread.start()

        # Return immediately with session ID
        return KnowledgeFilesResponseWithSession(
            **knowledge.model_dump(),
            files=[],
            session_id=session_id
        )

    except Exception as e:
        log.error(f"Error adding Google Drive folder to knowledge base: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add Google Drive folder: {str(e)}",
        )

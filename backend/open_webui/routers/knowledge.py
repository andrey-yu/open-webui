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


@router.get("/{id}", response_model=Optional[KnowledgeFilesResponse])
async def get_knowledge_by_id(id: str, user=Depends(get_verified_user)):
    knowledge = Knowledges.get_knowledge_by_id(id=id)

    if knowledge:

        if (
            user.role == "admin"
            or knowledge.user_id == user.id
            or has_access(user.id, "read", knowledge.access_control)
        ):

            file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
            files = Files.get_file_metadatas_by_ids(file_ids)

            return KnowledgeFilesResponse(
                **knowledge.model_dump(),
                files=files,
            )
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
    if not file.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.FILE_NOT_PROCESSED,
        )

    # Add content to the vector database
    try:
        process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
        )
    except Exception as e:
        log.debug(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if knowledge:
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])

        if form_data.file_id not in file_ids:
            file_ids.append(form_data.file_id)
            data["file_ids"] = file_ids

            knowledge = Knowledges.update_knowledge_data_by_id(id=id, data=data)

            if knowledge:
                files = Files.get_file_metadatas_by_ids(file_ids)

                return KnowledgeFilesResponse(
                    **knowledge.model_dump(),
                    files=files,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("knowledge"),
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("file_id"),
            )
    else:
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
    try:
        VECTOR_DB_CLIENT.delete(
            collection_name=knowledge.id, filter={"file_id": form_data.file_id}
        )
    except Exception as e:
        log.debug("This was most likely caused by bypassing embedding processing")
        log.debug(e)
        pass

    try:
        # Remove the file's collection from vector database
        file_collection = f"file-{form_data.file_id}"
        if VECTOR_DB_CLIENT.has_collection(collection_name=file_collection):
            VECTOR_DB_CLIENT.delete_collection(collection_name=file_collection)
    except Exception as e:
        log.debug("This was most likely caused by bypassing embedding processing")
        log.debug(e)
        pass

    # Delete file from storage and database
    try:
        Storage.delete_file_and_related(file.path)
    except Exception as e:
        log.warning(f"Failed to delete file and related files from storage: {e}")
    
    Files.delete_file_by_id(form_data.file_id)

    if knowledge:
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])

        if form_data.file_id in file_ids:
            file_ids.remove(form_data.file_id)
            data["file_ids"] = file_ids

            knowledge = Knowledges.update_knowledge_data_by_id(id=id, data=data)

            if knowledge:
                files = Files.get_file_metadatas_by_ids(file_ids)

                return KnowledgeFilesResponse(
                    **knowledge.model_dump(),
                    files=files,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("knowledge"),
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("file_id"),
            )
    else:
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

    # Clean up vector DB
    try:
        VECTOR_DB_CLIENT.delete_collection(collection_name=id)
    except Exception as e:
        log.debug(e)
        pass
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
    for file_id in successful_file_ids:
        if file_id not in existing_file_ids:
            existing_file_ids.append(file_id)

    data["file_ids"] = existing_file_ids
    knowledge = Knowledges.update_knowledge_data_by_id(id=id, data=data)

    # If there were any errors, include them in the response
    if result.errors:
        error_details = [f"{err.file_id}: {err.error}" for err in result.errors]
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=Files.get_file_metadatas_by_ids(existing_file_ids),
            warnings={
                "message": "Some files failed to process",
                "errors": error_details,
            },
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
    from open_webui.routers.progress import update_progress, mark_session_complete, mark_session_error
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
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "processing",
            "progress": 0,
            "message": "Starting file processing",
            "total_files": 1,
            "file_list": [form_data_file_id]
        })
        
        # Download file from Google Drive
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "processing",
            "progress": 20,
            "message": "Downloading file from Google Drive",
            "total_files": 1,
            "file_list": [form_data_file_id]
        })
        
        file_content, filename, mime_type = google_drive_service.download_file(
            form_data_file_id, oauth_token
        )

        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "processing",
            "progress": 40,
            "message": "Uploading file to storage",
            "total_files": 1,
            "file_list": [form_data_file_id]
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

        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "processing",
            "progress": 60,
            "message": "Creating file record",
            "total_files": 1,
            "file_list": [form_data_file_id]
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
                update_progress(session_id, {
                    "session_id": session_id,
                    "file_id": progress_file_id,
                    "status": "processing",
                    "progress": 80,
                    "message": "Processing file content",
                    "total_files": 1,
                    "file_list": [form_data_file_id]
                })
                
                # Process the file
                process_file(
                    request,
                    ProcessFileForm(file_id=file.id, collection_name=knowledge_id),
                    user=mock_user,
                )
                
                # Update progress to show completion
                update_progress(session_id, {
                    "session_id": session_id,
                    "file_id": progress_file_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "File processed successfully",
                    "total_files": 1,
                    "file_list": [form_data_file_id]
                })
                
            else:
                # For unsupported video/image files, skip processing
                log.info(f"File type {mime_type} is not supported for processing")
                
                update_progress(session_id, {
                    "session_id": session_id,
                    "file_id": progress_file_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "File type not supported for processing",
                    "total_files": 1,
                    "file_list": [form_data_file_id]
                })
        else:
            # If no content type, try to process anyway
            log.info(f"File type {mime_type} is not provided, but trying to process anyway")
            
            update_progress(session_id, {
                "session_id": session_id,
                "file_id": progress_file_id,
                "status": "processing",
                "progress": 80,
                "message": "Processing file content",
                "total_files": 1,
                "file_list": [form_data_file_id]
            })
            
            # Process the file
            process_file(
                request,
                ProcessFileForm(file_id=file.id, collection_name=knowledge_id),
                user=mock_user,
            )
            
            update_progress(session_id, {
                "session_id": session_id,
                "file_id": progress_file_id,
                "status": "completed",
                "progress": 100,
                "message": "File processed successfully",
                "total_files": 1,
                "file_list": [form_data_file_id]
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
    from open_webui.routers.progress import update_progress, mark_session_complete, mark_session_error
    from open_webui.routers.retrieval import process_file, ProcessFileForm
    from open_webui.models.users import Users
    
    try:
        # Create a mock user object for the background task
        class MockUser:
            def __init__(self, user_id):
                self.id = user_id
        
        mock_user = MockUser(user_id)
        
        # Update progress to show processing starting
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "processing",
            "progress": 80,
            "message": "Processing file content",
            "total_files": 1,
            "file_list": [form_data_file_id]
        })
        
        # Process the file
        process_file(
            request,
            ProcessFileForm(file_id=file_id, collection_name=knowledge_id),
            user=mock_user,
        )
        
        # Update progress to show completion
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "completed",
            "progress": 100,
            "message": "File processed successfully",
            "total_files": 1,
            "file_list": [form_data_file_id]
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
    from open_webui.routers.progress import update_progress, mark_session_complete, mark_session_error
    
    try:
        log.info(f"Starting transcription for file {file_id} with mime_type {mime_type}")
        
        # Update progress to show transcription starting
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "transcribing",
            "progress": 80,
            "message": "Transcribing audio/video file",
            "total_files": 1,
            "file_list": [form_data_file_id]
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
            
            time.sleep(2)  # Update every 2 seconds
        
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
        
        # Process the file with transcribed content
        # Create a mock user object for the background task
        class MockUser:
            def __init__(self, user_id):
                self.id = user_id
        
        mock_user = MockUser(user_id)
        process_file(
            request,
            ProcessFileForm(file_id=file_id, content=transcription_text, collection_name=knowledge_id),
            user=mock_user,
        )
        
        log.info(f"Processing completed for file {file_id}")
        
        # Update progress to show completion
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "completed",
            "progress": 100,
            "message": "File processed successfully",
            "total_files": 1,
            "file_list": [form_data_file_id]
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
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": progress_file_id,
            "status": "error",
            "progress": 0,
            "message": None,
            "error": str(e),
            "total_files": 1,
            "file_list": [form_data_file_id]
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
        # Import progress tracking functions
        from open_webui.routers.progress import update_progress, mark_session_complete, mark_session_error
        
        # Start progress tracking session for single file
        import uuid
        session_id = str(uuid.uuid4())
        file_id = str(uuid.uuid4())  # Generate file ID for progress tracking
        
        # Initialize progress tracking for the session
        update_progress(session_id, {
            "session_id": session_id,
            "file_id": file_id,
            "status": "processing",
            "progress": 0,
            "message": "Starting file processing",
            "total_files": 1,
            "file_list": [form_data.file_id]
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
            update_progress(session_id, {
                "session_id": session_id,
                "file_id": file_id,
                "status": "error",
                "progress": 0,
                "message": None,
                "error": str(e),
                "total_files": 1,
                "file_list": [form_data.file_id]
            })
            mark_session_error(session_id, str(e))
        
        # Log the actual error for debugging
        log.error(f"Error in add_google_drive_file_to_knowledge for user {user.id}: {str(e)}")
        raise ValueError(f"Failed to add Google Drive file: {str(e)}")


@router.post("/{id}/google-drive/folder", response_model=Optional[KnowledgeFilesResponse])
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
        # Import progress tracking functions
        from open_webui.socket.main import emit_session_start, emit_progress_update, emit_session_complete
        
        # List all files in the folder
        files = google_drive_service.list_folder_files(
            form_data.folder_id, form_data.oauth_token, form_data.recursive
        )

        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No supported files found in the selected folder",
            )

        log.info(f"Found {len(files)} files in Google Drive folder")

        # Start progress tracking session
        import uuid
        session_id = str(uuid.uuid4())
        file_list = [file_info.get("name", "unknown") for file_info in files]
        try:
            await emit_session_start(user.id, session_id, len(files), file_list)
        except Exception as session_error:
            log.warning(f"Failed to start session {session_id}: {session_error}")

        # Process files in batches to avoid overwhelming the system
        batch_size = 5
        successful_files = []
        failed_files = []

        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            
            for file_info in batch:
                progress_file_id = str(uuid.uuid4())  # ID for progress tracking
                filename = file_info.get("name", "unknown")
                
                try:
                    # Update progress - starting to process
                    try:
                        await emit_progress_update(user.id, session_id, progress_file_id, "processing", 10, f"Downloading {filename}")
                    except Exception as progress_error:
                        log.warning(f"Failed to emit progress update for {filename}: {progress_error}")
                    
                    # Download file from Google Drive
                    file_content, filename, mime_type = google_drive_service.download_file(
                        file_info["id"], form_data.oauth_token
                    )

                    try:
                        await emit_progress_update(user.id, session_id, progress_file_id, "processing", 30, f"Uploading {filename}")
                    except Exception as progress_error:
                        log.warning(f"Failed to emit progress update for {filename}: {progress_error}")

                    # Create a temporary file-like object
                    from io import BytesIO
                    file_obj = BytesIO(file_content)
                    file_obj.name = filename

                    # Upload file using existing storage provider
                    storage_file_id = str(uuid.uuid4())
                    tags = {
                        "OpenWebUI-User-Email": user.email,
                        "OpenWebUI-User-Id": user.id,
                        "OpenWebUI-User-Name": user.name,
                        "OpenWebUI-File-Id": storage_file_id,
                        "OpenWebUI-Source": "google-drive",
                    }

                    contents, file_path = Storage.upload_file(file_obj, f"{storage_file_id}_{filename}", tags)

                    try:
                        await emit_progress_update(user.id, session_id, progress_file_id, "processing", 50, f"Creating file record for {filename}")
                    except Exception as progress_error:
                        log.warning(f"Failed to emit progress update for {filename}: {progress_error}")

                    # Create file record
                    from open_webui.models.files import FileForm
                    file_item = Files.insert_new_file(
                        user.id,
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

                    # Check if file needs transcription
                    if mime_type and mime_type.startswith(("video/", "audio/")):
                        log.info(f"Starting transcription for file {storage_file_id} ({filename}) with mime_type {mime_type}")
                        try:
                            await emit_progress_update(user.id, session_id, progress_file_id, "transcribing", 70, f"Transcribing {filename}")
                        except Exception as progress_error:
                            log.warning(f"Failed to emit progress update for {filename}: {progress_error}")
                        
                        # Transcribe the file
                        file_path = Storage.get_file(file_path)
                        log.info(f"File path for transcription: {file_path}")
                        
                        # Start transcription in a background thread to allow progress updates
                        import threading
                        import time
                        
                        transcription_result = None
                        transcription_error = None
                        
                        def run_transcription():
                            nonlocal transcription_result, transcription_error
                            try:
                                transcription_result = transcribe(request, file_path, {"source": "google-drive"})
                            except Exception as e:
                                transcription_error = e
                        
                        # Start transcription in a thread
                        transcription_thread = threading.Thread(target=run_transcription)
                        transcription_thread.start()
                        
                        # Send periodic progress updates during transcription
                        start_time = time.time()
                        while transcription_thread.is_alive():
                            elapsed = time.time() - start_time
                            # Estimate progress based on elapsed time (assuming 30 seconds for transcription)
                            estimated_progress = min(75 + int((elapsed / 30) * 10), 95)
                            
                            try:
                                await emit_progress_update(user.id, session_id, progress_file_id, "transcribing", estimated_progress, f"Transcribing {filename}... ({int(elapsed)}s elapsed)")
                            except Exception as progress_error:
                                log.warning(f"Failed to emit progress update for {filename}: {progress_error}")
                            
                            time.sleep(2)  # Update every 2 seconds
                        
                        # Check for transcription errors
                        if transcription_error:
                            log.error(f"Error transcribing file {storage_file_id}: {str(transcription_error)}")
                            raise ValueError(f"Failed to transcribe audio/video file: {str(transcription_error)}")
                        
                        result = transcription_result
                        log.info(f"Transcription completed for file {storage_file_id}")
                        
                        try:
                            await emit_progress_update(user.id, session_id, progress_file_id, "transcribing", 78, f"Transcription completed for {filename}")
                        except Exception as progress_error:
                            log.warning(f"Failed to emit progress update for {filename}: {progress_error}")

                        log.info(f"Starting processing for transcribed file {storage_file_id}")
                        try:
                            await emit_progress_update(user.id, session_id, progress_file_id, "processing", 90, f"Processing {filename}")
                        except Exception as progress_error:
                            log.warning(f"Failed to emit progress update for {filename}: {progress_error}")

                        # Process file with transcription
                        try:
                            # Check if transcription result has content
                            transcription_text = result.get("text", "").strip()
                            if not transcription_text:
                                raise ValueError("Transcription resulted in empty content")
                            
                            process_file(
                                request,
                                ProcessFileForm(file_id=storage_file_id, content=transcription_text, collection_name=id),
                                user=user,
                            )
                            log.info(f"Processing completed for file {storage_file_id}")
                        except Exception as process_error:
                            log.error(f"Error processing file {storage_file_id} with transcription: {str(process_error)}")
                            raise ValueError(f"Failed to process transcribed content: {str(process_error)}")

                    else:
                        # Check if it's a PDF and provide helpful information
                        if mime_type == "application/pdf":
                            log.info(f"Processing PDF file {storage_file_id} ({filename})")
                            # Check if PDF image extraction is enabled
                            pdf_extract_images = getattr(request.app.state.config, "PDF_EXTRACT_IMAGES", False)
                            content_extraction_engine = getattr(request.app.state.config, "CONTENT_EXTRACTION_ENGINE", "")
                            
                            if not pdf_extract_images and not content_extraction_engine:
                                log.info(f"PDF image extraction is disabled and no content extraction engine is configured for file {filename}")
                        
                        try:
                            await emit_progress_update(user.id, session_id, progress_file_id, "processing", 70, f"Processing {filename}")
                        except Exception as progress_error:
                            log.warning(f"Failed to emit progress update for {filename}: {progress_error}")
                        
                        # Process file normally
                        try:
                            process_file(
                                request,
                                ProcessFileForm(file_id=storage_file_id, collection_name=id),
                                user=user,
                            )
                        except Exception as process_error:
                            log.error(f"Error processing file {storage_file_id}: {str(process_error)}")
                            
                            # Provide more specific error messages for PDF files
                            if mime_type == "application/pdf":
                                if "empty content" in str(process_error).lower():
                                    raise ValueError("PDF file could not be processed. This may be because the PDF is image-based, password-protected, or uses an unsupported format. Try enabling PDF image extraction in settings or use a different content extraction engine.")
                                else:
                                    raise ValueError(f"Failed to process PDF file: {str(process_error)}")
                            else:
                                raise ValueError(f"Failed to process file content: {str(process_error)}")

                    try:
                        await emit_progress_update(user.id, session_id, progress_file_id, "completed", 100, f"Completed {filename}")
                    except Exception as progress_error:
                        log.warning(f"Failed to emit progress update for {filename}: {progress_error}")
                    successful_files.append(storage_file_id)

                except Exception as e:
                    log.error(f"Error processing file {filename}: {e}")
                    try:
                        await emit_progress_update(user.id, session_id, progress_file_id, "error", 0, None, str(e))
                    except Exception as progress_error:
                        log.warning(f"Failed to emit progress update for file {filename}: {progress_error}")
                    failed_files.append({
                        "name": filename,
                        "error": str(e)
                    })

        # Complete progress tracking session
        try:
            await emit_session_complete(user.id, session_id)
        except Exception as session_error:
            log.warning(f"Failed to complete session {session_id}: {session_error}")

        # Add successful files to knowledge base
        data = knowledge.data or {}
        existing_file_ids = data.get("file_ids", [])
        for file_id in successful_files:
            if file_id not in existing_file_ids:
                existing_file_ids.append(file_id)
        data["file_ids"] = existing_file_ids
        knowledge = Knowledges.update_knowledge_data_by_id(id=id, data=data)

        # Prepare response
        response = KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=Files.get_file_metadatas_by_ids(existing_file_ids),
        )

        # Add warnings if there were failures
        if failed_files:
            response.warnings = {
                "message": f"Successfully added {len(successful_files)} files. {len(failed_files)} files failed.",
                "failed_files": failed_files,
            }

        return response

    except Exception as e:
        log.error(f"Error adding Google Drive folder to knowledge base: {e}", exc_info=True)
        
        # Try to complete session if it exists
        if 'session_id' in locals():
            try:
                await emit_session_complete(user.id, session_id)
            except Exception as session_error:
                log.warning(f"Failed to complete session {session_id}: {session_error}")
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add Google Drive folder: {str(e)}",
        )

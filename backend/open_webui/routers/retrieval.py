import json
import logging
import mimetypes
import os
import shutil
import asyncio


import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Union

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    Request,
    status,
    APIRouter,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import tiktoken


from langchain.text_splitter import RecursiveCharacterTextSplitter, TokenTextSplitter
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain_core.documents import Document

from open_webui.models.files import FileModel, Files
from open_webui.models.knowledge import Knowledges
from open_webui.storage.provider import Storage


from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.retrieval.utils import TimestampAwareTextSplitter

# Document loaders
from open_webui.retrieval.loaders.main import Loader, RAPIDOCR_AVAILABLE
from open_webui.retrieval.loaders.youtube import YoutubeLoader

# Web search engines
from open_webui.retrieval.web.main import SearchResult
from open_webui.retrieval.web.utils import get_web_loader
from open_webui.retrieval.web.brave import search_brave
from open_webui.retrieval.web.kagi import search_kagi
from open_webui.retrieval.web.mojeek import search_mojeek
from open_webui.retrieval.web.bocha import search_bocha
from open_webui.retrieval.web.duckduckgo import search_duckduckgo
from open_webui.retrieval.web.google_pse import search_google_pse
from open_webui.retrieval.web.jina_search import search_jina
from open_webui.retrieval.web.searchapi import search_searchapi
from open_webui.retrieval.web.serpapi import search_serpapi
from open_webui.retrieval.web.searxng import search_searxng
from open_webui.retrieval.web.yacy import search_yacy
from open_webui.retrieval.web.serper import search_serper
from open_webui.retrieval.web.serply import search_serply
from open_webui.retrieval.web.serpstack import search_serpstack
from open_webui.retrieval.web.tavily import search_tavily
from open_webui.retrieval.web.bing import search_bing
from open_webui.retrieval.web.exa import search_exa
from open_webui.retrieval.web.perplexity import search_perplexity
from open_webui.retrieval.web.sougou import search_sougou
from open_webui.retrieval.web.firecrawl import search_firecrawl
from open_webui.retrieval.web.external import search_external

from open_webui.retrieval.utils import (
    get_embedding_function,
    get_reranking_function,
    get_model_path,
    query_collection,
    query_collection_with_hybrid_search,
    query_doc,
    query_doc_with_hybrid_search,
)
from open_webui.utils.misc import (
    calculate_sha256_string,
)
from open_webui.utils.auth import get_admin_user, get_verified_user

from open_webui.config import (
    ENV,
    RAG_EMBEDDING_MODEL_AUTO_UPDATE,
    RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE,
    RAG_RERANKING_MODEL_AUTO_UPDATE,
    RAG_RERANKING_MODEL_TRUST_REMOTE_CODE,
    UPLOAD_DIR,
    DEFAULT_LOCALE,
    RAG_EMBEDDING_CONTENT_PREFIX,
    RAG_EMBEDDING_QUERY_PREFIX,
    ENABLE_TIMESTAMP_CITATIONS,
)
from open_webui.env import (
    SRC_LOG_LEVELS,
    DEVICE_TYPE,
    DOCKER,
    SENTENCE_TRANSFORMERS_BACKEND,
    SENTENCE_TRANSFORMERS_MODEL_KWARGS,
    SENTENCE_TRANSFORMERS_CROSS_ENCODER_BACKEND,
    SENTENCE_TRANSFORMERS_CROSS_ENCODER_MODEL_KWARGS,
)

from open_webui.constants import ERROR_MESSAGES

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

##########################################
#
# Utility functions
#
##########################################


def get_ef(
    engine: str,
    embedding_model: str,
    auto_update: bool = False,
):
    ef = None
    if embedding_model and engine == "":
        from sentence_transformers import SentenceTransformer

        try:
            ef = SentenceTransformer(
                get_model_path(embedding_model, auto_update),
                device=DEVICE_TYPE,
                trust_remote_code=RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE,
                backend=SENTENCE_TRANSFORMERS_BACKEND,
                model_kwargs=SENTENCE_TRANSFORMERS_MODEL_KWARGS,
            )
        except Exception as e:
            log.debug(f"Error loading SentenceTransformer: {e}")

    return ef


def get_rf(
    engine: str = "",
    reranking_model: Optional[str] = None,
    external_reranker_url: str = "",
    external_reranker_api_key: str = "",
    auto_update: bool = False,
):
    rf = None
    if reranking_model:
        if any(model in reranking_model for model in ["jinaai/jina-colbert-v2"]):
            try:
                from open_webui.retrieval.models.colbert import ColBERT

                rf = ColBERT(
                    get_model_path(reranking_model, auto_update),
                    env="docker" if DOCKER else None,
                )

            except Exception as e:
                log.error(f"ColBERT: {e}")
                raise Exception(ERROR_MESSAGES.DEFAULT(e))
        else:
            if engine == "external":
                try:
                    from open_webui.retrieval.models.external import ExternalReranker

                    rf = ExternalReranker(
                        url=external_reranker_url,
                        api_key=external_reranker_api_key,
                        model=reranking_model,
                    )
                except Exception as e:
                    log.error(f"ExternalReranking: {e}")
                    raise Exception(ERROR_MESSAGES.DEFAULT(e))
            else:
                import sentence_transformers

                try:
                    rf = sentence_transformers.CrossEncoder(
                        get_model_path(reranking_model, auto_update),
                        device=DEVICE_TYPE,
                        trust_remote_code=RAG_RERANKING_MODEL_TRUST_REMOTE_CODE,
                        backend=SENTENCE_TRANSFORMERS_CROSS_ENCODER_BACKEND,
                        model_kwargs=SENTENCE_TRANSFORMERS_CROSS_ENCODER_MODEL_KWARGS,
                    )
                except Exception as e:
                    log.error(f"CrossEncoder: {e}")
                    raise Exception(ERROR_MESSAGES.DEFAULT("CrossEncoder error"))

    return rf


##########################################
#
# API routes
#
##########################################


router = APIRouter()


class CollectionNameForm(BaseModel):
    collection_name: Optional[str] = None


class ProcessUrlForm(CollectionNameForm):
    url: str


class SearchForm(BaseModel):
    queries: List[str]


@router.get("/")
async def get_status(request: Request):
    return {
        "status": True,
        "chunk_size": request.app.state.config.CHUNK_SIZE,
        "chunk_overlap": request.app.state.config.CHUNK_OVERLAP,
        "template": request.app.state.config.RAG_TEMPLATE,
        "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
        "embedding_model": request.app.state.config.RAG_EMBEDDING_MODEL,
        "reranking_model": request.app.state.config.RAG_RERANKING_MODEL,
        "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
    }


@router.get("/embedding")
async def get_embedding_config(request: Request, user=Depends(get_admin_user)):
    return {
        "status": True,
        "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
        "embedding_model": request.app.state.config.RAG_EMBEDDING_MODEL,
        "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
        "openai_config": {
            "url": request.app.state.config.RAG_OPENAI_API_BASE_URL,
            "key": request.app.state.config.RAG_OPENAI_API_KEY,
        },
        "ollama_config": {
            "url": request.app.state.config.RAG_OLLAMA_BASE_URL,
            "key": request.app.state.config.RAG_OLLAMA_API_KEY,
        },
        "azure_openai_config": {
            "url": request.app.state.config.RAG_AZURE_OPENAI_BASE_URL,
            "key": request.app.state.config.RAG_AZURE_OPENAI_API_KEY,
            "version": request.app.state.config.RAG_AZURE_OPENAI_API_VERSION,
        },
    }


class OpenAIConfigForm(BaseModel):
    url: str
    key: str


class OllamaConfigForm(BaseModel):
    url: str
    key: str


class AzureOpenAIConfigForm(BaseModel):
    url: str
    key: str
    version: str


class EmbeddingModelUpdateForm(BaseModel):
    openai_config: Optional[OpenAIConfigForm] = None
    ollama_config: Optional[OllamaConfigForm] = None
    azure_openai_config: Optional[AzureOpenAIConfigForm] = None
    embedding_engine: str
    embedding_model: str
    embedding_batch_size: Optional[int] = 1


@router.post("/embedding/update")
async def update_embedding_config(
    request: Request, form_data: EmbeddingModelUpdateForm, user=Depends(get_admin_user)
):
    log.info(
        f"Updating embedding model: {request.app.state.config.RAG_EMBEDDING_MODEL} to {form_data.embedding_model}"
    )
    try:
        request.app.state.config.RAG_EMBEDDING_ENGINE = form_data.embedding_engine
        request.app.state.config.RAG_EMBEDDING_MODEL = form_data.embedding_model

        if request.app.state.config.RAG_EMBEDDING_ENGINE in [
            "ollama",
            "openai",
            "azure_openai",
        ]:
            if form_data.openai_config is not None:
                request.app.state.config.RAG_OPENAI_API_BASE_URL = (
                    form_data.openai_config.url
                )
                request.app.state.config.RAG_OPENAI_API_KEY = (
                    form_data.openai_config.key
                )

            if form_data.ollama_config is not None:
                request.app.state.config.RAG_OLLAMA_BASE_URL = (
                    form_data.ollama_config.url
                )
                request.app.state.config.RAG_OLLAMA_API_KEY = (
                    form_data.ollama_config.key
                )

            if form_data.azure_openai_config is not None:
                request.app.state.config.RAG_AZURE_OPENAI_BASE_URL = (
                    form_data.azure_openai_config.url
                )
                request.app.state.config.RAG_AZURE_OPENAI_API_KEY = (
                    form_data.azure_openai_config.key
                )
                request.app.state.config.RAG_AZURE_OPENAI_API_VERSION = (
                    form_data.azure_openai_config.version
                )

            request.app.state.config.RAG_EMBEDDING_BATCH_SIZE = (
                form_data.embedding_batch_size
            )

        request.app.state.ef = get_ef(
            request.app.state.config.RAG_EMBEDDING_ENGINE,
            request.app.state.config.RAG_EMBEDDING_MODEL,
        )

        request.app.state.EMBEDDING_FUNCTION = get_embedding_function(
            request.app.state.config.RAG_EMBEDDING_ENGINE,
            request.app.state.config.RAG_EMBEDDING_MODEL,
            request.app.state.ef,
            (
                request.app.state.config.RAG_OPENAI_API_BASE_URL
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
                else (
                    request.app.state.config.RAG_OLLAMA_BASE_URL
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                    else request.app.state.config.RAG_AZURE_OPENAI_BASE_URL
                )
            ),
            (
                request.app.state.config.RAG_OPENAI_API_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
                else (
                    request.app.state.config.RAG_OLLAMA_API_KEY
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                    else request.app.state.config.RAG_AZURE_OPENAI_API_KEY
                )
            ),
            request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
            azure_api_version=(
                request.app.state.config.RAG_AZURE_OPENAI_API_VERSION
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
                else None
            ),
        )

        return {
            "status": True,
            "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
            "embedding_model": request.app.state.config.RAG_EMBEDDING_MODEL,
            "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
            "openai_config": {
                "url": request.app.state.config.RAG_OPENAI_API_BASE_URL,
                "key": request.app.state.config.RAG_OPENAI_API_KEY,
            },
            "ollama_config": {
                "url": request.app.state.config.RAG_OLLAMA_BASE_URL,
                "key": request.app.state.config.RAG_OLLAMA_API_KEY,
            },
            "azure_openai_config": {
                "url": request.app.state.config.RAG_AZURE_OPENAI_BASE_URL,
                "key": request.app.state.config.RAG_AZURE_OPENAI_API_KEY,
                "version": request.app.state.config.RAG_AZURE_OPENAI_API_VERSION,
            },
        }
    except Exception as e:
        log.exception(f"Problem updating embedding model: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


@router.get("/config")
async def get_rag_config(request: Request, user=Depends(get_admin_user)):
    return {
        "status": True,
        # RAG settings
        "RAG_TEMPLATE": request.app.state.config.RAG_TEMPLATE,
        "TOP_K": request.app.state.config.TOP_K,
        "BYPASS_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL,
        "RAG_FULL_CONTEXT": request.app.state.config.RAG_FULL_CONTEXT,
        "ENABLE_TIMESTAMP_CITATIONS": request.app.state.config.ENABLE_TIMESTAMP_CITATIONS,
        # Hybrid search settings
        "ENABLE_RAG_HYBRID_SEARCH": request.app.state.config.ENABLE_RAG_HYBRID_SEARCH,
        "TOP_K_RERANKER": request.app.state.config.TOP_K_RERANKER,
        "RELEVANCE_THRESHOLD": request.app.state.config.RELEVANCE_THRESHOLD,
        "HYBRID_BM25_WEIGHT": request.app.state.config.HYBRID_BM25_WEIGHT,
        # Content extraction settings
        "CONTENT_EXTRACTION_ENGINE": request.app.state.config.CONTENT_EXTRACTION_ENGINE,
        "PDF_EXTRACT_IMAGES": request.app.state.config.PDF_EXTRACT_IMAGES,
        "DATALAB_MARKER_API_KEY": request.app.state.config.DATALAB_MARKER_API_KEY,
        "DATALAB_MARKER_LANGS": request.app.state.config.DATALAB_MARKER_LANGS,
        "DATALAB_MARKER_SKIP_CACHE": request.app.state.config.DATALAB_MARKER_SKIP_CACHE,
        "DATALAB_MARKER_FORCE_OCR": request.app.state.config.DATALAB_MARKER_FORCE_OCR,
        "DATALAB_MARKER_PAGINATE": request.app.state.config.DATALAB_MARKER_PAGINATE,
        "DATALAB_MARKER_STRIP_EXISTING_OCR": request.app.state.config.DATALAB_MARKER_STRIP_EXISTING_OCR,
        "DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION": request.app.state.config.DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION,
        "DATALAB_MARKER_USE_LLM": request.app.state.config.DATALAB_MARKER_USE_LLM,
        "DATALAB_MARKER_OUTPUT_FORMAT": request.app.state.config.DATALAB_MARKER_OUTPUT_FORMAT,
        "EXTERNAL_DOCUMENT_LOADER_URL": request.app.state.config.EXTERNAL_DOCUMENT_LOADER_URL,
        "EXTERNAL_DOCUMENT_LOADER_API_KEY": request.app.state.config.EXTERNAL_DOCUMENT_LOADER_API_KEY,
        "TIKA_SERVER_URL": request.app.state.config.TIKA_SERVER_URL,
        "DOCLING_SERVER_URL": request.app.state.config.DOCLING_SERVER_URL,
        "DOCLING_OCR_ENGINE": request.app.state.config.DOCLING_OCR_ENGINE,
        "DOCLING_OCR_LANG": request.app.state.config.DOCLING_OCR_LANG,
        "DOCLING_DO_PICTURE_DESCRIPTION": request.app.state.config.DOCLING_DO_PICTURE_DESCRIPTION,
        "DOCLING_PICTURE_DESCRIPTION_MODE": request.app.state.config.DOCLING_PICTURE_DESCRIPTION_MODE,
        "DOCLING_PICTURE_DESCRIPTION_LOCAL": request.app.state.config.DOCLING_PICTURE_DESCRIPTION_LOCAL,
        "DOCLING_PICTURE_DESCRIPTION_API": request.app.state.config.DOCLING_PICTURE_DESCRIPTION_API,
        "DOCUMENT_INTELLIGENCE_ENDPOINT": request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
        "DOCUMENT_INTELLIGENCE_KEY": request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
        "MISTRAL_OCR_API_KEY": request.app.state.config.MISTRAL_OCR_API_KEY,
        # Reranking settings
        "RAG_RERANKING_MODEL": request.app.state.config.RAG_RERANKING_MODEL,
        "RAG_RERANKING_ENGINE": request.app.state.config.RAG_RERANKING_ENGINE,
        "RAG_EXTERNAL_RERANKER_URL": request.app.state.config.RAG_EXTERNAL_RERANKER_URL,
        "RAG_EXTERNAL_RERANKER_API_KEY": request.app.state.config.RAG_EXTERNAL_RERANKER_API_KEY,
        # Chunking settings
        "TEXT_SPLITTER": request.app.state.config.TEXT_SPLITTER,
        "CHUNK_SIZE": request.app.state.config.CHUNK_SIZE,
        "CHUNK_OVERLAP": request.app.state.config.CHUNK_OVERLAP,
        # File upload settings
        "FILE_MAX_SIZE": request.app.state.config.FILE_MAX_SIZE,
        "FILE_MAX_COUNT": request.app.state.config.FILE_MAX_COUNT,
        "FILE_IMAGE_COMPRESSION_WIDTH": request.app.state.config.FILE_IMAGE_COMPRESSION_WIDTH,
        "FILE_IMAGE_COMPRESSION_HEIGHT": request.app.state.config.FILE_IMAGE_COMPRESSION_HEIGHT,
        "ALLOWED_FILE_EXTENSIONS": request.app.state.config.ALLOWED_FILE_EXTENSIONS,
        # Integration settings
        "ENABLE_GOOGLE_DRIVE_INTEGRATION": request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION,
        "ENABLE_ONEDRIVE_INTEGRATION": request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION,
        # Web search settings
        "web": {
            "ENABLE_WEB_SEARCH": request.app.state.config.ENABLE_WEB_SEARCH,
            "WEB_SEARCH_ENGINE": request.app.state.config.WEB_SEARCH_ENGINE,
            "WEB_SEARCH_TRUST_ENV": request.app.state.config.WEB_SEARCH_TRUST_ENV,
            "WEB_SEARCH_RESULT_COUNT": request.app.state.config.WEB_SEARCH_RESULT_COUNT,
            "WEB_SEARCH_CONCURRENT_REQUESTS": request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS,
            "WEB_SEARCH_DOMAIN_FILTER_LIST": request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL,
            "BYPASS_WEB_SEARCH_WEB_LOADER": request.app.state.config.BYPASS_WEB_SEARCH_WEB_LOADER,
            "SEARXNG_QUERY_URL": request.app.state.config.SEARXNG_QUERY_URL,
            "YACY_QUERY_URL": request.app.state.config.YACY_QUERY_URL,
            "YACY_USERNAME": request.app.state.config.YACY_USERNAME,
            "YACY_PASSWORD": request.app.state.config.YACY_PASSWORD,
            "GOOGLE_PSE_API_KEY": request.app.state.config.GOOGLE_PSE_API_KEY,
            "GOOGLE_PSE_ENGINE_ID": request.app.state.config.GOOGLE_PSE_ENGINE_ID,
            "BRAVE_SEARCH_API_KEY": request.app.state.config.BRAVE_SEARCH_API_KEY,
            "KAGI_SEARCH_API_KEY": request.app.state.config.KAGI_SEARCH_API_KEY,
            "MOJEEK_SEARCH_API_KEY": request.app.state.config.MOJEEK_SEARCH_API_KEY,
            "BOCHA_SEARCH_API_KEY": request.app.state.config.BOCHA_SEARCH_API_KEY,
            "SERPSTACK_API_KEY": request.app.state.config.SERPSTACK_API_KEY,
            "SERPSTACK_HTTPS": request.app.state.config.SERPSTACK_HTTPS,
            "SERPER_API_KEY": request.app.state.config.SERPER_API_KEY,
            "SERPLY_API_KEY": request.app.state.config.SERPLY_API_KEY,
            "TAVILY_API_KEY": request.app.state.config.TAVILY_API_KEY,
            "SEARCHAPI_API_KEY": request.app.state.config.SEARCHAPI_API_KEY,
            "SEARCHAPI_ENGINE": request.app.state.config.SEARCHAPI_ENGINE,
            "SERPAPI_API_KEY": request.app.state.config.SERPAPI_API_KEY,
            "SERPAPI_ENGINE": request.app.state.config.SERPAPI_ENGINE,
            "JINA_API_KEY": request.app.state.config.JINA_API_KEY,
            "BING_SEARCH_V7_ENDPOINT": request.app.state.config.BING_SEARCH_V7_ENDPOINT,
            "BING_SEARCH_V7_SUBSCRIPTION_KEY": request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY,
            "EXA_API_KEY": request.app.state.config.EXA_API_KEY,
            "PERPLEXITY_API_KEY": request.app.state.config.PERPLEXITY_API_KEY,
            "PERPLEXITY_MODEL": request.app.state.config.PERPLEXITY_MODEL,
            "PERPLEXITY_SEARCH_CONTEXT_USAGE": request.app.state.config.PERPLEXITY_SEARCH_CONTEXT_USAGE,
            "SOUGOU_API_SID": request.app.state.config.SOUGOU_API_SID,
            "SOUGOU_API_SK": request.app.state.config.SOUGOU_API_SK,
            "WEB_LOADER_ENGINE": request.app.state.config.WEB_LOADER_ENGINE,
            "ENABLE_WEB_LOADER_SSL_VERIFICATION": request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
            "PLAYWRIGHT_WS_URL": request.app.state.config.PLAYWRIGHT_WS_URL,
            "PLAYWRIGHT_TIMEOUT": request.app.state.config.PLAYWRIGHT_TIMEOUT,
            "FIRECRAWL_API_KEY": request.app.state.config.FIRECRAWL_API_KEY,
            "FIRECRAWL_API_BASE_URL": request.app.state.config.FIRECRAWL_API_BASE_URL,
            "TAVILY_EXTRACT_DEPTH": request.app.state.config.TAVILY_EXTRACT_DEPTH,
            "EXTERNAL_WEB_SEARCH_URL": request.app.state.config.EXTERNAL_WEB_SEARCH_URL,
            "EXTERNAL_WEB_SEARCH_API_KEY": request.app.state.config.EXTERNAL_WEB_SEARCH_API_KEY,
            "EXTERNAL_WEB_LOADER_URL": request.app.state.config.EXTERNAL_WEB_LOADER_URL,
            "EXTERNAL_WEB_LOADER_API_KEY": request.app.state.config.EXTERNAL_WEB_LOADER_API_KEY,
            "YOUTUBE_LOADER_LANGUAGE": request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
            "YOUTUBE_LOADER_PROXY_URL": request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
            "YOUTUBE_LOADER_TRANSLATION": request.app.state.YOUTUBE_LOADER_TRANSLATION,
        },
    }


####################################
#
# Document process and retrieval
#
####################################


def save_docs_to_vector_db(
    request: Request,
    docs,
    collection_name,
    metadata: Optional[dict] = None,
    overwrite: bool = False,
    split: bool = True,
    add: bool = False,
    user=None,
) -> bool:
    log.info(f"=== SAVE_DOCS_TO_VECTOR_DB START === Collection: {collection_name}, Overwrite: {overwrite}, Add: {add}")
    log.info(f"Metadata: {metadata}")
    log.info(f"Number of docs: {len(docs) if docs else 0}")
    
    def _get_docs_info(docs: list[Document]) -> str:
        docs_info = set()

        # Trying to select relevant metadata identifying the document.
        for doc in docs:
            metadata = getattr(doc, "metadata", {})
            doc_name = metadata.get("name", "")
            if not doc_name:
                doc_name = metadata.get("title", "")
            if not doc_name:
                doc_name = metadata.get("source", "")
            if doc_name:
                docs_info.add(doc_name)

        return ", ".join(docs_info)

    log.info(
        f"save_docs_to_vector_db: document {_get_docs_info(docs)} {collection_name}"
    )

    # Check if entries with the same hash (metadata.hash) already exist
    if metadata and "hash" in metadata:
        log.info(f"Checking for existing document with hash: {metadata['hash']}")
        result = VECTOR_DB_CLIENT.query(
            collection_name=collection_name,
            filter={"hash": metadata["hash"]},
        )

        if result is not None:
            existing_doc_ids = result.ids[0]
            if existing_doc_ids:
                log.info(f"Document with hash {metadata['hash']} already exists")
                raise ValueError(ERROR_MESSAGES.DUPLICATE_CONTENT)
            else:
                log.info(f"No existing document found with hash {metadata['hash']}")

    if split:
        # Check if any document has timestamp segments (from audio/video transcription)
        has_timestamps = any(
            doc.metadata.get("segments") and isinstance(doc.metadata.get("segments"), list)
            for doc in docs
        )
        
        if has_timestamps and request.app.state.config.ENABLE_TIMESTAMP_CITATIONS:
            # Use timestamp-aware splitter for audio/video transcriptions
            log.info("Using timestamp-aware text splitter for audio/video transcription")
            text_splitter = TimestampAwareTextSplitter(
                chunk_size=request.app.state.config.CHUNK_SIZE,
                chunk_overlap=request.app.state.config.CHUNK_OVERLAP,
                add_start_index=True,
            )
            docs = text_splitter.split_documents(docs)
        elif request.app.state.config.TEXT_SPLITTER in ["", "character"]:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=request.app.state.config.CHUNK_SIZE,
                chunk_overlap=request.app.state.config.CHUNK_OVERLAP,
                add_start_index=True,
            )
            docs = text_splitter.split_documents(docs)
        elif request.app.state.config.TEXT_SPLITTER == "token":
            log.info(
                f"Using token text splitter: {request.app.state.config.TIKTOKEN_ENCODING_NAME}"
            )

            tiktoken.get_encoding(str(request.app.state.config.TIKTOKEN_ENCODING_NAME))
            text_splitter = TokenTextSplitter(
                encoding_name=str(request.app.state.config.TIKTOKEN_ENCODING_NAME),
                chunk_size=request.app.state.config.CHUNK_SIZE,
                chunk_overlap=request.app.state.config.CHUNK_OVERLAP,
                add_start_index=True,
            )
            docs = text_splitter.split_documents(docs)
        elif request.app.state.config.TEXT_SPLITTER == "markdown":
            log.info("Using markdown text splitter")
            text_splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=request.app.state.config.MARKDOWN_HEADERS_TO_SPLIT_ON,
                return_each_line=False,
            )
            md_split_docs = []
            for doc in docs:
                md_split_docs.extend(text_splitter.split_text(doc.page_content))

            docs = md_split_docs
        else:
            raise ValueError(ERROR_MESSAGES.DEFAULT("Invalid text splitter"))

    log.info(f"After splitting, number of docs: {len(docs) if docs else 0}")

    if len(docs) == 0:
        log.error(f"Empty documents list provided to save_docs_to_vector_db for collection {collection_name}")
        raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)

    # Check for documents with empty content
    empty_docs = [i for i, doc in enumerate(docs) if not doc.page_content or not doc.page_content.strip()]
    if empty_docs:
        log.warning(f"Found {len(empty_docs)} documents with empty content at indices: {empty_docs}")

    texts = [doc.page_content for doc in docs]
    metadatas = [
        {
            **doc.metadata,
            **(metadata if metadata else {}),
            "embedding_config": json.dumps(
                {
                    "engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
                    "model": request.app.state.config.RAG_EMBEDDING_MODEL,
                }
            ),
        }
        for doc in docs
    ]

    # ChromaDB does not like datetime formats
    # for meta-data so convert them to string.
    for metadata in metadatas:
        for key, value in metadata.items():
            if (
                isinstance(value, datetime)
                or isinstance(value, list)
                or isinstance(value, dict)
            ):
                metadata[key] = str(value)

    try:
        log.info(f"Checking if collection exists: {collection_name}")
        if VECTOR_DB_CLIENT.has_collection(collection_name=collection_name):
            log.info(f"Collection {collection_name} already exists")

            if overwrite:
                log.info(f"Overwrite=True, deleting existing collection {collection_name}")
                VECTOR_DB_CLIENT.delete_collection(collection_name=collection_name)
                log.info(f"Successfully deleted existing collection {collection_name}")
            elif add is False:
                log.info(
                    f"Collection {collection_name} already exists, overwrite is False and add is False - RETURNING EARLY"
                )
                return True
            else:
                log.info(f"Collection {collection_name} exists, add is True - will add to existing collection")

        log.info(f"Adding to collection {collection_name}")
        embedding_function = get_embedding_function(
            request.app.state.config.RAG_EMBEDDING_ENGINE,
            request.app.state.config.RAG_EMBEDDING_MODEL,
            request.app.state.ef,
            (
                request.app.state.config.RAG_OPENAI_API_BASE_URL
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
                else (
                    request.app.state.config.RAG_OLLAMA_BASE_URL
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                    else request.app.state.config.RAG_AZURE_OPENAI_BASE_URL
                )
            ),
            (
                request.app.state.config.RAG_OPENAI_API_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
                else (
                    request.app.state.config.RAG_OLLAMA_API_KEY
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                    else request.app.state.config.RAG_AZURE_OPENAI_API_KEY
                )
            ),
            request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
            azure_api_version=(
                request.app.state.config.RAG_AZURE_OPENAI_API_VERSION
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
                else None
            ),
        )

        log.info(f"Generating embeddings for {len(texts)} texts")
        embeddings = embedding_function(
            list(map(lambda x: x.replace("\n", " "), texts)),
            prefix=RAG_EMBEDDING_CONTENT_PREFIX,
            user=user,
        )
        log.info(f"Generated {len(embeddings)} embeddings")

        items = [
            {
                "id": str(uuid.uuid4()),
                "text": text,
                "vector": embeddings[idx],
                "metadata": metadatas[idx],
            }
            for idx, text in enumerate(texts)
        ]

        log.info(f"Inserting {len(items)} items into collection {collection_name}")
        VECTOR_DB_CLIENT.insert(
            collection_name=collection_name,
            items=items,
        )
        log.info(f"Successfully inserted {len(items)} items into collection {collection_name}")

        log.info(f"=== SAVE_DOCS_TO_VECTOR_DB COMPLETE === Collection: {collection_name}")
        return True
    except Exception as e:
        log.exception(f"Error in save_docs_to_vector_db for collection {collection_name}: {str(e)}")
        raise e


class ProcessFileForm(BaseModel):
    file_id: str
    content: Optional[str] = None
    collection_name: Optional[str] = None


@router.post("/process/file")
def process_file(
    request: Request,
    form_data: ProcessFileForm,
    user=Depends(get_verified_user),
):
    log.info(f"=== PROCESS_FILE START === File ID: {form_data.file_id}, Collection Name: {form_data.collection_name}")
    
    try:
        file = Files.get_file_by_id(form_data.file_id)
        log.info(f"File found: {file.filename} (ID: {file.id})")

        collection_name = form_data.collection_name

        if collection_name is None:
            collection_name = f"file-{file.id}"
            log.info(f"No collection name provided, using default: {collection_name}")
        else:
            log.info(f"Using provided collection name: {collection_name}")

        # Check if file already exists in vector DB by file_id (for knowledge base mode)
        if form_data.collection_name:
            log.info(f"Checking for existing document with file_id: {file.id} in collection {collection_name}")
            existing_docs = VECTOR_DB_CLIENT.query(
                collection_name=collection_name,
                filter={"file_id": file.id},
            )

            if existing_docs is not None and existing_docs.ids[0]:
                log.info(f"Document with file_id {file.id} already exists in collection {collection_name}, skipping file")
                raise ValueError(f"File already exists in collection {collection_name}")

            # Fallback: Check by filename for files added before file_id metadata was consistent
            log.info(f"Checking for existing document with filename: {file.filename} in collection {collection_name}")
            existing_docs_by_name = VECTOR_DB_CLIENT.query(
                collection_name=collection_name,
                filter={"name": file.filename},
            )

            if existing_docs_by_name is not None and existing_docs_by_name.ids[0]:
                log.info(f"Document with filename {file.filename} already exists in collection {collection_name}, skipping file")
                raise ValueError(f"File with same name already exists in collection {collection_name}")

        if form_data.content:
            log.info("Processing with provided content (content update mode)")
            # Update the content in the file
            # Usage: /files/{file_id}/data/content/update, /files/ (audio file upload pipeline)

            try:
                # /files/{file_id}/data/content/update
                log.info(f"Deleting file collection: file-{file.id}")
                VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file.id}")
            except:
                # Audio file upload pipeline
                log.info("Audio file upload pipeline - skipping file collection deletion")
                pass

            docs = [
                Document(
                    page_content=form_data.content.replace("<br/>", "\n"),
                    metadata={
                        **file.meta,
                        "name": file.filename,
                        "created_by": file.user_id,
                        "file_id": file.id,
                        "source": file.filename,
                    },
                )
            ]

            text_content = form_data.content
            log.info(f"Created {len(docs)} documents from provided content")
        elif form_data.collection_name:
            log.info("Processing with collection name (knowledge base mode)")
            # Check if the file has already been processed and save the content
            # Usage: /knowledge/{id}/file/add, /knowledge/{id}/file/update

            log.info(f"Querying existing vector DB entries for file {file.id}")
            result = VECTOR_DB_CLIENT.query(
                collection_name=f"file-{file.id}", filter={"file_id": file.id}
            )

            if result is not None and len(result.ids[0]) > 0:
                log.info(f"Found {len(result.ids[0])} existing vector DB entries for file {file.id}")
                docs = [
                    Document(
                        page_content=result.documents[0][idx],
                        metadata=result.metadatas[0][idx],
                    )
                    for idx, id in enumerate(result.ids[0])
                ]
            else:
                log.info(f"No existing vector DB entries found for file {file.id}, using file data")
                docs = [
                    Document(
                        page_content=file.data.get("content", ""),
                        metadata={
                            **file.meta,
                            "name": file.filename,
                            "created_by": file.user_id,
                            "file_id": file.id,
                            "source": file.filename,
                        },
                    )
                ]

            text_content = file.data.get("content", "")
            log.info(f"Created {len(docs)} documents from file data, content length: {len(text_content)}")
        else:
            log.info("Processing file from scratch (file upload mode)")
            # Process the file and save the content
            # Usage: /files/
            file_path = file.path
            if file_path:
                file_path = Storage.get_file(file_path)
                log.info(f"Processing file: {file.filename} at path: {file_path}")
                
                # Log the processing configuration
                content_extraction_engine = request.app.state.config.CONTENT_EXTRACTION_ENGINE
                pdf_extract_images = request.app.state.config.PDF_EXTRACT_IMAGES
                log.info(f"Processing file {file.filename} with engine: {content_extraction_engine}, PDF extract images: {pdf_extract_images}")
                log.info("=== DEBUG: This is a test message to verify our changes are loaded ===")
                
                loader = Loader(
                    engine=request.app.state.config.CONTENT_EXTRACTION_ENGINE,
                    DATALAB_MARKER_API_KEY=request.app.state.config.DATALAB_MARKER_API_KEY,
                    DATALAB_MARKER_LANGS=request.app.state.config.DATALAB_MARKER_LANGS,
                    DATALAB_MARKER_SKIP_CACHE=request.app.state.config.DATALAB_MARKER_SKIP_CACHE,
                    DATALAB_MARKER_FORCE_OCR=request.app.state.config.DATALAB_MARKER_FORCE_OCR,
                    DATALAB_MARKER_PAGINATE=request.app.state.config.DATALAB_MARKER_PAGINATE,
                    DATALAB_MARKER_STRIP_EXISTING_OCR=request.app.state.config.DATALAB_MARKER_STRIP_EXISTING_OCR,
                    DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION=request.app.state.config.DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION,
                    DATALAB_MARKER_USE_LLM=request.app.state.config.DATALAB_MARKER_USE_LLM,
                    DATALAB_MARKER_OUTPUT_FORMAT=request.app.state.config.DATALAB_MARKER_OUTPUT_FORMAT,
                    EXTERNAL_DOCUMENT_LOADER_URL=request.app.state.config.EXTERNAL_DOCUMENT_LOADER_URL,
                    EXTERNAL_DOCUMENT_LOADER_API_KEY=request.app.state.config.EXTERNAL_DOCUMENT_LOADER_API_KEY,
                    TIKA_SERVER_URL=request.app.state.config.TIKA_SERVER_URL,
                    DOCLING_SERVER_URL=request.app.state.config.DOCLING_SERVER_URL,
                    DOCLING_PARAMS={
                        "ocr_engine": request.app.state.config.DOCLING_OCR_ENGINE,
                        "ocr_lang": request.app.state.config.DOCLING_OCR_LANG,
                        "do_picture_description": request.app.state.config.DOCLING_DO_PICTURE_DESCRIPTION,
                        "picture_description_mode": request.app.state.config.DOCLING_PICTURE_DESCRIPTION_MODE,
                        "picture_description_local": request.app.state.config.DOCLING_PICTURE_DESCRIPTION_LOCAL,
                        "picture_description_api": request.app.state.config.DOCLING_PICTURE_DESCRIPTION_API,
                    },
                    PDF_EXTRACT_IMAGES=request.app.state.config.PDF_EXTRACT_IMAGES,
                    DOCUMENT_INTELLIGENCE_ENDPOINT=request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
                    DOCUMENT_INTELLIGENCE_KEY=request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
                    MISTRAL_OCR_API_KEY=request.app.state.config.MISTRAL_OCR_API_KEY,
                )
                log.info(f"Loader created successfully: {loader.__class__.__name__}")
                log.info(f"About to call loader.load() for {file.filename}")
                docs = loader.load(
                    file.filename, file.meta.get("content_type"), file_path
                )
                log.info(f"loader.load() completed, got {len(docs) if docs else 0} documents")

                docs = [
                    Document(
                        page_content=doc.page_content,
                        metadata={
                            **doc.metadata,
                            "name": file.filename,
                            "created_by": file.user_id,
                            "file_id": file.id,
                            "source": file.filename,
                        },
                    )
                    for doc in docs
                ]
            else:
                log.info("No file path available, using file data")
                docs = [
                    Document(
                        page_content=file.data.get("content", ""),
                        metadata={
                            **file.meta,
                            "name": file.filename,
                            "created_by": file.user_id,
                            "file_id": file.id,
                            "source": file.filename,
                        },
                    )
                ]
            text_content = " ".join([doc.page_content for doc in docs])

        log.debug(f"text_content: {text_content}")
        
        # Check if content is empty before proceeding
        if not text_content or not text_content.strip():
            log.warning(f"Empty content extracted from file {file.filename} (ID: {file.id})")
            
            # Try RapidOCR as fallback for PDFs if available
            if (file.filename.lower().endswith('.pdf') and 
                RAPIDOCR_AVAILABLE and 
                (not request.app.state.config.CONTENT_EXTRACTION_ENGINE or 
                 request.app.state.config.CONTENT_EXTRACTION_ENGINE == "rapidocr")):
                
                log.info(f"Attempting RapidOCR fallback for PDF {file.filename}")
                try:
                    from open_webui.retrieval.loaders.rapidocr_pdf import RapidOCRPDFLoader, is_rapidocr_available
                    
                    # Check if RapidOCR is available
                    if not is_rapidocr_available():
                        log.warning("RapidOCR is not available for fallback")
                        raise ValueError("RapidOCR is not available")
                    
                    # Get the file path for the fallback
                    fallback_file_path = file.path
                    if fallback_file_path:
                        fallback_file_path = Storage.get_file(fallback_file_path)
                    
                    log.info("Creating RapidOCR loader...")
                    # Create RapidOCR loader
                    ocr_loader = RapidOCRPDFLoader(fallback_file_path, extract_images=True)
                    
                    log.info("Loading PDF with RapidOCR...")
                    ocr_docs = ocr_loader.load()
                    
                    if ocr_docs and ocr_docs[0].page_content.strip():
                        log.info(f"RapidOCR successfully extracted {len(ocr_docs[0].page_content)} characters")
                        
                        # Update the docs and text_content with OCR results
                        docs = ocr_docs
                        text_content = ocr_docs[0].page_content
                        
                        # Continue with the OCR-extracted content
                        log.info(f"Using OCR-extracted content for {file.filename}")
                    else:
                        log.warning("RapidOCR returned empty content")
                        raise ValueError("RapidOCR also failed to extract content")
                        
                except Exception as ocr_error:
                    log.error(f"RapidOCR fallback also failed: {str(ocr_error)}")
                    raise ValueError("No content could be extracted from the file. This may be because the file is empty, corrupted, password-protected, or uses an unsupported format.")
            else:
                raise ValueError("No content could be extracted from the file. This may be because the file is empty, corrupted, password-protected, or uses an unsupported format.")
        
        log.info(f"Updating file data with content length: {len(text_content)}")
        Files.update_file_data_by_id(
            file.id,
            {"content": text_content},
        )

        hash = calculate_sha256_string(text_content)
        log.info(f"Calculated hash: {hash}")
        Files.update_file_hash_by_id(file.id, hash)

        if not request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL:
            log.info("BYPASS_EMBEDDING_AND_RETRIEVAL is False, proceeding with vector DB operations")
            try:
                # Determine the add parameter
                add_param = True if form_data.collection_name else False
                log.info(f"Calling save_docs_to_vector_db with add={add_param}, collection_name={collection_name}")
                
                result = save_docs_to_vector_db(
                    request,
                    docs=docs,
                    collection_name=collection_name,
                    metadata={
                        "file_id": file.id,
                        "name": file.filename,
                        "hash": hash,
                    },
                    add=add_param,
                    user=user,
                )

                if result:
                    log.info(f"Successfully saved docs to vector DB, updating file metadata with collection_name: {collection_name}")
                    Files.update_file_metadata_by_id(
                        file.id,
                        {
                            "collection_name": collection_name,
                        },
                    )

                    log.info(f"=== PROCESS_FILE COMPLETE === File ID: {form_data.file_id}, Collection: {collection_name}")
                    return {
                        "status": True,
                        "collection_name": collection_name,
                        "filename": file.filename,
                        "content": text_content,
                    }
            except Exception as e:
                log.error(f"Error in save_docs_to_vector_db: {str(e)}")
                raise e
        else:
            log.info("BYPASS_EMBEDDING_AND_RETRIEVAL is True, skipping vector DB operations")
            return {
                "status": True,
                "collection_name": None,
                "filename": file.filename,
                "content": text_content,
            }

    except Exception as e:
        log.exception(f"Error in process_file for file {form_data.file_id}: {str(e)}")
        if "No pandoc was found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.PANDOC_NOT_INSTALLED,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )


class ProcessTextForm(BaseModel):
    name: str
    content: str
    collection_name: Optional[str] = None


@router.post("/process/text")
def process_text(
    request: Request,
    form_data: ProcessTextForm,
    user=Depends(get_verified_user),
):
    collection_name = form_data.collection_name
    if collection_name is None:
        collection_name = calculate_sha256_string(form_data.content)

    docs = [
        Document(
            page_content=form_data.content,
            metadata={"name": form_data.name, "created_by": user.id},
        )
    ]
    text_content = form_data.content
    log.debug(f"text_content: {text_content}")

    result = save_docs_to_vector_db(request, docs, collection_name, user=user)
    if result:
        return {
            "status": True,
            "collection_name": collection_name,
            "content": text_content,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(),
        )


@router.post("/process/youtube")
def process_youtube_video(
    request: Request, form_data: ProcessUrlForm, user=Depends(get_verified_user)
):
    try:
        collection_name = form_data.collection_name
        if not collection_name:
            collection_name = calculate_sha256_string(form_data.url)[:63]

        loader = YoutubeLoader(
            form_data.url,
            language=request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
            proxy_url=request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
        )

        docs = loader.load()
        content = " ".join([doc.page_content for doc in docs])
        log.debug(f"text_content: {content}")

        save_docs_to_vector_db(
            request, docs, collection_name, overwrite=True, user=user
        )

        return {
            "status": True,
            "collection_name": collection_name,
            "filename": form_data.url,
            "file": {
                "data": {
                    "content": content,
                },
                "meta": {
                    "name": form_data.url,
                },
            },
        }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


@router.post("/process/web")
def process_web(
    request: Request, form_data: ProcessUrlForm, user=Depends(get_verified_user)
):
    try:
        collection_name = form_data.collection_name
        if not collection_name:
            collection_name = calculate_sha256_string(form_data.url)[:63]

        loader = get_web_loader(
            form_data.url,
            verify_ssl=request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
            requests_per_second=request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS,
        )
        docs = loader.load()
        content = " ".join([doc.page_content for doc in docs])

        log.debug(f"text_content: {content}")

        if not request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL:
            save_docs_to_vector_db(
                request, docs, collection_name, overwrite=True, user=user
            )
        else:
            collection_name = None

        return {
            "status": True,
            "collection_name": collection_name,
            "filename": form_data.url,
            "file": {
                "data": {
                    "content": content,
                },
                "meta": {
                    "name": form_data.url,
                    "source": form_data.url,
                },
            },
        }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


def search_web(request: Request, engine: str, query: str) -> list[SearchResult]:
    """Search the web using a search engine and return the results as a list of SearchResult objects.
    Will look for a search engine API key in environment variables in the following order:
    - SEARXNG_QUERY_URL
    - YACY_QUERY_URL + YACY_USERNAME + YACY_PASSWORD
    - GOOGLE_PSE_API_KEY + GOOGLE_PSE_ENGINE_ID
    - BRAVE_SEARCH_API_KEY
    - KAGI_SEARCH_API_KEY
    - MOJEEK_SEARCH_API_KEY
    - BOCHA_SEARCH_API_KEY
    - SERPSTACK_API_KEY
    - SERPER_API_KEY
    - SERPLY_API_KEY
    - TAVILY_API_KEY
    - EXA_API_KEY
    - PERPLEXITY_API_KEY
    - SOUGOU_API_SID + SOUGOU_API_SK
    - SEARCHAPI_API_KEY + SEARCHAPI_ENGINE (by default `google`)
    - SERPAPI_API_KEY + SERPAPI_ENGINE (by default `google`)
    Args:
        query (str): The query to search for
    """

    # TODO: add playwright to search the web
    if engine == "searxng":
        if request.app.state.config.SEARXNG_QUERY_URL:
            return search_searxng(
                request.app.state.config.SEARXNG_QUERY_URL,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No SEARXNG_QUERY_URL found in environment variables")
    elif engine == "yacy":
        if request.app.state.config.YACY_QUERY_URL:
            return search_yacy(
                request.app.state.config.YACY_QUERY_URL,
                request.app.state.config.YACY_USERNAME,
                request.app.state.config.YACY_PASSWORD,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No YACY_QUERY_URL found in environment variables")
    elif engine == "google_pse":
        if (
            request.app.state.config.GOOGLE_PSE_API_KEY
            and request.app.state.config.GOOGLE_PSE_ENGINE_ID
        ):
            return search_google_pse(
                request.app.state.config.GOOGLE_PSE_API_KEY,
                request.app.state.config.GOOGLE_PSE_ENGINE_ID,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception(
                "No GOOGLE_PSE_API_KEY or GOOGLE_PSE_ENGINE_ID found in environment variables"
            )
    elif engine == "brave":
        if request.app.state.config.BRAVE_SEARCH_API_KEY:
            return search_brave(
                request.app.state.config.BRAVE_SEARCH_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No BRAVE_SEARCH_API_KEY found in environment variables")
    elif engine == "kagi":
        if request.app.state.config.KAGI_SEARCH_API_KEY:
            return search_kagi(
                request.app.state.config.KAGI_SEARCH_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No KAGI_SEARCH_API_KEY found in environment variables")
    elif engine == "mojeek":
        if request.app.state.config.MOJEEK_SEARCH_API_KEY:
            return search_mojeek(
                request.app.state.config.MOJEEK_SEARCH_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No MOJEEK_SEARCH_API_KEY found in environment variables")
    elif engine == "bocha":
        if request.app.state.config.BOCHA_SEARCH_API_KEY:
            return search_bocha(
                request.app.state.config.BOCHA_SEARCH_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No BOCHA_SEARCH_API_KEY found in environment variables")
    elif engine == "serpstack":
        if request.app.state.config.SERPSTACK_API_KEY:
            return search_serpstack(
                request.app.state.config.SERPSTACK_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
                https_enabled=request.app.state.config.SERPSTACK_HTTPS,
            )
        else:
            raise Exception("No SERPSTACK_API_KEY found in environment variables")
    elif engine == "serper":
        if request.app.state.config.SERPER_API_KEY:
            return search_serper(
                request.app.state.config.SERPER_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No SERPER_API_KEY found in environment variables")
    elif engine == "serply":
        if request.app.state.config.SERPLY_API_KEY:
            return search_serply(
                request.app.state.config.SERPLY_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No SERPLY_API_KEY found in environment variables")
    elif engine == "duckduckgo":
        return search_duckduckgo(
            query,
            request.app.state.config.WEB_SEARCH_RESULT_COUNT,
            request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
        )
    elif engine == "tavily":
        if request.app.state.config.TAVILY_API_KEY:
            return search_tavily(
                request.app.state.config.TAVILY_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No TAVILY_API_KEY found in environment variables")
    elif engine == "exa":
        if request.app.state.config.EXA_API_KEY:
            return search_exa(
                request.app.state.config.EXA_API_KEY,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No EXA_API_KEY found in environment variables")
    elif engine == "searchapi":
        if request.app.state.config.SEARCHAPI_API_KEY:
            return search_searchapi(
                request.app.state.config.SEARCHAPI_API_KEY,
                request.app.state.config.SEARCHAPI_ENGINE,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No SEARCHAPI_API_KEY found in environment variables")
    elif engine == "serpapi":
        if request.app.state.config.SERPAPI_API_KEY:
            return search_serpapi(
                request.app.state.config.SERPAPI_API_KEY,
                request.app.state.config.SERPAPI_ENGINE,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception("No SERPAPI_API_KEY found in environment variables")
    elif engine == "jina":
        return search_jina(
            request.app.state.config.JINA_API_KEY,
            query,
            request.app.state.config.WEB_SEARCH_RESULT_COUNT,
        )
    elif engine == "bing":
        return search_bing(
            request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY,
            request.app.state.config.BING_SEARCH_V7_ENDPOINT,
            str(DEFAULT_LOCALE),
            query,
            request.app.state.config.WEB_SEARCH_RESULT_COUNT,
            request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
        )
    elif engine == "exa":
        return search_exa(
            request.app.state.config.EXA_API_KEY,
            query,
            request.app.state.config.WEB_SEARCH_RESULT_COUNT,
            request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
        )
    elif engine == "perplexity":
        return search_perplexity(
            request.app.state.config.PERPLEXITY_API_KEY,
            query,
            request.app.state.config.WEB_SEARCH_RESULT_COUNT,
            request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            model=request.app.state.config.PERPLEXITY_MODEL,
            search_context_usage=request.app.state.config.PERPLEXITY_SEARCH_CONTEXT_USAGE,
        )
    elif engine == "sougou":
        if (
            request.app.state.config.SOUGOU_API_SID
            and request.app.state.config.SOUGOU_API_SK
        ):
            return search_sougou(
                request.app.state.config.SOUGOU_API_SID,
                request.app.state.config.SOUGOU_API_SK,
                query,
                request.app.state.config.WEB_SEARCH_RESULT_COUNT,
                request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
            )
        else:
            raise Exception(
                "No SOUGOU_API_SID or SOUGOU_API_SK found in environment variables"
            )
    elif engine == "firecrawl":
        return search_firecrawl(
            request.app.state.config.FIRECRAWL_API_BASE_URL,
            request.app.state.config.FIRECRAWL_API_KEY,
            query,
            request.app.state.config.WEB_SEARCH_RESULT_COUNT,
            request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
        )
    elif engine == "external":
        return search_external(
            request.app.state.config.EXTERNAL_WEB_SEARCH_URL,
            request.app.state.config.EXTERNAL_WEB_SEARCH_API_KEY,
            query,
            request.app.state.config.WEB_SEARCH_RESULT_COUNT,
            request.app.state.config.WEB_SEARCH_DOMAIN_FILTER_LIST,
        )
    else:
        raise Exception("No search engine API key found in environment variables")


@router.post("/process/web/search")
async def process_web_search(
    request: Request, form_data: SearchForm, user=Depends(get_verified_user)
):

    urls = []
    try:
        logging.info(
            f"trying to web search with {request.app.state.config.WEB_SEARCH_ENGINE, form_data.queries}"
        )

        search_tasks = [
            run_in_threadpool(
                search_web,
                request,
                request.app.state.config.WEB_SEARCH_ENGINE,
                query,
            )
            for query in form_data.queries
        ]

        search_results = await asyncio.gather(*search_tasks)

        for result in search_results:
            if result:
                for item in result:
                    if item and item.link:
                        urls.append(item.link)

        urls = list(dict.fromkeys(urls))
        log.debug(f"urls: {urls}")

    except Exception as e:
        log.exception(e)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.WEB_SEARCH_ERROR(e),
        )

    try:
        if request.app.state.config.BYPASS_WEB_SEARCH_WEB_LOADER:
            search_results = [
                item for result in search_results for item in result if result
            ]

            docs = [
                Document(
                    page_content=result.snippet,
                    metadata={
                        "source": result.link,
                        "title": result.title,
                        "snippet": result.snippet,
                        "link": result.link,
                    },
                )
                for result in search_results
                if hasattr(result, "snippet")
            ]
        else:
            loader = get_web_loader(
                urls,
                verify_ssl=request.app.state.config.ENABLE_WEB_LOADER_SSL_VERIFICATION,
                requests_per_second=request.app.state.config.WEB_SEARCH_CONCURRENT_REQUESTS,
                trust_env=request.app.state.config.WEB_SEARCH_TRUST_ENV,
            )
            docs = await loader.aload()

        urls = [
            doc.metadata.get("source") for doc in docs if doc.metadata.get("source")
        ]  # only keep the urls returned by the loader

        if request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL:
            return {
                "status": True,
                "collection_name": None,
                "filenames": urls,
                "docs": [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                    }
                    for doc in docs
                ],
                "loaded_count": len(docs),
            }
        else:
            # Create a single collection for all documents
            collection_name = (
                f"web-search-{calculate_sha256_string('-'.join(form_data.queries))}"[
                    :63
                ]
            )

            try:
                await run_in_threadpool(
                    save_docs_to_vector_db,
                    request,
                    docs,
                    collection_name,
                    overwrite=True,
                    user=user,
                )
            except Exception as e:
                log.debug(f"error saving docs: {e}")

            return {
                "status": True,
                "collection_names": [collection_name],
                "filenames": urls,
                "loaded_count": len(docs),
            }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


class QueryDocForm(BaseModel):
    collection_name: str
    query: str
    k: Optional[int] = None
    k_reranker: Optional[int] = None
    r: Optional[float] = None
    hybrid: Optional[bool] = None


@router.post("/query/doc")
def query_doc_handler(
    request: Request,
    form_data: QueryDocForm,
    user=Depends(get_verified_user),
):
    try:
        if request.app.state.config.ENABLE_RAG_HYBRID_SEARCH:
            collection_results = {}
            collection_results[form_data.collection_name] = VECTOR_DB_CLIENT.get(
                collection_name=form_data.collection_name
            )
            return query_doc_with_hybrid_search(
                collection_name=form_data.collection_name,
                collection_result=collection_results[form_data.collection_name],
                query=form_data.query,
                embedding_function=lambda query, prefix: request.app.state.EMBEDDING_FUNCTION(
                    query, prefix=prefix, user=user
                ),
                k=form_data.k if form_data.k else request.app.state.config.TOP_K,
                reranking_function=(
                    (
                        lambda sentences: request.app.state.RERANKING_FUNCTION(
                            sentences, user=user
                        )
                    )
                    if request.app.state.RERANKING_FUNCTION
                    else None
                ),
                k_reranker=form_data.k_reranker
                or request.app.state.config.TOP_K_RERANKER,
                r=(
                    form_data.r
                    if form_data.r
                    else request.app.state.config.RELEVANCE_THRESHOLD
                ),
                hybrid_bm25_weight=(
                    form_data.hybrid_bm25_weight
                    if form_data.hybrid_bm25_weight
                    else request.app.state.config.HYBRID_BM25_WEIGHT
                ),
                user=user,
            )
        else:
            return query_doc(
                collection_name=form_data.collection_name,
                query_embedding=request.app.state.EMBEDDING_FUNCTION(
                    form_data.query, prefix=RAG_EMBEDDING_QUERY_PREFIX, user=user
                ),
                k=form_data.k if form_data.k else request.app.state.config.TOP_K,
                user=user,
            )
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


class QueryCollectionsForm(BaseModel):
    collection_names: list[str]
    query: str
    k: Optional[int] = None
    k_reranker: Optional[int] = None
    r: Optional[float] = None
    hybrid: Optional[bool] = None
    hybrid_bm25_weight: Optional[float] = None


@router.post("/query/collection")
def query_collection_handler(
    request: Request,
    form_data: QueryCollectionsForm,
    user=Depends(get_verified_user),
):
    try:
        if request.app.state.config.ENABLE_RAG_HYBRID_SEARCH:
            return query_collection_with_hybrid_search(
                collection_names=form_data.collection_names,
                queries=[form_data.query],
                embedding_function=lambda query, prefix: request.app.state.EMBEDDING_FUNCTION(
                    query, prefix=prefix, user=user
                ),
                k=form_data.k if form_data.k else request.app.state.config.TOP_K,
                reranking_function=(
                    (
                        lambda sentences: request.app.state.RERANKING_FUNCTION(
                            sentences, user=user
                        )
                    )
                    if request.app.state.RERANKING_FUNCTION
                    else None
                ),
                k_reranker=form_data.k_reranker
                or request.app.state.config.TOP_K_RERANKER,
                r=(
                    form_data.r
                    if form_data.r
                    else request.app.state.config.RELEVANCE_THRESHOLD
                ),
                hybrid_bm25_weight=(
                    form_data.hybrid_bm25_weight
                    if form_data.hybrid_bm25_weight
                    else request.app.state.config.HYBRID_BM25_WEIGHT
                ),
            )
        else:
            return query_collection(
                collection_names=form_data.collection_names,
                queries=[form_data.query],
                embedding_function=lambda query, prefix: request.app.state.EMBEDDING_FUNCTION(
                    query, prefix=prefix, user=user
                ),
                k=form_data.k if form_data.k else request.app.state.config.TOP_K,
            )

    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


####################################
#
# Vector DB operations
#
####################################


class DeleteForm(BaseModel):
    collection_name: str
    file_id: str


@router.post("/delete")
def delete_entries_from_collection(form_data: DeleteForm, user=Depends(get_admin_user)):
    try:
        if VECTOR_DB_CLIENT.has_collection(collection_name=form_data.collection_name):
            file = Files.get_file_by_id(form_data.file_id)
            hash = file.hash

            VECTOR_DB_CLIENT.delete(
                collection_name=form_data.collection_name,
                metadata={"hash": hash},
            )
            return {"status": True}
        else:
            return {"status": False}
    except Exception as e:
        log.exception(e)
        return {"status": False}


@router.post("/reset/db")
def reset_vector_db(user=Depends(get_admin_user)):
    VECTOR_DB_CLIENT.reset()
    Knowledges.delete_all_knowledge()


@router.post("/reset/uploads")
def reset_upload_dir(user=Depends(get_admin_user)) -> bool:
    folder = f"{UPLOAD_DIR}"
    try:
        # Check if the directory exists
        if os.path.exists(folder):
            # Iterate over all the files and directories in the specified directory
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)  # Remove the file or link
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)  # Remove the directory
                except Exception as e:
                    log.exception(f"Failed to delete {file_path}. Reason: {e}")
        else:
            log.warning(f"The directory {folder} does not exist")
    except Exception as e:
        log.exception(f"Failed to process the directory {folder}. Reason: {e}")
    return True


if ENV == "dev":

    @router.get("/ef/{text}")
    async def get_embeddings(request: Request, text: Optional[str] = "Hello World!"):
        return {
            "result": request.app.state.EMBEDDING_FUNCTION(
                text, prefix=RAG_EMBEDDING_QUERY_PREFIX
            )
        }


class BatchProcessFilesForm(BaseModel):
    files: List[FileModel]
    collection_name: str


class BatchProcessFilesResult(BaseModel):
    file_id: str
    status: str
    error: Optional[str] = None


class BatchProcessFilesResponse(BaseModel):
    results: List[BatchProcessFilesResult]
    errors: List[BatchProcessFilesResult]


@router.post("/process/files/batch")
def process_files_batch(
    request: Request,
    form_data: BatchProcessFilesForm,
    user=Depends(get_verified_user),
) -> BatchProcessFilesResponse:
    """
    Process a batch of files and save them to the vector database.
    """
    results: List[BatchProcessFilesResult] = []
    errors: List[BatchProcessFilesResult] = []
    collection_name = form_data.collection_name

    # Prepare all documents first
    all_docs: List[Document] = []
    for file in form_data.files:
        try:
            text_content = file.data.get("content", "")

            # Check if file already exists in vector DB by file_id (more reliable than hash for audio/video)
            log.info(f"Checking for existing document with file_id: {file.id}")
            existing_docs = VECTOR_DB_CLIENT.query(
                collection_name=collection_name,
                filter={"file_id": file.id},
            )

            if existing_docs is not None and existing_docs.ids[0]:
                log.info(f"Document with file_id {file.id} already exists in collection {collection_name}, skipping file")
                results.append(BatchProcessFilesResult(file_id=file.id, status="skipped", error="File already exists in collection"))
                continue

            # Fallback: Check by filename for files added before file_id metadata was consistent
            log.info(f"Checking for existing document with filename: {file.filename}")
            existing_docs_by_name = VECTOR_DB_CLIENT.query(
                collection_name=collection_name,
                filter={"name": file.filename},
            )

            if existing_docs_by_name is not None and existing_docs_by_name.ids[0]:
                log.info(f"Document with filename {file.filename} already exists in collection {collection_name}, skipping file")
                results.append(BatchProcessFilesResult(file_id=file.id, status="skipped", error="File with same name already exists in collection"))
                continue

            # Calculate hash for the file (for future deduplication)
            hash = calculate_sha256_string(text_content)
            Files.update_file_hash_by_id(file.id, hash)
            Files.update_file_data_by_id(file.id, {"content": text_content})

            docs: List[Document] = [
                Document(
                    page_content=text_content.replace("<br/>", "\n"),
                    metadata={
                        **file.meta,
                        "name": file.filename,
                        "created_by": file.user_id,
                        "file_id": file.id,
                        "source": file.filename,
                        "hash": hash,  # Include hash in metadata for future deduplication
                    },
                )
            ]

            all_docs.extend(docs)
            results.append(BatchProcessFilesResult(file_id=file.id, status="prepared"))

        except Exception as e:
            log.error(f"process_files_batch: Error processing file {file.id}: {str(e)}")
            errors.append(
                BatchProcessFilesResult(file_id=file.id, status="failed", error=str(e))
            )

    # Save all documents in one batch
    if all_docs:
        try:
            save_docs_to_vector_db(
                request=request,
                docs=all_docs,
                collection_name=collection_name,
                add=True,
                user=user,
            )

            # Update all files with collection name
            for result in results:
                if result.status == "prepared":
                    Files.update_file_metadata_by_id(
                        result.file_id, {"collection_name": collection_name}
                    )
                    result.status = "completed"

        except Exception as e:
            log.error(
                f"process_files_batch: Error saving documents to vector DB: {str(e)}"
            )
            for result in results:
                if result.status == "prepared":
                    result.status = "failed"
                    errors.append(
                        BatchProcessFilesResult(file_id=result.file_id, error=str(e))
                    )

    return BatchProcessFilesResponse(results=results, errors=errors)

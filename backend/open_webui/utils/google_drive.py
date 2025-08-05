import logging
import requests
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote

log = logging.getLogger(__name__)


class GoogleDriveService:
    """Service for interacting with Google Drive API using provided OAuth tokens"""
    
    def __init__(self):
        self.base_url = "https://www.googleapis.com/drive/v3"
    
    def download_file(self, file_id: str, oauth_token: str) -> Tuple[bytes, str, str]:
        """
        Download a file from Google Drive using OAuth token
        
        Args:
            file_id: Google Drive file ID
            oauth_token: OAuth access token
            
        Returns:
            Tuple of (file_content, filename, mime_type)
        """
        try:
            # First get file metadata
            metadata_url = f"{self.base_url}/files/{file_id}"
            headers = {
                "Authorization": f"Bearer {oauth_token}",
                "Accept": "application/json"
            }
            
            metadata_response = requests.get(metadata_url, headers=headers)
            metadata_response.raise_for_status()
            file_metadata = metadata_response.json()
            
            filename = file_metadata.get("name", "unknown_file")
            mime_type = file_metadata.get("mimeType", "application/octet-stream")
            
            # Determine download URL based on MIME type
            if mime_type.startswith("application/vnd.google-apps"):
                # Google Workspace files need export
                export_format = self._get_export_format(mime_type)
                download_url = f"{self.base_url}/files/{file_id}/export?mimeType={quote(export_format)}"
            else:
                # Regular files use direct download
                download_url = f"{self.base_url}/files/{file_id}?alt=media"
            
            # Download file content
            download_response = requests.get(download_url, headers=headers)
            download_response.raise_for_status()
            
            return download_response.content, filename, mime_type
            
        except requests.exceptions.RequestException as e:
            log.error(f"Error downloading file {file_id}: {e}")
            raise RuntimeError(f"Failed to download file from Google Drive: {e}")
    
    def list_folder_files(self, folder_id: str, oauth_token: str, recursive: bool = True) -> List[Dict]:
        """
        List all files in a Google Drive folder
        
        Args:
            folder_id: Google Drive folder ID
            oauth_token: OAuth access token
            recursive: Whether to include files in subfolders
            
        Returns:
            List of file metadata dictionaries
        """
        try:
            files = []
            page_token = None
            
            while True:
                # Build query for files in folder
                query = f"'{folder_id}' in parents and trashed=false"
                
                url = f"{self.base_url}/files"
                params = {
                    "q": query,
                    "fields": "nextPageToken,files(id,name,mimeType,size,parents)",
                    "pageSize": 1000
                }
                
                if page_token:
                    params["pageToken"] = page_token
                
                headers = {
                    "Authorization": f"Bearer {oauth_token}",
                    "Accept": "application/json"
                }
                
                response = requests.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                # Process files in current page
                for file_info in data.get("files", []):
                    mime_type = file_info.get("mimeType", "")
                    file_name = file_info.get("name", "")
                    
                    log.info(f"Google Drive file found: {file_name} (MIME: {mime_type})")
                    
                    if mime_type == "application/vnd.google-apps.folder":
                        # It's a folder
                        log.info(f"Found folder: {file_name}")
                        if recursive:
                            # Recursively get files from subfolder
                            subfolder_files = self.list_folder_files(
                                file_info["id"], 
                                oauth_token, 
                                recursive=True
                            )
                            files.extend(subfolder_files)
                    else:
                        # It's a file - check if it's a supported type
                        is_supported = self._is_supported_file_type(mime_type)
                        log.info(f"File {file_name} (MIME: {mime_type}) - Supported: {is_supported}")
                        if is_supported:
                            files.append(file_info)
                        else:
                            log.info(f"File {file_name} filtered out - unsupported MIME type: {mime_type}")
                
                # Check if there are more pages
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
            
            return files
            
        except requests.exceptions.RequestException as e:
            log.error(f"Error listing folder {folder_id}: {e}")
            raise RuntimeError(f"Failed to list folder contents: {e}")
    
    def _get_export_format(self, mime_type: str) -> str:
        """Get the appropriate export format for Google Workspace files"""
        if "document" in mime_type:
            return "text/plain"
        elif "spreadsheet" in mime_type:
            return "text/csv"
        elif "presentation" in mime_type:
            return "text/plain"
        else:
            return "application/pdf"
    
    def _is_supported_file_type(self, mime_type: str) -> bool:
        """Check if the MIME type is supported for processing"""
        supported_types = [
            "application/pdf",
            "text/plain",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.google-apps.document",
            "application/vnd.google-apps.spreadsheet", 
            "application/vnd.google-apps.presentation",
            "application/epub+zip",
            "text/markdown",
            "text/csv",
            "application/json",
            "application/xml",
            "text/html",
            # Video file types
            "video/mp4",
            "video/webm",
            "video/avi",
            "video/quicktime",
            "video/x-msvideo",
            "video/x-ms-wmv",
            "video/x-flv",
            "video/x-matroska",
            "video/3gpp",
            "video/ogg",
            # Audio file types
            "audio/mpeg",
            "audio/wav",
            "audio/mp4",
            "audio/aac",
            "audio/flac",
            "audio/ogg",
            "audio/m4a",
            "audio/x-m4a",
            "audio/x-aac",
            "audio/x-wav"
        ]
        
        is_supported = mime_type in supported_types
        log.info(f"MIME type check: '{mime_type}' -> Supported: {is_supported}")
        if not is_supported:
            log.info(f"Unsupported MIME type: '{mime_type}'. Supported audio types: {[t for t in supported_types if t.startswith('audio/')]}")
        
        return is_supported


# Global instance
google_drive_service = GoogleDriveService() 
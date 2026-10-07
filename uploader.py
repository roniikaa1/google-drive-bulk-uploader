import os
import pickle
import logging
import mimetypes
import time
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


# ============================================================
# Configuration
# ============================================================

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.pickle"

# Change this to your local directory
LOCAL_FOLDER_TO_UPLOAD = Path("./my_folder_to_upload")

# Existing Google Drive folder ID.
# Set to None to upload into Drive root.
DESTINATION_PARENT_ID: Optional[str] = None

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAY = 2

# Upload chunk size
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB

# Whether to skip files that already exist in the target folder
SKIP_EXISTING_FILES = True

# Whether to skip folders that already exist in the target folder
REUSE_EXISTING_FOLDERS = True


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# Authentication
# ============================================================

def get_drive_service():
    """
    Authenticate with Google Drive and return a Drive API service.

    Credentials are cached in token.pickle so that the browser
    authentication is normally required only once.
    """

    creds = None

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Missing '{CREDENTIALS_FILE}'. "
            "Download your OAuth client credentials from Google Cloud Console."
        )

    # Load cached credentials
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "rb") as token:
                creds = pickle.load(token)
        except Exception:
            logger.warning("Could not load cached credentials.")
            creds = None

    # Refresh or perform OAuth login
    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing Google OAuth token...")
            creds.refresh(Request())

        else:
            logger.info("Opening browser for Google authentication...")

            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE,
                SCOPES,
            )

            creds = flow.run_local_server(port=0)

        # Save credentials
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    logger.info("Google Drive authentication successful.")

    return build(
        "drive",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )


# ============================================================
# API Helpers
# ============================================================

def execute_with_retry(request, description="Google Drive request"):
    """
    Execute a Google API request with automatic retries.
    """

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            return request.execute()

        except HttpError as error:

            status = getattr(error.resp, "status", None)

            # Retry temporary/server/rate-limit errors
            if status in (429, 500, 502, 503, 504):

                if attempt == MAX_RETRIES:
                    raise

                delay = RETRY_DELAY * (2 ** (attempt - 1))

                logger.warning(
                    "%s failed with HTTP %s. "
                    "Retrying in %s seconds (%s/%s)...",
                    description,
                    status,
                    delay,
                    attempt,
                    MAX_RETRIES,
                )

                time.sleep(delay)

            else:
                raise


# ============================================================
# Drive Search Helpers
# ============================================================

def find_folder(service, folder_name, parent_id=None):
    """
    Find an existing folder by name inside a parent folder.
    Returns its ID or None.
    """

    escaped_name = folder_name.replace("'", "\\'")

    query = (
        f"name = '{escaped_name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )

    if parent_id:
        query += f" and '{parent_id}' in parents"
    else:
        query += " and 'root' in parents"

    response = execute_with_retry(
        service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=10,
        ),
        f"Searching for folder '{folder_name}'",
    )

    files = response.get("files", [])

    return files[0]["id"] if files else None


def find_file(service, file_name, parent_id=None):
    """
    Find an existing file by name inside a parent folder.
    Returns its ID or None.
    """

    escaped_name = file_name.replace("'", "\\'")

    query = (
        f"name = '{escaped_name}' "
        f"and trashed = false"
    )

    if parent_id:
        query += f" and '{parent_id}' in parents"
    else:
        query += " and 'root' in parents"

    response = execute_with_retry(
        service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name, size, modifiedTime)",
            pageSize=10,
        ),
        f"Searching for file '{file_name}'",
    )

    files = response.get("files", [])

    return files[0] if files else None


# ============================================================
# Folder Management
# ============================================================

def create_drive_folder(service, folder_name, parent_id=None):
    """
    Create a Drive folder.

    If REUSE_EXISTING_FOLDERS is enabled, an existing folder
    with the same name inside the parent is reused.
    """

    if REUSE_EXISTING_FOLDERS:

        existing_id = find_folder(
            service,
            folder_name,
            parent_id,
        )

        if existing_id:
            logger.info(
                "Using existing Drive folder: %s (%s)",
                folder_name,
                existing_id,
            )

            return existing_id

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }

    if parent_id:
        metadata["parents"] = [parent_id]

    folder = execute_with_retry(
        service.files().create(
            body=metadata,
            fields="id,name",
        ),
        f"Creating folder '{folder_name}'",
    )

    folder_id = folder["id"]

    logger.info(
        "Created Drive folder: %s (%s)",
        folder_name,
        folder_id,
    )

    return folder_id


# ============================================================
# File Upload
# ============================================================

def upload_file(service, file_path: Path, parent_id=None):
    """
    Upload a file to Google Drive using resumable upload.

    Existing files with the same name can optionally be skipped.
    """

    file_path = Path(file_path)

    if not file_path.is_file():
        logger.warning("Skipping non-file: %s", file_path)
        return None

    file_name = file_path.name

    # Check for duplicate
    if SKIP_EXISTING_FILES:

        existing = find_file(
            service,
            file_name,
            parent_id,
        )

        if existing:

            logger.info(
                "Skipping existing file: %s (ID: %s)",
                file_name,
                existing["id"],
            )

            return existing["id"]

    mime_type, _ = mimetypes.guess_type(str(file_path))

    if mime_type is None:
        mime_type = "application/octet-stream"

    metadata = {
        "name": file_name,
    }

    if parent_id:
        metadata["parents"] = [parent_id]

    logger.info(
        "Uploading: %s (%.2f MB)",
        file_name,
        file_path.stat().st_size / (1024 * 1024),
    )

    media = MediaFileUpload(
        str(file_path),
        mimetype=mime_type,
        chunksize=CHUNK_SIZE,
        resumable=True,
    )

    request = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,size",
    )

    # Resumable upload loop
    response = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            while response is None:

                status, response = request.next_chunk()

                if status:
                    progress = int(status.progress() * 100)

                    logger.info(
                        "%s: %d%%",
                        file_name,
                        progress,
                    )

            break

        except HttpError as error:

            status_code = getattr(error.resp, "status", None)

            if (
                status_code in (429, 500, 502, 503, 504)
                and attempt < MAX_RETRIES
            ):

                delay = RETRY_DELAY * (2 ** (attempt - 1))

                logger.warning(
                    "Upload error for %s (HTTP %s). "
                    "Retrying in %s seconds...",
                    file_name,
                    status_code,
                    delay,
                )

                time.sleep(delay)

            else:
                raise

    file_id = response["id"]

    logger.info(
        "Uploaded successfully: %s (ID: %s)",
        file_name,
        file_id,
    )

    return file_id


# ============================================================
# Directory Upload
# ============================================================

def upload_directory(service, local_dir: Path, parent_id=None):
    """
    Recursively mirror a local directory structure in Google Drive.
    """

    local_dir = Path(local_dir)

    if not local_dir.exists():
        raise FileNotFoundError(
            f"Directory does not exist: {local_dir}"
        )

    if not local_dir.is_dir():
        raise NotADirectoryError(
            f"Not a directory: {local_dir}"
        )

    # Create/reuse matching Drive folder
    drive_folder_id = create_drive_folder(
        service,
        local_dir.name,
        parent_id,
    )

    # Sort for deterministic processing
    items = sorted(
        local_dir.iterdir(),
        key=lambda p: p.name.lower(),
    )

    for item in items:

        try:

            if item.is_dir():

                upload_directory(
                    service,
                    item,
                    drive_folder_id,
                )

            elif item.is_file():

                upload_file(
                    service,
                    item,
                    drive_folder_id,
                )

        except Exception as error:

            logger.error(
                "Failed to process '%s': %s",
                item,
                error,
            )

            # Continue with the remaining files
            continue

    return drive_folder_id


# ============================================================
# Statistics
# ============================================================

def count_local_files(directory: Path):
    """Count files that will potentially be uploaded."""

    return sum(
        1
        for path in directory.rglob("*")
        if path.is_file()
    )


def calculate_directory_size(directory: Path):
    """Calculate total local directory size."""

    return sum(
        path.stat().st_size
        for path in directory.rglob("*")
        if path.is_file()
    )


# ============================================================
# Main
# ============================================================

def main():

    logger.info("=" * 60)
    logger.info("Google Drive Bulk Uploader")
    logger.info("=" * 60)

    local_folder = LOCAL_FOLDER_TO_UPLOAD.expanduser().resolve()

    if not local_folder.exists():
        raise FileNotFoundError(
            f"Local folder does not exist: {local_folder}"
        )

    if not local_folder.is_dir():
        raise NotADirectoryError(
            f"Local path is not a directory: {local_folder}"
        )

    # Show upload statistics
    total_files = count_local_files(local_folder)
    total_size = calculate_directory_size(local_folder)

    logger.info("Local folder: %s", local_folder)
    logger.info("Files found: %d", total_files)
    logger.info(
        "Total size: %.2f MB",
        total_size / (1024 * 1024),
    )

    # Authenticate
    drive_service = get_drive_service()

    logger.info("Starting upload...")

    start_time = time.time()

    upload_directory(
        drive_service,
        local_folder,
        DESTINATION_PARENT_ID,
    )

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Upload completed!")
    logger.info("Files scanned: %d", total_files)
    logger.info(
        "Total size: %.2f MB",
        total_size / (1024 * 1024),
    )
    logger.info(
        "Elapsed time: %.2f seconds",
        elapsed,
    )

    if elapsed > 0:
        speed = total_size / elapsed / (1024 * 1024)

        logger.info(
            "Average upload throughput: %.2f MB/s",
            speed,
        )

    logger.info("=" * 60)


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        logger.warning("Upload cancelled by user.")

    except Exception as error:
        logger.exception(
            "Upload failed: %s",
            error,
        )
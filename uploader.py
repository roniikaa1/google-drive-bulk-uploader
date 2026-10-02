import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Define the required OAuth scope for creating and managing files/folders in Google Drive
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service():
    """
    Authenticates the user using OAuth 2.0 and returns the Google Drive API service object.
    Caches credentials in 'token.pickle' to avoid repetitive browser sign-ins.
    """
    creds = None
    
    # Check if a previously saved token exists
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # If credentials are not valid or do not exist, refresh or prompt user to log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Requires credentials.json from the Google Cloud Console
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the current credentials for future runs
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    # Build and return the Google Drive API client (v3)
    return build('drive', 'v3', execute_queries=True, credentials=creds)

def create_drive_folder(service, folder_name, parent_id=None):
    """
    Creates a new folder on Google Drive and returns its unique folder ID.
    Optionally places the folder inside a specified parent directory.
    """
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    
    # If a parent ID is provided, nest this folder under it
    if parent_id:
        folder_metadata['parents'] = [parent_id]
    
    # Send request to create the folder
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    return folder.get('id')

def upload_file(service, file_path, parent_id=None):
    """
    Uploads a single local file to Google Drive using chunked resumable upload.
    Places the file inside the specified Google Drive parent folder ID if given.
    """
    file_name = os.path.basename(file_path)
    file_metadata = {'name': file_name}
    
    if parent_id:
        file_metadata['parents'] = [parent_id]
        
    # Enable resumable uploads to securely handle larger files
    media = MediaFileUpload(file_path, resumable=True)
    
    # Execute file creation and upload
    file = service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields='id'
    ).execute()
    
    print(f"Uploaded file: {file_name} (ID: {file.get('id')})")

def upload_directory(service, local_dir, parent_id=None):
    """
    Recursively scans a local directory, mirrors its folder structure on Google Drive,
    and uploads all nested files and subdirectories.
    """
    if not os.path.isdir(local_dir):
        print(f"Error: {local_dir} is not a valid directory.")
        return

    # Mirror the current local directory by creating a matching folder on Google Drive
    dir_name = os.path.basename(os.path.normpath(local_dir))
    drive_folder_id = create_drive_folder(service, dir_name, parent_id)
    print(f"Created Drive Folder: {dir_name} (ID: {drive_folder_id})")

    # Iterate through all items in the local folder
    for item in os.listdir(local_dir):
        item_path = os.path.join(local_dir, item)
        
        if os.path.isdir(item_path):
            # Recursively call function for nested subdirectories
            upload_directory(service, item_path, drive_folder_id)
        elif os.path.isfile(item_path):
            # Upload individual files directly into the current Drive folder
            upload_file(service, item_path, drive_folder_id)

if __name__ == '__main__':
    # Initialize the authenticated Google Drive API client
    drive_service = get_drive_service()
    
    # Configure the path to the local folder you want to bulk upload
    LOCAL_FOLDER_TO_UPLOAD = './my_folder_to_upload'
    
    # Optional: Target an existing Google Drive Folder ID as the root destination.
    # Keep as None to upload directly to your main Google Drive root.
    DESTINATION_PARENT_ID = None 

    print(f"Starting bulk upload of '{LOCAL_FOLDER_TO_UPLOAD}'...")
    upload_directory(drive_service, LOCAL_FOLDER_TO_UPLOAD, DESTINATION_PARENT_ID)
    print("Bulk upload completed successfully!")
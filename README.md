# Google Drive Bulk Uploader

A lightweight, robust Python utility that recursively scans a local directory and bulk uploads its entire contents—including nested subfolders—to Google Drive while preserving the exact folder structure.

## Features

* **Recursive Folder Mirroring:** Automatically replicates your local directory structure inside Google Drive.
* **Resumable Uploads:** Utilizes chunked resumable media uploads to securely transfer large files without dropped connections.
* **Token Caching:** Saves OAuth credentials locally (`token.pickle`) for seamless subsequent runs without repetitive browser logins.

---

## Prerequisites

1. Python 3.8+ installed on your system.
2. A Google Cloud Project with the **Google Drive API** enabled.
3. An OAuth Client ID (`Desktop application`) credentials file downloaded and saved as `credentials.json` in the project root.

---

## Installation

Clone the repository and install the required Google API client libraries:

```bash
git clone [https://github.com/roniikaa1/google-drive-bulk-uploader.git](https://github.com/roniikaa1/google-drive-bulk-uploader.git)
cd google-drive-bulk-uploader
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

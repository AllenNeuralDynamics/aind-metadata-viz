"""pinpoint — per-ORCID encrypted storage for arbitrary files.

Public API
----------
    pinpoint_router      FastAPI router for /pinpoint-get and /pinpoint-post.
    store_file           Encrypt and store a byte payload for an ORCID iD.
    get_file             Decrypt and return a stored payload and its content type.
    store_blob           Encrypt and store a JSON blob for an ORCID iD.
    get_blob             Decrypt and return a stored JSON blob.
    list_blobs           List an account's blob metadata.
    DecryptionError      Raised when supplied credentials cannot decrypt a blob.
"""

from .handlers import pinpoint_router
from .store import (
    DecryptionError,
    get_blob,
    get_file,
    list_blobs,
    store_blob,
    store_file,
)

__all__ = [
    "pinpoint_router",
    "store_file",
    "get_file",
    "store_blob",
    "get_blob",
    "list_blobs",
    "DecryptionError",
]

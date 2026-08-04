"""pinpoint — per-ORCID encrypted storage for arbitrary JSON blobs.

Public API
----------
    pinpoint_router      FastAPI router for /pinpoint-get and /pinpoint-post.
    store_blob           Encrypt and store a JSON blob for an ORCID iD.
    get_blob             Decrypt and return a stored blob.
    list_blobs           List an account's blob metadata.
    DecryptionError      Raised when supplied credentials cannot decrypt a blob.
"""

from .handlers import pinpoint_router
from .store import DecryptionError, get_blob, list_blobs, store_blob

__all__ = [
    "pinpoint_router",
    "store_blob",
    "get_blob",
    "list_blobs",
    "DecryptionError",
]

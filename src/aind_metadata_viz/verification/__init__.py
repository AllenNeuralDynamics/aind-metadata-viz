"""Internal verification graph implementation.

The verification router is retained for isolated backend tests and future
reuse, but it is not mounted by the metadata portal application.
"""

from .handlers import verification_router

__all__ = ["verification_router"]

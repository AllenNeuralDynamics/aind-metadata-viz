"""Verification graph: statements linked to the evidence and code behind them.

Public API
----------
    verification_router   FastAPI router for the /verification/* endpoints.
"""

from .handlers import verification_router

__all__ = ["verification_router"]

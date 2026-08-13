"""Declarative model registry for the Ticketbox database schema.

This module owns only SQLAlchemy model registration and metadata. Importing it
must not resolve runtime settings, construct an engine, or open a database
connection.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base"]


class Base(DeclarativeBase):
    """Shared declarative base for every application model."""

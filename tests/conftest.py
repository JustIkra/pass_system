"""Shared pytest fixtures and configuration.

This file is automatically discovered by pytest and provides
fixtures available to all test modules.
"""

import sys
import os
from pathlib import Path

import pytest

# Add backend to Python path so imports work
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Set test environment to avoid loading real database config
os.environ["DATABASE_URL"] = "sqlite:///:memory:"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers",
        "unit: marks tests as unit tests"
    )

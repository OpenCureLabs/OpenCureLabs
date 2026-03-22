"""Shared test fixtures for OpenCure Labs test suite."""

import os
import sys

import pytest

# Allow synthetic data fallback in tests (blocked in production)
os.environ.setdefault("LABCLAW_ALLOW_SYNTHETIC", "true")

# Ensure agentiq_labclaw package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

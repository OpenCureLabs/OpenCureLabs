"""Shared test fixtures for OpenCure Labs test suite."""

import os
import sys

import pytest

# Ensure agentiq_labclaw package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

"""Vercel serverless entry point.

Imports and exposes the FastAPI app so Vercel can discover it.
Vercel looks for an `app` variable in files inside the api/ directory.
"""

import sys
import os

# Add the project root to the Python path so all imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402, F401

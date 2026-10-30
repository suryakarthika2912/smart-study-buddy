import os
import sys

# Ensure parent directory is in sys.path for module resolution on Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


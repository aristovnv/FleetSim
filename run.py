#!/usr/bin/env python3
"""Entry point — run from the project root: python run.py [--port 8765] [--data ./data]"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portal.server import main
if __name__ == "__main__":
    main()

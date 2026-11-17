import os
import sys
import tempfile
from pathlib import Path

os.environ.update(DB=str(Path(tempfile.mkdtemp()) / "test.db"), NO_SERIAL="1", NO_ENGINE="1", ICAL_URL="")
sys.path.insert(0, str(Path(__file__).parent.parent))

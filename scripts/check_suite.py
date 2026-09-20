"""Run offline tests without writing task history into the real workspace."""
import contextlib
import io
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server.tasks as tasks

logging.disable(logging.CRITICAL)
with tempfile.TemporaryDirectory(prefix="novel-tests-") as directory:
    suite = unittest.defaultTestLoader.discover("tests", pattern=sys.argv[1] if len(sys.argv) > 1 else "test*.py")
    report = io.StringIO()
    with patch.object(tasks, "TASKS_DIR", Path(directory) / "tasks"), contextlib.redirect_stdout(io.StringIO()):
        result = unittest.TextTestRunner(stream=report, verbosity=1).run(suite)
    output = report.getvalue()
    Path("runtime").mkdir(exist_ok=True)
    Path("runtime/test-report.txt").write_text(output, encoding="utf-8")
    print(output)
    raise SystemExit(not result.wasSuccessful())

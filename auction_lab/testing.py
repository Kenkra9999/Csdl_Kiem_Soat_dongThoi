from __future__ import annotations

import io
import json
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from .db import ROOT


def run_tests(output="output/test-results.json") -> dict:
    class RecordingResult(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.records = []
        def startTest(self, test):
            self.started = time.perf_counter()
            super().startTest(test)
        def addSuccess(self, test):
            self.records.append({"test": test.id(), "status": "PASSED", "duration_ms": round((time.perf_counter()-self.started)*1000, 3)})
            super().addSuccess(test)
        def addFailure(self, test, err):
            self.records.append({"test": test.id(), "status": "FAILED", "error": self._exc_info_to_string(err, test)})
            super().addFailure(test, err)
        def addError(self, test, err):
            self.records.append({"test": test.id(), "status": "ERROR", "error": self._exc_info_to_string(err, test)})
            super().addError(test, err)
        def addSkip(self, test, reason):
            self.records.append({"test": test.id(), "status": "SKIPPED", "reason": reason})
            super().addSkip(test, reason)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    stream = io.StringIO()
    began = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult).run(suite)
    report = {"measured_at_utc": datetime.now(timezone.utc).isoformat(),
              "passed": result.wasSuccessful(), "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped),
              "elapsed_ms": round((time.perf_counter()-began)*1000, 3),
              "tests": result.records, "runner_output": stream.getvalue()}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(stream.getvalue())
    return report

import tempfile
import threading
import time
import unittest
from pathlib import Path

from devicebridge.devices.scanners.base import ScanRequest, ScanResult
from devicebridge.jobs.models import JobState
from devicebridge.jobs.repository import SQLiteJobRepository
from devicebridge.jobs.scan_manager import ScanJobManager
from devicebridge.storage.files import TemporaryFileStore


class BlockingDriver:
    identifier = "scanner-a"
    display_name = "Scanner A"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def scan(self, request):
        self.started.set()
        self.release.wait(timeout=2)
        return ScanResult(b"image", "image/png", "png")


class ScanJobManagerTest(unittest.TestCase):
    request = ScanRequest("flatbed", "color", 300, "png", False)

    def test_serializes_jobs_and_cancels_a_queued_job(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = SQLiteJobRepository(root / "jobs.sqlite3")
            manager = ScanJobManager(repository, TemporaryFileStore(root / "files"), False)
            driver = BlockingDriver()
            first = repository.create_or_get("scan", "scanner-a", "first")
            second = repository.create_or_get("scan", "scanner-a", "second")

            manager.enqueue(first, driver, self.request)
            self.assertTrue(driver.started.wait(timeout=1))
            manager.enqueue(second, driver, self.request)
            time.sleep(0.05)
            self.assertEqual(JobState.PROCESSING, repository.get(first.identifier).state)
            self.assertEqual(JobState.QUEUED, repository.get(second.identifier).state)

            cancelled = manager.cancel(second.identifier)
            self.assertEqual(JobState.CANCELLED, cancelled.state)
            driver.release.set()
            self._wait_for_state(repository, first.identifier, JobState.COMPLETED)
            self.assertEqual(JobState.CANCELLED, repository.get(second.identifier).state)

    def test_marks_processing_work_uncertain_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = SQLiteJobRepository(Path(temporary_directory) / "jobs.sqlite3")
            job = repository.create_or_get("scan", "scanner-a", "processing")
            repository.update(job.identifier, JobState.PROCESSING)

            repository.recover_interrupted_scans()

            recovered = repository.get(job.identifier)
            self.assertEqual(JobState.UNCERTAIN, recovered.state)
            self.assertEqual("AGENT_RESTARTED", recovered.error_code)

    def test_cancelling_an_active_job_discards_its_result(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = SQLiteJobRepository(root / "jobs.sqlite3")
            manager = ScanJobManager(repository, TemporaryFileStore(root / "files"), False)
            driver = BlockingDriver()
            job = repository.create_or_get("scan", "scanner-a", "active")

            manager.enqueue(job, driver, self.request)
            self.assertTrue(driver.started.wait(timeout=1))
            self.assertEqual(JobState.CANCEL_REQUESTED, manager.cancel(job.identifier).state)
            driver.release.set()
            self._wait_for_state(repository, job.identifier, JobState.CANCELLED)
            self.assertFalse(repository.get(job.identifier).file_path)

    def _wait_for_state(self, repository, job_id, expected):
        for _ in range(40):
            if repository.get(job_id).state == expected:
                return
            time.sleep(0.05)
        self.fail(f"El trabajo {job_id} no llegó a {expected}.")

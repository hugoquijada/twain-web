import tempfile
import unittest
from pathlib import Path

from devicebridge.jobs.models import JobState
from devicebridge.jobs.repository import JobInProgressError, SQLiteJobRepository


class SQLiteJobRepositoryTest(unittest.TestCase):
    def test_same_idempotency_key_returns_original_job(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = SQLiteJobRepository(Path(temporary_directory) / "jobs.sqlite3")
            first = repository.create_or_get("scan", "scanner-a", "request-1")
            second = repository.create_or_get("scan", "scanner-a", "request-1")

            self.assertEqual(first.identifier, second.identifier)
            self.assertEqual(JobState.QUEUED, second.state)

    def test_a_key_cannot_be_reused_for_another_device(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = SQLiteJobRepository(Path(temporary_directory) / "jobs.sqlite3")
            repository.create_or_get("scan", "scanner-a", "request-1")

            with self.assertRaises(ValueError):
                repository.create_or_get("scan", "scanner-b", "request-1")

    def test_updates_are_persisted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "jobs.sqlite3"
            first_repository = SQLiteJobRepository(database)
            job = first_repository.create_or_get("scan", "scanner-a", "request-1")
            first_repository.update(job.identifier, JobState.COMPLETED, file_path="C:/tmp/file.png",
                                    file_media_type="image/png")

            recovered = SQLiteJobRepository(database).get(job.identifier)
            self.assertIsNotNone(recovered)
            self.assertEqual(JobState.COMPLETED, recovered.state)
            self.assertEqual("C:/tmp/file.png", recovered.file_path)

    def test_exclusive_job_rejects_second_request_for_same_scanner(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = SQLiteJobRepository(Path(temporary_directory) / "jobs.sqlite3")
            first = repository.create_or_get_exclusive("scan", "scanner-a", "first")

            with self.assertRaises(JobInProgressError) as context:
                repository.create_or_get_exclusive("scan", "scanner-a", "second")

            self.assertEqual(first.identifier, context.exception.job.identifier)

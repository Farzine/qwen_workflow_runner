"""Real model upload routes must never replace existing or concurrently published bytes."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from qwen_runner.config import Config
from ui.runner_bridge import RunJob, RunnerBridge
from ui.server import app


class TestModelUploads(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.models = Path(self.directory.name) / 'models'
        self.models.mkdir()
        self.bridge = RunnerBridge(output_dir=str(Path(self.directory.name) / 'outputs'))
        self.models_patch = patch('ui.server.get_models_dir', return_value=self.models)
        self.bridge_patch = patch('ui.server.get_runner_bridge', return_value=self.bridge)
        self.models_patch.start()
        self.bridge_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.bridge.shutdown()
        self.bridge_patch.stop()
        self.models_patch.stop()
        self.directory.cleanup()

    def upload(self, name, content=b'new weights', index=0, total=1, uid='upload'):
        return self.client.post('/api/models/upload', files={'file': (name, content)}, data={
            'filename': name, 'chunk_index': index, 'total_chunks': total, 'upload_id': uid.replace('.', '_'),
        })

    def assert_clean(self):
        self.assertEqual(list(self.models.glob('.model-upload-*.tmp')), [])
        self.assertEqual(list((self.models / '.uploads').glob('*.part')), [])

    def test_existing_files_and_active_model_are_preserved(self):
        target = self.models / 'active.gguf'
        target.write_bytes(b'original weights')
        config = Config()
        config.model.source = str(target)
        job = RunJob('active-upload-guard', config, demo_mode=False)
        self.bridge.jobs[job.job_id] = job
        for status in ('queued', 'running', 'completed'):
            job.status = status
            for total in (1, 2):
                response = self.upload(target.name, total=total)
                self.assertEqual(response.status_code, 409)
                self.assertIn('Rename your upload', response.json()['detail'])
                self.assertEqual(target.read_bytes(), b'original weights')
                self.assertEqual(job.status, status)
                self.assert_clean()

    def test_new_single_and_chunked_uploads_appear_in_catalog(self):
        for total in (1, 2):
            name = f'new-{total}.gguf'
            for index in range(total):
                response = self.upload(name, b'chunk', index=index, total=total, uid=name)
                self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['status'], 'completed')
            self.assertEqual(data['path'], str(self.models / name))
            self.assertEqual(data['size'], 5 * total)
            self.assertEqual((self.models / name).read_bytes(), b'chunk' * total)
            catalog = self.client.get('/api/models').json()['models']
            self.assertTrue(any(item['path'] == data['path'] for item in catalog))
            self.assert_clean()

    def test_long_filenames_use_short_owned_temporary_paths(self):
        for total in (1, 2):
            name = 'x' * 238 + f'{total}.gguf'
            for index in range(total):
                response = self.upload(name, b'chunk', index=index, total=total, uid=f'long_{total}')
                self.assertEqual(response.status_code, 200)
            self.assertEqual((self.models / name).read_bytes(), b'chunk' * total)
            self.assert_clean()

    def test_late_collisions_and_publication_errors_clean_temporary_files(self):
        real_link = os.link
        for total in (1, 2):
            for failure in ('collision', 'permission'):
                name = f'{failure}-{total}.gguf'
                target = self.models / name
                if total == 2:
                    self.assertEqual(self.upload(name, total=2, uid=name).status_code, 200)

                def failing_link(source, destination):
                    if failure == 'collision':
                        target.write_bytes(b'racing winner')
                        return real_link(source, destination)
                    raise PermissionError('publication denied')

                with patch('ui.server.os.link', side_effect=failing_link):
                    response = self.upload(name, index=total - 1, total=total, uid=name)
                self.assertEqual(response.status_code, 409 if failure == 'collision' else 500)
                if failure == 'collision':
                    self.assertEqual(target.read_bytes(), b'racing winner')
                else:
                    self.assertFalse(target.exists())
                    self.assertIn('publication denied', response.json()['detail'])
                self.assert_clean()

    def test_concurrent_uploads_publish_one_complete_winner(self):
        real_link = os.link
        for total in (1, 2):
            name = f'concurrent-{total}.gguf'
            contents = (b'AAAA', b'BBBB')
            if total == 2:
                for uid, content in enumerate(contents):
                    self.assertEqual(self.upload(name, content, total=2, uid=str(uid)).status_code, 200)
            barrier = threading.Barrier(2, timeout=5)

            def racing_link(source, destination):
                barrier.wait()
                return real_link(source, destination)

            with patch('ui.server.os.link', side_effect=racing_link), ThreadPoolExecutor(2) as workers:
                futures = [workers.submit(self.upload, name, content, total - 1, total, str(uid))
                           for uid, content in enumerate(contents)]
                responses = [future.result(timeout=10) for future in futures]
            self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
            winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
            self.assertEqual((self.models / name).read_bytes(), contents[winner] * total)
            self.assert_clean()

    def test_chunk_conflicts_clean_only_their_parts_and_reject_dangling_symlinks(self):
        self.assertEqual(self.upload('late.gguf', total=2, uid='late').status_code, 200)
        other = self.models / '.uploads' / 'other_chunk_0000.part'
        other.write_bytes(b'unrelated upload')
        (self.models / 'late.gguf').write_bytes(b'completed elsewhere')
        response = self.upload('late.gguf', index=1, total=2, uid='late')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(list((self.models / '.uploads').glob('late*.part')), [])
        self.assertEqual(other.read_bytes(), b'unrelated upload')
        self.assertEqual((self.models / 'late.gguf').read_bytes(), b'completed elsewhere')
        link = self.models / 'dangling.gguf'
        link.symlink_to(self.models / 'missing.gguf')
        for total in (1, 2):
            self.assertEqual(self.upload(link.name, total=total).status_code, 409)
            self.assertTrue(link.is_symlink())
            self.assertFalse((self.models / 'missing.gguf').exists())

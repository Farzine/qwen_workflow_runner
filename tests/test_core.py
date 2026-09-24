import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image
from qwen_runner.config import Config, GenerationConfig
from qwen_runner.images import reference_size, load_references
from qwen_runner.models import ModelStore, parse_model_ref, select_gguf
from qwen_runner.sampling import sigma_schedule


class ConfigurationTests(unittest.TestCase):
    def test_default_graph_values(self):
        c = Config()
        c.validate(check_images=False)
        graph = json.loads((Path(__file__).parents[1] / 'workflow/original.json').read_text())
        n = next(n for n in graph['nodes'] if n['id'] == 459)['widgets_values_named']
        for key in ('prompt', 'negative_prompt', 'steps', 'cfg', 'seed', 'resolution', 'width', 'height'):
            self.assertEqual(getattr(c.generation, key), n[key])
        self.assertEqual(c.generation.custom_size, n['switch'])

    def test_invalid_sampler_not_ignored(self):
        c = Config(); c.generation.sampler = 'invented'
        with self.assertRaises(ValueError): c.validate(False)

    def test_invalid_strength(self):
        for value in (-1, 0, 2):
            c = Config(); c.generation.strength = value
            with self.assertRaises(ValueError): c.validate(False)

    def test_custom_dimensions_require_grid(self):
        c = Config(); c.generation.custom_size = True; c.generation.width = 1000
        with self.assertRaises(ValueError): c.validate(False)

    def test_legacy_and_explicit_image_contracts(self):
        legacy = Config(generation=GenerationConfig(images=['input.png', 'ref.png']))
        self.assertEqual(legacy.resolved_image_inputs(), (['input.png'], ['ref.png']))

        explicit = Config(generation=GenerationConfig(
            images=['ignored-legacy.png'],
            input_images=['input-b.png', 'input-a.png'],
            reference_images=['ref-2.png', 'ref-1.png'],
        ))
        explicit.validate(check_images=False)
        self.assertEqual(
            explicit.resolved_image_inputs(),
            (['input-b.png', 'input-a.png'], ['ref-2.png', 'ref-1.png']),
        )
        self.assertEqual(explicit.as_dict()['generation']['images'], [])

    def test_explicit_image_contract_boundaries(self):
        invalid = (
            GenerationConfig(input_images=[]),
            GenerationConfig(input_images=None, reference_images=['ref.png']),
            GenerationConfig(input_images=['input.png'], reference_images=['ref.png'] * 10),
            GenerationConfig(input_images=['']),
            GenerationConfig(input_images='input.png'),
        )
        for generation in invalid:
            with self.subTest(generation=generation):
                with self.assertRaises(ValueError):
                    Config(generation=generation).validate(check_images=False)


class ImageTests(unittest.TestCase):
    def test_original_resolution_and_rounding(self):
        self.assertEqual(reference_size(1000, 750, 0), (992, 736))
        self.assertEqual(reference_size(10, 10, 0), (32, 32))
        self.assertEqual(reference_size(800, 800, 1024), (1024, 1024))

    def test_first_reference_controls_canvas_and_rgb(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f'{i}.png' for i in range(2)]
            Image.new('RGBA', (128, 96), (50, 30, 20, 0)).save(paths[0])
            Image.new('RGB', (64, 160)).save(paths[1])
            c = Config().generation; c.images = [str(p) for p in paths]
            images, canvas, meta = load_references(c)
            self.assertEqual(canvas, (128, 96))
            self.assertEqual([i.size for i in images], [(128, 96), (64, 160)])
            self.assertEqual(images[0].mode, 'RGB')
            self.assertEqual(len(meta[0]['sha256']), 64)
            c.custom_size = True; c.width = c.height = 256
            self.assertEqual(load_references(c)[1], (256, 256))


class ReferenceTests(unittest.TestCase):
    def test_all_user_links(self):
        for suffix in ('', '/tree/main', '/tree/main/'):
            ref = parse_model_ref('https://huggingface.co/Qwen/Qwen-Image-2.1' + suffix)
            self.assertEqual(ref.repo_id, 'Qwen/Qwen-Image-2.1')
            self.assertEqual(ref.revision, 'main')
        self.assertEqual(parse_model_ref('https://huggingface.co/abenzerps/Qwen-Image-2.1-GGUF').repo_id,
                         'abenzerps/Qwen-Image-2.1-GGUF')

    def test_file_and_revision(self):
        ref = parse_model_ref('https://huggingface.co/a/b/blob/v1/weights/model.gguf?download=true')
        self.assertEqual((ref.revision, ref.filename), ('v1', 'weights/model.gguf'))

    def test_bad_url_and_traversal(self):
        for source in ('https://example.com/a/b', 'https://huggingface.co/a/b/resolve/main/../bad', '/missing/file.gguf'):
            with self.assertRaises(ValueError): parse_model_ref(source)

    def test_multiple_variants_never_silently_selected(self):
        with self.assertRaises(ValueError): select_gguf(['a-Q4_K_M.gguf', 'b-Q4_K_M.gguf'], 'Q4_K_M')
        self.assertEqual(select_gguf(['a-Q4_K_M.gguf', 'b-Q8_0.gguf'], 'Q4_K_M'), 'a-Q4_K_M.gguf')

    def test_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'model.gguf'; p.write_bytes(b'data')
            self.assertEqual(parse_model_ref(str(p)).local, str(p.resolve()))


class CacheTests(unittest.TestCase):
    def setup_store(self, directory, files):
        api = Mock()
        api.model_info.return_value = SimpleNamespace(sha='commit123', siblings=[SimpleNamespace(rfilename=f) for f in files])
        def download(**kwargs):
            p = Path(directory) / 'hub' / 'snapshots' / kwargs['revision'] / kwargs['filename']
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"_class_name":"QwenImage21Pipeline"}' if kwargs['filename']=='model_index.json' else 'weights')
            return str(p)
        downloader = Mock(side_effect=download)
        return ModelStore(directory, api=api, downloader=downloader), api, downloader

    def test_second_run_never_contacts_hub(self):
        with tempfile.TemporaryDirectory() as directory:
            store, api, download = self.setup_store(directory, ['model_index.json', 'transformer/model.safetensors'])
            ref = parse_model_ref('test/model')
            first, meta = store.fetch(ref)
            self.assertFalse(meta['cache_hit'])
            api.reset_mock(); download.reset_mock()
            store.offline = True
            second, meta = store.fetch(ref)
            self.assertEqual(first, second); self.assertTrue(meta['cache_hit'])
            api.model_info.assert_not_called(); download.assert_not_called()

    def test_missing_cached_shard_fails_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _, _ = self.setup_store(directory, ['model_index.json', 'transformer/model.safetensors'])
            ref = parse_model_ref('test/model'); p, _ = store.fetch(ref)
            (p / 'transformer/model.safetensors').unlink()
            store.offline = True
            with self.assertRaises(FileNotFoundError): store.fetch(ref)

    def test_only_selected_gguf_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _, download = self.setup_store(directory, ['x-Q4_K_M.gguf', 'x-Q8_0.gguf', 'text_encoders/foo.safetensors'])
            p, meta = store.fetch(parse_model_ref('test/model'))
            self.assertEqual(p.name, 'x-Q4_K_M.gguf')
            self.assertEqual(download.call_count, 1)
            self.assertEqual(meta['format'], 'gguf')

    def test_companions_exclude_full_transformer(self):
        with tempfile.TemporaryDirectory() as directory:
            files = ['model_index.json','transformer/config.json','transformer/model.safetensors','text_encoder/model.safetensors']
            store, _, download = self.setup_store(directory, files)
            store.fetch(parse_model_ref('test/model'), 'companions')
            self.assertNotIn('transformer/model.safetensors', [x.kwargs['filename'] for x in download.call_args_list])


class SamplingTests(unittest.TestCase):
    def test_full_and_reduced_denoise(self):
        full = sigma_schedule(25)
        self.assertEqual(len(full), 25); self.assertEqual(full[0], 1)
        self.assertTrue(all(a > b > 0 for a, b in zip(full, full[1:])))
        reduced = sigma_schedule(25, .5)
        self.assertEqual(reduced, sigma_schedule(50)[-25:])
        self.assertLess(reduced[0], 1)

    def test_simple_training_grid(self):
        result = sigma_schedule(3, shift=0)
        for a, b in zip(result, [1, .6667, .3334]): self.assertAlmostEqual(a, b)


if __name__ == '__main__': unittest.main()

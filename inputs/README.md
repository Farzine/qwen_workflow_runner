Place your ordered input images here and edit `generation.images` in `run.py`.

The supplied workflow JSON contains filenames, not image bytes. To fetch the
two public template assets named in that JSON, run:

```bash
python scripts/download_examples.py
```

This downloads only sample input images. It does not download model weights.

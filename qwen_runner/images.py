import hashlib
import math
from pathlib import Path
from PIL import Image, ImageOps


def reference_size(width, height, resolution):
    if resolution:
        ratio = width / height
        width = math.sqrt(resolution * resolution * ratio)
        height = math.sqrt(resolution * resolution / ratio)
    return max(32, round(width / 32) * 32), max(32, round(height / 32) * 32)


def load_references(config):
    images, metadata = [], []
    for filename in config.images:
        path = Path(filename)
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert(config.reference_mode.upper())
        size = reference_size(*image.size, config.resolution)
        metadata.append({"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "original_size": list(image.size), "reference_size": list(size), "mode": image.mode})
        if image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        images.append(image)
    canvas = (config.width, config.height) if config.custom_size else images[0].size
    return images, canvas, metadata


def save_comparison(source, output, destination):
    height = min(1024, max(source.height, output.height))
    frames = [x.convert("RGB").resize((round(x.width * height / x.height), height), Image.Resampling.LANCZOS)
              for x in (source, output)]
    canvas = Image.new("RGB", (sum(x.width for x in frames), height), "white")
    canvas.paste(frames[0], (0, 0)); canvas.paste(frames[1], (frames[0].width, 0))
    canvas.save(destination)

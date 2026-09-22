"""Download the two public reference assets named in the supplied workflow."""
from pathlib import Path
from urllib.request import urlopen
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://raw.githubusercontent.com/Comfy-Org/workflow_templates/refs/heads/main/input/'
NAMES = ('portrait_model_denim.png', 'clothing_light_blue_denim_shirt.png')


def main():
    destination = ROOT / 'inputs'
    destination.mkdir(exist_ok=True)
    for name in NAMES:
        path = destination / name
        if path.exists():
            print(f'Reusing {path}')
            continue
        temp = path.with_suffix('.download')
        try:
            with urlopen(BASE + name, timeout=60) as response, temp.open('wb') as out:
                while chunk := response.read(1024 * 1024): out.write(chunk)
            with Image.open(temp) as image: image.verify()
            temp.replace(path)
            print(f'Downloaded {path}')
        finally:
            temp.unlink(missing_ok=True)


if __name__ == '__main__': main()

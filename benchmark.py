"""Compare models in isolated processes so their allocations do not overlap."""
import subprocess
import sys

MODELS = [
    'https://huggingface.co/Qwen/Qwen-Image-2.1',
    'https://huggingface.co/abenzerps/Qwen-Image-2.1-GGUF',
]

if __name__ == '__main__':
    failed = []
    for model in MODELS:
        print(f'Running {model}', flush=True)
        result = subprocess.run([sys.executable, 'run.py', '--model', model], check=False)
        if result.returncode: failed.append(model)
    if failed:
        raise SystemExit('Failed models (see individual logs): ' + ', '.join(failed))

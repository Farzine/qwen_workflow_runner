"""Print a CSV table from successful, non-warmup inference logs."""
import argparse
import csv
import json
from pathlib import Path
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', nargs='?', default='outputs')
    args = p.parse_args()
    writer = csv.writer(sys.stdout)
    writer.writerow(['run_id', 'model', 'filename', 'seed', 'width', 'height', 'steps', 'seconds', 'gpu_allocated_GiB', 'gpu_reserved_GiB', 'rss_GiB'])
    for path in sorted(Path(args.directory).glob('*.json')):
        record = json.loads(path.read_text())
        if record.get('status') != 'success' or record.get('is_warmup'): continue
        model, params, effective = record['model'], record['parameters']['generation'], record['effective_parameters']
        memory = record.get('peak_memory_usage') or {}
        def gib(key):
            value = memory.get(key)
            return '' if value is None else round(value / 2**30, 4)
        writer.writerow([record['run_id'], model.get('repo_id', model.get('source')), model.get('filename'), params['seed'],
                         effective['width'], effective['height'], params['steps'], record['inference_time_seconds'],
                         gib('gpu_peak_allocated_bytes'), gib('gpu_peak_reserved_bytes'), gib('process_rss_peak_bytes')])


if __name__ == '__main__': main()

#!/usr/bin/env python3
"""Prepare a supplied V1 consultation export using a reviewed identity crosswalk."""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from v1_consultation_mapping import MappingError, prepare

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('input', type=Path, help='approved V1 consultation-table CSV or JSON export')
parser.add_argument('crosswalk', type=Path, help='staff-reviewed consultation/patient mapping JSON')
parser.add_argument('output', type=Path, help='new private V2 migration preview JSON file')
args = parser.parse_args()
if len({p.resolve() for p in (args.input, args.crosswalk, args.output)}) != 3:
    parser.error('Input, crosswalk and output must be different files')
try:
    if args.input.suffix.lower() == '.csv':
        with args.input.open(newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
    elif args.input.suffix.lower() == '.json':
        rows = json.loads(args.input.read_text(encoding='utf-8'))
        if isinstance(rows, dict):
            rows = rows.get('consultations')
    else:
        parser.error('Input must be CSV or JSON')
    crosswalk = json.loads(args.crosswalk.read_text(encoding='utf-8'))
    payload = prepare(rows, crosswalk)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
except (MappingError, OSError, UnicodeError, json.JSONDecodeError) as error:
    parser.exit(2, str(error) + '\n')
print(json.dumps({'output': str(args.output), 'review': payload['review']}))

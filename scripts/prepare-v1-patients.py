#!/usr/bin/env python3
"""Convert a supplied, approved read-only V1 patient export to a V2 preview file."""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from v1_patient_mapping import MappingError, prepare

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('input', type=Path, help='V1 patient-table CSV or JSON export')
parser.add_argument('output', type=Path, help='new private V2 migration preview JSON file')
parser.add_argument('--source-clinic-id', required=True, help='V1 clinic UUID in the export')
args = parser.parse_args()
if args.input.resolve() == args.output.resolve():
    parser.error('Input and output must be different files')
try:
    if args.input.suffix.lower() == '.csv':
        with args.input.open(newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
    elif args.input.suffix.lower() == '.json':
        rows = json.loads(args.input.read_text(encoding='utf-8'))
        if isinstance(rows, dict):
            rows = rows.get('patients')
    else:
        parser.error('Input must be CSV or JSON')
    payload = prepare(rows, source_clinic_id=args.source_clinic_id)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
except (MappingError, OSError, UnicodeError, json.JSONDecodeError) as error:
    parser.exit(2, str(error) + '\n')
print(json.dumps({'output': str(args.output), 'review': payload['review']}))

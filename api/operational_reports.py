"""Clinic-scoped operational counts from the complete persisted record set.

The browser bootstrap is deliberately not a reporting source: it can be filtered,
stale or paged. Calendar dates use the clinic zone; recorded timestamps use an
inclusive UTC lower bound and exclusive upper bound for those local dates.
"""
import csv
import io
import json
import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query, Request, Response

from actions import fail
from db import connection, get, json_text, now
from read_access import ALL, require

router = APIRouter(prefix='/api/reports/operations')


def _stamp_filter(c):
    if c.dialect == 'postgres':
        return 'created_at::timestamptz >= ?::timestamptz AND created_at::timestamptz < ?::timestamptz'
    return 'julianday(created_at) >= julianday(?) AND julianday(created_at) < julianday(?)'


def _status_counts(c, clinic, kind, condition='', extra=()):
    status = json_text(c, 'data', 'status')
    rows = c.execute(
        f'SELECT {status} AS label, COUNT(*) AS amount FROM records '
        f'WHERE clinic_id=? AND kind=? {condition} GROUP BY 1 ORDER BY 1',
        (clinic, kind, *extra),
    )
    return _groups(rows)


def _groups(rows):
    counts = {}
    for row in rows:
        raw = row['label']
        label = 'Not recorded' if raw is None or raw == '' else str(raw)
        counts[label] = counts.get(label, 0) + row['amount']
    return [{'label': label, 'count': count} for label, count in sorted(counts.items())]


def _total(groups):
    return sum(row['count'] for row in groups)


def build(c, clinic, days, *, as_of=None):
    if type(days) is not int or not 1 <= days <= 366:
        fail('Choose a reporting period of 1–366 days')
    practice = get(c, clinic, clinic)
    try:
        zone = ZoneInfo(practice['data'].get('timezone', 'Asia/Singapore'))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        fail('The clinic timezone must be configured before reporting', 409)
    end = as_of or datetime.now(zone).date()
    start = end - timedelta(days=days - 1)
    lower = datetime.combine(start, time.min, zone).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(timezone.utc).isoformat()

    def count(kind):
        return c.execute('SELECT COUNT(*) FROM records WHERE clinic_id=? AND kind=?', (clinic, kind)).fetchone()[0]

    patient_total = count('patient')
    species = json_text(c, 'data', 'species')
    species_rows = c.execute(
        f"SELECT COALESCE(NULLIF({species},''),'Not recorded') AS label, COUNT(*) AS amount "
        'FROM records WHERE clinic_id=? AND kind=? GROUP BY 1 ORDER BY 1',
        (clinic, 'patient'),
    )
    by_species = _groups(species_rows)
    # A PostgreSQL JSON-expression join against owners became the dominant
    # report cost under concurrent synthetic load. Scan the indexed clinic/kind
    # ranges once each, then resolve valid primary/additional links in memory.
    # This counts each patient once and never treats a merged or foreign owner
    # as current, including for malformed historical link lists.
    active_ids = set()
    for row in c.execute("SELECT id,data FROM records WHERE clinic_id=? AND kind='owner'", (clinic,)):
        try:
            owner = json.loads(row['data'])
            if isinstance(owner, dict) and owner.get('merged_into') in (None, ''):
                active_ids.add(row['id'])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    linked = 0
    for row in c.execute("SELECT data FROM records WHERE clinic_id=? AND kind='patient'", (clinic,)):
        try:
            data = json.loads(row[0])
            if not isinstance(data, dict):
                continue
            primary = data.get('owner_id')
            additional = data.get('additional_owner_ids')
            if (isinstance(primary, str) and primary in active_ids) or (
                isinstance(additional, list) and any(
                    isinstance(owner, str) and owner in active_ids for owner in additional
                )
            ):
                linked += 1
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    timestamp = _stamp_filter(c)
    consultations = _status_counts(c, clinic, 'consultation', 'AND ' + timestamp, (lower, upper))
    appointments = _status_counts(c, clinic, 'appointment',
                                  'AND ' + json_text(c, 'data', 'date') + ' BETWEEN ? AND ?',
                                  (start.isoformat(), end.isoformat()))
    reminders = _status_counts(c, clinic, 'reminder',
                               'AND ' + json_text(c, 'data', 'due') + ' BETWEEN ? AND ?',
                               (start.isoformat(), end.isoformat()))
    messages = _status_counts(c, clinic, 'outbox', 'AND ' + timestamp, (lower, upper))
    intake_status = json_text(c, 'data', 'status')
    open_intakes = c.execute(
        f"SELECT COUNT(*) FROM records WHERE clinic_id=? AND kind='intake' AND {intake_status}='new'",
        (clinic,),
    ).fetchone()[0]
    failed_jobs = c.execute(
        "SELECT COUNT(*) FROM jobs WHERE clinic_id=? AND status IN ('failed','conflict')",
        (clinic,),
    ).fetchone()[0]

    low_stock = stock_items = invalid_stock = 0
    for row in c.execute("SELECT data FROM records WHERE clinic_id=? AND kind='inventory'", (clinic,)):
        try:
            item = json.loads(row[0])
            if item.get('unit') == 'service':
                continue
            stock, reorder = item['stock'], item['reorder']
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                   not math.isfinite(value) for value in (stock, reorder)):
                raise ValueError('Invalid quantity')
            stock_items += 1
            low_stock += stock <= reorder
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            invalid_stock += 1

    return {
        'clinic_id': clinic, 'timezone': str(zone), 'start': start.isoformat(),
        'end': end.isoformat(), 'days': days, 'generated_at': now(),
        'patients': {'total': patient_total, 'linked_to_owner': linked, 'by_species': by_species},
        'owners_total': count('owner'),
        'consultations': {'total': _total(consultations), 'by_status': consultations},
        'appointments': {'total': _total(appointments), 'by_status': appointments},
        'reminders': {'total': _total(reminders), 'by_status': reminders},
        'messages': {'total': _total(messages), 'by_status': messages},
        'open_intakes': open_intakes, 'failed_or_conflicting_jobs': failed_jobs,
        'stock': {'items': stock_items, 'low': low_stock, 'invalid': invalid_stock},
    }


def read(request, days):
    from main import identity
    clinic, actor = identity(request)
    with connection(snapshot=True) as c:
        require(c, clinic, actor, ALL)
        return build(c, clinic, days)


@router.get('')
def report(request: Request, days: int = Query(30, ge=1, le=366)):
    return read(request, days)


@router.get('/export')
def export(request: Request, days: int = Query(30, ge=1, le=366)):
    result = read(request, days)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Metric', 'Value', 'Period start', 'Period end', 'Timezone', 'Generated UTC'])

    def item(label, value):
        writer.writerow([label, value, result['start'], result['end'],
                         result['timezone'], result['generated_at']])

    item('Patients registered, all time', result['patients']['total'])
    item('Patients linked to a current owner, all time', result['patients']['linked_to_owner'])
    item('Owners registered, all time', result['owners_total'])
    for species in result['patients']['by_species']:
        item('Species: ' + species['label'], species['count'])
    for key, label in [('consultations', 'Consultations created'), ('appointments', 'Appointments scheduled'),
                       ('reminders', 'Reminders due'), ('messages', 'Messages created')]:
        item(label + ', period', result[key]['total'])
        for status in result[key]['by_status']:
            item(label + ' / status: ' + status['label'], status['count'])
    for label, value in [('Open owner intakes, current', result['open_intakes']),
                         ('Failed or conflicting jobs, current', result['failed_or_conflicting_jobs']),
                         ('Stock items, current', result['stock']['items']),
                         ('Low stock items, current', result['stock']['low']),
                         ('Invalid stock records, current', result['stock']['invalid'])]:
        item(label, value)
    return Response(out.getvalue(), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="broby-operational-report.csv"'})

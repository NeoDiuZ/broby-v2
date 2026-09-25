"""Native history remains complete and source-identical without per-event SQL."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event as sql_event, select

from spine import database, projection, reader, service
from spine.models import Concept, Event, Observation, Patient, Source
from test_spine import client


def seed_history(count):
    projection.sync('clinic-east')
    projection.sync('clinic-river')
    with database.session() as session:
        session.add(Patient(id='batch-foreign-patient', clinic_id='clinic-river',
                            name='SYNTHETIC foreign patient', species='Cat', breed='', sex='Unknown'))
        session.add_all([
            Concept(id='batch-number', code='synthetic_batch_number', name='Synthetic number', unit='units', value_type='number'),
            Concept(id='batch-boolean', code='synthetic_batch_boolean', name='Synthetic boolean', unit='', value_type='boolean'),
        ])
        session.flush()
        for index in range(count + 2):
            clinic = 'clinic-river' if index == count else 'clinic-east'
            patient = 'batch-foreign-patient' if index == count else 'luna' if index == count + 1 else 'milo'
            when = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
            source_id = f'batch-source-{index}'
            session.add(Source(id=source_id, clinic_id=clinic, patient_id=patient,
                               kind='document', reference_id=f'synthetic-report-{index}', page=index + 1,
                               content={'text': f'SYNTHETIC original receipt {index}'}))
            session.flush()
            session.add(Event(id=f'batch-event-{index}', clinic_id=clinic, patient_id=patient,
                event_type='lab_result', occurred_at=when, summary=f'SYNTHETIC batch {index}',
                actor={'kind': 'system', 'name': 'Synthetic acceptance'}, source_id=source_id if index % 3 else None,
                body={'text': f'SYNTHETIC fact {index}', 'owner_approved': index % 2 == 0},
                dedupe_key=f'batch:{index}', payload_hash='synthetic'))
            session.flush()
            session.add_all([
                Observation(id=f'batch-number-{index}', event_id=f'batch-event-{index}', concept_id='batch-number',
                    observed_at=when, value_type='number', value=6, ref_low=1, ref_high=5, source_id=source_id),
                Observation(id=f'batch-boolean-{index}', event_id=f'batch-event-{index}', concept_id='batch-boolean',
                    observed_at=when, value_type='boolean', boolean_value=False, source_id=None),
            ])
        session.commit()


def test_batch_views_preserve_every_flag_value_and_positioned_source(client):
    seed_history(5)
    with database.session() as session:
        events = list(session.scalars(select(Event).where(Event.id.like('batch-event-%'))))
        expected = [service.event_view(session, entry) for entry in events]
    with database.session() as session:
        events = list(session.scalars(select(Event).where(Event.id.like('batch-event-%'))))
        context = service.event_context(session, events)
        actual = [service.event_view(session, entry, context) for entry in events]
    assert actual == expected
    assert any({'type': 'missing_source'} in view['flags'] for view in actual)
    for view in actual:
        boolean = next(value for value in view['observations'] if value['value_type'] == 'boolean')
        numeric = next(value for value in view['observations'] if value['value_type'] == 'number')
        assert boolean['value'] is False and boolean['source'] is None and boolean['flag'] is None
        assert numeric['flag'] == 'high' and numeric['source']['page'] >= 1


def test_native_read_crosses_batch_boundary_without_cross_patient_or_clinic_rows(client):
    count = 405
    seed_history(count)
    statements = []
    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith('SELECT'): statements.append(statement)
    engine = database.engine()
    sql_event.listen(engine, 'before_cursor_execute', capture)
    try:
        records = reader.native_records('clinic-east', 'milo')
    finally:
        sql_event.remove(engine, 'before_cursor_execute', capture)
    events = [r for r in records if r['kind'] == 'event']
    observations = [r for r in records if r['kind'] == 'observation']
    sources = [r for r in records if r['kind'] == 'source']
    assert len(events) == count and len(observations) == count * 2 and len(sources) == count
    assert len(statements) == 6  # events + 2 observation + 1 concept + 2 source batches
    assert all(r['clinic_id'] == 'clinic-east' and r['data']['patient_id'] == 'milo' for r in records)
    assert len({r['id'] for r in records}) == len(records)
    assert [r['created_at'] for r in events] == sorted((r['created_at'] for r in events), reverse=True)
    assert all(r['data']['value'] is False for r in observations if r['data']['value_type'] == 'boolean')
    assert reader.native_records('clinic-east', 'batch-foreign-patient') == []


def test_timeline_pages_keep_complete_receipts_with_bounded_queries(client):
    seed_history(25)
    statements = []
    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith('SELECT'): statements.append(statement)
    engine = database.engine()
    sql_event.listen(engine, 'before_cursor_execute', capture)
    try:
        with database.session() as session:
            page = service.timeline(session, 'clinic-east', 'milo', 20, None, category='bloods')
    finally:
        sql_event.remove(engine, 'before_cursor_execute', capture)
    assert len(page['items']) == 20 and page['next_cursor']
    assert len(statements) == 5  # patient authorization plus four complete page queries
    with database.session() as session:
        following = service.timeline(session, 'clinic-east', 'milo', 20, page['next_cursor'], category='bloods')
    assert len(following['items']) == 5 and following['next_cursor'] is None
    assert not {v['id'] for v in page['items']} & {v['id'] for v in following['items']}
    assert all(len(v['observations']) == 2 for v in page['items'] + following['items'])

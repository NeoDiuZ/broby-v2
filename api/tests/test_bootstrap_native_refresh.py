"""Actual PostgreSQL native ingest and direct fact edits invalidate polling."""
from sqlalchemy import select, delete
import db
from spine import database
from spine.models import Event, Observation, Source, Concept
from test_spine import client, ingest


def read(client, previous=None):
    response = client.get('/api/bootstrap', params={'since': previous['snapshot_revision']} if previous else {})
    assert response.status_code == 200, response.text
    return response.json()


def test_native_ingest_approval_source_observation_and_concept_changes(client):
    before = read(client)
    response = ingest(client); assert response.status_code == 200, response.text
    event_id = response.json()['id']
    current = read(client, before); assert 'records' in current
    assert read(client, current)['unchanged']
    with db.connection() as c:
        revision = c.execute('SELECT revision FROM bootstrap_revisions WHERE clinic_id=?', ('clinic-east',)).fetchone()[0]
    changes = [
        ('event', lambda e, o, source, concept: setattr(e, 'body', {**e.body, 'owner_approved': True})),
        ('source', lambda e, o, source, concept: setattr(source, 'content', {**source.content, 'text': 'SYNTHETIC corrected source receipt'})),
        ('observation', lambda e, o, source, concept: setattr(o, 'value', 4.2)),
        ('concept', lambda e, o, source, concept: setattr(concept, 'name', 'SYNTHETIC reviewed concept label')),
    ]
    for label, change in changes:
        with database.session() as s, s.begin():
            e = s.get(Event, event_id)
            o = s.scalar(select(Observation).where(Observation.event_id == event_id))
            source = s.get(Source, e.source_id or o.source_id)
            concept = s.get(Concept, o.concept_id)
            change(e, o, source, concept)
        latest = read(client, current)
        assert 'records' in latest, label
        assert latest['snapshot_revision'] != current['snapshot_revision'], label
        current = latest
    with db.connection() as c:
        assert c.execute('SELECT revision FROM bootstrap_revisions WHERE clinic_id=?', ('clinic-east',)).fetchone()[0] == revision
    with database.session() as s, s.begin():
        s.execute(delete(Observation).where(Observation.event_id == event_id))
        s.execute(delete(Event).where(Event.id == event_id))
    latest = read(client, current)
    assert 'records' in latest
    assert event_id not in {row['id'] for row in latest['records']}

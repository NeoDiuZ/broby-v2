"""Durable, private enquiries from the public onboarding form."""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

import auth
from db import connection, get, now

router = APIRouter(prefix='/api/marketing/leads')


class Enquiry(BaseModel):
    submission_key: str = Field(min_length=36, max_length=36)
    contact_name: str = Field(min_length=2, max_length=120)
    clinic_name: str = Field(default='', max_length=120)
    country: Literal['SG', 'MY', 'other']
    contact_channel: Literal['email', 'whatsapp', 'phone', 'other']
    contact_handle: str = Field(min_length=5, max_length=120)
    subject: str = Field(default='', max_length=100)
    message: str = Field(default='', max_length=2000)
    company_website: str = Field(default='', max_length=200)

    @field_validator('submission_key')
    @classmethod
    def valid_key(cls, value):
        try:
            if str(uuid.UUID(value)) != value.lower():
                raise ValueError('Invalid submission key')
        except ValueError as exc:
            raise ValueError('Invalid submission key') from exc
        return value.lower()

    @field_validator('contact_name', 'clinic_name', 'contact_handle', 'subject', 'message', 'company_website')
    @classmethod
    def trim(cls, value):
        return value.strip()


def validate_contact(enquiry):
    handle = enquiry.contact_handle
    if not enquiry.contact_name or not handle:
        raise HTTPException(422, 'Provide your name and contact details')
    if enquiry.contact_channel == 'email':
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', handle) or len(handle) > 254:
            raise HTTPException(422, 'Provide a valid email address')
    elif enquiry.contact_channel in ('whatsapp', 'phone'):
        digits = re.sub(r'\D', '', handle)
        if not re.fullmatch(r'\+?[0-9 ()-]+', handle) or not 7 <= len(digits) <= 15:
            raise HTTPException(422, 'Provide a valid phone number')


def contact_key(enquiry):
    handle = enquiry.contact_handle
    if enquiry.contact_channel in ('whatsapp', 'phone'):
        handle = re.sub(r'\D', '', handle)
    else:
        handle = handle.casefold()
    return hashlib.sha256((enquiry.contact_channel + ':' + handle).encode()).hexdigest()


def owner(request):
    from main import identity
    clinic, actor = identity(request)
    with connection() as c:
        member = get(c, actor, clinic)
    if not member or member['data'].get('role') != 'admin':
        raise HTTPException(403, 'Website enquiries require the site administrator')
    if auth.enabled():
        session = auth.session(request)
        if not session or not os.getenv('BROBY_ADMIN_USERNAME') or session['username'] != os.getenv('BROBY_ADMIN_USERNAME'):
            raise HTTPException(403, 'Website enquiries require the site administrator')
    return actor


@router.post('/submit', status_code=201)
def submit(enquiry: Enquiry, request: Request):
    # A bounded honeypot avoids storing obvious bot submissions.
    if enquiry.company_website:
        return {'received': True}
    validate_contact(enquiry)
    payload = enquiry.model_dump(exclude={'company_website', 'submission_key'})
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    key = contact_key(enquiry)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with connection(True) as c:
        prior = c.execute('SELECT id,payload_hash FROM marketing_leads WHERE submission_key=?', (enquiry.submission_key,)).fetchone()
        if prior:
            if prior['payload_hash'] != digest:
                raise HTTPException(409, 'This request key belongs to a different enquiry')
            return {'received': True, 'reference': prior['id']}
        recent = c.execute('SELECT COUNT(*) FROM marketing_leads WHERE contact_key=? AND created_at>=?',
                           (key, cutoff)).fetchone()[0]
        if recent >= 3:
            raise HTTPException(429, 'Too many enquiries from this contact. Please email us directly.')
        lead_id = str(uuid.uuid4())
        c.execute('''INSERT INTO marketing_leads
          (id,submission_key,payload_hash,contact_name,clinic_name,country,contact_channel,contact_handle,contact_key,subject,message,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
          (lead_id,enquiry.submission_key,digest,enquiry.contact_name,enquiry.clinic_name,
           enquiry.country,enquiry.contact_channel,enquiry.contact_handle,key,enquiry.subject,enquiry.message,now()))
    return {'received': True, 'reference': lead_id}


@router.get('')
def list_enquiries(request: Request, offset: int = 0):
    owner(request)
    if offset < 0 or offset > 100000:
        raise HTTPException(422, 'Invalid offset')
    with connection() as c:
        rows = c.execute('''SELECT id,contact_name,clinic_name,country,contact_channel,
                           contact_handle,subject,message,status,created_at,contacted_at,contacted_by
                           FROM marketing_leads ORDER BY created_at DESC,id DESC LIMIT 100 OFFSET ?''',
                         (offset,)).fetchall()
        total = c.execute('SELECT COUNT(*) FROM marketing_leads').fetchone()[0]
        outstanding = c.execute("SELECT COUNT(*) FROM marketing_leads WHERE status='new'").fetchone()[0]
    return {'leads': [dict(row) for row in rows], 'total': total, 'outstanding': outstanding}


@router.post('/{lead_id}/contacted')
def mark_contacted(lead_id: str, request: Request):
    actor = owner(request)
    with connection(True) as c:
        changed = c.execute("UPDATE marketing_leads SET status='contacted',contacted_at=?,contacted_by=? WHERE id=? AND status='new'",
                            (now(), actor, lead_id)).rowcount
        row = c.execute('SELECT id,status,contacted_at FROM marketing_leads WHERE id=?', (lead_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Enquiry not found')
    return {'id': row['id'], 'status': row['status'], 'contacted_at': row['contacted_at'], 'changed': bool(changed)}

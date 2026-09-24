'use client';
import {useState} from 'react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {Row} from '@/lib/types';
import {Modal} from './ui';

type Preview = {request_version: number; schedule_version: number | null; overlapping_leave_ids: string[]; conflicts: {id: string; date: string; time: string; patient: string; clinician: string}[]};
const states = ['pending', 'approved', 'rejected', 'cancelled'];

function LeaveRequestForm({onClose}: {onClose: () => void}) {
 const w = useWorkspace(), actor = w.snapshot!.actor;
 const members = w.records.filter(r => r.kind === 'member' && r.data.active && (actor.data.role === 'admin' || r.id === actor.id));
 const [draft, setDraft] = useState({member_id: actor.id, start: '', end: '', reason: ''});
 const [key, setKey] = useState(() => crypto.randomUUID()), [busy, setBusy] = useState(false), [error, setError] = useState('');
 const change = (field: string, value: string) => {setDraft(p => ({...p, [field]: value})); setKey(crypto.randomUUID()); setError('')};
 return <Modal title="Request leave" onClose={() => {if (!busy) onClose()}}><form className="form" onSubmit={async e => {
  e.preventDefault(); setBusy(true); setError('');
  try {await w.act('leave.request', draft, key); w.notify('Leave requested. Availability changes only after approval.'); onClose()}
  catch (e) {setError((e as Error).message)} finally {setBusy(false)}
 }}>
  <p>Full days in {w.snapshot?.clinic.data.timezone || 'Asia/Singapore'}, including both dates. Pending leave does not block appointments. An administrator cannot approve their own leave.</p>
  <fieldset disabled={busy || w.offline} className="rota-controls">
   <label>Leave staff member<select value={draft.member_id} onChange={e => change('member_id', e.target.value)}>{members.map(m => <option key={m.id} value={m.id}>{m.data.name}</option>)}</select></label>
   <label>Leave start date<input type="date" required value={draft.start} onChange={e => change('start', e.target.value)}/></label>
   <label>Leave end date<input type="date" required value={draft.end} min={draft.start} onChange={e => change('end', e.target.value)}/></label>
   <label>Leave operational reason<textarea required minLength={3} maxLength={500} value={draft.reason} onChange={e => change('reason', e.target.value)}/></label>
   <p className="muted">The clinic team can see this rota note and its decision history. Do not enter medical or confidential HR information.</p>
   <button className="primary" type="submit">{busy ? 'Submitting…' : 'Submit leave request'}</button>
  </fieldset>{error && <p role="alert" className="error">{error}</p>}
 </form></Modal>;
}

function LeaveDecision({initial, onClose}: {initial: Row; onClose: () => void}) {
 const w = useWorkspace();
 const row = w.records.find(r => r.id === initial.id) || initial;
 const member = w.records.find(r => r.id === row.data.member_id);
 const canReview = !!w.snapshot?.permissions.includes('leave.review') && row.data.member_id !== w.snapshot.actor.id;
 const canCancel = !!w.snapshot?.permissions.includes('leave.cancel') && (row.data.member_id === w.snapshot.actor.id || w.snapshot.actor.data.role === 'admin');
 const [reason, setReason] = useState(''), [review, setReview] = useState<Preview | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
 const [decisionKey, setDecisionKey] = useState(() => crypto.randomUUID());
 const config = w.records.find(r => r.kind === 'schedule');
 const stale = review && (row.version !== review.request_version || (config?.version ?? null) !== review.schedule_version);
 const mutate = async (decision: string) => {
  setBusy(true); setError('');
  try {
   await w.act(decision === 'cancelled' ? 'leave.cancel' : 'leave.review', {id: row.id, version: row.version, reason, ...(decision === 'cancelled' ? {} : {decision}), ...(decision === 'approved' ? {schedule_version: review?.schedule_version} : {})}, `${decisionKey}-${decision}`);
   w.notify(decision === 'approved' ? 'Leave approved. Appointments now respect these days off.' : decision === 'rejected' ? 'Leave rejected.' : 'Leave withdrawn. Underlying rota hours apply again.'); onClose();
  } catch (e) {setError((e as Error).message)} finally {setBusy(false)}
 };
 return <Modal title="Leave request details" onClose={() => {if (!busy) onClose()}} wide><div className="modal-body">
  <h3>{member?.data.name || 'Staff member'} · {row.data.start} to {row.data.end}</h3><p>Status: <strong>{row.data.status}</strong></p><p>{row.data.reason}</p>
  <ol>{row.data.history.map((h: any, i: number) => <li key={i}><strong>{h.status}</strong> · {w.records.find(r => r.id === h.actor)?.data.name || 'Staff'} · {new Date(h.at).toLocaleString('en-SG')}<p>{h.reason}</p></li>)}</ol>
  {['pending', 'approved'].includes(row.data.status) && <>
   <label>Decision or withdrawal reason<textarea value={reason} minLength={3} maxLength={500} disabled={busy} onChange={e => {setReason(e.target.value); setDecisionKey(crypto.randomUUID())}}/></label>
   <p className="muted">Use an operational note visible to clinic staff. Withdrawal restores the underlying rota; it does not erase this history or change any appointments.</p>
   {review && <section className="rota-review" aria-live="polite"><h4>{stale ? 'Rota or request changed — review again' : review.conflicts.length || review.overlapping_leave_ids.length ? 'Resolve conflicts before approval' : 'Ready to approve'}</h4>
    {!!review.overlapping_leave_ids.length && <p>Approved leave overlaps this request.</p>}
    {review.conflicts.length > 0 ? <><p>Move or cancel these bookings in Appointments, then review again.</p><ul>{review.conflicts.map(c => <li key={c.id}>{c.date} {c.time} · {c.patient} · {c.clinician}</li>)}</ul></> : <p>No conflicting active bookings in this review. Approval checks again for bookings created since review.</p>}
   </section>}
   <div className="actions">
    {row.data.status === 'pending' && canReview && <><button className="secondary" disabled={busy || w.offline} onClick={async () => {
     setBusy(true); setError(''); setReview(null);
     try {const result = await api('/schedule/leave/preview', {method: 'POST', body: JSON.stringify({id: row.id, version: row.version})}); setReview(result); setDecisionKey(crypto.randomUUID())}
     catch (e) {setError((e as Error).message)} finally {setBusy(false)}
    }}>Review leave conflicts</button>
    <button className="primary" disabled={busy || w.offline || reason.trim().length < 3 || !review || !!stale || review.conflicts.length > 0 || review.overlapping_leave_ids.length > 0} onClick={() => void mutate('approved')}>Approve reviewed leave</button>
    <button className="secondary" disabled={busy || w.offline || reason.trim().length < 3} onClick={() => void mutate('rejected')}>Reject leave</button></>}
    {canCancel && <button className="secondary" disabled={busy || w.offline || reason.trim().length < 3} onClick={() => void mutate('cancelled')}>Withdraw leave</button>}
   </div>
   {row.data.status === 'pending' && row.data.member_id === w.snapshot?.actor.id && <p>Another administrator must review your leave request.</p>}
  </>}
  {error && <p role="alert" className="error">{error}</p>}{w.offline && <p role="alert">Reconnect to change leave.</p>}
 </div></Modal>;
}

export function LeaveRequests() {
 const w = useWorkspace();
 const [status, setStatus] = useState('pending'), [showForm, setShowForm] = useState(false), [selected, setSelected] = useState<Row | null>(null), [limit, setLimit] = useState(25);
 const rows = w.records.filter(r => r.kind === 'staff_leave' && r.data.status === status).sort((a, b) => a.data.start.localeCompare(b.data.start) || a.id.localeCompare(b.id));
 return <section className="section-gap"><div className="section-heading"><h3>Leave requests</h3>{w.snapshot?.permissions.includes('leave.request') && <button className="secondary" disabled={w.offline} onClick={() => setShowForm(true)}>Request leave</button>}</div>
  <p>Pending requests leave appointments unchanged. Approved full-day leave blocks bookings even if a dated override or rota period has shifts.</p>
  <label>Leave request status<select value={status} onChange={e => {setStatus(e.target.value); setLimit(25)}}>{states.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}</select></label>
  {!rows.length && <p className="muted">No {status} leave requests.</p>}
  {rows.slice(0, limit).map(r => <article key={r.id} className="rota-exception"><div className="section-heading"><div><strong>{w.records.find(m => m.id === r.data.member_id)?.data.name || 'Staff'}</strong><p>{r.data.start} to {r.data.end} · {r.data.reason}</p></div><button className="secondary small" onClick={() => setSelected(r)}>View leave request</button></div></article>)}
  {rows.length > limit && <button className="secondary" onClick={() => setLimit(n => n + 25)}>Show more leave requests ({rows.length - limit} remaining)</button>}
  {showForm && <LeaveRequestForm onClose={() => setShowForm(false)}/>}
  {selected && <LeaveDecision key={selected.id} initial={selected} onClose={() => setSelected(null)}/>}
 </section>;
}

'use client';
import React, {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace';
import {Row} from '@/lib/types';
import {validCalendarDate} from '@/lib/calendar';
import {Modal} from './ui';
import {LeaveRequests} from './LeaveRequests';

type Shift = {start: string; end: string};
type Exception = {windows: Shift[]; reason: string};
type Period = {start: string; end: string; week: Record<string, Shift[]>; reason: string};
type Schedule = {rooms: string[]; availability: Record<string, Record<string, Shift[]>>; date_overrides: Record<string, Record<string, Exception>>; periods: Record<string, Period[]>};
type Conflict = {id: string; date: string; time: string; duration: number; patient: string; clinician: string; reasons: string[]};
type Review = {version: number | null; data: Schedule; conflicts: Conflict[]; key: string};
type Rota = {timezone: string; dates: string[]; members: {id: string; name: string; days: {date: string; source: string; windows: Shift[] | null; reason: string}[]}[]};
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const newShift = (): Shift => ({start: '09:00', end: '17:00'});
const dayLabel = (date: string) => new Date(date + 'T12:00:00').toLocaleDateString('en-SG', {weekday: 'short', day: 'numeric', month: 'short'});

function Shifts({label, value, onChange}: {label: string; value: Shift[]; onChange: (value: Shift[]) => void}) {
 return <fieldset className="rota-shifts"><legend>{label}</legend>
  {!value.length && <span className="muted">Day off</span>}
  {value.map((shift, i) => <div className="actions" key={i}>
   <label>From<input type="time" aria-label={`${label} shift ${i + 1} start`} value={shift.start} onChange={e => onChange(value.map((w, n) => n === i ? {...w, start: e.target.value} : w))}/></label>
   <label>Until<input type="time" aria-label={`${label} shift ${i + 1} end`} value={shift.end} onChange={e => onChange(value.map((w, n) => n === i ? {...w, end: e.target.value} : w))}/></label>
   <button type="button" className="text-button" aria-label={`Remove ${label} shift ${i + 1}`} onClick={() => onChange(value.filter((_, n) => n !== i))}>Remove</button>
  </div>)}
  <button type="button" className="secondary small" disabled={value.length >= 8} onClick={() => onChange([...value, newShift()])}>Add {label} shift</button>
 </fieldset>;
}

function RotaEditor({config, onClose}: {config?: Row; onClose: () => void}) {
 const w = useWorkspace();
 const members = w.records.filter(r => r.kind === 'member');
 // Capture one version when opened. Polling must never replace an administrator's draft.
 const [baseVersion] = useState(config?.version ?? null);
 const [draft, setDraft] = useState<Schedule>(() => structuredClone({rooms: config?.data.rooms || [], availability: config?.data.availability || {}, date_overrides: config?.data.date_overrides || {}, periods: config?.data.periods || {}}));
 const [rooms, setRooms] = useState(draft.rooms.join('\n'));
 const [member, setMember] = useState(members.find(r => r.data.role === 'vet' && r.data.active)?.id || members[0]?.id || '');
 const [date, setDate] = useState('');
 const [review, setReview] = useState<Review | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
 const revise = (next: Schedule) => {setDraft(next); setReview(null); setError('')};
 const week = draft.availability[member];
 const exceptions = draft.date_overrides[member] || {};
 const periods = draft.periods[member] || [];
 const changePeriod = (i: number, value?: Period) => revise({...draft, periods: {...draft.periods, [member]: value ? periods.map((p, n) => n === i ? value : p) : periods.filter((_, n) => n !== i)}});
 const changeException = (day: string, value?: Exception) => {
  const days = {...exceptions}; if (value) days[day] = value; else delete days[day];
  revise({...draft, date_overrides: {...draft.date_overrides, [member]: days}});
 };
 const preview = async () => {
  setBusy(true); setError(''); setReview(null);
  try {const result = await api('/schedule/preview', {method: 'POST', body: JSON.stringify({...draft, rooms: rooms.split('\n').map(r => r.trim()).filter(Boolean), version: baseVersion})}); setReview({...result, key: crypto.randomUUID()})}
  catch (e) {setError((e as Error).message)} finally {setBusy(false)}
 };
 const save = async () => {
  if (!review || review.conflicts.length) return;
  setBusy(true); setError('');
  try {await w.act('schedule.configure', {...review.data, version: review.version}, review.key); w.notify('Staff rota saved'); onClose()}
  catch (e) {setError((e as Error).message)} finally {setBusy(false)}
 };
 return <Modal title="Edit staff rota" onClose={() => {if (!busy) onClose()}} wide>
  <div className="modal-body rota-editor">
   <p>Times use {w.snapshot?.clinic.data.timezone || 'Asia/Singapore'}. Gaps between shifts are breaks. Approved leave takes priority, then dated changes, then rota periods, then base weekly hours. Existing appointments must fit before changes can be saved.</p>
   <fieldset disabled={busy} className="rota-controls">
    <label>Room names, one per line<textarea aria-label="Room names, one per line" value={rooms} onChange={e => {setRooms(e.target.value); setReview(null); setError('')}} rows={3}/></label>
    <label>Staff member<select value={member} onChange={e => setMember(e.target.value)}>{members.map(r => <option key={r.id} value={r.id}>{r.data.name}{r.data.active ? '' : ' (inactive)'}</option>)}</select></label>
    <label className="actions"><input type="checkbox" checked={week !== undefined} onChange={e => {const availability = {...draft.availability}; if (e.target.checked) availability[member] = {}; else delete availability[member]; revise({...draft, availability})}}/>Use weekly shifts for this staff member</label>
    <p className="muted">{week === undefined ? 'No weekly restriction. Dated leave or replacement hours still apply.' : 'Days without a shift are days off. Add separate shifts for breaks.'}</p>
    {week !== undefined && <div className="rota-week-editor">{weekdays.map((day, i) => <Shifts key={day} label={day} value={week[String(i)] || []} onChange={value => revise({...draft, availability: {...draft.availability, [member]: {...week, [String(i)]: value}}})}/>)}</div>}
    <h3>Rota periods</h3><p>Plan different weekly hours for an inclusive date range. Periods cannot overlap. Outside these dates, base weekly hours apply. Days without a shift inside a period are days off.</p>
    {periods.map((p, i) => <section className="rota-exception" key={member + ':' + i}>
     <h4>Period {i + 1}</h4><div className="actions"><label>Period {i + 1} start<input type="date" value={p.start} onChange={e => changePeriod(i, {...p, start: e.target.value})}/></label><label>Period {i + 1} end<input type="date" value={p.end} onChange={e => changePeriod(i, {...p, end: e.target.value})}/></label></div>
     <label>Period {i + 1} reason<input value={p.reason} maxLength={500} onChange={e => changePeriod(i, {...p, reason: e.target.value})}/></label>
     <div className="rota-week-editor">{weekdays.map((day, n) => <Shifts key={day} label={`Period ${i + 1} ${day}`} value={p.week[String(n)] || []} onChange={value => changePeriod(i, {...p, week: {...p.week, [String(n)]: value}})}/>)}</div>
     <button className="text-button" type="button" onClick={() => changePeriod(i)}>Remove period {i + 1}</button>
    </section>)}
    <button className="secondary" type="button" disabled={periods.length >= 104} onClick={() => revise({...draft, periods: {...draft.periods, [member]: [...periods, {start: '', end: '', week: structuredClone(week || {}), reason: ''}]}})}>Add rota period</button>
    <h3>Dated changes</h3><p>For a leave request and approval record, use Leave requests below the rota. Direct dated changes remain administrator overrides and cannot override approved leave.</p>
    <div className="actions"><label>Date for a rota change<input type="date" value={date} onChange={e => setDate(e.target.value)}/></label><button type="button" className="secondary" disabled={!date || !!exceptions[date]} onClick={() => {changeException(date, {windows: [], reason: ''}); setDate('')}}>Add dated change</button></div>
    {Object.keys(exceptions).sort().map(day => <section className="rota-exception" key={member + day}>
     <div className="section-heading"><h4>{dayLabel(day)} · {day}</h4><button type="button" className="text-button" onClick={() => changeException(day)}>Remove change for {day}</button></div>
     <label>Reason for {day}<input value={exceptions[day].reason} maxLength={500} onChange={e => changeException(day, {...exceptions[day], reason: e.target.value})} placeholder="Leave or replacement shift"/></label>
     <Shifts label={day} value={exceptions[day].windows} onChange={value => changeException(day, {...exceptions[day], windows: value})}/>
     <small>Remove the change to restore weekly hours for this date.</small>
    </section>)}
    {!Object.keys(exceptions).length && <p className="muted">No dated changes for this staff member.</p>}
   </fieldset>
   {error && <p className="error" role="alert">{error} If this schedule was changed elsewhere, close and reopen the editor to load the latest version.</p>}
   {review && <section aria-live="polite" className="rota-review">
    <h3>{review.conflicts.length ? `${review.conflicts.length} appointment conflicts` : 'Ready to save'}</h3>
    {review.conflicts.length ? <><p>Reschedule or cancel these appointments in Appointments, then review again. No bookings have been changed.</p><ul>{review.conflicts.map(c => <li key={c.id}><strong>{c.date} {c.time} · {c.patient}</strong> · {c.clinician}, {c.duration} min — {c.reasons.join('; ')}</li>)}</ul></> : <p>The proposed rota fits all current and future active appointments. Saving checks again for bookings made since this review. Changes for every staff member in this draft will be saved together.</p>}
   </section>}
   <div className="actions"><button className="secondary" disabled={busy || w.offline} onClick={() => void preview()}>{busy ? 'Checking…' : 'Review rota changes'}</button>{review && !review.conflicts.length && <button className="primary" disabled={busy || w.offline} onClick={() => void save()}>Save reviewed rota</button>}<button className="text-button" disabled={busy} onClick={onClose}>Discard and close</button></div>
   {w.offline && <p role="alert">Reconnect to review and save the rota.</p>}
  </div>
 </Modal>;
}

export function StaffRota() {
 const w = useWorkspace();
 const config = w.records.find(r => r.kind === 'schedule');
 const [open, setOpen] = useState(false), [editing, setEditing] = useState(false), [start, setStart] = useState<string | null>(null);
 const [rota, setRota] = useState<Rota | null>(null), [error, setError] = useState(''), [retry, setRetry] = useState(0);
 const clinicId = w.snapshot?.clinic.id;
 useEffect(() => {
  if (!open) return;
  let active = true; setError(''); setRota(null);
  if (start !== null && !validCalendarDate(start)) {setError('Choose a complete, valid rota date.'); return}
  void api('/schedule/rota?days=7' + (start ? '&start=' + encodeURIComponent(start) : '')).then(result => {if (active) setRota(result)}).catch(e => {if (active) setError(e.message)});
  return () => {active = false};
 }, [open, start, clinicId, config?.version, retry]);
 return <details className="panel section-gap rota-panel" onToggle={e => setOpen(e.currentTarget.open)}>
  <summary>Staff rota and rooms</summary>
  {open && <div className="modal-body">
   <div className="section-heading"><div><h3>Staff availability</h3><p>{rota?.timezone || w.snapshot?.clinic.data.timezone || 'Asia/Singapore'} · {config?.data.rooms?.length ? 'Rooms: ' + config.data.rooms.join(', ') : 'No rooms configured'}</p></div>{w.snapshot?.permissions.includes('schedule.configure') && <button className="secondary" disabled={w.offline} onClick={() => setEditing(true)}>Edit staff rota</button>}</div>
   <label>Rota starting date<input type="date" value={start ?? rota?.dates[0] ?? ''} onChange={e => setStart(e.target.value)}/></label>
   {error && <p className="error" role="alert">{error} <button className="text-button" onClick={() => setRetry(n => n + 1)}>Retry loading rota</button></p>}
   {!rota && !error && <p>Loading rota…</p>}
   {rota && <div className="table-wrap"><table className="rota-table"><caption>Weekly rota — gaps between shifts are breaks</caption><thead><tr><th scope="col">Staff</th>{rota.dates.map(d => <th scope="col" key={d}>{dayLabel(d)}</th>)}</tr></thead><tbody>{rota.members.map(m => <tr key={m.id}><th scope="row">{m.name}</th>{m.days.map(d => <td key={d.date}>{d.windows === null ? 'No weekly restriction' : !d.windows.length ? 'Day off' : d.windows.map((s, i) => <div key={i}>{s.start}–{s.end}</div>)}{d.source === 'exception' && <small>Dated change: {d.reason}</small>}{d.source === 'period' && <small>Rota period: {d.reason}</small>}{d.source === 'approved_leave' && <small>Approved leave</small>}</td>)}</tr>)}</tbody></table></div>}
   <LeaveRequests key={clinicId}/>
   {editing && <RotaEditor key={clinicId} config={config} onClose={() => setEditing(false)}/>}
  </div>}
 </details>;
}

"""Incremental speech previews over immutable uploaded recording prefixes.

One durable job follows a recording. Appends can advance its desired prefix
while a worker runs; the worker queues another pass instead of losing that work.
Only final, strictly decoded audio can publish a clinical source.
"""
import hashlib
import json

import audio_windows
import providers
from db import connection, now, uid, unpack, update


def options(c, value, clinic, actor):
    from actions import authorize, fail
    if value is None:
        return None
    authorize(c, clinic, actor, 'recording.transcribe')
    if not providers.available()['transcription']:
        fail('Configure speech before enabling automatic transcription', 503)
    if not isinstance(value, dict) or value.get('language', 'multi') not in ('multi', 'en', 'zh', 'ms'):
        fail('Choose a supported speech language')
    if not isinstance(value.get('diarize', True), bool):
        fail('Speaker separation must be true or false')
    return {'language': value.get('language', 'multi'), 'diarize': value.get('diarize', True),
            'actor_id': actor, 'window_seconds': audio_windows.WINDOW_SECONDS}


def enqueue(c, recording, count):
    """Called inside the shared action transaction; never resets a failed job."""
    from actions import fail
    data = recording['data']
    config = data.get('refinement')
    if not config:
        fail('Automatic transcription was not enabled for this recording')
    final = data['status'] == 'saved'
    job = unpack(c.execute('SELECT * FROM jobs WHERE id=?', (data.get('refinement_job_id', ''),)).fetchone())
    if job:
        payload = job['payload']
        if count <= payload['prefix_chunks'] and (not final or payload.get('final')):
            return {'id': job['id'], 'status': job['status']}
        payload.update(prefix_chunks=max(count, payload['prefix_chunks']), final=final or payload.get('final', False))
        status = 'queued' if job['status'] == 'waiting' else job['status']
        c.execute('UPDATE jobs SET payload=?,status=?,updated_at=? WHERE id=?',
                  (json.dumps(payload), status, now(), job['id']))
        if status == 'queued' and job['status'] == 'waiting':
            c.execute('DELETE FROM job_claims WHERE job_id=?', (job['id'],))
        return {'id': job['id'], 'status': status}
    job_id = uid()
    payload = {'kind': 'transcription', 'continuous': True, 'recording_id': recording['id'],
               'patient_id': data['patient_id'], **config, 'prefix_chunks': count, 'final': final, 'clinical_epoch':__import__('clinical_reconciliation').scope_epoch(__import__('clinical_reconciliation').eligibility(c,recording['clinic_id']),data['patient_id'])}
    c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',
              (job_id, recording['clinic_id'], data['consultation_id'], 'queued', json.dumps(payload),
               None, None, now(), now()))
    update(c, recording, {**data, 'refinement_job_id': job_id})
    return {'id': job_id, 'status': 'queued'}


def request_prefix(c, payload, clinic):
    from actions import owned, integer, fail
    recording = owned(c, payload['id'], clinic, 'recording')
    count = integer(payload.get('expected_chunks'), 'Prefix chunk count', 1)
    if count > 100001:
        fail('Too many audio chunks')
    chunks = [r[0] for r in c.execute('SELECT chunk_index FROM chunks WHERE recording_id=? AND chunk_index<? ORDER BY chunk_index',
                                     (recording['id'], count))]
    if chunks != list(range(count)):
        fail('Upload every chunk in this prefix before transcribing', 409)
    if recording['data']['status'] == 'saved':
        count = recording['data']['expected_chunks']
    return enqueue(c, recording, count)


def wait_for_audio(job, payload, token, message=None):
    from jobs import owns_claim
    with connection(True) as c:
        if not owns_claim(c, job['id'], token):
            return
        current = json.loads(c.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
        advanced = current['prefix_chunks'] > payload['prefix_chunks'] or current.get('final') != payload.get('final')
        c.execute('UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=?',
                  ('queued' if advanced else 'waiting', message, now(), job['id']))
        c.execute('UPDATE job_claims SET attempts=0,next_attempt=? WHERE job_id=?', ('', job['id']))


def transcribe_prefix(job, payload, token, chunks):
    from jobs import owns_claim, authorize
    final = bool(payload.get('final'))
    windows = list((job.get('result') or {}).get('windows', []))
    if payload['window_seconds'] != audio_windows.WINDOW_SECONDS:
        raise audio_windows.AudioValidationError('Speech window settings changed. Review saved progress before retrying.')
    try:
        with audio_windows.prepare(chunks, partial=not final) as audio:
            # Hold back the tail to avoid publishing a padded/truncated last codec packet.
            count = audio.count if final else max(0, int((audio.duration - 2) // payload['window_seconds']))
            if [w['index'] for w in windows] != list(range(len(windows))) or len(windows) > count:
                raise audio_windows.AudioValidationError('Saved speech progress exceeds the verified audio prefix.')
            for index, window in enumerate(windows):
                if hashlib.sha256(audio.read(index)).hexdigest() != window['pcm_sha256']:
                    raise audio_windows.AudioValidationError('A completed speech window changed on final decoding. The preview cannot be published; retain and review the original.')

            def checkpoint(c):
                __import__('clinical_reconciliation').guard_job(c,job,payload)
                c.execute('UPDATE jobs SET result=?,error=NULL,updated_at=? WHERE id=?',
                          (json.dumps({'mode': 'transcription', 'continuous': True, 'provisional': True,
                                       'completed_windows': len(windows), 'total_windows': count,
                                       'decoded_duration': audio.duration, 'prefix_chunks': payload['prefix_chunks'],
                                       'windows': windows}), now(), job['id']))

            with connection(True) as c:
                if not owns_claim(c, job['id'], token):
                    return None
                checkpoint(c)
            for index in range(len(windows), count):
                with connection() as c:
                    if not owns_claim(c, job['id'], token):
                        return None
                    authorize(c, job['clinic_id'], payload['actor_id'], 'recording.transcribe')
                    __import__('clinical_reconciliation').guard_job(c,job,payload)
                start, end = audio.bounds(index)
                content = audio.read(index)
                output = providers.transcribe(content, 'audio/wav', payload['language'],
                                              diarize=payload['diarize'], allow_empty=True)
                utterances = []
                for segment in output['utterances']:
                    if segment['start'] > end-start or segment['end'] > end-start+.5:
                        raise providers.ProviderError('Speech timestamps exceed their audio window')
                    speaker = segment.get('speaker')
                    utterances.append({**segment, 'start': start+segment['start'], 'end': min(start+segment['end'], end),
                                       'window_index': index, 'speaker': f'{index+1}.{speaker}' if speaker is not None else None})
                windows.append({'index': index, 'start': start, 'end': end, **output, 'utterances': utterances,
                                'pcm_sha256': hashlib.sha256(content).hexdigest()})
                with connection(True) as c:
                    if not owns_claim(c, job['id'], token):
                        return None
                    authorize(c, job['clinic_id'], payload['actor_id'], 'recording.transcribe')
                    __import__('clinical_reconciliation').guard_job(c,job,payload)
                    checkpoint(c)
            if not final:
                wait_for_audio(job, payload, token)
                return None
            text = '\n\n'.join(w['text'] for w in windows if w['text'].strip())
            if not text:
                raise audio_windows.AudioValidationError('No speech was recognized. The original audio is preserved; listen to it before creating a replacement recording.')
            return {'text': text, 'utterances': [s for w in windows for s in w['utterances']],
                    'provider': 'deepgram', 'request_id': windows[0]['request_id'] if len(windows) == 1 else None,
                    'duration': audio.duration, 'diarize': payload['diarize'],
                    'refinement_windows': [{k: w[k] for k in ('index', 'start', 'end', 'provider', 'request_id', 'pcm_sha256')} for w in windows]}
    except audio_windows.IncompleteAudio:
        if final:
            raise
        wait_for_audio(job, payload, token, 'Waiting for decodable audio packets. The complete note will be checked when recording finishes.')
        return None

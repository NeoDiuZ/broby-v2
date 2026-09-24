"""Real media decoding plus deterministic provider-failure and lease tests."""
import hashlib
from io import BytesIO
import json
import subprocess
import uuid
import wave

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import actions
import audio_windows
import db
import jobs
import main
import providers


def wav(seconds):
    content = BytesIO()
    with wave.open(content, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * round(seconds * 16000))
    return content.getvalue()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(db, 'DATA', tmp_path)
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr('spine.reader.native_records', lambda *a, **k: [])
    monkeypatch.setattr(providers, 'available', lambda: {'transcription': True, 'ai': False})
    db.init()


def act(action, payload):
    return actions.execute(action, payload, 'clinic-east', 'clinic-east-vet', str(uuid.uuid4()))


def saved_recording(content=None):
    original = wav(5) if content is None else content
    recording = act('recording.create', {'patient_id': 'luna', 'consultation_id': 'consult-luna'})
    client = TestClient(main.app)
    # Split a single media file, as MediaRecorder does. The second half has no header.
    for index, chunk in enumerate((original[:len(original)//2], original[len(original)//2:])):
        assert client.put('/api/recordings/' + recording['id'] + '/chunks/' + str(index), content=chunk).status_code == 200
    act('recording.complete', {'id': recording['id'], 'expected_chunks': 2, 'duration': 0})
    return recording['id'], original


def job_state(job_id):
    with db.connection() as c:
        return db.unpack(c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


def output(text='A recorded finding.', speaker=0):
    return {'text': text, 'utterances': [{'start': 0, 'end': .9, 'speaker': speaker, 'text': text}] if text else [],
            'provider': 'synthetic', 'request_id': str(uuid.uuid4())}


def test_real_25_minute_boundaries_do_not_drop_or_repeat_samples(tmp_path):
    original = wav(1501.125)
    path = tmp_path / 'audio.wav'
    path.write_bytes(original)
    with audio_windows.prepare([{'path': str(path), 'sha256': hashlib.sha256(original).hexdigest()}]) as audio:
        assert audio.count == 2
        assert audio.bounds(0) == (0, 1500)
        assert audio.bounds(1) == (1500, 1501.125)
        frames = []
        for index in range(audio.count):
            with wave.open(BytesIO(audio.read(index)), 'rb') as window:
                frames.append(window.getnframes())
        assert sum(frames) == 1501.125 * 16000
        temporary = audio.path
    assert not temporary.exists()
    assert path.read_bytes() == original


@pytest.mark.parametrize('extension,codec', [('webm','libopus'), ('mp4','aac'), ('flac','flac')])
def test_browser_audio_formats_decode_with_actual_duration(tmp_path,extension,codec):
    source=tmp_path/'original.wav'
    source.write_bytes(wav(5))
    encoded=tmp_path/('encoded.'+extension)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(source),'-c:a',codec,str(encoded)],check=True)
    digest=hashlib.sha256(encoded.read_bytes()).hexdigest()
    with audio_windows.prepare([{'path':str(encoded),'sha256':digest}]) as audio:
        assert audio.count==1 and 4.9<audio.duration<5.1


def test_webkit_duplicate_initial_opus_timestamps_keep_all_samples(tmp_path):
    """Reproduce WebKit timing with generated tones; no user's audio fixture."""
    original=tmp_path/'synthetic.webm'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                    'sine=frequency=440:sample_rate=48000:duration=1',
                    '-c:a','libopus','-frame_duration','2.5',str(original)],check=True)
    raw=bytearray(original.read_bytes())

    def vint(offset,identifier=False):
        length=1
        while not raw[offset] & (1 << (8-length)):length+=1
        value=int.from_bytes(raw[offset:offset+length],'big')
        return (value if identifier else value & ((1 << (7*length))-1)),length

    blocks=[]
    def walk(start,end):
        pos=start
        while pos<end:
            tag,n=vint(pos,True);size,m=vint(pos+n);body=pos+n+m;stop=min(end,body+size)
            if tag in (0x18538067,0x1f43b675):walk(body,stop)
            elif tag==0xa3:
                _,track_length=vint(body)
                blocks.append(body+track_length)
            pos=stop
    walk(0,len(raw));assert len(blocks)>10
    for offset in blocks[:5]:raw[offset:offset+2]=b'\0\0'
    original.write_bytes(raw)
    # The raw PCM muxer ignores presentation timestamps. It supplies an
    # independent full-sample reference, without relaxing decoder errors.
    reference=subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror',
                              '-i',str(original),'-map','0:a:0','-ac','1','-ar','16000',
                              '-f','s16le','pipe:1'],capture_output=True,check=True).stdout
    digest=hashlib.sha256(raw).hexdigest()
    with audio_windows.prepare([{'path':str(original),'sha256':digest}]) as audio:
        with wave.open(BytesIO(audio.read(0)),'rb') as decoded:
            assert decoded.readframes(decoded.getnframes())==reference
        assert .99<audio.duration<1.02
    assert original.read_bytes()==raw


def test_retry_keeps_finished_windows_offsets_speakers_and_one_source(monkeypatch):
    monkeypatch.setattr(audio_windows, 'WINDOW_SECONDS', 2)
    recording, original = saved_recording()
    calls = []
    def transcribe(content, mime, language, **options):
        calls.append(options)
        assert mime == 'audio/wav' and options == {'diarize': True, 'allow_empty': True}
        if len(calls) == 2:
            raise providers.ProviderError('Temporary provider outage')
        return output()
    monkeypatch.setattr(providers, 'transcribe', transcribe)
    job = act('recording.transcribe', {'id': recording})
    with pytest.raises(providers.ProviderError):
        jobs.run_job(job['id'])
    state = job_state(job['id'])
    assert state['status'] == 'queued' and state['result']['completed_windows'] == 1
    # Simulate restart after the retry delay. The checkpoint is read from disk.
    with db.connection(True) as c:
        c.execute("UPDATE job_claims SET next_attempt='' WHERE job_id=?", (job['id'],))
    jobs.run_job(job['id'])
    jobs.run_job(job['id'])
    assert len(calls) == 4  # window 0 once, window 1 twice, window 2 once
    with db.connection() as c:
        r = db.get(c, recording)
        source = db.get(c, r['data']['transcript_source_id'])
        assert r['data']['duration'] == 5  # decoder, not untrusted browser duration
        assert db.get(c, 'consult-luna')['data']['source_ids'] == [source['id']]
    assert [u['start'] for u in source['data']['utterances']] == [0, 2, 4]
    assert [u['speaker'] for u in source['data']['utterances']] == ['1.0', '2.0', '3.0']
    assert len(source['data']['refinement_windows']) == 3
    assert TestClient(main.app).get('/api/recordings/' + recording + '/audio').content == original


def test_silent_window_is_checkpointed_without_losing_later_speech(monkeypatch):
    monkeypatch.setattr(audio_windows, 'WINDOW_SECONDS', 2)
    recording, _ = saved_recording()
    calls = []
    def transcribe(*args, **options):
        calls.append(options)
        assert options['diarize'] is False
        return output('' if len(calls) == 1 else 'Later speech.', None)
    monkeypatch.setattr(providers, 'transcribe', transcribe)
    job = act('recording.transcribe', {'id': recording, 'diarize': False})
    jobs.run_job(job['id'])
    with db.connection() as c:
        source = db.get(c, db.get(c, recording)['data']['transcript_source_id'])
    assert source['data']['utterances'][0]['start'] == 2
    assert all(u['speaker'] is None for u in source['data']['utterances'])
    assert len(source['data']['refinement_windows']) == 3


def test_failed_job_is_retried_in_place_and_does_not_charge_completed_windows(monkeypatch):
    recording, _ = saved_recording()
    calls = []
    monkeypatch.setattr(providers, 'transcribe', lambda *a, **k: calls.append(1) or output(''))
    job = act('recording.transcribe', {'id': recording})
    with pytest.raises(audio_windows.AudioValidationError, match='No speech'):
        jobs.run_job(job['id'])
    assert job_state(job['id'])['status'] == 'failed'
    assert act('recording.transcribe', {'id': recording})['id'] == job['id']
    act('job.retry', {'id': job['id']})
    with pytest.raises(audio_windows.AudioValidationError):
        jobs.run_job(job['id'])
    assert len(calls) == 1


def test_expired_worker_cannot_publish_a_window(monkeypatch):
    recording, _ = saved_recording()
    job = act('recording.transcribe', {'id': recording})
    def stale(*args, **kwargs):
        with db.connection(True) as c:
            c.execute("UPDATE job_claims SET token='new-worker' WHERE job_id=?", (job['id'],))
        return output()
    monkeypatch.setattr(providers, 'transcribe', stale)
    jobs.run_job(job['id'])
    assert job_state(job['id'])['result']['completed_windows'] == 0
    with db.connection() as c:
        assert not db.get(c, recording)['data'].get('transcript_source_id')


def test_revoked_member_cannot_publish_provider_output(monkeypatch):
    recording, _ = saved_recording()
    job = act('recording.transcribe', {'id': recording})
    def revoke(*args, **kwargs):
        with db.connection(True) as c:
            member = db.get(c, 'clinic-east-vet')
            db.update(c, member, {**member['data'], 'active': False})
        return output()
    monkeypatch.setattr(providers, 'transcribe', revoke)
    with pytest.raises(HTTPException):
        jobs.run_job(job['id'])
    assert job_state(job['id'])['status'] == 'failed'
    with db.connection() as c:
        assert not db.get(c, recording)['data'].get('transcript_source_id')


def test_bad_media_and_tampered_chunks_never_reach_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(providers, 'transcribe', lambda *a, **k: calls.append(1))
    recording, _ = saved_recording(b'#EXTM3U\nhttp://example.test/secret\n')
    job = act('recording.transcribe', {'id': recording})
    with pytest.raises(audio_windows.AudioValidationError, match='Unsupported audio'):
        jobs.run_job(job['id'])
    recording, _ = saved_recording()
    with db.connection(True) as c:
        c.execute("UPDATE chunks SET sha256='tampered' WHERE recording_id=?", (recording,))
    job = act('recording.transcribe', {'id': recording})
    with pytest.raises(audio_windows.AudioValidationError, match='checksum'):
        jobs.run_job(job['id'])
    assert not calls


def test_decoder_rejects_duration_limit_without_publishing_truncated_audio(monkeypatch):
    monkeypatch.setattr(audio_windows, 'MAX_SECONDS', 2)
    recording, _ = saved_recording()
    job = act('recording.transcribe', {'id': recording})
    with pytest.raises(audio_windows.AudioValidationError, match='four hours'):
        jobs.run_job(job['id'])
    with db.connection() as c:
        assert not db.get(c, recording)['data'].get('transcript_source_id')


def test_provider_can_disable_speakers_and_accept_silent_windows(monkeypatch):
    import httpx
    monkeypatch.setenv('DEEPGRAM_API_KEY', 'test-only')
    real_client = httpx.Client
    def respond(request):
        assert request.url.params['diarize'] == 'false'
        return httpx.Response(200, json={'results': {'channels': [{'alternatives': [{'transcript': ''}]}], 'utterances': []}})
    monkeypatch.setattr(providers.httpx, 'Client', lambda **k: real_client(transport=httpx.MockTransport(respond)))
    assert providers.transcribe(b'test', 'audio/wav', diarize=False, allow_empty=True)['text'] == ''


def test_provider_timestamps_outside_the_window_are_rejected(monkeypatch):
    recording, _ = saved_recording()
    invalid = output()
    invalid['utterances'][0]['end'] = 100
    monkeypatch.setattr(providers, 'transcribe', lambda *a, **k: invalid)
    job = act('recording.transcribe', {'id': recording})
    with pytest.raises(providers.ProviderError, match='timestamps'):
        jobs.run_job(job['id'])
    assert job_state(job['id'])['result']['completed_windows'] == 0

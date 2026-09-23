"""Decode local recordings into bounded speech windows, preserving the original.

The media decoder never accepts a URL or a playlist. Temporary PCM is private,
bounded to four hours and removed even when a provider call fails.
"""
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import hashlib
import math
import subprocess
import tempfile
import wave

WINDOW_SECONDS = 25 * 60
MAX_SECONDS = 4 * 60 * 60
MAX_INPUT_BYTES = 512 * 1024 * 1024
SAMPLE_RATE = 16000


class AudioValidationError(Exception):
    pass


def media_format(header):
    if header.startswith(b'\x1aE\xdf\xa3'):
        return 'matroska'
    if header[:4] == b'RIFF' and header[8:12] == b'WAVE':
        return 'wav'
    if header[4:8] == b'ftyp':
        return 'mov'
    if header.startswith(b'OggS'):
        return 'ogg'
    if header.startswith(b'fLaC'):
        return 'flac'
    if header.startswith(b'ID3') or (len(header) > 1 and header[0] == 255 and header[1] & 0xe0 == 0xe0):
        return 'mp3'
    raise AudioValidationError('Unsupported audio. Use WebM, MP4, WAV, Ogg, FLAC or MP3; the original is preserved.')


class AudioWindows:
    def __init__(self, path, audio_hash):
        self.path = path
        self.audio_hash = audio_hash
        with wave.open(str(path), 'rb') as audio:
            self.frames = audio.getnframes()
        self.duration = self.frames / SAMPLE_RATE
        if not self.frames or self.duration > MAX_SECONDS:
            raise AudioValidationError('Choose a recording with audio lasting no more than four hours. The original is preserved.')
        self.count = math.ceil(self.frames / (WINDOW_SECONDS * SAMPLE_RATE))

    def bounds(self, index):
        if not 0 <= index < self.count:
            raise AudioValidationError('Invalid speech window')
        start = index * WINDOW_SECONDS
        return start, min(self.duration, start + WINDOW_SECONDS)

    def read(self, index):
        start, end = self.bounds(index)
        with wave.open(str(self.path), 'rb') as audio:
            audio.setpos(int(start * SAMPLE_RATE))
            pcm = audio.readframes(round((end - start) * SAMPLE_RATE))
        result = BytesIO()
        with wave.open(result, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(SAMPLE_RATE)
            audio.writeframes(pcm)
        return result.getvalue()


@contextmanager
def prepare(chunks):
    with tempfile.TemporaryDirectory(prefix='broby-speech-') as directory:
        original = Path(directory) / 'input.audio'
        decoded = Path(directory) / 'decoded.wav'
        total = 0
        combined = hashlib.sha256()
        with original.open('wb') as output:
            for chunk in chunks:
                digest = hashlib.sha256()
                with Path(chunk['path']).open('rb') as source:
                    while part := source.read(1024 * 1024):
                        total += len(part)
                        if total > MAX_INPUT_BYTES:
                            raise AudioValidationError('Recording exceeds the 512 MB processing limit. The original is preserved.')
                        digest.update(part)
                        combined.update(part)
                        output.write(part)
                if digest.hexdigest() != chunk['sha256']:
                    raise AudioValidationError('Audio checksum mismatch. The original needs to be recovered before transcription.')
        original.chmod(0o600)
        with original.open('rb') as source:
            demuxer = media_format(source.read(16))
        try:
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror',
                            '-protocol_whitelist', 'file,pipe', '-f', demuxer,
                            '-i', str(original), '-map', '0:a:0', '-vn', '-sn', '-dn',
                            '-t', str(MAX_SECONDS + 1), '-ac', '1', '-ar', str(SAMPLE_RATE),
                            '-c:a', 'pcm_s16le', str(decoded)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        except FileNotFoundError as exc:
            raise AudioValidationError('Audio processing is unavailable; install FFmpeg on the backend. The original is preserved.') from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise AudioValidationError('Audio could not be decoded within the processing limit. The original is preserved.') from exc
        decoded.chmod(0o600)
        yield AudioWindows(decoded, combined.hexdigest())

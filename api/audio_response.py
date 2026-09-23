"""Byte ranges allow browsers to seek in approved recorded audio."""
import re
from fastapi import Response


def audio_response(content, mime, range_header=None):
    size = len(content)
    headers = {'Accept-Ranges': 'bytes'}
    if not range_header:
        return Response(content, media_type=mime, headers=headers)
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header.strip())
    if not match or not any(match.groups()) or not size:
        return Response(status_code=416, headers={**headers, 'Content-Range': f'bytes */{size}'})
    first, last = match.groups()
    start = int(first) if first else max(0, size - int(last))
    end = min(int(last), size - 1) if first and last else size - 1
    if start > end or start >= size:
        return Response(status_code=416, headers={**headers, 'Content-Range': f'bytes */{size}'})
    return Response(content[start:end + 1], status_code=206, media_type=mime,
                    headers={**headers, 'Content-Range': f'bytes {start}-{end}/{size}'})

"""Value-preserving backup receipts, independent of SQL collation and row order."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_inventory(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink(): raise ValueError('Backup data must be an existing directory, not a link')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ValueError('Backup data must not contain symbolic links')
        if path.is_file(): result[str(path.relative_to(root))] = {'bytes': path.stat().st_size, 'sha256': sha256(path)}
    return result


def database_inventory(connection):
    tables = connection.execute(text("SELECT table_schema,table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN ('information_schema','pg_catalog') AND table_schema NOT LIKE 'pg_%' ORDER BY table_schema,table_name")).all()
    quote = connection.dialect.identifier_preparer.quote
    result = {}
    for schema, name in tables:
        qualified = quote(schema) + '.' + quote(name)
        query = connection.exec_driver_sql('SELECT * FROM ' + qualified)
        columns = list(query.keys())
        hashes = []
        for row in query:
            encoded = json.dumps(list(row), sort_keys=True, default=str, ensure_ascii=False, separators=(',', ':')).encode()
            hashes.append(hashlib.sha256(encoded).digest())
        result[schema + '.' + name] = {'columns': columns, 'rows': len(hashes), 'sha256': hashlib.sha256(b''.join(sorted(hashes))).hexdigest()}
    return result


def binary_receipts(rows, chunks, data):
    """Verify every indexed attachment/chunk against its database receipt."""
    count = 0
    for id, raw in rows:
        entry = json.loads(raw) if isinstance(raw, str) else raw
        if not id or Path(id).name != id: raise ValueError('Invalid attachment identifier in backup')
        if sha256(Path(data) / 'files' / id) != entry['sha256']: raise ValueError('Attachment content does not match its saved receipt')
        count += 1
    for recording, index, digest in chunks:
        if not recording or Path(recording).name != recording or not isinstance(index, int) or index < 0:
            raise ValueError('Invalid audio chunk identifier in backup')
        if sha256(Path(data) / 'audio' / recording / str(index)) != digest: raise ValueError('Audio content does not match its saved receipt')
        count += 1
    return count

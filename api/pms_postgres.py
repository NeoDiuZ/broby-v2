"""PostgreSQL PMS connection boundary; SQL dialect choices stay explicit.

Existing application transactions use DB-API question-mark parameters and rows
addressable by name or position. Only parameter syntax is adapted here: values
are always sent separately to psycopg. Schema/upsert/JSON differences are handled
by named helpers, never by rewriting arbitrary SQL into a guessed equivalent.
"""
import os,re
from functools import lru_cache
from sqlalchemy import create_engine
from psycopg.rows import dict_row
from psycopg.pq import TransactionStatus


def schema():
    value=os.getenv('BROBY_PMS_SCHEMA','broby_pms')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',value):
        raise ValueError('BROBY_PMS_SCHEMA must be a simple lowercase schema name')
    return value


def url():
    value=os.getenv('BROBY_PMS_URL') or os.getenv('BROBY_SPINE_URL','')
    if value.startswith('postgresql://'):value=value.replace('postgresql://','postgresql+psycopg://',1)
    elif value.startswith('postgres://'):value=value.replace('postgres://','postgresql+psycopg://',1)
    if not value.startswith('postgresql+psycopg://'):
        raise ValueError('PostgreSQL PMS requires a PostgreSQL connection URL')
    return value


@lru_cache(maxsize=8)
def pool(connection_url, namespace):
    return create_engine(connection_url,pool_pre_ping=True,pool_size=8,max_overflow=8,
                         pool_timeout=20,connect_args={'options':'-csearch_path='+namespace})


def parameters(query):
    """Convert bind markers without touching quoted literals or identifiers."""
    result=[];quote=None;i=0
    while i<len(query):
        char=query[i]
        if char=='%':result.append('%%')
        elif quote:
            result.append(char)
            if char==quote:
                if i+1<len(query) and query[i+1]==quote:
                    result.append(query[i+1]);i+=1
                else:quote=None
        elif char in ("'",'"'):
            quote=char;result.append(char)
        elif char=='?':result.append('%s')
        else:result.append(char)
        i+=1
    return ''.join(result)


class Row(dict):
    def __getitem__(self,key):
        return tuple(self.values())[key] if isinstance(key,(int,slice)) else super().__getitem__(key)
    def __iter__(self):return iter(self.values())


class Result:
    def __init__(self,cursor):self.cursor=cursor
    @property
    def rowcount(self):return self.cursor.rowcount
    def fetchone(self):
        value=self.cursor.fetchone()
        return Row(value) if value is not None else None
    def fetchall(self):return [Row(value) for value in self.cursor.fetchall()]
    def __iter__(self):return (Row(value) for value in self.cursor)


class Connection:
    dialect='postgres'
    def __init__(self):
        self.pooled=pool(url(),schema()).raw_connection()
        self.raw=self.pooled.driver_connection
        self.rollback_files=[]
    @property
    def in_transaction(self):return self.raw.info.transaction_status!=TransactionStatus.IDLE
    def execute(self,query,values=()):
        cursor=self.raw.cursor(row_factory=dict_row)
        cursor.execute(parameters(query) if values else query,tuple(values) if values else None)
        return Result(cursor)
    def executemany(self,query,values):
        cursor=self.raw.cursor(row_factory=dict_row)
        cursor.executemany(parameters(query),values)
        return Result(cursor)
    def executescript(self,query):
        self.raw.execute(query)
    def begin(self,write,*,snapshot=False):
        self.raw.execute('BEGIN ISOLATION LEVEL REPEATABLE READ' if snapshot and not write else 'BEGIN')
        self.raw.execute("SET LOCAL lock_timeout='20s'")
        self.raw.execute("SET LOCAL statement_timeout='60s'")
        if write:
            # Preserve the application's serial writer invariant during the
            # storage transition. This is deliberately not a throughput claim.
            self.raw.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('broby-pms-writer:'+schema(),))
    def commit(self):self.pooled.commit()
    def rollback(self):self.pooled.rollback()
    def close(self):
        self.pooled.rollback()
        self.pooled.close()


def create_schema():
    # The identifier is validated above; it never comes from a request payload.
    with pool(url(),schema()).begin() as c:
        c.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS '+schema())


def history(c):
    c.executescript('''
    CREATE OR REPLACE FUNCTION save_record_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      INSERT INTO record_versions VALUES(OLD.id,OLD.version,OLD.clinic_id,OLD.kind,OLD.data,OLD.updated_at)
        ON CONFLICT DO NOTHING;
      RETURN NEW;
    END;
    $$;
    CREATE OR REPLACE TRIGGER record_history BEFORE UPDATE ON records
      FOR EACH ROW EXECUTE FUNCTION save_record_history();
    ''')


def projection_queue(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS spine_changes(sequence BIGSERIAL PRIMARY KEY,clinic_id TEXT);
    CREATE OR REPLACE FUNCTION enqueue_spine_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN
        INSERT INTO spine_changes(clinic_id) VALUES(OLD.clinic_id);
        RETURN OLD;
      END IF;
      INSERT INTO spine_changes(clinic_id) VALUES(NEW.clinic_id);
      RETURN NEW;
    END;
    $$;
    CREATE OR REPLACE TRIGGER spine_records AFTER INSERT OR UPDATE ON records
      FOR EACH ROW EXECUTE FUNCTION enqueue_spine_change();
    CREATE OR REPLACE TRIGGER spine_memberships AFTER INSERT OR UPDATE OR DELETE ON auth_memberships
      FOR EACH ROW EXECUTE FUNCTION enqueue_spine_change();
    ''')

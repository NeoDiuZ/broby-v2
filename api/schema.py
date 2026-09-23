"""Additive, repeatable migrations for existing preview databases."""
import json
DEFINITIONS=[
 ('weight','Weight','number','kg','Vitals'),('temperature','Temperature','number','°C','Vitals'),
 ('heart_rate','Heart rate','number','bpm','Vitals'),('creatinine','Creatinine','number','mg/dL','Bloods'),
 ('haematocrit','Haematocrit','number','%','Bloods'),('cytology_finding','Cytology finding','text','','Cytology'),
 ('imaging_finding','Recorded imaging finding','text','','X-ray'),('appetite','Appetite','text','','Clinical'),
]
def migrate(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS job_claims(job_id TEXT PRIMARY KEY,token TEXT,lease_until TEXT,attempts INTEGER DEFAULT 0,next_attempt TEXT DEFAULT '',last_error TEXT);
    CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS record_versions(record_id TEXT,version INTEGER,clinic_id TEXT,kind TEXT,data TEXT,recorded_at TEXT,PRIMARY KEY(record_id,version));
    CREATE TRIGGER IF NOT EXISTS record_history BEFORE UPDATE ON records BEGIN
      INSERT OR IGNORE INTO record_versions VALUES(OLD.id,OLD.version,OLD.clinic_id,OLD.kind,OLD.data,OLD.updated_at);
    END;
    CREATE TABLE IF NOT EXISTS ontology(code TEXT PRIMARY KEY,name TEXT,value_type TEXT,unit TEXT,category TEXT);
    CREATE TABLE IF NOT EXISTS owner_claims(token_hash TEXT PRIMARY KEY,grant_token TEXT,expires_at TEXT);
    CREATE TABLE IF NOT EXISTS saved_pets(vault_hash TEXT,grant_token TEXT,expires_at TEXT,PRIMARY KEY(vault_hash,grant_token));
    CREATE TABLE IF NOT EXISTS grant_parents(token TEXT PRIMARY KEY,parent_token TEXT);
    CREATE TABLE IF NOT EXISTS credentials(username TEXT PRIMARY KEY,member_id TEXT NOT NULL,clinic_id TEXT NOT NULL,salt TEXT,password_hash TEXT);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,username TEXT,expires_at TEXT);
    CREATE TABLE IF NOT EXISTS login_attempts(address TEXT PRIMARY KEY,failures INTEGER,blocked_until TEXT);
    INSERT OR IGNORE INTO schema_migrations(version) VALUES(1);
    ''')
    c.executemany('INSERT OR IGNORE INTO ontology VALUES(?,?,?,?,?)',DEFINITIONS)
    from accounts import setup
    setup(c)
    from integration_hooks import setup as setup_hooks
    setup_hooks(c)
    from organizations import setup as setup_organizations
    setup_organizations(c)
    from transfers import setup as setup_transfers
    setup_transfers(c)
    from stripe_payments import setup as setup_stripe
    setup_stripe(c)

    from assistant_history import setup as setup_assistant
    setup_assistant(c)

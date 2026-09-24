"""Equivalent database-enforced failure injection for both supported stores."""
import db

def reject_transfer_audit(c,name,message):
    name=db.identifier(name);literal="'"+message.replace("'","''")+"'"
    if c.dialect=='sqlite':
        c.execute(f"CREATE TRIGGER {name} BEFORE INSERT ON audit WHEN NEW.action='transfer.accept' BEGIN SELECT RAISE(ABORT,{literal}); END")
    else:
        c.executescript(f'''CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.action='transfer.accept' THEN RAISE EXCEPTION {literal}; END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER {name} BEFORE INSERT ON audit FOR EACH ROW EXECUTE FUNCTION {name}();''')

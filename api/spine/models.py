"""Normalized first-build spine; no AI dependencies."""
from datetime import datetime,date
from sqlalchemy import String,DateTime,Date,Float,Integer,ForeignKey,UniqueConstraint,Index,JSON,Boolean,Text,CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
class Base(DeclarativeBase):pass
J=JSON().with_variant(JSONB,'postgresql')
class Clinic(Base):
    __tablename__='clinics'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    name:Mapped[str]=mapped_column(String)
class Person(Base):
    __tablename__='people'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    name:Mapped[str]=mapped_column(String)
class Member(Base):
    __tablename__='clinic_members'
    person_id:Mapped[str]=mapped_column(ForeignKey('people.id'),primary_key=True)
    clinic_id:Mapped[str]=mapped_column(ForeignKey('clinics.id'),primary_key=True)
    role:Mapped[str]=mapped_column(String)
    active:Mapped[bool]=mapped_column(default=True)
class Owner(Base):
    __tablename__='owners'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    clinic_id:Mapped[str]=mapped_column(ForeignKey('clinics.id'),index=True)
    name:Mapped[str]=mapped_column(String)
    phone:Mapped[str]=mapped_column(String,default='')
    email:Mapped[str]=mapped_column(String,default='')
class Patient(Base):
    __tablename__='patients'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    clinic_id:Mapped[str]=mapped_column(ForeignKey('clinics.id'),index=True)
    name:Mapped[str]=mapped_column(String)
    species:Mapped[str]=mapped_column(String)
    breed:Mapped[str]=mapped_column(String,default='')
    sex:Mapped[str]=mapped_column(String,default='Unknown')
    date_of_birth:Mapped[date|None]=mapped_column(Date)
    __table_args__=(Index('patients_order','clinic_id','name','id'),)
class OwnerPatient(Base):
    __tablename__='owner_patients'
    owner_id:Mapped[str]=mapped_column(ForeignKey('owners.id'),primary_key=True)
    patient_id:Mapped[str]=mapped_column(ForeignKey('patients.id'),primary_key=True)
    is_primary:Mapped[bool]=mapped_column(default=False)
class Source(Base):
    __tablename__='sources'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    clinic_id:Mapped[str]=mapped_column(ForeignKey('clinics.id'),index=True)
    patient_id:Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True)
    kind:Mapped[str]=mapped_column(String)
    reference_id:Mapped[str]=mapped_column(String)
    page:Mapped[int|None]=mapped_column(Integer)
    start_ms:Mapped[int|None]=mapped_column(Integer)
    end_ms:Mapped[int|None]=mapped_column(Integer)
    content:Mapped[dict]=mapped_column(J,default=dict)
class Event(Base):
    __tablename__='events'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    clinic_id:Mapped[str]=mapped_column(ForeignKey('clinics.id'),index=True)
    patient_id:Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True)
    event_type:Mapped[str]=mapped_column(String)
    occurred_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    summary:Mapped[str]=mapped_column(String)
    actor:Mapped[dict]=mapped_column(J)
    source_id:Mapped[str|None]=mapped_column(ForeignKey('sources.id'))
    body:Mapped[dict]=mapped_column(J,default=dict)
    dedupe_key:Mapped[str]=mapped_column(String)
    payload_hash:Mapped[str]=mapped_column(String)
    __table_args__=(UniqueConstraint('clinic_id','dedupe_key',name='uq_event_dedupe'),Index('events_timeline','clinic_id','patient_id','occurred_at','id'))
class Concept(Base):
    __tablename__='concepts'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    name:Mapped[str]=mapped_column(String)
    code:Mapped[str]=mapped_column(String,index=True)
    unit:Mapped[str]=mapped_column(String)
    value_type:Mapped[str]=mapped_column(String,default='number')
    __table_args__=(UniqueConstraint('code','unit',name='uq_concept_unit'),)
class Observation(Base):
    __tablename__='observations'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    event_id:Mapped[str]=mapped_column(ForeignKey('events.id'),index=True)
    concept_id:Mapped[str]=mapped_column(ForeignKey('concepts.id'),index=True)
    observed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    value:Mapped[float|None]=mapped_column(Float)
    value_type:Mapped[str]=mapped_column(String,default='number')
    text_value:Mapped[str|None]=mapped_column(Text)
    boolean_value:Mapped[bool|None]=mapped_column(Boolean)
    ref_low:Mapped[float|None]=mapped_column(Float)
    ref_high:Mapped[float|None]=mapped_column(Float)
    source_id:Mapped[str|None]=mapped_column(ForeignKey('sources.id'))
    __table_args__=(CheckConstraint("(value_type = 'number' AND value IS NOT NULL AND text_value IS NULL AND boolean_value IS NULL) OR (value_type = 'text' AND value IS NULL AND text_value IS NOT NULL AND boolean_value IS NULL AND ref_low IS NULL AND ref_high IS NULL) OR (value_type = 'boolean' AND value IS NULL AND text_value IS NULL AND boolean_value IS NOT NULL AND ref_low IS NULL AND ref_high IS NULL)",name='ck_observation_type'),)
class Projection(Base):
    __tablename__='projection_checkpoints'
    name:Mapped[str]=mapped_column(String,primary_key=True)
    sequence:Mapped[int]=mapped_column(Integer,default=0)

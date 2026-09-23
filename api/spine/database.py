import os
from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
@lru_cache
def engine():
    url=os.getenv('BROBY_SPINE_URL')
    if not url:raise RuntimeError('BROBY_SPINE_URL must name the PostgreSQL spine database')
    if url.startswith('postgresql://'):url=url.replace('postgresql://','postgresql+psycopg://',1)
    elif url.startswith('postgres://'):url=url.replace('postgres://','postgresql+psycopg://',1)
    return create_engine(url,pool_pre_ping=True)
def session():return Session(engine())

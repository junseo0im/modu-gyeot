from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from gyeot.config import load_config
from gyeot.db import Store


@pytest.fixture
def store():
    # Real PostgreSQL, isolated schema; never truncate application tables.
    base = load_config().database_url
    schema = 'test_' + uuid4().hex
    with psycopg.connect(base) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

    class IsolatedStore(Store):
        def connect(self):
            conn = super().connect()
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            return conn

    instance = IsolatedStore(base)
    instance.migrate()
    try:
        yield instance
    finally:
        with psycopg.connect(base) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
"""Фикстуры для интеграционных тестов.

Стратегия изоляции: для каждого теста создаём пару временных схем
(test_src_<uuid> в source-БД, test_tgt_<uuid> в target-БД), наполняем их
тестовыми объектами, прогоняем compare->generate->apply, в teardown'е делаем
DROP SCHEMA ... CASCADE.

Так мы:
  - не трогаем боевые public.* (init.sql пользователя),
  - не зависим от docker reset-скрипта,
  - получаем чистый, повторяемый стенд за миллисекунды.

Если БД недоступны, все интеграционные тесты пропускаются.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SOURCE_URL = os.environ.get(
    "TEST_SOURCE_URL",
    "postgresql+psycopg://source_user:source_password@localhost:5433/source_db",
)
TARGET_URL = os.environ.get(
    "TEST_TARGET_URL",
    "postgresql+psycopg://target_user:target_password@localhost:5434/target_db",
)


def _try_engine(url: str) -> Engine | None:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except OperationalError:
        return None
    except Exception:
        return None


@pytest.fixture(scope="session")
def source_engine() -> Engine:
    engine = _try_engine(SOURCE_URL)
    if engine is None:
        pytest.skip(f"Source DB не доступна по {SOURCE_URL}")
    return engine


@pytest.fixture(scope="session")
def target_engine() -> Engine:
    engine = _try_engine(TARGET_URL)
    if engine is None:
        pytest.skip(f"Target DB не доступна по {TARGET_URL}")
    return engine


@pytest.fixture()
def temp_schemas(source_engine: Engine, target_engine: Engine):
    suffix = uuid.uuid4().hex[:8]
    src = f"test_src_{suffix}"
    tgt = f"test_tgt_{suffix}"
    # Создаём чистые схемы. AUTOCOMMIT, потому что CREATE SCHEMA в обычной
    # транзакции тоже работает, но проще иметь явный контроль.
    for engine, schema in [(source_engine, src), (target_engine, tgt)]:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield src, tgt
    finally:
        # CASCADE гарантирует, что объекты в схеме (таблицы, sequences, FK)
        # уходят вместе с ней. Это и есть "откат" наших тестовых правок.
        for engine, schema in [(source_engine, src), (target_engine, tgt)]:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

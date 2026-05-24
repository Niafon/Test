"""End-to-end интеграционные тесты.

Прогоняем полный конвейер: реальная БД -> introspection -> compare -> classify ->
generate_sql -> apply -> снова introspection. Все объекты создаются во временных
схемах (см. conftest.py), поэтому существующие public.* данные не трогаются.
"""
from sqlalchemy import Engine, text

from apply import apply_sql_text
from compare_database import compare_databases
from introspection import get_columns, get_tables
from plan import classify_changes
from sql_generator import generate_sql


def _exec(engine: Engine, statements: list[str]) -> None:
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def test_safe_apply_adds_missing_table_and_preserves_target_data(
    source_engine, target_engine, temp_schemas
):
    src, tgt = temp_schemas
    # source: две таблицы. target: только users (с реальными данными).
    _exec(
        source_engine,
        [
            f'CREATE TABLE "{src}".users (id BIGINT PRIMARY KEY, email VARCHAR(255))',
            f'CREATE TABLE "{src}".products (id BIGINT PRIMARY KEY, name VARCHAR(100) NOT NULL)',
        ],
    )
    _exec(
        target_engine,
        [
            f'CREATE TABLE "{tgt}".users (id BIGINT PRIMARY KEY, email VARCHAR(255))',
            f"INSERT INTO \"{tgt}\".users (id, email) VALUES (1, 'a@b.c'), (2, 'x@y.z')",
        ],
    )

    changes = compare_databases(
        source_engine, target_engine, source_schema=src, target_schema=tgt
    )
    plan = classify_changes(changes)
    assert any(c["kind"] == "missing_table" and c["table"] == "products" for c in plan["safe"])

    sql = generate_sql(plan["safe"], mode="safe")
    result = apply_sql_text(target_engine, sql)
    assert result["status"] == "ok", result

    # products появилась, users.email и существующие данные не пострадали.
    tables_after = set(get_tables(target_engine, schema=tgt))
    assert "products" in tables_after
    assert "users" in tables_after
    with target_engine.connect() as conn:
        rows = conn.execute(text(f'SELECT COUNT(*) FROM "{tgt}".users')).scalar()
    assert rows == 2


def test_safe_does_not_drop_extra_table_in_target(
    source_engine, target_engine, temp_schemas
):
    src, tgt = temp_schemas
    _exec(source_engine, [f'CREATE TABLE "{src}".users (id BIGINT PRIMARY KEY)'])
    _exec(
        target_engine,
        [
            f'CREATE TABLE "{tgt}".users (id BIGINT PRIMARY KEY)',
            f'CREATE TABLE "{tgt}".legacy_notes (id BIGINT PRIMARY KEY, note TEXT)',
            f"INSERT INTO \"{tgt}\".legacy_notes (id, note) VALUES (1, 'keep me')",
        ],
    )

    plan = classify_changes(
        compare_databases(
            source_engine, target_engine, source_schema=src, target_schema=tgt
        )
    )
    assert any(c["kind"] == "extra_table" and c["table"] == "legacy_notes" for c in plan["destructive"])

    # В safe-режиме все destructive операции закомментированы - в SQL не должно
    # быть исполняемого DROP TABLE для legacy_notes.
    safe_sql = generate_sql(plan["safe"], mode="safe")
    assert "DROP TABLE" not in safe_sql

    # Применяем safe (на самом деле тут нечего применять, но проверим что таблица жива).
    apply_result = apply_sql_text(target_engine, safe_sql)
    assert apply_result["status"] == "ok"
    with target_engine.connect() as conn:
        rows = conn.execute(text(f'SELECT COUNT(*) FROM "{tgt}".legacy_notes')).scalar()
    assert rows == 1


def test_missing_nullable_column_is_added_without_data_loss(
    source_engine, target_engine, temp_schemas
):
    src, tgt = temp_schemas
    _exec(
        source_engine,
        [
            f'CREATE TABLE "{src}".users '
            f'(id BIGINT PRIMARY KEY, email VARCHAR(255), nickname VARCHAR(50))'
        ],
    )
    _exec(
        target_engine,
        [
            f'CREATE TABLE "{tgt}".users (id BIGINT PRIMARY KEY, email VARCHAR(255))',
            f"INSERT INTO \"{tgt}\".users VALUES (1, 'a@b.c'), (2, 'x@y.z')",
        ],
    )

    plan = classify_changes(
        compare_databases(
            source_engine, target_engine, source_schema=src, target_schema=tgt
        )
    )
    assert any(
        c["kind"] == "missing_column" and c["column"] == "nickname"
        for c in plan["safe"]
    )

    sql = generate_sql(plan["safe"], mode="safe")
    result = apply_sql_text(target_engine, sql)
    assert result["status"] == "ok"

    columns = {c["name"] for c in get_columns(target_engine, "users", schema=tgt)}
    assert "nickname" in columns
    # Данные не пострадали - 2 строки, nickname NULL у обеих.
    with target_engine.connect() as conn:
        rows = conn.execute(
            text(f'SELECT id, email, nickname FROM "{tgt}".users ORDER BY id')
        ).fetchall()
    assert len(rows) == 2
    assert rows[0].email == "a@b.c"
    assert rows[0].nickname is None


def test_string_default_is_quoted_and_does_not_break_sql(
    source_engine, target_engine, temp_schemas
):
    """Регрессия: до фикса format_default строковый дефолт без кавычек
    ломал ALTER TABLE. Сейчас format_default цитирует bare-строки."""
    src, tgt = temp_schemas
    _exec(
        source_engine,
        [
            f'CREATE TABLE "{src}".items '
            f'(id BIGINT PRIMARY KEY, status VARCHAR(32) NOT NULL DEFAULT \'active\')'
        ],
    )
    _exec(
        target_engine,
        [f'CREATE TABLE "{tgt}".items (id BIGINT PRIMARY KEY)'],
    )

    plan = classify_changes(
        compare_databases(
            source_engine, target_engine, source_schema=src, target_schema=tgt
        )
    )
    sql = generate_sql(plan["safe"], mode="safe")
    # Должна попасть закавыченная литерал-строка, а не голое active.
    assert "DEFAULT 'active'" in sql or "DEFAULT 'active'::" in sql

    result = apply_sql_text(target_engine, sql)
    assert result["status"] == "ok", result

    cols = {c["name"]: c for c in get_columns(target_engine, "items", schema=tgt)}
    assert "status" in cols
    with target_engine.begin() as conn:
        conn.execute(text(f'INSERT INTO "{tgt}".items (id) VALUES (1)'))
        status = conn.execute(text(f'SELECT status FROM "{tgt}".items WHERE id = 1')).scalar()
    assert status == "active"


def test_cyclic_foreign_keys_create_tables_then_alter(
    source_engine, target_engine, temp_schemas
):
    """Цикл A.b_id->B, B.a_id->A. Inline FK сломали бы CREATE TABLE, deferred FK
    через ALTER TABLE отрабатывают за счёт того, что обе таблицы уже созданы."""
    src, tgt = temp_schemas
    _exec(
        source_engine,
        [
            f'CREATE TABLE "{src}".a (id BIGINT PRIMARY KEY, b_id BIGINT)',
            f'CREATE TABLE "{src}".b (id BIGINT PRIMARY KEY, a_id BIGINT)',
            f'ALTER TABLE "{src}".a ADD CONSTRAINT a_b_id_fk FOREIGN KEY (b_id) REFERENCES "{src}".b(id)',
            f'ALTER TABLE "{src}".b ADD CONSTRAINT b_a_id_fk FOREIGN KEY (a_id) REFERENCES "{src}".a(id)',
        ],
    )
    # target пустой - ожидаем full sync.
    plan = classify_changes(
        compare_databases(
            source_engine, target_engine, source_schema=src, target_schema=tgt
        )
    )
    safe = plan["safe"] + plan["risky"]
    sql = generate_sql(safe, mode="risky")
    # CREATE TABLE без inline FK, FK идут позже как ALTER TABLE.
    assert sql.index("CREATE TABLE") < sql.index("ADD CONSTRAINT")
    result = apply_sql_text(target_engine, sql)
    assert result["status"] == "ok", result

    tables = set(get_tables(target_engine, schema=tgt))
    assert {"a", "b"}.issubset(tables)


def test_alter_column_type_uses_using_for_compatible_widening(
    source_engine, target_engine, temp_schemas
):
    """ALTER TYPE с USING - PG может расширить INTEGER->BIGINT и без USING,
    но с USING это работает и на реальных строках. Тест проверяет, что данные
    не теряются и тип реально меняется."""
    src, tgt = temp_schemas
    _exec(
        source_engine,
        [f'CREATE TABLE "{src}".m (id BIGINT PRIMARY KEY, qty BIGINT NOT NULL)'],
    )
    _exec(
        target_engine,
        [
            f'CREATE TABLE "{tgt}".m (id BIGINT PRIMARY KEY, qty INTEGER NOT NULL)',
            f'INSERT INTO "{tgt}".m (id, qty) VALUES (1, 100), (2, 200)',
        ],
    )
    plan = classify_changes(
        compare_databases(
            source_engine, target_engine, source_schema=src, target_schema=tgt
        )
    )
    sql = generate_sql(plan["safe"], mode="safe")
    assert "USING" in sql

    result = apply_sql_text(target_engine, sql)
    assert result["status"] == "ok", result

    cols = {c["name"]: c for c in get_columns(target_engine, "m", schema=tgt)}
    assert str(cols["qty"]["type"]).upper().startswith("BIGINT")
    with target_engine.connect() as conn:
        rows = conn.execute(text(f'SELECT qty FROM "{tgt}".m ORDER BY id')).fetchall()
    assert [r.qty for r in rows] == [100, 200]


def test_post_apply_diff_is_empty_after_full_sync(
    source_engine, target_engine, temp_schemas
):
    """После apply всех бакетов diff должен сходиться к нулю по структуре."""
    src, tgt = temp_schemas
    _exec(
        source_engine,
        [
            f'CREATE TABLE "{src}".users (id BIGINT PRIMARY KEY, email VARCHAR(255))',
            f'CREATE TABLE "{src}".orders (id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL, '
            f'CONSTRAINT fk_o_u FOREIGN KEY (user_id) REFERENCES "{src}".users(id))',
            f'CREATE INDEX idx_orders_user ON "{src}".orders(user_id)',
        ],
    )
    _exec(
        target_engine,
        [f'CREATE TABLE "{tgt}".users (id BIGINT PRIMARY KEY)'],
    )

    plan = classify_changes(
        compare_databases(
            source_engine, target_engine, source_schema=src, target_schema=tgt
        )
    )
    all_changes = plan["safe"] + plan["risky"]
    sql = generate_sql(all_changes, mode="risky")
    result = apply_sql_text(target_engine, sql)
    assert result["status"] == "ok", result

    leftover = compare_databases(
        source_engine, target_engine, source_schema=src, target_schema=tgt
    )
    leftover_kinds = [c["kind"] for c in leftover]
    # Любые оставшиеся изменения должны быть только destructive (extra_* в target),
    # которые мы намеренно не применяли. Тут их быть не должно - target создавали мы.
    assert not any(k.startswith("missing_") or k.startswith("different_") for k in leftover_kinds), leftover_kinds

"""Unit-тесты apply.py с моком Engine - проверяем парсер SQL и поведение rollback'а.

apply_sql_text открывает соединение и транзакцию через SQLAlchemy Engine. Чтобы
не поднимать БД, подменяем Engine минимальным фейком, который сохраняет порядок
вызовов и умеет имитировать падение конкретного statement-а.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from apply import apply_sql_text, save_apply_result, split_sql_statements


def test_split_sql_statements_skips_comments_and_keeps_dollar_blocks():
    sql = """
    -- comment line
    CREATE TABLE x (id INT);
    /* multi
       line */
    DO $$
    BEGIN
        RAISE NOTICE 'with ; inside';
    END $$;
    INSERT INTO x VALUES (1);
    """
    statements = split_sql_statements(sql)
    assert len(statements) == 3
    # split сохраняет ведущие комментарии перед statement-ом - они уезжают в БД,
    # PG их просто пропустит. Главное - DDL/DML находится в правильном statement.
    assert "CREATE TABLE x (id INT)" in statements[0]
    assert "DO $$" in statements[1]
    assert "RAISE NOTICE 'with ; inside'" in statements[1]
    assert "INSERT INTO x VALUES (1)" in statements[2]


def test_split_sql_handles_quoted_semicolons():
    sql = "INSERT INTO t VALUES ('a;b'); INSERT INTO t VALUES ('c');"
    statements = split_sql_statements(sql)
    assert statements == [
        "INSERT INTO t VALUES ('a;b')",
        "INSERT INTO t VALUES ('c')",
    ]


def _make_fake_engine(fail_on: str | None = None):
    """Фейк Engine: запоминает выполненные statement-ы, при необходимости
    падает на запросе с указанной подстрокой и фиксирует commit/rollback."""
    state = {"executed": [], "committed": False, "rolled_back": False}

    transaction = MagicMock()
    transaction.commit = lambda: state.update(committed=True)
    transaction.rollback = lambda: state.update(rolled_back=True)

    conn = MagicMock()
    conn.begin.return_value = transaction

    def execute(clause):
        text_value = str(clause.text if hasattr(clause, "text") else clause)
        if fail_on and fail_on in text_value:
            raise RuntimeError(f"simulated failure on: {fail_on}")
        state["executed"].append(text_value)

    conn.execute.side_effect = execute

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    return engine, state


def test_apply_sql_text_commits_on_success():
    engine, state = _make_fake_engine()
    sql = "CREATE TABLE a (id INT); INSERT INTO a VALUES (1);"
    result = apply_sql_text(engine, sql)
    assert result["status"] == "ok"
    assert result["executed_count"] == 2
    assert state["committed"] is True
    assert state["rolled_back"] is False


def test_save_apply_result_rejects_path_traversal_in_report_id():
    """report_id попадает в имя файла -> '..' или '/' могут вытащить запись
    наружу REPORTS_DIR. Валидация формата должна это блокировать."""
    for bad_id in (
        "../etc/passwd",
        "/abs/path",
        "20240101T120000_safe/..",
        "20240101T120000_invalidmode",
        "20240101T120000",  # без суффикса
        "",
    ):
        with pytest.raises(ValueError, match="invalid report_id"):
            save_apply_result(bad_id, {"status": "ok"}, "postgresql://x")


def test_apply_sql_text_rolls_back_on_failure():
    engine, state = _make_fake_engine(fail_on="INSERT")
    sql = "CREATE TABLE a (id INT); INSERT INTO a VALUES (1); CREATE INDEX i ON a(id);"
    result = apply_sql_text(engine, sql)
    assert result["status"] == "error"
    assert result["executed_count"] == 1  # CREATE TABLE прошёл
    assert "INSERT" in result["failed_statement"]
    assert state["rolled_back"] is True
    assert state["committed"] is False

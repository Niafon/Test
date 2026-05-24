import re
from typing import Any, Literal


Mode = Literal["safe", "risky", "destructive"]
Change = dict[str, Any]

NEXTVAL_RE = re.compile(r"^nextval\('([^']+)'::regclass\)$")


def quote_ident(name: str | None) -> str:
    if name is None or name == "":
        raise ValueError("identifier cannot be empty")
    return '"' + name.replace('"', '""') + '"'


def quote_ident_list(names: list[str]) -> str:
    return ", ".join(quote_ident(name) for name in names)


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_SQL_EXPR_KEYWORDS = {
    "NULL",
    "TRUE",
    "FALSE",
    "CURRENT_DATE",
    "CURRENT_TIME",
    "CURRENT_TIMESTAMP",
    "LOCALTIME",
    "LOCALTIMESTAMP",
    "NOW()",
}


def format_default(value: Any) -> str:
    # SQLAlchemy reflection возвращает default в виде SQL-выражения для PG
    # ("'hello'::text", "nextval(...)", "42"), но не для всех диалектов это
    # гарантировано. Безопасный путь:
    #   - числа/булевы значения -> SQL литералы
    #   - строка, похожая на SQL-выражение (с (), ::, ключевое слово, кавычки) -> as-is
    #   - всё остальное -> quote_literal, чтобы непроверенный текст не сломал SQL.
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return quote_literal(str(value))
    stripped = value.strip()
    if not stripped:
        return quote_literal(value)
    upper = stripped.upper()
    if upper in _SQL_EXPR_KEYWORDS:
        return stripped
    if "(" in stripped or "::" in stripped:
        return stripped
    if stripped[0] in ("'", '"') and stripped[-1] in ("'", '"'):
        return stripped
    try:
        float(stripped)
        return stripped
    except ValueError:
        pass
    return quote_literal(value)


def qualified_name(name: str, schema: str | None = None) -> str:
    if schema:
        return f"{quote_ident(schema)}.{quote_ident(name)}"
    return quote_ident(name)


def table_name(change: Change) -> str:
    return qualified_name(change["table"], change.get("schema"))


def table_key(name: str, schema: str | None = None) -> tuple[str | None, str]:
    return (schema, name)


def constraint_name(name: str | None) -> str | None:
    return quote_ident(name) if name else None


def required_constraint_name(name: str | None, kind: str) -> str:
    quoted = constraint_name(name)
    if quoted is None:
        raise ValueError(f"{kind} constraint name is required to generate SQL")
    return quoted


def reference_table_name(fk: Change, fallback_schema: str | None = None) -> str:
    referred_table = fk.get("referred_table")
    if not referred_table:
        raise ValueError("foreign key referred_table is required to generate SQL")
    referred_schema = fk.get("referred_schema") or fallback_schema
    return qualified_name(referred_table, referred_schema)


def generate_sql(changes: list[Change], mode: Mode) -> str:
    lines: list[str] = []
    comment_destructive = mode != "destructive"

    lines.append("-- Generated database correction SQL")
    lines.append(f"-- Mode: {mode}")
    lines.append("-- Review this file before applying to production.")
    lines.append("")
    if mode == "risky":
        lines.append("-- WARNING: risky changes may fail on existing data.")
        lines.append("")

    if mode == "destructive":
        lines.append("-- WARNING: destructive changes may delete data or constraints.")
        lines.append("")

    deferred_fks: list[str] = []
    for change in order_changes(changes):
        lines.extend(
            change_to_sql(change, mode, comment_destructive=comment_destructive)
        )
        lines.append("")
        if change["kind"] == "missing_table":
            deferred_fks.extend(generate_create_table_fk_sql(change))

    if deferred_fks:
        lines.append("-- Foreign keys for newly created tables (deferred to break cycles).")
        for stmt in deferred_fks:
            lines.append(stmt)
            lines.append("")

    return "\n".join(lines)


def order_changes(changes: list[Change]) -> list[Change]:
    missing_tables = [change for change in changes if change["kind"] == "missing_table"]
    if not missing_tables:
        return changes

    sorted_missing_tables = sort_missing_tables(missing_tables)
    remaining = [change for change in changes if change["kind"] != "missing_table"]
    return remove_redundant_missing_indexes(sorted_missing_tables + remaining)


def remove_redundant_missing_indexes(changes: list[Change]) -> list[Change]:
    unique_keys = set()
    for change in changes:
        if change["kind"] != "missing_unique_constraint":
            continue
        unique = change.get("source") or {}
        unique_keys.add(
            (
                change.get("schema"),
                change.get("table"),
                tuple(unique.get("columns") or []),
            )
        )

    result: list[Change] = []
    for change in changes:
        if change["kind"] == "missing_index":
            index = change.get("source") or {}
            index_key = (
                change.get("schema"),
                change.get("table"),
                tuple(index.get("columns") or []),
            )
            if index.get("unique") and index_key in unique_keys:
                continue
        result.append(change)
    return result


def sort_missing_tables(changes: list[Change]) -> list[Change]:
    by_table = {
        table_key(change["table"], change.get("schema")): change for change in changes
    }
    ordered: list[Change] = []
    visiting: set[tuple[str | None, str]] = set()
    visited: set[tuple[str | None, str]] = set()

    def visit(change: Change) -> None:
        key = table_key(change["table"], change.get("schema"))
        if key in visited:
            return
        if key in visiting:
            return

        visiting.add(key)
        source = change.get("source") or {}
        for fk in source.get("foreign_keys") or []:
            ref_key = table_key(
                fk.get("referred_table"),
                fk.get("referred_schema") or change.get("schema"),
            )
            dependency = by_table.get(ref_key)
            if dependency:
                visit(dependency)
        visiting.remove(key)
        visited.add(key)
        ordered.append(change)

    for change in changes:
        visit(change)

    return ordered


def change_to_sql(
    change: Change,
    mode: Mode,
    comment_destructive: bool = True,
) -> list[str]:
    kind = change["kind"]

    if kind == "missing_table":
        return generate_create_table_sql(change)

    if kind == "missing_column":
        return generate_add_column_sql(change)

    if kind == "different_column_type":
        return generate_alter_column_type_sql(change)

    if kind == "different_column_nullable":
        return generate_alter_column_nullable_sql(change)

    if kind == "different_column_default":
        return generate_alter_column_default_sql(change)

    if kind == "missing_index":
        return generate_create_index_sql(change)

    if kind == "missing_unique_constraint":
        return generate_add_unique_constraint_sql(change)

    if kind == "missing_foreign_key":
        return generate_add_foreign_key_sql(change)

    if kind == "missing_check_constraint":
        return generate_add_check_constraint_sql(change)

    if kind == "extra_column":
        return maybe_comment(
            generate_drop_column_sql(change),
            mode=mode,
            comment_destructive=comment_destructive,
        )

    if kind == "extra_table":
        return maybe_comment(
            generate_drop_table_sql(change),
            mode=mode,
            comment_destructive=comment_destructive,
        )

    if kind == "extra_index":
        return maybe_comment(
            generate_drop_index_sql(change),
            mode=mode,
            comment_destructive=comment_destructive,
        )

    if kind == "extra_foreign_key":
        return maybe_comment(
            generate_drop_constraint_sql(change, source_key="target"),
            mode=mode,
            comment_destructive=comment_destructive,
        )

    if kind == "extra_unique_constraint":
        return maybe_comment(
            generate_drop_constraint_sql(change, source_key="target"),
            mode=mode,
            comment_destructive=comment_destructive,
        )

    if kind == "extra_check_constraint":
        return maybe_comment(
            generate_drop_constraint_sql(change, source_key="target"),
            mode=mode,
            comment_destructive=comment_destructive,
        )

    if kind == "different_primary_key":
        return maybe_comment(
            generate_primary_key_sql(change),
            mode=mode,
            comment_destructive=comment_destructive,
        )

    raise ValueError(f"unsupported change kind: {kind}")


def generate_create_table_sql(change: Change) -> list[str]:
    table = table_name(change)
    schema = change.get("schema")
    source = change.get("source") or {}

    columns = source.get("columns") or []
    pk = source.get("primary_key") or {}
    uniques = source.get("unique_constraints") or []
    checks = source.get("check_constraints") or []
    # foreign_keys намеренно НЕ берём здесь: они эмитятся как отдельный
    # ALTER TABLE через generate_create_table_fk_sql, чтобы циклические FK
    # между новыми таблицами не ломали CREATE TABLE.
    indexes = source.get("indexes") or []

    body: list[str] = []

    for col in columns:
        parts = [f"    {quote_ident(col['name'])} {col['type']}"]
        if not col.get("nullable", True):
            parts.append("NOT NULL")
        if col.get("default") is not None:
            parts.append(f"DEFAULT {format_default(col['default'])}")
        body.append(" ".join(parts))

    if pk.get("constrained_columns"):
        pk_cols = quote_ident_list(pk["constrained_columns"])
        pk_name = constraint_name(pk.get("name"))
        if pk_name:
            body.append(f"    CONSTRAINT {pk_name} PRIMARY KEY ({pk_cols})")
        else:
            body.append(f"    PRIMARY KEY ({pk_cols})")

    for u in uniques:
        cols = quote_ident_list(u.get("columns") or [])
        name = constraint_name(u.get("name"))
        if name:
            body.append(f"    CONSTRAINT {name} UNIQUE ({cols})")
        else:
            body.append(f"    UNIQUE ({cols})")

    for ch in checks:
        sqltext = ch.get("sqltext")
        name = constraint_name(ch.get("name"))
        if name:
            body.append(f"    CONSTRAINT {name} CHECK ({sqltext})")
        else:
            body.append(f"    CHECK ({sqltext})")

    lines: list[str] = generate_sequence_sql(source, fallback_schema=schema)
    lines.append(f"CREATE TABLE {table} (")
    lines.append(",\n".join(body))
    lines.append(");")

    for idx in indexes:
        idx_cols = list(idx.get("columns") or [])
        if idx_cols == list(pk.get("constrained_columns") or []):
            continue
        if any(idx_cols == list(u.get("columns") or []) for u in uniques):
            continue
        cols = quote_ident_list(idx_cols)
        unique = "UNIQUE " if idx.get("unique") else ""
        lines.append(
            f"CREATE {unique}INDEX {quote_ident(idx['name'])} ON {table} ({cols});"
        )

    return lines


def generate_create_table_fk_sql(change: Change) -> list[str]:
    schema = change.get("schema")
    source = change.get("source") or {}
    table = table_name(change)
    statements: list[str] = []
    for fk in source.get("foreign_keys") or []:
        cols = quote_ident_list(fk.get("constrained_columns") or [])
        ref_table = reference_table_name(fk, fallback_schema=schema)
        ref_cols = quote_ident_list(fk.get("referred_columns") or [])
        name = constraint_name(fk.get("name"))
        clause = f"FOREIGN KEY ({cols}) REFERENCES {ref_table} ({ref_cols})"
        if name:
            statements.append(
                f"ALTER TABLE {table} ADD CONSTRAINT {name} {clause};"
            )
        else:
            statements.append(f"ALTER TABLE {table} ADD {clause};")
    return statements


def generate_sequence_sql(source: Change, fallback_schema: str | None = None) -> list[str]:
    lines: list[str] = []
    for col in source.get("columns") or []:
        default = col.get("default")
        if not isinstance(default, str):
            continue
        match = NEXTVAL_RE.match(default)
        if not match:
            continue
        lines.append(f"CREATE SEQUENCE IF NOT EXISTS {sequence_name(match.group(1), fallback_schema)};")
    return lines


def sequence_name(raw_name: str, fallback_schema: str | None = None) -> str:
    if "." in raw_name:
        schema, name = raw_name.split(".", 1)
        return qualified_name(name, schema)
    return qualified_name(raw_name, fallback_schema)


def comment_line(text: str) -> str:
    return f"-- {text}"


def maybe_comment(lines: list[str], mode: Mode, comment_destructive: bool) -> list[str]:
    if mode == "destructive" or not comment_destructive:
        return lines
    return [comment_line(line) for line in lines]


def generate_add_column_sql(change: Change) -> list[str]:
    table = table_name(change)
    column = quote_ident(change["column"])
    col_type = change.get("source_type", "")
    nullable = change.get("source_nullable", True)
    default = change.get("source_default")

    parts = [f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"]
    if not nullable:
        parts.append("NOT NULL")
    if default is not None:
        parts.append(f"DEFAULT {format_default(default)}")
    return [" ".join(parts) + ";"]


def generate_alter_column_type_sql(change: Change) -> list[str]:
    table = table_name(change)
    column = quote_ident(change["column"])
    new_type = change.get("source", "")
    # USING явно конвертирует существующие значения - без этого PG падает на
    # реальном cast (например varchar -> integer). Для совместимого расширения
    # типа PG всё равно применит каст безопасно.
    return [
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {new_type} "
        f"USING {column}::{new_type};"
    ]


def generate_alter_column_nullable_sql(change: Change) -> list[str]:
    table = table_name(change)
    column = quote_ident(change["column"])

    if change.get("source"):
        return [f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL;"]
    return [f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL;"]


def generate_alter_column_default_sql(change: Change) -> list[str]:
    table = table_name(change)
    column = quote_ident(change["column"])
    source_default = change.get("source")
    if source_default is None:
        return [f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT;"]
    return [
        f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {format_default(source_default)};"
    ]


def generate_create_index_sql(change: Change) -> list[str]:
    table = table_name(change)
    index = change.get("source") or {}
    name = quote_ident(index.get("name"))
    cols = quote_ident_list(index.get("columns") or [])
    unique = "UNIQUE " if index.get("unique") else ""
    return [f"CREATE {unique}INDEX {name} ON {table} ({cols});"]


def generate_add_unique_constraint_sql(change: Change) -> list[str]:
    table = table_name(change)
    unique = change.get("source") or {}
    name = constraint_name(unique.get("name"))
    cols = quote_ident_list(unique.get("columns") or [])
    raw_name = unique.get("name")
    if name and raw_name:
        return [
            generate_guarded_unique_constraint_sql(
                table=table,
                raw_table=change["table"],
                raw_schema=change.get("schema"),
                constraint=name,
                raw_constraint=raw_name,
                columns=unique.get("columns") or [],
                quoted_columns=cols,
            )
        ]
    return [f"ALTER TABLE {table} ADD UNIQUE ({cols});"]


def generate_add_foreign_key_sql(change: Change) -> list[str]:
    table = table_name(change)
    fk = change.get("source") or {}
    name = constraint_name(fk.get("name"))
    cols = quote_ident_list(fk.get("constrained_columns") or [])
    ref_table = reference_table_name(fk, fallback_schema=change.get("schema"))
    ref_cols = quote_ident_list(fk.get("referred_columns") or [])
    clause = f"FOREIGN KEY ({cols}) REFERENCES {ref_table} ({ref_cols})"
    if name:
        return [f"ALTER TABLE {table} ADD CONSTRAINT {name} {clause} NOT VALID;"]
    return [f"ALTER TABLE {table} ADD {clause} NOT VALID;"]


def generate_guarded_unique_constraint_sql(
    table: str,
    raw_table: str,
    raw_schema: str | None,
    constraint: str,
    raw_constraint: str,
    columns: list[str],
    quoted_columns: str,
) -> str:
    relation = qualified_name(raw_table, raw_schema)
    relation_literal = quote_literal(relation)
    constraint_literal = quote_literal(raw_constraint)
    duplicate_filter = " AND ".join(f"{quote_ident(col)} IS NOT NULL" for col in columns)
    duplicate_query = (
        f"SELECT 1 FROM {table}"
        + (f" WHERE {duplicate_filter}" if duplicate_filter else "")
        + f" GROUP BY {quoted_columns} HAVING COUNT(*) > 1"
    )
    add_constraint = (
        f"ALTER TABLE {table} ADD CONSTRAINT {constraint} UNIQUE ({quoted_columns})"
    )
    return "\n".join(
        [
            "DO $$",
            "BEGIN",
            "    IF EXISTS (",
            "        SELECT 1",
            "        FROM pg_constraint",
            f"        WHERE conrelid = to_regclass({relation_literal})",
            f"          AND conname = {constraint_literal}",
            "    ) THEN",
            f"        RAISE NOTICE 'UNIQUE constraint % already exists on %', {constraint_literal}, {relation_literal};",
            f"    ELSIF EXISTS ({duplicate_query}) THEN",
            f"        RAISE WARNING 'Skipped UNIQUE constraint % on % because duplicate key values exist', {constraint_literal}, {relation_literal};",
            "    ELSE",
            f"        {add_constraint};",
            "    END IF;",
            "END $$;",
        ]
    )


def generate_add_check_constraint_sql(change: Change) -> list[str]:
    table = table_name(change)
    check = change.get("source") or {}
    name = constraint_name(check.get("name"))
    sqltext = check.get("sqltext")
    if name:
        return [f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sqltext});"]
    return [f"ALTER TABLE {table} ADD CHECK ({sqltext});"]


def generate_drop_column_sql(change: Change) -> list[str]:
    table = table_name(change)
    column = quote_ident(change["column"])
    return [f"ALTER TABLE {table} DROP COLUMN {column};"]


def generate_drop_table_sql(change: Change) -> list[str]:
    table = table_name(change)
    return [f"DROP TABLE {table};"]


def generate_drop_index_sql(change: Change) -> list[str]:
    index = change.get("target") or {}
    index_name = index.get("name")
    if not index_name:
        raise ValueError("index name is required to generate DROP INDEX SQL")
    name = qualified_name(index_name, change.get("schema"))
    return [f"DROP INDEX {name};"]


def generate_drop_constraint_sql(
    change: Change, source_key: str = "target"
) -> list[str]:
    table = table_name(change)
    constraint = change.get(source_key) or {}
    name = required_constraint_name(constraint.get("name"), change["kind"])
    return [f"ALTER TABLE {table} DROP CONSTRAINT {name};"]


def generate_primary_key_sql(change: Change) -> list[str]:
    table = table_name(change)
    target_name = required_constraint_name(change.get("target_name"), change["kind"])
    raw_table = change["table"]
    source_name = constraint_name(change.get("source_name") or f"{raw_table}_pkey")
    source_cols = quote_ident_list(change.get("source") or [])
    return [
        f"ALTER TABLE {table} DROP CONSTRAINT {target_name};",
        f"ALTER TABLE {table} ADD CONSTRAINT {source_name} PRIMARY KEY ({source_cols});",
    ]

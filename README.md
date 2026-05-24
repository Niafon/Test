# PostgreSQL schema sync test environment

## Start

```powershell
docker compose up -d
```

This creates two isolated PostgreSQL instances:

- `source-postgres`
  - host port: `5433`
  - db: `source_db`
  - user: `source_user`
  - password: `source_password`
- `target-postgres`
  - host port: `5434`
  - db: `target_db`
  - user: `target_user`
  - password: `target_password`

Application URLs are already aligned in `.env`.

## Reset to initial state

```powershell
./scripts/reset-test-env.ps1
```

The reset script removes both containers and both named volumes, then recreates them from `docker-compose.yml`. This guarantees the databases return to the original seeded state even if previous test runs partially changed schema or data.

## Intentional schema differences

`source_db` is the reference schema. It contains structure only and no business rows.

`target_db` contains seeded data and intentional drift so a schema comparison tool can detect:

- Safe additions:
  - missing columns `users.email`, `products.sku`, `products.created_at`
  - missing tables `roles`, `user_roles`, `audit_logs`
  - missing indexes `idx_users_created_at`, `idx_orders_created_at`
- Risky changes:
  - missing `UNIQUE(users.username)` while target has duplicate usernames
  - missing `FOREIGN KEY orders.user_id -> users.id` while target contains `user_id = 999`
  - type changes from `TIMESTAMP` to `TIMESTAMPTZ`
  - type changes from `INTEGER` to `NUMERIC(12, 2)`
- Destructive changes:
  - extra target columns `users.full_name`, `users.old_phone`, `products.old_vendor_code`
  - extra target table `legacy_notes`



## Функционал

Инструмент сравнивает структуру двух PostgreSQL-баз (`source` — эталон, `target` — боевая) и приводит target в соответствие с source, **не повреждая существующие данные**. Работает как FastAPI-сервис и как CLI.

### Что умеет находить и чинить

| Объект | Кладёт в diff | Генерирует SQL |
|--------|--------------|----------------|
| Таблицы | `missing_table`, `extra_table` | `CREATE TABLE`, `DROP TABLE` |
| Колонки | `missing_column`, `extra_column` | `ALTER TABLE ADD/DROP COLUMN` |
| Атрибуты колонок | `different_column_type/nullable/default` | `ALTER COLUMN TYPE ... USING`, `SET/DROP NOT NULL`, `SET/DROP DEFAULT` |
| Первичные ключи | `different_primary_key` | `DROP CONSTRAINT` + `ADD CONSTRAINT PRIMARY KEY` |
| Внешние ключи | `missing_foreign_key`, `extra_foreign_key` | `ADD CONSTRAINT ... NOT VALID`, `DROP CONSTRAINT` |
| UNIQUE | `missing_unique_constraint`, `extra_unique_constraint` | guarded `ADD CONSTRAINT UNIQUE` (с защитой от дубликатов), `DROP CONSTRAINT` |
| Индексы | `missing_index`, `extra_index` | `CREATE INDEX`, `DROP INDEX` |
| CHECK-constraints | `missing_check_constraint`, `extra_check_constraint` | `ADD CONSTRAINT CHECK`, `DROP CONSTRAINT` |
| Sequences (для `nextval(...)`) | — | `CREATE SEQUENCE IF NOT EXISTS` |

### Три режима применения

Каждое изменение классифицируется и попадает в одну из корзин:

- **`safe`** — аддитивные операции, которые не теряют данные: `CREATE TABLE`, `ADD COLUMN` (nullable или с DEFAULT), `CREATE INDEX` (не unique), расширение типа (`INTEGER → BIGINT`, `VARCHAR(50) → VARCHAR(255)`).
- **`risky`** — может упасть на существующих данных: `ADD COLUMN NOT NULL` без default, `ADD UNIQUE` при наличии дублей, `ADD FOREIGN KEY` при битых ссылках, смена nullable/default, несовместимая смена типа.
- **`destructive`** — теряет данные: любые `DROP`, `extra_*`, пересоздание primary key.

В режимах `safe` / `risky` все destructive операции эмитятся **закомментированными** — даже при случайном `/apply` ничего не удалится. Чтобы реально удалить — нужен явный режим `destructive`.

### Защита данных target

- `FOREIGN KEY` добавляется с `NOT VALID` — проверяет только новые записи, не падает на исторических данных.
- `UNIQUE constraint` оборачивается в guarded `DO $$ ... END $$` блок: при наличии дубликатов выдаётся `RAISE WARNING` вместо падения транзакции.
- `ALTER COLUMN TYPE` всегда c `USING <col>::<new_type>` — PG корректно конвертирует существующие значения.
- `apply_sql_text` выполняется в одной транзакции: при ошибке любого statement-а делается **rollback всех изменений**, БД остаётся нетронутой.
- Циклические FK между новыми таблицами разруливаются через deferred `ALTER TABLE ADD CONSTRAINT` после всех `CREATE TABLE`.
- В diagnostics отчёта попадают:
  - примеры строк, нарушающих FK (`existing_violations_sample`)
  - примеры дубликатов для UNIQUE (`duplicate_values_sample`)
  - оценка `row_count` и предупреждение про `ACCESS EXCLUSIVE` lock для PK rewrite и DROP TABLE

### Workflow

1. **`POST /generate/{mode}`** — сравнивает source с target, формирует SQL для выбранного режима, сохраняет `reports/<report_id>.sql` + meta JSON с changes и diagnostics. Возвращает `report_id`.
2. Человек открывает `.sql`-файл и проверяет глазами.
3. **`POST /apply/{report_id}`** — применяет ранее одобренный отчёт к target. После успеха в meta-файл попадает `post_apply` с остаточным diff.

CLI-вариант:

```powershell
python apply.py <report_id>            # с подтверждением y/N
python apply.py <report_id> --yes      # без подтверждения
python apply.py path/to/report.sql     # произвольный .sql-файл
```

### Модули

| Файл | Ответственность |
|------|-----------------|
| [introspection.py](introspection.py) | Чтение схемы через `SQLAlchemy inspect()` (таблицы, колонки, PK, FK, UNIQUE, индексы, CHECK) |
| [compare.py](compare.py) | Попарное сравнение и формирование `Change`-записей |
| [compare_database.py](compare_database.py) | Оркестратор: собирает все diff'ы по двум engine'ам |
| [plan.py](plan.py) | Классификация changes по `safe / risky / destructive` + человекочитаемое описание |
| [sql_generator.py](sql_generator.py) | Генерация SQL по changes (один режим = один SQL-скрипт) |
| [apply.py](apply.py) | Транзакционное применение SQL, парсер statement-ов с поддержкой `DO $$ ... $$` и комментариев |
| [main.py](main.py) | FastAPI-эндпойнты `/generate`, `/report`, `/apply` + diagnostics |
| [reports_meta.py](reports_meta.py) | Общие константы: `REPORT_ID_RE`, `REPORTS_DIR`, формат UTC timestamp |
| [config.py](config.py), [db.py](db.py) | Settings из `.env`, кешируемая фабрика `Engine` |

## Тесты

```powershell
python -m pytest tests/unit/         # быстрые моки, без БД
python -m pytest tests/integration/  # реальные source/target (нужны docker-контейнеры)
python -m pytest tests/              # всё сразу
```

- **25 unit-тестов** — golden-SQL генератора, моки `Engine` для проверки rollback'а, классификация changes, сравнение схем на синтетических входах.
- **7 integration-тестов** — полный конвейер на реальных БД во временных схемах (`test_src_<uuid>` / `test_tgt_<uuid>`); после каждого теста `DROP SCHEMA ... CASCADE`, поэтому ваши `public.*` не трогаются и `reset-test-env.ps1` для них не нужен. Если БД недоступна — пропускаются автоматически.

URL для интеграционных тестов можно переопределить через `TEST_SOURCE_URL` / `TEST_TARGET_URL`.

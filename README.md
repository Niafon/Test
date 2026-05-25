# DB Diff — синхронизация схемы PostgreSQL

Инструмент сравнивает структуру двух PostgreSQL-баз (`source` — эталон, `target` — боевая) и приводит target к виду source, **не повреждая существующие данные**. Работает как FastAPI-сервис и как CLI.

---

## Быстрый старт (Docker)

```powershell
docker compose up -d
```

Поднимаются два изолированных PostgreSQL-инстанса:

- `source-postgres`
  - порт хоста: `5433`
  - БД: `source_db`
  - пользователь: `source_user`
  - пароль: `source_password`
- `target-postgres`
  - порт хоста: `5434`
  - БД: `target_db`
  - пользователь: `target_user`
  - пароль: `target_password`

URLs приложения уже выровнены с `.env`.

### Сброс к исходному состоянию

```powershell
./scripts/reset-test-env.ps1
```

Скрипт удаляет оба контейнера и оба именованных volume, после чего пересоздаёт их из `docker-compose.yml`. Гарантирует возврат к исходным посеянным данным даже если прошлый прогон тестов частично изменил схему или данные.

---

## Запуск без Docker

Если PostgreSQL уже стоит локально (или доступен где-то ещё) и Docker поднимать незачем, можно запустить только Python-часть.

### 1. Подготовить виртуальное окружение и зависимости

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(На Linux/macOS вместо `.\.venv\Scripts\Activate.ps1` будет `source .venv/bin/activate`.)

### 2. Прописать подключения

Создайте файл `.env` рядом с `main.py` (или задайте переменные окружения):

```
SOURCE_DATABASE_URL=postgresql+psycopg://user:password@host:5432/source_db
TARGET_DATABASE_URL=postgresql+psycopg://user:password@host:5432/target_db
# Опционально - имена схем; если не задано, используется search_path
SOURCE_SCHEMA=public
TARGET_SCHEMA=public
```

URL — стандартный SQLAlchemy. Драйвер `psycopg` (v3) ставится из `requirements.txt`.

### 3. Запустить сервис

```powershell
python main.py
```

По умолчанию сервис слушает `127.0.0.1:8000`. Адрес/порт можно переопределить переменными окружения:

- `DB_DIFF_HOST` — хост, по умолчанию `127.0.0.1`
- `DB_DIFF_PORT` — порт, по умолчанию `8000`
- `DB_DIFF_LOG_LEVEL` — уровень логирования (`debug`/`info`/`warning`/`error`), по умолчанию `info`

Альтернативно, через `uvicorn` напрямую:

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Swagger UI откроется на http://127.0.0.1:8000/docs.

### 4. CLI

```powershell
python apply.py <report_id>            # с подтверждением y/N
python apply.py <report_id> --yes      # без подтверждения
python apply.py path/to/report.sql     # произвольный .sql-файл
python apply.py <report_id> --log-level DEBUG   # подробные логи
```

---

## Подключение к своей БД

Чтобы прогнать инструмент против ваших собственных БД (не тестовых из `docker-compose.yml`):

1. **Убедитесь, что обе БД доступны** — их URLs нужны и при `/generate`, и при `/apply`. Можно использовать одну и ту же БД с разными схемами, разные БД в одном кластере, или разные кластеры.
2. **Источник (`source`) — эталон.** Это должна быть БД с *правильной* схемой (без данных или с тестовыми данными). Инструмент НЕ модифицирует source: только читает.
3. **Цель (`target`) — то, что приводим к source.** Безопасность данных target обеспечивается тем, что:
   - все DROP-операции в `safe`/`risky` режимах выходят закомментированными;
   - `FOREIGN KEY` добавляется с `NOT VALID` — не падает на исторических нарушениях;
   - `UNIQUE constraint` обёрнут в `DO $$ ... END $$` блок: при наличии дубликатов выдаётся `RAISE WARNING` вместо падения транзакции;
   - `apply_sql_text` выполняется одной транзакцией: при ошибке любого statement-а делается **rollback всего**.
4. **Заполните `.env`** URL обеих БД (как выше) ИЛИ передавайте URL прямо в теле каждого запроса:
   ```json
   {
     "source_url": "postgresql+psycopg://...",
     "target_url": "postgresql+psycopg://..."
   }
   ```
5. **Workflow:**
   ```powershell
   # 1. Сгенерировать отчёт - сравнение + SQL для выбранного режима
   curl.exe -X POST http://127.0.0.1:8000/generate/safe `
     -H "Content-Type: application/json" `
     -d '{"source_url":"...","target_url":"..."}'

   # 2. В ответе будет report_id - изучите ./reports/<report_id>.sql глазами
   # 3. Если ок - применить:
   curl.exe -X POST http://127.0.0.1:8000/apply/<report_id> `
     -H "Content-Type: application/json" `
     -d '{"target_url":"..."}'

   # или через CLI без HTTP:
   python apply.py <report_id>
   ```
6. **Перед запуском в production** настоятельно рекомендую:
   - сделать бэкап target (`pg_dump`);
   - прогнать сначала с режимом `safe`, посмотреть, что получится;
   - читать `diagnostics` в ответе `/generate` — там примеры строк, которые нарушат FK/UNIQUE;
   - если включаете `destructive` — ещё раз убедиться, что `extra_table`/`extra_column` действительно не нужны.

---

## Намеренные различия схем (для тестовой среды)

`source_db` — эталонная схема. Содержит только структуру, без бизнес-данных.

`target_db` содержит посеянные данные и намеренные расхождения, чтобы инструмент сравнения мог обнаружить:

- Безопасные добавления:
  - отсутствующие колонки `users.email`, `products.sku`, `products.created_at`
  - отсутствующие таблицы `roles`, `user_roles`, `audit_logs`
  - отсутствующие индексы `idx_users_created_at`, `idx_orders_created_at`
- Рискованные изменения:
  - отсутствующий `UNIQUE(users.username)` при наличии дублей в target
  - отсутствующий `FOREIGN KEY orders.user_id -> users.id` при наличии `user_id = 999`
  - смена типа с `TIMESTAMP` на `TIMESTAMPTZ`
  - смена типа с `INTEGER` на `NUMERIC(12, 2)`
- Деструктивные изменения:
  - лишние колонки target: `users.full_name`, `users.old_phone`, `products.old_vendor_code`
  - лишняя таблица target: `legacy_notes`

---

## Функционал

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
- `ALTER COLUMN TYPE` всегда с `USING <col>::<new_type>` — PG корректно конвертирует существующие значения.
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
| [main.py](main.py) | Точка запуска: сборка FastAPI-приложения, `include_router`, uvicorn |
| [routes.py](routes.py) | HTTP-маршруты `/generate`, `/report`, `/apply` + Pydantic-модели запроса |
| [report_service.py](report_service.py) | Сервисный слой за эндпойнтами: валидация, построение плана, сохранение/чтение отчётов, диагностика |
| [reports_meta.py](reports_meta.py) | Общие константы: `REPORT_ID_RE`, `REPORTS_DIR`, формат UTC timestamp |
| [config.py](config.py), [db.py](db.py) | Settings из `.env`, кешируемая фабрика `Engine` |

---

## Тесты

```powershell
python -m pytest tests/unit/         # быстрые моки, без БД
python -m pytest tests/integration/  # реальные source/target (нужны docker-контейнеры)
python -m pytest tests/              # всё сразу
```

- **25 unit-тестов** — golden-SQL генератора, моки `Engine` для проверки rollback'а, классификация changes, сравнение схем на синтетических входах.
- **7 integration-тестов** — полный конвейер на реальных БД во временных схемах (`test_src_<uuid>` / `test_tgt_<uuid>`); после каждого теста `DROP SCHEMA ... CASCADE`, поэтому ваши `public.*` не трогаются и `reset-test-env.ps1` для них не нужен. Если БД недоступна — пропускаются автоматически.

URL для интеграционных тестов можно переопределить через `TEST_SOURCE_URL` / `TEST_TARGET_URL`.

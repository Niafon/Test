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



For testing (mock + with real db):
  - python -m pytest tests/ -v

6 модулей ядра + 6 файлов тестов
32 теста: 25 unit (моки + golden-SQL) + 7 integration (реальные source/target БД)


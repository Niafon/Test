CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    full_name VARCHAR(255) NULL,
    old_phone VARCHAR(50) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price INTEGER NOT NULL,
    old_vendor_code VARCHAR(50) NULL
);

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    total INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE legacy_notes (
    id BIGSERIAL PRIMARY KEY,
    note_text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

INSERT INTO users (id, username, full_name, old_phone, created_at) VALUES
    (1, 'alice', 'Alice Adams', '+10000000001', '2024-01-10 09:00:00'),
    (2, 'bob', 'Bob Brown', '+10000000002', '2024-01-11 10:30:00'),
    (3, 'alice', 'Alice Clone', '+10000000003', '2024-01-12 11:45:00');

INSERT INTO products (id, name, price, old_vendor_code) VALUES
    (1, 'Keyboard', 12500, 'OLD-KB-01'),
    (2, 'Mouse', 4900, 'OLD-MS-99');

INSERT INTO orders (id, user_id, total, created_at) VALUES
    (1, 1, 12500, '2024-01-15 08:15:00'),
    (2, 999, 4900, '2024-01-16 14:20:00');

INSERT INTO legacy_notes (id, note_text, created_at) VALUES
    (1, 'Imported from legacy CRM', '2024-01-05 12:00:00'),
    (2, 'Do not delete this table during sync tests', '2024-01-06 13:30:00');

SELECT setval('users_id_seq', 3, true);
SELECT setval('products_id_seq', 2, true);
SELECT setval('orders_id_seq', 2, true);
SELECT setval('legacy_notes_id_seq', 2, true);

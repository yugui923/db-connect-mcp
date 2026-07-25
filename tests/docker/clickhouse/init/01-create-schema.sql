CREATE DATABASE IF NOT EXISTS testdb;

CREATE TABLE IF NOT EXISTS testdb.categories
(
    category_id UInt32,
    name String,
    parent_category_id Nullable(UInt32),
    created_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY category_id;

CREATE TABLE IF NOT EXISTS testdb.products
(
    product_id UInt32,
    category_id UInt32,
    name String,
    description Nullable(String),
    price Decimal(12, 2),
    stock_quantity Int32,
    is_active Bool,
    created_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY product_id;

CREATE TABLE IF NOT EXISTS testdb.users
(
    user_id UInt32,
    username String,
    email String,
    is_active Bool,
    created_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY user_id;

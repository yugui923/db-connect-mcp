INSERT INTO testdb.categories (category_id, name, parent_category_id) VALUES
    (1, 'Electronics', NULL),
    (2, 'Computers', 1),
    (3, 'Accessories', 1);

INSERT INTO testdb.products
    (product_id, category_id, name, description, price, stock_quantity, is_active)
VALUES
    (1, 2, 'Laptop', 'Development laptop', 1299.00, 12, true),
    (2, 3, 'Keyboard', 'Mechanical keyboard', 149.50, 40, true),
    (3, 3, 'Mouse', NULL, 79.99, 0, false);

INSERT INTO testdb.users (user_id, username, email, is_active) VALUES
    (1, 'alice', 'alice@example.com', true),
    (2, 'bob', 'bob@example.com', true),
    (3, 'inactive', 'inactive@example.com', false);

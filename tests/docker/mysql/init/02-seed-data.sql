SET NAMES utf8mb4;

INSERT INTO categories (name, description) VALUES
    ('Electronics', 'Electronic devices and accessories'),
    ('Books', 'Physical and digital books'),
    ('Clothing', 'Apparel and fashion items');

INSERT INTO users (email, username) VALUES
    ('alice@example.com', 'alice'),
    ('bob@example.com', 'bob'),
    ('charlie@example.com', 'charlie');

INSERT INTO products (name, category_id, price, stock_quantity) VALUES
    ('Laptop', 1, 999.99, 50),
    ('Headphones', 1, 79.99, 200),
    ('Python Cookbook', 2, 49.99, 100),
    ('T-Shirt', 3, 19.99, 500),
    ('Smartphone', 1, 699.99, 75);

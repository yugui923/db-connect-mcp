-- ============================================
-- Sample Data Generation for db-connect-mcp
-- Purpose: Create realistic data for testing statistics and analysis
-- ============================================

SET client_encoding = 'UTF8';
SET timezone = 'UTC';

-- ============================================
-- Categories (50 categories with hierarchy)
-- ============================================
INSERT INTO categories (name, description, parent_category_id, metadata, is_active) VALUES
-- Root categories
('Electronics', 'Electronic devices and accessories', NULL, '{"level": "root", "priority": 1}'::jsonb, true),
('Clothing', 'Apparel and fashion items', NULL, '{"level": "root", "priority": 2}'::jsonb, true),
('Home & Garden', 'Home improvement and garden supplies', NULL, '{"level": "root", "priority": 3}'::jsonb, true),
('Books', 'Physical and digital books', NULL, '{"level": "root", "priority": 4}'::jsonb, true),
('Sports & Outdoors', 'Sporting goods and outdoor equipment', NULL, '{"level": "root", "priority": 5}'::jsonb, true),

-- Electronics subcategories (parent_id = 1)
('Computers', 'Desktop and laptop computers', 1, '{"level": "sub", "keywords": ["pc", "laptop", "desktop"]}'::jsonb, true),
('Smartphones', 'Mobile phones and accessories', 1, '{"level": "sub", "trending": true}'::jsonb, true),
('Audio', 'Headphones, speakers, and audio equipment', 1, '{"level": "sub"}'::jsonb, true),
('Cameras', 'Digital cameras and photography equipment', 1, '{"level": "sub"}'::jsonb, true),
('Gaming', 'Video game consoles and accessories', 1, '{"level": "sub", "trending": true}'::jsonb, true),

-- Clothing subcategories (parent_id = 2)
('Men''s Clothing', 'Clothing for men', 2, '{"level": "sub", "gender": "male"}'::jsonb, true),
('Women''s Clothing', 'Clothing for women', 2, '{"level": "sub", "gender": "female"}'::jsonb, true),
('Kids'' Clothing', 'Clothing for children', 2, '{"level": "sub", "age_group": "children"}'::jsonb, true),
('Shoes', 'Footwear for all ages', 2, '{"level": "sub"}'::jsonb, true),
('Accessories', 'Fashion accessories', 2, '{"level": "sub"}'::jsonb, true),

-- More categories
('Furniture', 'Home furniture', 3, '{"level": "sub"}'::jsonb, true),
('Kitchen', 'Kitchen appliances and tools', 3, '{"level": "sub"}'::jsonb, true),
('Garden Tools', 'Gardening equipment', 3, '{"level": "sub"}'::jsonb, true),
('Decor', 'Home decoration items', 3, '{"level": "sub"}'::jsonb, true),
('Lighting', 'Indoor and outdoor lighting', 3, '{"level": "sub"}'::jsonb, true),

-- Books subcategories (parent_id = 4)
('Fiction', 'Fiction books and novels', 4, '{"level": "sub"}'::jsonb, true),
('Non-Fiction', 'Non-fiction and educational books', 4, '{"level": "sub"}'::jsonb, true),
('Science Fiction', 'Science fiction novels', 21, '{"level": "subsub", "genre": "scifi"}'::jsonb, true),
('Mystery', 'Mystery and thriller books', 21, '{"level": "subsub", "genre": "mystery"}'::jsonb, true),
('Biography', 'Biographical works', 22, '{"level": "subsub"}'::jsonb, true);

-- Add 25 more categories for statistical diversity
INSERT INTO categories (name, description, is_active, metadata)
SELECT
    'Category ' || i,
    'Test category ' || i,
    CASE WHEN i % 10 = 0 THEN false ELSE true END,
    ('{"test_id": ' || i || '}')::jsonb
FROM generate_series(26, 50) AS i;

-- ============================================
-- Products (2000 products for statistical analysis)
-- ============================================

-- First, insert some known products
INSERT INTO products (sku, name, description, category_id, price, cost, weight_kg, stock_quantity, is_featured, tags, supplier_ip) VALUES
('ELEC-001', 'UltraBook Pro 15"', 'High-performance laptop', 6, 1299.99, 850.00, 1.8, 45, true, ARRAY['laptop', 'computer'], '192.168.1.100'),
('ELEC-002', 'Smartphone X1', 'Latest flagship smartphone', 7, 899.99, 600.00, 0.18, 120, true, ARRAY['phone', 'smartphone'], '192.168.1.101'),
('ELEC-003', 'Wireless Headphones', 'Noise-cancelling headphones', 8, 349.99, 180.00, 0.25, 200, true, ARRAY['audio', 'headphones'], '192.168.1.102'),
('ELEC-004', 'Gaming Console Pro', 'Next-gen gaming console', 10, 499.99, 320.00, 4.5, 85, true, ARRAY['gaming', 'console'], '192.168.1.103'),
('ELEC-005', 'Digital Camera 24MP', 'Professional digital camera', 9, 1199.99, 750.00, 0.65, 30, false, ARRAY['camera', 'photography'], '192.168.1.104'),
('CLTH-001', 'Men''s Cotton T-Shirt', 'Classic cotton t-shirt', 11, 19.99, 8.00, 0.2, 500, false, ARRAY['shirt', 'cotton'], NULL),
('CLTH-002', 'Women''s Dress', 'Elegant evening dress', 12, 89.99, 35.00, 0.4, 75, true, ARRAY['dress', 'formal'], NULL),
('CLTH-003', 'Kids'' Jacket', 'Warm winter jacket', 13, 49.99, 22.00, 0.6, 150, false, ARRAY['jacket', 'winter'], NULL),
('CLTH-004', 'Running Shoes', 'Professional running shoes', 14, 129.99, 55.00, 0.9, 200, true, ARRAY['shoes', 'running'], NULL),
('CLTH-005', 'Leather Wallet', 'Genuine leather wallet', 15, 39.99, 15.00, 0.1, 300, false, ARRAY['wallet', 'leather'], NULL),
('HOME-001', 'Sofa 3-Seater', 'Comfortable sofa', 16, 799.99, 400.00, 85.0, 12, true, ARRAY['furniture', 'sofa'], '10.0.0.1'),
('HOME-002', 'Blender Pro', 'High-speed blender', 17, 89.99, 40.00, 2.5, 80, false, ARRAY['kitchen', 'appliance'], '10.0.0.2'),
('HOME-003', 'Garden Hose 50ft', 'Expandable hose', 18, 29.99, 12.00, 1.2, 250, false, ARRAY['garden', 'hose'], NULL),
('BOOK-001', 'The Great Novel', 'Award-winning fiction', 21, 24.99, 10.00, 0.5, 200, true, ARRAY['fiction', 'bestseller'], NULL),
('BOOK-002', 'Learn Python', 'Python programming guide', 22, 39.99, 18.00, 0.8, 150, true, ARRAY['programming', 'python'], NULL);

-- Generate remaining products with simpler formula
INSERT INTO products (sku, name, description, category_id, price, cost, weight_kg, stock_quantity, is_featured, tags, supplier_ip)
SELECT
    'GEN-' || LPAD(i::text, 6, '0'),
    'Product ' || i,
    CASE
        WHEN i % 5 = 0 THEN 'Premium quality product'
        WHEN i % 3 = 0 THEN 'Standard product'
        ELSE NULL
    END,
    CASE
        WHEN i % 100 < 30 THEN 6
        WHEN i % 100 < 50 THEN 7
        WHEN i % 100 < 65 THEN 11
        WHEN i % 100 < 80 THEN 12
        ELSE (i % 25) + 1
    END,
    ROUND((10 + (i::float / 5))::numeric, 2),
    ROUND((10 + (i::float / 5))::numeric * 0.75, 2),
    ROUND((0.1 + (i % 20))::numeric, 2),
    CASE
        WHEN i % 50 = 0 THEN 0
        WHEN i % 10 = 0 THEN (i % 20)
        ELSE (50 + (i % 500))
    END,
    i % 10 = 1,
    CASE
        WHEN i % 3 = 0 THEN ARRAY['tag1', 'tag2']
        WHEN i % 2 = 0 THEN ARRAY['tag1']
        ELSE NULL
    END,
    CASE
        WHEN i % 2 = 0 THEN ('192.168.' || ((i % 255) + 1) || '.' || ((i % 255) + 1))::inet
        ELSE NULL
    END
FROM generate_series(16, 2000) AS i;

-- Set some products as discontinued
UPDATE products SET discontinued_at = CURRENT_TIMESTAMP - ((product_id % 365) || ' days')::interval
WHERE product_id % 20 = 0;

-- ============================================
-- Users (5000 users for JOIN testing)
-- ============================================
INSERT INTO users (email, username, first_name, last_name, phone, birth_date, is_verified, is_premium, last_login_ip, preferences)
SELECT
    'user' || i || '@example.com',
    'user' || i,
    CASE WHEN i % 10 = 0 THEN NULL ELSE 'FirstName' || i END,
    CASE WHEN i % 10 = 0 THEN NULL ELSE 'LastName' || i END,
    CASE WHEN i % 10 < 7 THEN '+1-555-' || LPAD((i % 10000)::text, 4, '0') ELSE NULL END,
    CURRENT_DATE - (INTERVAL '1 year' * (18 + (i % 62))),
    i % 10 < 8,
    i % 5 = 0,
    CASE WHEN i % 10 < 7 THEN ('10.0.' || ((i % 255) + 1) || '.' || ((i % 255) + 1))::inet ELSE NULL END,
    ('{"theme": "' || (ARRAY['light', 'dark'])[1 + (i % 2)] || '", "notifications": ' || ((i % 2 = 0)::text) || '}')::jsonb
FROM generate_series(1, 5000) AS i;

-- Set last login for 70% of users
UPDATE users SET last_login_at = CURRENT_TIMESTAMP - ((user_id % 90) || ' days')::interval
WHERE user_id % 10 < 7;

-- ============================================
-- Orders (10000 orders)
-- ============================================
INSERT INTO orders (order_number, user_id, subtotal, tax_amount, shipping_amount, total_amount, status, ordered_at, shipping_city, shipping_state, shipping_country)
SELECT
    'ORD-' || LPAD(i::text, 8, '0'),
    1 + (i % 5000),
    subtotal_val,
    ROUND(subtotal_val * 0.08, 2),
    CASE WHEN subtotal_val > 100 THEN 0 ELSE 10.00 END,
    ROUND(subtotal_val * 1.08 + CASE WHEN subtotal_val > 100 THEN 0 ELSE 10.00 END, 2),
    (ARRAY['delivered', 'delivered', 'delivered', 'delivered', 'shipped', 'processing', 'pending', 'cancelled'])[1 + (i % 8)],
    CURRENT_TIMESTAMP - ((i::float / 10000 * 730) || ' days')::interval,
    (ARRAY['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia', 'San Antonio', 'San Diego', 'Dallas', 'San Jose'])[1 + (i % 10)],
    (ARRAY['NY', 'CA', 'IL', 'TX', 'AZ', 'PA', 'TX', 'CA', 'TX', 'CA'])[1 + (i % 10)],
    'US'
FROM (
    SELECT i, ROUND((20 + (i::float / 10000 * 980))::numeric, 2) AS subtotal_val
    FROM generate_series(1, 10000) AS i
) AS subquery;

UPDATE orders SET shipped_at = ordered_at + ((order_id % 120) || ' hours')::interval
WHERE status IN ('shipped', 'delivered');

UPDATE orders SET delivered_at = shipped_at + ((order_id % 168) || ' hours')::interval
WHERE status = 'delivered';

-- ============================================
-- Order Items (25000 line items)
-- ============================================
INSERT INTO order_items (order_id, product_id, line_number, quantity, unit_price, discount_amount, line_total)
SELECT
    o.order_id,
    p.product_id,
    ROW_NUMBER() OVER (PARTITION BY o.order_id ORDER BY p.product_id),
    1 + ((o.order_id + p.product_id) % 3),
    p.price,
    CASE WHEN (o.order_id + p.product_id) % 10 = 0 THEN ROUND(p.price * 0.10, 2) ELSE 0 END,
    ROUND((1 + ((o.order_id + p.product_id) % 3)) * p.price - CASE WHEN (o.order_id + p.product_id) % 10 = 0 THEN ROUND(p.price * 0.10, 2) ELSE 0 END, 2)
FROM
    orders o
    CROSS JOIN LATERAL (
        SELECT product_id, price
        FROM products
        WHERE product_id % (o.order_id % 100 + 1) = 0
        LIMIT 3
    ) p
LIMIT 25000;

-- ============================================
-- Product Reviews (8000 reviews)
-- ============================================
INSERT INTO product_reviews (product_id, user_id, rating, title, review_text, helpful_count, verified_purchase)
SELECT
    p.product_id,
    1 + ((p.product_id + i) % 5000),
    CASE
        WHEN i % 100 < 50 THEN 5
        WHEN i % 100 < 75 THEN 4
        WHEN i % 100 < 85 THEN 3
        WHEN i % 100 < 92 THEN 2
        ELSE 1
    END,
    CASE WHEN i % 10 < 8 THEN 'Review title ' || i ELSE NULL END,
    CASE
        WHEN i % 20 = 0 THEN NULL
        WHEN i % 3 = 0 THEN 'Short review'
        ELSE 'Detailed review text. Good product quality. ' || i
    END,
    CASE WHEN i % 100 = 0 THEN (i % 100) WHEN i % 10 = 0 THEN (i % 20) ELSE (i % 5) END,
    i % 10 < 7
FROM
    products p
    CROSS JOIN generate_series(1, 4) AS i
LIMIT 8000
ON CONFLICT (product_id, user_id) DO NOTHING;

-- ============================================
-- Data Type Examples (100 rows)
-- ============================================
INSERT INTO data_type_examples (
    smallint_col, integer_col, bigint_col, decimal_col, numeric_col, real_col, double_col,
    char_col, varchar_col, text_col,
    date_col, time_col, timestamp_col, timestamptz_col, interval_col,
    boolean_col, uuid_col,
    inet_col, cidr_col, macaddr_col,
    json_col, jsonb_col,
    int_array_col, text_array_col,
    point_col,
    bytea_col, money_col
)
SELECT
    (i % 32767)::smallint,
    i * 100,
    i::bigint * 1000000,
    ROUND((i * 1.23456)::numeric, 5),
    ROUND((i * 9.8765432)::numeric, 10),
    (i * 1.5)::real,
    (i * 2.5)::double precision,
    LPAD('test', 10),
    'varchar_' || i,
    'Text content for row ' || i,
    CURRENT_DATE - (i || ' days')::interval,
    '12:30:45'::time + (i || ' seconds')::interval,
    CURRENT_TIMESTAMP - (i || ' hours')::interval,
    CURRENT_TIMESTAMP - (i || ' hours')::interval,
    (i || ' days')::interval,
    i % 2 = 0,
    gen_random_uuid(),
    ('192.168.1.' || (1 + i % 254))::inet,
    ('10.0.0.0/' || (24 + i % 8))::cidr,
    ('08:00:2b:01:02:' || LPAD(to_hex(i % 256), 2, '0'))::macaddr,
    ('{"id": ' || i || ', "value": "test"}')::json,
    ('{"id": ' || i || ', "data": [1, 2, 3]}')::jsonb,
    ARRAY[i, i*2, i*3],
    ARRAY['tag' || i, 'tag' || (i+1)],
    point(i::double precision, i::double precision * 2),
    decode(LPAD(to_hex(i), 8, '0'), 'hex'),
    (i * 1.23)::money
FROM generate_series(1, 100) AS i;

-- Add NULL rows
INSERT INTO data_type_examples (id)
SELECT 101 + i FROM generate_series(1, 10) AS i;

-- ============================================
-- Update statistics
-- ============================================
ANALYZE categories;
ANALYZE products;
ANALYZE users;
ANALYZE orders;
ANALYZE order_items;
ANALYZE product_reviews;
ANALYZE data_type_examples;

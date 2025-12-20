-- ============================================
-- Views and Materialized Views for Testing
-- Tests: View support, materialized view capability
-- ============================================

-- ============================================
-- Regular View: Product Summary
-- Tests: View listing, complex JOINs, aggregations
-- ============================================
CREATE VIEW product_summary AS
SELECT
    p.product_id,
    p.sku,
    p.name,
    p.price,
    p.stock_quantity,
    c.name AS category_name,
    c.parent_category_id,
    COUNT(DISTINCT r.review_id) AS review_count,
    ROUND(AVG(r.rating), 2) AS average_rating,
    p.is_featured,
    p.created_at
FROM
    products p
    LEFT JOIN categories c ON p.category_id = c.category_id
    LEFT JOIN product_reviews r ON p.product_id = r.product_id
GROUP BY
    p.product_id, p.sku, p.name, p.price, p.stock_quantity,
    c.name, c.parent_category_id, p.is_featured, p.created_at;

COMMENT ON VIEW product_summary IS 'Aggregated product information with ratings';

-- ============================================
-- Regular View: Order Details
-- Tests: Multi-table JOINs, calculated fields
-- ============================================
CREATE VIEW order_details AS
SELECT
    o.order_id,
    o.order_number,
    o.ordered_at,
    o.status,
    o.total_amount,
    u.email AS customer_email,
    u.username AS customer_username,
    COUNT(oi.line_number) AS item_count,
    SUM(oi.quantity) AS total_quantity,
    o.shipping_city,
    o.shipping_state
FROM
    orders o
    JOIN users u ON o.user_id = u.user_id
    LEFT JOIN order_items oi ON o.order_id = oi.order_id
GROUP BY
    o.order_id, o.order_number, o.ordered_at, o.status, o.total_amount,
    u.email, u.username, o.shipping_city, o.shipping_state;

COMMENT ON VIEW order_details IS 'Complete order information with customer details';

-- ============================================
-- Materialized View: Product Statistics
-- Tests: Materialized view support, refresh capability
-- ============================================
CREATE MATERIALIZED VIEW product_statistics AS
SELECT
    p.product_id,
    p.name,
    p.category_id,
    c.name AS category_name,
    p.price,
    p.stock_quantity,
    COUNT(DISTINCT r.review_id) AS total_reviews,
    ROUND(AVG(r.rating), 2) AS avg_rating,
    COUNT(DISTINCT oi.order_id) AS times_ordered,
    COALESCE(SUM(oi.quantity), 0) AS total_quantity_sold,
    COALESCE(SUM(oi.line_total), 0) AS total_revenue,
    MAX(o.ordered_at) AS last_ordered_at,
    NOW() AS refreshed_at
FROM
    products p
    LEFT JOIN categories c ON p.category_id = c.category_id
    LEFT JOIN product_reviews r ON p.product_id = r.product_id
    LEFT JOIN order_items oi ON p.product_id = oi.product_id
    LEFT JOIN orders o ON oi.order_id = o.order_id AND o.status != 'cancelled'
GROUP BY
    p.product_id, p.name, p.category_id, c.name, p.price, p.stock_quantity;

COMMENT ON MATERIALIZED VIEW product_statistics IS 'Pre-calculated product performance metrics';

-- Create index on materialized view for better query performance
CREATE INDEX idx_product_stats_category ON product_statistics(category_id);
CREATE INDEX idx_product_stats_revenue ON product_statistics(total_revenue DESC);

-- ============================================
-- Materialized View: User Activity Summary
-- Tests: User behavior aggregations
-- ============================================
CREATE MATERIALIZED VIEW user_activity_summary AS
SELECT
    u.user_id,
    u.username,
    u.email,
    u.is_premium,
    u.is_verified,
    u.registered_at,
    u.last_login_at,
    COUNT(DISTINCT o.order_id) AS total_orders,
    COALESCE(SUM(o.total_amount), 0) AS lifetime_value,
    COALESCE(AVG(o.total_amount), 0) AS average_order_value,
    COUNT(DISTINCT r.review_id) AS total_reviews,
    COALESCE(AVG(r.rating), 0) AS average_review_rating,
    MAX(o.ordered_at) AS last_order_at,
    NOW() AS refreshed_at
FROM
    users u
    LEFT JOIN orders o ON u.user_id = o.user_id AND o.status != 'cancelled'
    LEFT JOIN product_reviews r ON u.user_id = r.user_id
GROUP BY
    u.user_id, u.username, u.email, u.is_premium, u.is_verified,
    u.registered_at, u.last_login_at;

COMMENT ON MATERIALIZED VIEW user_activity_summary IS 'User engagement and purchase metrics';

CREATE INDEX idx_user_activity_lifetime_value ON user_activity_summary(lifetime_value DESC);
CREATE INDEX idx_user_activity_orders ON user_activity_summary(total_orders DESC);

-- ============================================
-- Simple View for Quick Testing
-- ============================================
CREATE VIEW active_products AS
SELECT
    product_id,
    sku,
    name,
    price,
    stock_quantity,
    category_id
FROM
    products
WHERE
    discontinued_at IS NULL
    AND stock_quantity > 0;

COMMENT ON VIEW active_products IS 'Currently available products';

-- Initial refresh of materialized views
REFRESH MATERIALIZED VIEW product_statistics;
REFRESH MATERIALIZED VIEW user_activity_summary;

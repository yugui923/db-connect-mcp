-- ============================================
-- Schema: Test Database for db-connect-mcp
-- Purpose: Comprehensive coverage of PostgreSQL features
-- for testing MCP server capabilities
-- ============================================

SET client_encoding = 'UTF8';
SET timezone = 'UTC';

-- ============================================
-- Categories Table
-- Tests: Basic table structure, primary keys, sequences
-- ============================================
CREATE TABLE categories (
    category_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    parent_category_id INTEGER REFERENCES categories(category_id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    metadata JSONB,

    CONSTRAINT valid_name CHECK (length(trim(name)) > 0)
);

COMMENT ON TABLE categories IS 'Product categories with hierarchical structure';
COMMENT ON COLUMN categories.parent_category_id IS 'Self-referencing foreign key for category hierarchy';

CREATE INDEX idx_categories_parent ON categories(parent_category_id);
CREATE INDEX idx_categories_active ON categories(is_active) WHERE is_active = true;
CREATE INDEX idx_categories_metadata ON categories USING GIN(metadata);

-- ============================================
-- Products Table
-- Tests: Foreign keys, numeric types, constraints, indexes
-- ============================================
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category_id INTEGER NOT NULL REFERENCES categories(category_id) ON DELETE RESTRICT,

    -- Various numeric types for statistics testing
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    cost NUMERIC(10, 2) CHECK (cost >= 0),
    weight_kg DOUBLE PRECISION,
    stock_quantity INTEGER DEFAULT 0 CHECK (stock_quantity >= 0),

    -- Temporal types
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    discontinued_at TIMESTAMP WITH TIME ZONE,

    -- Boolean and special types
    is_featured BOOLEAN DEFAULT false,
    product_uuid UUID DEFAULT gen_random_uuid(),
    tags TEXT[],

    -- Network types for serialization testing
    supplier_ip INET,

    CONSTRAINT valid_profit_margin CHECK (cost IS NULL OR price > cost)
);

COMMENT ON TABLE products IS 'Product catalog with various data types for comprehensive testing';
COMMENT ON COLUMN products.product_uuid IS 'UUID for testing UUID serialization';

CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_price ON products(price);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_featured ON products(is_featured) WHERE is_featured = true;
CREATE INDEX idx_products_tags ON products USING GIN(tags);

-- ============================================
-- Users Table
-- Tests: Unique constraints, nullable columns, various types
-- ============================================
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    username VARCHAR(50) NOT NULL UNIQUE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),

    -- Testing NULL values in statistics
    phone VARCHAR(20),
    alternate_email VARCHAR(255),

    -- Temporal
    birth_date DATE,
    registered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP WITH TIME ZONE,

    -- Boolean
    is_verified BOOLEAN DEFAULT false,
    is_premium BOOLEAN DEFAULT false,

    -- Network and special types
    last_login_ip INET,
    user_uuid UUID DEFAULT gen_random_uuid(),
    preferences JSONB DEFAULT '{}'::jsonb,

    CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'),
    CONSTRAINT valid_age CHECK (birth_date IS NULL OR birth_date < CURRENT_DATE)
);

COMMENT ON TABLE users IS 'User accounts with diverse data types and constraints';

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_verified ON users(is_verified);
CREATE INDEX idx_users_last_login ON users(last_login_at);
CREATE INDEX idx_users_preferences ON users USING GIN(preferences);

-- ============================================
-- Orders Table
-- Tests: Composite foreign keys, many-to-many relationships, aggregations
-- ============================================
CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    order_number VARCHAR(50) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,

    -- Order amounts for statistical analysis
    subtotal NUMERIC(12, 2) NOT NULL CHECK (subtotal >= 0),
    tax_amount NUMERIC(12, 2) DEFAULT 0 CHECK (tax_amount >= 0),
    shipping_amount NUMERIC(12, 2) DEFAULT 0 CHECK (shipping_amount >= 0),
    total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0),

    -- Order status for categorical statistics
    status VARCHAR(20) NOT NULL DEFAULT 'pending',

    -- Temporal tracking
    ordered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    shipped_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,

    -- Address (for JOIN testing)
    shipping_address TEXT,
    shipping_city VARCHAR(100),
    shipping_state VARCHAR(50),
    shipping_postal_code VARCHAR(20),
    shipping_country VARCHAR(2) DEFAULT 'US',

    notes TEXT,

    CONSTRAINT valid_status CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled', 'refunded')),
    CONSTRAINT valid_total CHECK (total_amount = subtotal + tax_amount + shipping_amount),
    CONSTRAINT valid_shipped_sequence CHECK (shipped_at IS NULL OR shipped_at >= ordered_at),
    CONSTRAINT valid_delivered_sequence CHECK (delivered_at IS NULL OR delivered_at >= shipped_at)
);

COMMENT ON TABLE orders IS 'Customer orders with complex constraints and relationships';

CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_ordered_at ON orders(ordered_at);
CREATE INDEX idx_orders_number ON orders(order_number);

-- ============================================
-- Order Items Table (Junction Table)
-- Tests: Composite primary keys, many-to-many relationships
-- ============================================
CREATE TABLE order_items (
    order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL,

    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    discount_amount NUMERIC(10, 2) DEFAULT 0 CHECK (discount_amount >= 0),
    line_total NUMERIC(12, 2) NOT NULL CHECK (line_total >= 0),

    PRIMARY KEY (order_id, line_number),

    CONSTRAINT valid_line_total CHECK (line_total = (quantity * unit_price) - discount_amount)
);

COMMENT ON TABLE order_items IS 'Order line items with composite primary key';

CREATE INDEX idx_order_items_product ON order_items(product_id);

-- ============================================
-- Product Reviews Table
-- Tests: Rating distributions, text analysis, aggregations
-- ============================================
CREATE TABLE product_reviews (
    review_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title VARCHAR(200),
    review_text TEXT,

    helpful_count INTEGER DEFAULT 0 CHECK (helpful_count >= 0),
    verified_purchase BOOLEAN DEFAULT false,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT unique_user_product_review UNIQUE (product_id, user_id)
);

COMMENT ON TABLE product_reviews IS 'Product reviews for testing rating distributions';

CREATE INDEX idx_reviews_product ON product_reviews(product_id);
CREATE INDEX idx_reviews_user ON product_reviews(user_id);
CREATE INDEX idx_reviews_rating ON product_reviews(rating);
CREATE INDEX idx_reviews_created ON product_reviews(created_at);

-- ============================================
-- Data Type Showcase Table
-- Tests: PostgreSQL-specific types, serialization edge cases
-- ============================================
CREATE TABLE data_type_examples (
    id SERIAL PRIMARY KEY,

    -- Numeric types
    smallint_col SMALLINT,
    integer_col INTEGER,
    bigint_col BIGINT,
    decimal_col DECIMAL(15, 5),
    numeric_col NUMERIC(20, 10),
    real_col REAL,
    double_col DOUBLE PRECISION,

    -- Character types
    char_col CHAR(10),
    varchar_col VARCHAR(100),
    text_col TEXT,

    -- Temporal types
    date_col DATE,
    time_col TIME,
    timetz_col TIME WITH TIME ZONE,
    timestamp_col TIMESTAMP,
    timestamptz_col TIMESTAMP WITH TIME ZONE,
    interval_col INTERVAL,

    -- Boolean
    boolean_col BOOLEAN,

    -- UUID
    uuid_col UUID,

    -- Network types
    inet_col INET,
    cidr_col CIDR,
    macaddr_col MACADDR,

    -- JSON types
    json_col JSON,
    jsonb_col JSONB,

    -- Arrays
    int_array_col INTEGER[],
    text_array_col TEXT[],

    -- Geometric types (for serialization testing)
    point_col POINT,

    -- Binary
    bytea_col BYTEA,

    -- Money
    money_col MONEY
);

COMMENT ON TABLE data_type_examples IS 'Comprehensive data type coverage for serialization testing';

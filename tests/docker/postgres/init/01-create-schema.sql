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
COMMENT ON COLUMN categories.category_id IS 'Auto-incrementing primary key';
COMMENT ON COLUMN categories.name IS 'Category display name, must be unique';
COMMENT ON COLUMN categories.description IS 'Optional detailed description of the category';
COMMENT ON COLUMN categories.parent_category_id IS 'Self-referencing foreign key for category hierarchy';
COMMENT ON COLUMN categories.created_at IS 'Timestamp when category was created';
COMMENT ON COLUMN categories.is_active IS 'Soft delete flag: false means category is hidden';
COMMENT ON COLUMN categories.metadata IS 'Flexible JSON storage for category attributes like icon, color, sort_order';

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
COMMENT ON COLUMN products.product_id IS 'Unique product identifier';
COMMENT ON COLUMN products.sku IS 'Stock Keeping Unit - unique inventory code';
COMMENT ON COLUMN products.name IS 'Product display name shown to customers';
COMMENT ON COLUMN products.description IS 'Full product description with HTML allowed';
COMMENT ON COLUMN products.category_id IS 'FK to categories table, required for all products';
COMMENT ON COLUMN products.price IS 'Current selling price in USD, must be >= 0';
COMMENT ON COLUMN products.cost IS 'Wholesale cost for margin calculations';
COMMENT ON COLUMN products.weight_kg IS 'Shipping weight in kilograms';
COMMENT ON COLUMN products.stock_quantity IS 'Current inventory count, 0 means out of stock';
COMMENT ON COLUMN products.created_at IS 'Product creation timestamp';
COMMENT ON COLUMN products.updated_at IS 'Last modification timestamp';
COMMENT ON COLUMN products.discontinued_at IS 'NULL if active, set when product is discontinued';
COMMENT ON COLUMN products.is_featured IS 'Show in featured products carousel on homepage';
COMMENT ON COLUMN products.product_uuid IS 'UUID for testing UUID serialization';
COMMENT ON COLUMN products.tags IS 'Array of searchable tags like ["organic", "sale", "new"]';
COMMENT ON COLUMN products.supplier_ip IS 'IP address of supplier API for inventory sync';

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
COMMENT ON COLUMN users.user_id IS 'Unique user identifier';
COMMENT ON COLUMN users.email IS 'Primary contact email, used for login and notifications';
COMMENT ON COLUMN users.username IS 'Public display name, unique across platform';
COMMENT ON COLUMN users.first_name IS 'Legal first name for orders and support';
COMMENT ON COLUMN users.last_name IS 'Legal last name for orders and support';
COMMENT ON COLUMN users.phone IS 'Phone number with country code, e.g., +1-555-123-4567';
COMMENT ON COLUMN users.alternate_email IS 'Secondary email for account recovery';
COMMENT ON COLUMN users.birth_date IS 'Date of birth for age verification';
COMMENT ON COLUMN users.registered_at IS 'Account creation timestamp';
COMMENT ON COLUMN users.last_login_at IS 'Most recent successful login';
COMMENT ON COLUMN users.is_verified IS 'Email verification status';
COMMENT ON COLUMN users.is_premium IS 'Paid subscription status';
COMMENT ON COLUMN users.last_login_ip IS 'IP address from last login for security auditing';
COMMENT ON COLUMN users.user_uuid IS 'External-facing UUID (never expose user_id)';
COMMENT ON COLUMN users.preferences IS 'User settings: {"theme": "dark", "notifications": true, "language": "en"}';

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
COMMENT ON COLUMN orders.order_id IS 'Internal order identifier';
COMMENT ON COLUMN orders.order_number IS 'Customer-facing order reference like ORD-2024-00001';
COMMENT ON COLUMN orders.user_id IS 'FK to users table';
COMMENT ON COLUMN orders.subtotal IS 'Sum of line items before tax and shipping';
COMMENT ON COLUMN orders.tax_amount IS 'Calculated tax based on shipping address';
COMMENT ON COLUMN orders.shipping_amount IS 'Shipping cost based on carrier and weight';
COMMENT ON COLUMN orders.total_amount IS 'Final amount charged: subtotal + tax + shipping';
COMMENT ON COLUMN orders.status IS 'Order lifecycle: pending -> processing -> shipped -> delivered (or cancelled/refunded)';
COMMENT ON COLUMN orders.ordered_at IS 'When customer placed the order';
COMMENT ON COLUMN orders.shipped_at IS 'When order left warehouse';
COMMENT ON COLUMN orders.delivered_at IS 'Carrier delivery confirmation timestamp';
COMMENT ON COLUMN orders.shipping_address IS 'Full street address';
COMMENT ON COLUMN orders.shipping_city IS 'City for shipping';
COMMENT ON COLUMN orders.shipping_state IS 'State/province code';
COMMENT ON COLUMN orders.shipping_postal_code IS 'ZIP/postal code';
COMMENT ON COLUMN orders.shipping_country IS 'ISO 3166-1 alpha-2 country code';
COMMENT ON COLUMN orders.notes IS 'Customer special instructions';

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
COMMENT ON COLUMN order_items.order_id IS 'FK to orders table, part of composite PK';
COMMENT ON COLUMN order_items.product_id IS 'FK to products table';
COMMENT ON COLUMN order_items.line_number IS 'Sequential line number within order, part of composite PK';
COMMENT ON COLUMN order_items.quantity IS 'Number of units ordered, must be > 0';
COMMENT ON COLUMN order_items.unit_price IS 'Price per unit at time of order (may differ from current product price)';
COMMENT ON COLUMN order_items.discount_amount IS 'Per-line discount applied';
COMMENT ON COLUMN order_items.line_total IS 'Calculated: (quantity * unit_price) - discount_amount';

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
COMMENT ON COLUMN product_reviews.review_id IS 'Unique review identifier';
COMMENT ON COLUMN product_reviews.product_id IS 'FK to products table';
COMMENT ON COLUMN product_reviews.user_id IS 'FK to users table, each user can review a product once';
COMMENT ON COLUMN product_reviews.rating IS 'Star rating 1-5, required';
COMMENT ON COLUMN product_reviews.title IS 'Review headline';
COMMENT ON COLUMN product_reviews.review_text IS 'Full review content';
COMMENT ON COLUMN product_reviews.helpful_count IS 'Number of "helpful" votes from other users';
COMMENT ON COLUMN product_reviews.verified_purchase IS 'True if reviewer actually purchased this product';
COMMENT ON COLUMN product_reviews.created_at IS 'When review was submitted';
COMMENT ON COLUMN product_reviews.updated_at IS 'Last edit timestamp';

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

COMMENT ON TABLE data_type_examples IS 'Comprehensive data type coverage for serialization testing. This table contains one column of each PostgreSQL data type to verify the MCP server correctly handles all type conversions and JSON serialization.';
COMMENT ON COLUMN data_type_examples.id IS 'Auto-incrementing primary key';
COMMENT ON COLUMN data_type_examples.smallint_col IS 'PostgreSQL SMALLINT: -32768 to 32767';
COMMENT ON COLUMN data_type_examples.integer_col IS 'PostgreSQL INTEGER: -2147483648 to 2147483647';
COMMENT ON COLUMN data_type_examples.bigint_col IS 'PostgreSQL BIGINT: -9223372036854775808 to 9223372036854775807';
COMMENT ON COLUMN data_type_examples.decimal_col IS 'DECIMAL(15,5) for precise decimal arithmetic';
COMMENT ON COLUMN data_type_examples.numeric_col IS 'NUMERIC(20,10) for high-precision calculations';
COMMENT ON COLUMN data_type_examples.real_col IS 'Single precision floating point (4 bytes)';
COMMENT ON COLUMN data_type_examples.double_col IS 'Double precision floating point (8 bytes)';
COMMENT ON COLUMN data_type_examples.char_col IS 'Fixed-length character string, padded with spaces';
COMMENT ON COLUMN data_type_examples.varchar_col IS 'Variable-length string up to 100 characters';
COMMENT ON COLUMN data_type_examples.text_col IS 'Unlimited length text storage';
COMMENT ON COLUMN data_type_examples.date_col IS 'Date without time component';
COMMENT ON COLUMN data_type_examples.time_col IS 'Time without timezone';
COMMENT ON COLUMN data_type_examples.timetz_col IS 'Time with timezone';
COMMENT ON COLUMN data_type_examples.timestamp_col IS 'Timestamp without timezone';
COMMENT ON COLUMN data_type_examples.timestamptz_col IS 'Timestamp with timezone (stored in UTC)';
COMMENT ON COLUMN data_type_examples.interval_col IS 'Time interval, e.g., ''1 year 2 months 3 days''';
COMMENT ON COLUMN data_type_examples.boolean_col IS 'Boolean: true/false/null';
COMMENT ON COLUMN data_type_examples.uuid_col IS 'Universally Unique Identifier (128-bit)';
COMMENT ON COLUMN data_type_examples.inet_col IS 'IPv4 or IPv6 host address';
COMMENT ON COLUMN data_type_examples.cidr_col IS 'IPv4 or IPv6 network address';
COMMENT ON COLUMN data_type_examples.macaddr_col IS 'MAC address (6 bytes)';
COMMENT ON COLUMN data_type_examples.json_col IS 'JSON data stored as text (slower queries, preserves formatting)';
COMMENT ON COLUMN data_type_examples.jsonb_col IS 'Binary JSON (faster queries, decomposed storage)';
COMMENT ON COLUMN data_type_examples.int_array_col IS 'Array of integers, e.g., ''{1, 2, 3}''';
COMMENT ON COLUMN data_type_examples.text_array_col IS 'Array of text values';
COMMENT ON COLUMN data_type_examples.point_col IS 'Geometric point (x, y)';
COMMENT ON COLUMN data_type_examples.bytea_col IS 'Binary data (byte array)';
-- Very long comment to test edge cases - 5000+ characters
COMMENT ON COLUMN data_type_examples.money_col IS 'PostgreSQL MONEY type for currency values with locale-aware formatting. This is an intentionally very long comment designed to test how the MCP server handles extremely lengthy column descriptions that might be found in legacy databases or auto-generated documentation systems.

DETAILED TECHNICAL DOCUMENTATION:
The money type stores a currency amount with a fixed fractional precision. The fractional precision is determined by the lc_monetary setting. The range is -92233720368547758.08 to +92233720368547758.07.

USAGE GUIDELINES:
1. Input is accepted in a variety of formats, including integer and floating-point literals, as well as typical currency formatting like ''$1,000.00''.
2. Output is generally in the latter form but depends on the locale.
3. Since the output is locale-sensitive, it might not work to load money data into a database that has a different setting of lc_monetary.

PRECISION AND ROUNDING:
- Values are stored as 64-bit integers
- Arithmetic operations maintain precision
- Division may result in rounding

COMMON PITFALLS:
- Different locales display different currency symbols
- Importing/exporting between locales can cause issues
- Consider using NUMERIC for multi-currency applications

MIGRATION NOTES:
When migrating from other database systems, be aware that:
- MySQL DECIMAL(19,4) is often a better equivalent
- Oracle NUMBER(19,4) provides similar functionality
- SQL Server MONEY has slightly different precision

BEST PRACTICES FOR AI INTEGRATION:
When querying this column via the MCP server, the AI should be aware that:
1. The values will be returned as strings with currency formatting
2. Locale settings affect the output format
3. For calculations, convert to numeric types first
4. Consider timezone implications for financial reporting

HISTORICAL CONTEXT:
The money type was one of the original PostgreSQL types and predates the SQL standard NUMERIC type. While still supported for backward compatibility, many applications now prefer NUMERIC or DECIMAL for new development due to their locale-independent behavior and explicit precision specification.

SERIALIZATION BEHAVIOR:
When serialized to JSON by the MCP server, money values are converted to strings to preserve formatting and avoid floating-point precision issues. This ensures that a value like $1,234.56 is transmitted exactly as displayed rather than as a potentially imprecise floating-point number.

END OF EXTENDED DOCUMENTATION.
This comment intentionally exceeds 4000 characters to test MCP server handling of very long database metadata. Real-world databases sometimes contain auto-generated or comprehensive documentation in column comments, and the system must handle these gracefully without truncation errors or performance degradation.';

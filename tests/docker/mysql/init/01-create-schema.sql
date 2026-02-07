SET NAMES utf8mb4;

-- ============================================
-- Categories Table with Comments
-- ============================================
CREATE TABLE categories (
    category_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-incrementing primary key',
    name VARCHAR(100) NOT NULL UNIQUE COMMENT 'Category display name, must be unique',
    description TEXT COMMENT 'Optional detailed description of the category',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when category was created'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Product categories for organizing inventory';

-- ============================================
-- Products Table with Comments
-- ============================================
CREATE TABLE products (
    product_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique product identifier',
    name VARCHAR(200) NOT NULL COMMENT 'Product display name shown to customers',
    category_id INT COMMENT 'FK to categories table',
    price DECIMAL(10, 2) NOT NULL COMMENT 'Current selling price in USD',
    stock_quantity INT DEFAULT 0 COMMENT 'Current inventory count, 0 means out of stock',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Product creation timestamp',
    FOREIGN KEY (category_id) REFERENCES categories(category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Product catalog with pricing and inventory';

-- ============================================
-- Users Table with Comments
-- ============================================
CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique user identifier',
    email VARCHAR(255) NOT NULL UNIQUE COMMENT 'Primary contact email, used for login and notifications',
    username VARCHAR(50) NOT NULL UNIQUE COMMENT 'Public display name, unique across platform',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Account creation timestamp'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='User accounts with authentication info';

-- ============================================
-- Comment Edge Case Table
-- Tests very long comments near MySQL limits
-- MySQL column comment limit: 1024 characters
-- MySQL table comment limit: 2048 characters
-- ============================================
CREATE TABLE comment_edge_cases (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Standard short comment',
    short_comment_col VARCHAR(50) COMMENT 'Short',
    medium_comment_col VARCHAR(100) COMMENT 'This is a medium-length comment that provides useful context about the column purpose and expected values.',
    long_comment_col TEXT COMMENT 'This is a long column comment designed to test MySQL handling of comments approaching the 1024 character limit. The MCP server must correctly retrieve and return this comment without truncation or errors. Column comments in MySQL are useful for providing context to AI tools that need to understand database schema semantics. When a large language model queries the database through the MCP server, these comments help it understand the purpose of each column, expected value ranges, business rules, and relationships to other data. This enables more accurate SQL query generation and better data interpretation. Comments like this one might be found in enterprise databases with comprehensive documentation requirements. Total characters in this comment should be close to the MySQL limit of 1024 characters for column comments. Adding more text to reach approximately 1000 chars here.'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Table for testing comment length edge cases. MySQL table comments can be up to 2048 characters. This table exists specifically to verify the MCP server correctly handles various comment lengths from very short to near the maximum allowed. The comment retrieval and JSON serialization must work properly regardless of comment length. Testing edge cases like this ensures robust handling of real-world databases that may contain extensive documentation in their metadata. This comment is intentionally long to test the near-limit case. Adding padding to approach 2048 chars. More content here to reach the limit safely. Enterprise databases often have extensive comments.';

CREATE INDEX idx_products_name ON products(name);
CREATE INDEX idx_users_email ON users(email);

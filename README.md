# db-connect-mcp - Multi-Database MCP Server

A read-only MCP (Model Context Protocol) server for exploratory data analysis across multiple database systems. This server provides safe, read-only access to PostgreSQL, MySQL, and ClickHouse databases with comprehensive analysis capabilities.

## Quick Start

1. **Install:**
   ```bash
   pip install db-connect-mcp
   ```

2. **Add to Claude Desktop** `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "db-connect": {
         "command": "python",
         "args": ["-m", "db_connect_mcp"],
         "env": {
           "DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
         }
       }
     }
   }
   ```

3. **Restart Claude Desktop** and start querying your database!

> **Note**: Using `python -m db_connect_mcp` ensures the command works even if Python's Scripts directory isn't in your PATH.

## Features

### 🗄️ Multi-Database Support
- **PostgreSQL** - Full support with advanced metadata and statistics
- **MySQL** - Complete support for MySQL and MariaDB databases
- **ClickHouse** - Support for analytical workloads and columnar storage

### 🔍 Database Exploration
- **List schemas** - View all schemas in the database
- **List tables** - See all tables with metadata (size, row counts, comments)
- **Describe tables** - Get detailed column information, indexes, and constraints
- **View relationships** - Understand foreign key relationships between tables

### 📊 Data Analysis
- **Column profiling** - Statistical analysis of column data
  - Basic statistics (count, unique values, nulls)
  - Numeric statistics (mean, median, std dev, quartiles)
  - Value frequency distribution
  - Cardinality analysis
- **Data sampling** - Preview table data with configurable limits
- **Custom queries** - Execute read-only SQL queries safely
- **Database profiling** - Get high-level database metrics and largest tables

### 🔒 Safety Features
- **Read-only enforcement** - All connections are read-only at multiple levels
- **Query validation** - Only SELECT and WITH queries are allowed
- **Automatic limits** - Queries are automatically limited to prevent large result sets
- **Connection string safety** - Automatically adds read-only parameters
- **Database-specific safety** - Each adapter implements appropriate safety measures

## Installation

### Prerequisites
- **Python 3.10 or higher**
- **A database**: PostgreSQL (9.6+), MySQL/MariaDB (5.7+/10.2+), or ClickHouse

### Install via pip

```bash
pip install db-connect-mcp
```

That's it! The package is now ready to use.

> **For developers**: See [Development Guide](docs/DEVELOPMENT.md) for setting up a development environment.

## Configuration

Create a `.env` file with your database connection string:

```env
DATABASE_URL=your_database_connection_string_here
```

The server automatically detects the database type and adds appropriate read-only parameters.

### Connection String Examples

The server now provides more flexible and secure URL handling:
- **Automatic driver detection**: Async drivers are automatically added if not specified
- **JDBC URL support**: JDBC prefixes are automatically handled
  - `jdbc:postgresql://...` → `postgresql+asyncpg://...`
  - `jdbc:mysql://...` → `mysql+aiomysql://...`
  - Works with all dialect variations (e.g., `jdbc:postgres://`, `jdbc:mariadb://`)
- **Database dialect variations**: Common variations are automatically normalized
  - PostgreSQL: `postgresql`, `postgres`, `pg`, `psql`, `pgsql`
  - MySQL/MariaDB: `mysql`, `mariadb`, `maria`
  - ClickHouse: `clickhouse`, `ch`, `click`
- **Allowlist-based parameter filtering**: Only known-safe parameters are preserved
- **Database-specific parameters**: Each database type has its own set of supported parameters
- **Robust parsing**: Handles various URL formats gracefully

**PostgreSQL:**
```
# Simple URL (driver automatically added)
DATABASE_URL=postgresql://user:password@localhost:5432/mydb

# Common variations (all normalized to postgresql+asyncpg)
DATABASE_URL=postgres://user:pass@host:5432/db  # Heroku, AWS RDS style
DATABASE_URL=pg://user:pass@host:5432/db         # Short form
DATABASE_URL=psql://user:pass@host:5432/db       # CLI style

# JDBC URLs (automatically converted)
DATABASE_URL=jdbc:postgresql://user:pass@host:5432/db  # From Java apps
DATABASE_URL=jdbc:postgres://user:pass@host:5432/db    # JDBC with variant

# With explicit async driver
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# With supported parameters (see list below)
DATABASE_URL=postgres://user:pass@host:5432/db?application_name=myapp&connect_timeout=10
```

**Supported PostgreSQL Parameters:**
- `application_name` - Identifies your app in pg_stat_activity (useful for monitoring)
- `connect_timeout` - Connection timeout in seconds
- `command_timeout` - Default timeout for operations
- `ssl` / `sslmode` - SSL connection requirements (automatically converted for asyncpg compatibility)
- `server_settings` - Server settings dictionary
- `options` - Command-line options to send to server
- Performance tuning: `prepared_statement_cache_size`, `max_cached_statement_lifetime`, etc.

**MySQL/MariaDB:**
```
# Simple URL (driver automatically added)
DATABASE_URL=mysql://root:password@localhost:3306/mydb

# MariaDB URLs (normalized to mysql+aiomysql)
DATABASE_URL=mariadb://user:pass@host:3306/db    # MariaDB style
DATABASE_URL=maria://user:pass@host:3306/db      # Short form

# JDBC URLs (automatically converted)
DATABASE_URL=jdbc:mysql://user:pass@host:3306/db     # From Java apps
DATABASE_URL=jdbc:mariadb://user:pass@host:3306/db   # JDBC MariaDB

# With explicit async driver
DATABASE_URL=mysql+aiomysql://user:pass@host:3306/db

# With charset (critical for proper Unicode support)
DATABASE_URL=mariadb://user:pass@remote.host:3306/db?charset=utf8mb4
```

**Supported MySQL Parameters:**
- `charset` - Character encoding (e.g., utf8mb4) - **critical for data integrity**
- `use_unicode` - Enable Unicode support
- `connect_timeout`, `read_timeout`, `write_timeout` - Various timeouts
- `autocommit` - Transaction autocommit mode
- `init_command` - Initial SQL command to run
- `sql_mode` - SQL mode settings
- `time_zone` - Time zone setting

**ClickHouse:**
```
# Simple URL (driver automatically added)
DATABASE_URL=clickhouse://default:@localhost:9000/default

# Short forms (normalized to clickhouse+asynch)
DATABASE_URL=ch://user:pass@host:9000/db         # Short form
DATABASE_URL=click://user:pass@host:9000/db      # Alternative

# JDBC URLs (automatically converted)
DATABASE_URL=jdbc:clickhouse://user:pass@host:9000/db  # From Java apps
DATABASE_URL=jdbc:ch://user:pass@host:9000/db         # JDBC with short form

# With explicit async driver
DATABASE_URL=clickhouse+asynch://user:pass@host:9000/db

# With performance settings
DATABASE_URL=ch://user:pass@host:9000/db?timeout=60&max_threads=4
```

**Supported ClickHouse Parameters:**
- `database` - Default database selection
- `timeout`, `connect_timeout`, `send_receive_timeout` - Various timeouts
- `compress`, `compression` - Enable compression
- `max_block_size`, `max_threads` - Performance tuning

**Note:**
- SSL parameters (`ssl`, `sslmode`) are automatically converted to the correct format for asyncpg
- Certificate file parameters (`sslcert`, `sslkey`, `sslrootcert`) are filtered out as they can cause compatibility issues
- Only parameters known to work with async drivers are preserved

## Usage

### Running the Server

```bash
# Run the server (works everywhere, no PATH configuration needed)
python -m db_connect_mcp

# With environment variable
DATABASE_URL="postgresql://user:pass@host:5432/db" python -m db_connect_mcp
```

> **Note**: Using `python -m db_connect_mcp` works regardless of whether Python's Scripts directory is in your PATH.

### Using with Claude Desktop

Add the server to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "db-connect": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db"
      }
    }
  }
}
```

**Multiple database connections:**

```json
{
  "mcpServers": {
    "postgres-prod": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@pg-host:5432/db"
      }
    },
    "mysql-analytics": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "mysql+aiomysql://user:pass@mysql-host:3306/analytics"
      }
    }
  }
}
```

> **For development**: See [Development Guide](docs/DEVELOPMENT.md) for running from source with uv.

## Database Feature Support

| Feature | PostgreSQL | MySQL | ClickHouse |
|---------|------------|-------|------------|
| Schemas | ✅ Full | ✅ Full | ✅ Full |
| Tables | ✅ Full | ✅ Full | ✅ Full |
| Views | ✅ Full | ✅ Full | ✅ Full |
| Indexes | ✅ Full | ✅ Full | ⚠️ Limited |
| Foreign Keys | ✅ Full | ✅ Full | ❌ No |
| Constraints | ✅ Full | ✅ Full | ⚠️ Limited |
| Table Size | ✅ Exact | ✅ Exact | ✅ Exact |
| Row Count | ✅ Exact | ✅ Exact | ✅ Exact |
| Column Stats | ✅ Full | ✅ Full | ✅ Full |
| Sampling | ✅ Full | ✅ Full | ✅ Full |

## Available Tools

### list_schemas
List all schemas in the database.

### list_tables
List all tables in a schema with metadata.
- Parameters:
  - `schema` (optional): Schema name (default: "public")

### describe_table
Get detailed information about a table.
- Parameters:
  - `table_name`: Name of the table
  - `schema` (optional): Schema name (default: "public")

### analyze_column
Analyze a column with statistics and distribution.
- Parameters:
  - `table_name`: Name of the table
  - `column_name`: Name of the column
  - `schema` (optional): Schema name (default: "public")

### sample_data
Get a sample of data from a table.
- Parameters:
  - `table_name`: Name of the table
  - `schema` (optional): Schema name (default: "public")
  - `limit` (optional): Number of rows (default: 100, max: 1000)

### execute_query
Execute a read-only SQL query.
- Parameters:
  - `query`: SQL query (must be SELECT or WITH)
  - `limit` (optional): Maximum rows (default: 1000, max: 10000)

### get_table_relationships
Get foreign key relationships in a schema.
- Parameters:
  - `schema` (optional): Schema name (default: "public")

### profile_database
Get a high-level profile of the entire database.

## Example Usage in Claude

Once configured, you can use the server in Claude:

```
"Can you analyze my database and tell me about the table structure?"

"Show me the relationships between tables in the public schema"

"What's the distribution of values in the users.created_at column?"

"Give me a sample of data from the orders table"

"Run this query: SELECT COUNT(*) FROM users WHERE created_at > '2024-01-01'"
```

### Database-Specific Examples

**Working with PostgreSQL:**
```
"List all schemas except system ones"
"Show me the foreign key relationships in the sales schema"
"Analyze the performance of indexes on the products table"
```

**Working with MySQL:**
```
"What storage engines are being used in my database?"
"Show me all tables in the information_schema"
"Analyze the customer_orders table structure"
```

**Working with ClickHouse:**
```
"Show me the partitions for the events table"
"What's the compression ratio for the analytics.clicks table?"
"Sample 1000 rows from the metrics table"
```

## Safety and Security

- **Read-only by design**: The server enforces read-only access at multiple levels:
  - Connection string parameters
  - Session-level settings
  - Query validation

- **No data modification**: INSERT, UPDATE, DELETE, CREATE, DROP, and other modification statements are blocked

- **Query limits**: All queries are automatically limited to prevent excessive resource usage

- **No sensitive operations**: No access to system catalogs or administrative functions

## Development

For detailed development setup, testing, and contribution guidelines, see the [Development Guide](docs/DEVELOPMENT.md).

### Project Structure
```
db-connect-mcp/
├── src/
│   └── db_connect_mcp/
│       ├── adapters/         # Database-specific adapters
│       │   ├── __init__.py
│       │   ├── base.py      # Base adapter interface
│       │   ├── postgresql.py # PostgreSQL adapter
│       │   ├── mysql.py     # MySQL adapter
│       │   └── clickhouse.py # ClickHouse adapter
│       ├── core/            # Core functionality
│       │   ├── __init__.py
│       │   ├── connection.py # Database connection management
│       │   ├── executor.py  # Query execution
│       │   ├── inspector.py # Metadata inspection
│       │   └── analyzer.py  # Statistical analysis
│       ├── models/          # Data models
│       │   ├── __init__.py
│       │   ├── capabilities.py # Database capabilities
│       │   ├── config.py    # Configuration models
│       │   ├── database.py  # Database models
│       │   ├── query.py     # Query models
│       │   ├── statistics.py # Statistics models
│       │   └── table.py     # Table metadata models
│       ├── __init__.py
│       ├── __main__.py      # Module entry point
│       └── server.py        # Main MCP server implementation
├── tests/
│   ├── conftest.py      # Test configuration
│   └── test_server.py   # Integration tests
├── .env.example         # Example environment configuration
├── main.py             # Legacy entry point (optional)
├── pyproject.toml      # Project dependencies and console scripts
└── README.md          # This file
```

### Architecture

The server uses an adapter pattern to support multiple database systems:

- **Adapters**: Each database type has its own adapter that implements database-specific functionality
- **Core**: Shared functionality for connection management, query execution, and metadata inspection
- **Models**: Pydantic models for type safety and validation
- **Server**: MCP server implementation that routes requests to appropriate components

### Running Tests

See the [Development Guide](docs/DEVELOPMENT.md#running-tests) and [Test Guide](tests/README.md) for detailed testing instructions.

## Troubleshooting

### Connection Issues
- Verify your DATABASE_URL is correct and includes the appropriate driver
- Check network connectivity to the database
- Ensure the database user has appropriate read permissions
- For PostgreSQL: Check if SSL is required (`?ssl=require`)
- For MySQL: Verify charset settings (`?charset=utf8mb4`)
- For ClickHouse: Check port (default is 9000 for native, 8123 for HTTP)

### Database-Specific Issues

**PostgreSQL:**
- Ensure `asyncpg` driver is specified for async operations
- SSL certificates may be required for cloud databases

**MySQL/MariaDB:**
- Use `aiomysql` driver for async support
- Check MySQL version compatibility (5.7+ or MariaDB 10.2+)
- Verify charset and collation settings

**ClickHouse:**
- Use `asynch` driver for async operations
- Note that ClickHouse has limited support for foreign keys and constraints
- Some statistical functions may not be available

### Permission Errors
- The database user needs at least SELECT permissions on the schemas/tables you want to analyze
- Some statistical functions may require additional permissions
- ClickHouse may require specific permissions for system tables

### Large Result Sets
- Use the `limit` parameter to control result size
- The server automatically limits results to prevent memory issues
- For large analyses, consider using more specific queries

## Contributing

Contributions are welcome! The server is designed to be read-only and safe by default. Any new features should maintain these safety guarantees.

## License

MIT License - See LICENSE file for details

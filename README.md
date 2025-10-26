# db-connect-mcp - Multi-Database MCP Server

A read-only MCP (Model Context Protocol) server for exploratory data analysis across multiple database systems. This server provides safe, read-only access to PostgreSQL, MySQL, and ClickHouse databases with comprehensive analysis capabilities.

## Quick Start

1. **Install:**
   ```bash
   git clone https://github.com/yugui923/db-connect-mcp.git
   cd db-connect-mcp
   uv sync
   ```

2. **Configure** `.env`:
   ```env
   DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/mydb
   ```

3. **Add to Claude Desktop** `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "db-connect": {
         "command": "uv",
         "args": ["run", "python", "C:/path/to/db-connect-mcp/main.py"],
         "env": {
           "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/mydb"
         }
       }
     }
   }
   ```

4. **Restart Claude Desktop** and start querying your database!

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
- Python 3.13 or higher
- One or more of:
  - PostgreSQL database (9.6+)
  - MySQL/MariaDB database (5.7+/10.2+)
  - ClickHouse database
- `uv` package manager (or pip)

### Setup with uv

1. Clone the repository:
```bash
git clone https://github.com/yourusername/db-connect-mcp.git
cd db-connect-mcp
```

2. Install dependencies:
```bash
uv sync
```

3. Configure database connection:
```bash
cp .env.example .env
# Edit .env with your database connection string
```

## Configuration

Create a `.env` file with your database connection string:

```env
DATABASE_URL=your_database_connection_string_here
```

The server automatically detects the database type and adds appropriate read-only parameters.

### Connection String Examples

**PostgreSQL:**
```
# Local database
DATABASE_URL=postgresql://postgres:password@localhost:5432/mydb

# With asyncpg driver (recommended for PostgreSQL)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# Remote with SSL
DATABASE_URL=postgresql+asyncpg://user:pass@remote.host:5432/db?ssl=require
```

**MySQL/MariaDB:**
```
# Local database
DATABASE_URL=mysql://root:password@localhost:3306/mydb

# With aiomysql driver (recommended for async)
DATABASE_URL=mysql+aiomysql://user:pass@host:3306/db

# Remote with charset
DATABASE_URL=mysql+aiomysql://user:pass@remote.host:3306/db?charset=utf8mb4
```

**ClickHouse:**
```
# Local database
DATABASE_URL=clickhouse://default:@localhost:9000/default

# With asynch driver
DATABASE_URL=clickhouse+asynch://user:pass@host:9000/db

# With specific settings
DATABASE_URL=clickhouse+asynch://user:pass@host:9000/db?timeout=60
```

## Usage

### Running the Server

Run the MCP server:
```bash
python main.py
```

Or with uv:
```bash
uv run python main.py
```

### Using with Claude Desktop

Add the server to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "db-connect": {
      "command": "python",
      "args": ["C:/path/to/db-connect-mcp/main.py"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/db"
      }
    }
  }
}
```

Or using uv:
```json
{
  "mcpServers": {
    "db-connect": {
      "command": "uv",
      "args": ["run", "python", "C:/path/to/db-connect-mcp/main.py"],
      "env": {
        "DATABASE_URL": "mysql+aiomysql://user:pass@host:3306/db"
      }
    }
  }
}
```

You can configure multiple database connections:
```json
{
  "mcpServers": {
    "postgres-prod": {
      "command": "uv",
      "args": ["run", "python", "C:/path/to/db-connect-mcp/main.py"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@pg-host:5432/db"
      }
    },
    "mysql-analytics": {
      "command": "uv",
      "args": ["run", "python", "C:/path/to/db-connect-mcp/main.py"],
      "env": {
        "DATABASE_URL": "mysql+aiomysql://user:pass@mysql-host:3306/analytics"
      }
    }
  }
}
```

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

### Project Structure
```
db-connect-mcp/
├── src/
│   ├── adapters/         # Database-specific adapters
│   │   ├── __init__.py
│   │   ├── base.py      # Base adapter interface
│   │   ├── postgresql.py # PostgreSQL adapter
│   │   ├── mysql.py     # MySQL adapter
│   │   └── clickhouse.py # ClickHouse adapter
│   ├── core/            # Core functionality
│   │   ├── __init__.py
│   │   ├── connection.py # Database connection management
│   │   ├── executor.py  # Query execution
│   │   ├── inspector.py # Metadata inspection
│   │   └── analyzer.py  # Statistical analysis
│   ├── models/          # Data models
│   │   ├── __init__.py
│   │   ├── capabilities.py # Database capabilities
│   │   ├── config.py    # Configuration models
│   │   ├── database.py  # Database models
│   │   ├── query.py     # Query models
│   │   ├── statistics.py # Statistics models
│   │   └── table.py     # Table metadata models
│   ├── __init__.py
│   ├── __main__.py
│   └── server.py        # Main MCP server implementation
├── tests/
│   ├── conftest.py      # Test configuration
│   └── test_server.py   # Integration tests
├── .env.example         # Example environment configuration
├── main.py             # Entry point
├── pyproject.toml      # Project dependencies
└── README.md          # This file
```

### Architecture

The server uses an adapter pattern to support multiple database systems:

- **Adapters**: Each database type has its own adapter that implements database-specific functionality
- **Core**: Shared functionality for connection management, query execution, and metadata inspection
- **Models**: Pydantic models for type safety and validation
- **Server**: MCP server implementation that routes requests to appropriate components

### Running Tests
```bash
# Run integration tests
uv run python tests/test_server.py

# Or with pytest (when available)
uv run pytest tests/
```

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

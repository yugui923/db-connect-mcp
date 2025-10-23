# pg-da - PostgreSQL Data Analyst MCP Server

A read-only MCP (Model Context Protocol) server for exploratory data analysis on PostgreSQL databases. This server provides safe, read-only access to PostgreSQL databases with comprehensive analysis capabilities.

## Features

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

## Installation

### Prerequisites
- Python 3.10 or higher
- PostgreSQL database (any version from 9.6+)
- `uv` package manager (or pip)

### Setup with uv

1. Clone the repository:
```bash
git clone https://github.com/yourusername/pg-da.git
cd pg-da
```

2. Install dependencies:
```bash
uv sync
```

3. Configure database connection:
```bash
cp .env.example .env
# Edit .env with your PostgreSQL connection string
```

## Configuration

Create a `.env` file with your PostgreSQL connection string:

```env
DATABASE_URL=postgresql://username:password@host:port/database
```

The server automatically adds read-only parameters to ensure safe operation.

### Connection String Examples

Local database:
```
DATABASE_URL=postgresql://postgres:password@localhost:5432/mydb
```

Remote database with SSL:
```
DATABASE_URL=postgresql://user:pass@remote.host:5432/db?sslmode=require
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
    "pg-da": {
      "command": "python",
      "args": ["C:/path/to/pg-da/main.py"],
      "env": {
        "DATABASE_URL": "postgresql://user:pass@host:5432/db"
      }
    }
  }
}
```

Or using uv:
```json
{
  "mcpServers": {
    "pg-da": {
      "command": "uv",
      "args": ["run", "python", "C:/path/to/pg-da/main.py"],
      "env": {
        "DATABASE_URL": "postgresql://user:pass@host:5432/db"
      }
    }
  }
}
```

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
pg-da/
├── src/
│   └── pg_da/
│       ├── __init__.py
│       ├── __main__.py
│       └── server.py      # Main MCP server implementation
├── .env.example          # Example environment configuration
├── main.py              # Entry point
├── pyproject.toml       # Project dependencies
└── README.md           # This file
```

### Running Tests
```bash
# Add tests in tests/ directory
uv run pytest tests/
```

## Troubleshooting

### Connection Issues
- Verify your DATABASE_URL is correct
- Check network connectivity to the database
- Ensure the database user has appropriate read permissions
- Check if SSL is required for your database

### Permission Errors
- The database user needs at least SELECT permissions on the schemas/tables you want to analyze
- Some statistical functions may require additional permissions

### Large Result Sets
- Use the `limit` parameter to control result size
- The server automatically limits results to prevent memory issues
- For large analyses, consider using more specific queries

## Contributing

Contributions are welcome! The server is designed to be read-only and safe by default. Any new features should maintain these safety guarantees.

## License

MIT License - See LICENSE file for details

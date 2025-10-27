# Development Guide

This guide covers setting up a development environment for contributing to db-connect-mcp.

## Quick Setup

```bash
# Clone the repository
git clone https://github.com/yugui923/db-connect-mcp.git
cd db-connect-mcp

# Install dependencies using uv (recommended)
uv sync

# Or using pip
pip install -e ".[dev]"
```

## Prerequisites

### Python Version
- **Python 3.10 or higher** (tested on 3.10, 3.11, 3.12, 3.13)

### Database Systems (for testing)
- **PostgreSQL 9.6+** (optional)
- **MySQL/MariaDB 5.7+/10.2+** (optional)
- **ClickHouse** (optional)

### Development Tools
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer (recommended)
- Git for version control

## Installation Methods

### Option 1: Using uv (Recommended)

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh  # Unix
# or
irm https://astral.sh/uv/install.ps1 | iex       # Windows

# Clone and setup
git clone https://github.com/yugui923/db-connect-mcp.git
cd db-connect-mcp

# Install dependencies (creates virtual environment automatically)
uv sync

# Install with dev dependencies
uv sync --dev
```

### Option 2: Using pip

```bash
# Clone repository
git clone https://github.com/yugui923/db-connect-mcp.git
cd db-connect-mcp

# Create virtual environment
python -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # Unix
# or
.venv\Scripts\activate     # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

## Running the Server

### From Source (Development)

```bash
# Using the module (recommended)
python -m db_connect_mcp

# Using uv
uv run python -m db_connect_mcp

# With environment variables
DATABASE_URL="postgresql://..." python -m db_connect_mcp
```

### For Testing with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "db-connect-dev": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb"
      }
    }
  }
}
```

Or using uv (ensures dependencies are available):

```json
{
  "mcpServers": {
    "db-connect-dev": {
      "command": "uv",
      "args": ["--directory", "C:/path/to/db-connect-mcp", "run", "python", "-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb"
      }
    }
  }
}
```

## Development Workflow

### Code Quality Tools

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Fix linting issues automatically
uv run ruff check --fix .

# Type checking
uv run pyright src/

# Run all quality checks
uv run ruff format . && uv run ruff check . && uv run pyright src/
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_postgresql.py

# Run with verbose output
uv run pytest -v

# Run only PostgreSQL tests
uv run pytest -m postgresql
```

See [tests/README.md](../tests/README.md) for detailed testing documentation.

### Setting Up Test Databases

Create a `.env` file in the project root:

```env
# PostgreSQL test database
PG_TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/testdb

# MySQL test database (optional)
MYSQL_TEST_DATABASE_URL=mysql+aiomysql://user:password@localhost:3306/testdb

# ClickHouse test database (optional)
CH_TEST_DATABASE_URL=clickhouse+asynch://user:password@localhost:9000/testdb
```

## Project Structure

```
db-connect-mcp/
├── src/
│   └── db_connect_mcp/
│       ├── adapters/         # Database-specific adapters
│       │   ├── base.py      # Base adapter interface
│       │   ├── postgresql.py
│       │   ├── mysql.py
│       │   └── clickhouse.py
│       ├── core/            # Core functionality
│       │   ├── connection.py # Connection management
│       │   ├── executor.py  # Query execution
│       │   ├── inspector.py # Metadata inspection
│       │   └── analyzer.py  # Statistical analysis
│       ├── models/          # Pydantic models
│       │   ├── config.py
│       │   ├── database.py
│       │   ├── table.py
│       │   └── statistics.py
│       ├── __init__.py
│       ├── __main__.py      # Module entry point
│       └── server.py        # MCP server implementation
├── tests/                   # Test suite
├── docs/                    # Documentation
├── .env.example            # Example environment config
├── pyproject.toml          # Project configuration
└── README.md              # User documentation
```

## Architecture Overview

### Adapter Pattern

Each database type has its own adapter implementing the `BaseAdapter` interface:

- **BaseAdapter**: Defines the interface for all database operations
- **PostgresAdapter**: PostgreSQL-specific implementation
- **MySQLAdapter**: MySQL/MariaDB implementation
- **ClickHouseAdapter**: ClickHouse implementation

The adapter is selected automatically based on the `DATABASE_URL` dialect.

### Core Components

1. **DatabaseConnection** (`core/connection.py`)
   - Manages SQLAlchemy async/sync engines
   - Handles connection pooling
   - Enforces read-only mode

2. **MetadataInspector** (`core/inspector.py`)
   - Retrieves database metadata
   - Uses adapters for database-specific enrichment

3. **QueryExecutor** (`core/executor.py`)
   - Executes read-only SQL queries
   - Validates query safety
   - Applies automatic limits

4. **StatisticsAnalyzer** (`core/analyzer.py`)
   - Performs column profiling
   - Delegates to adapters for statistics

### MCP Server Integration

**DatabaseMCPServer** (`server.py`):
- Initializes core components with selected adapter
- Registers MCP tools based on database capabilities
- Routes tool calls to appropriate components
- Manages connection lifecycle

## Making Changes

### Adding a New Database Adapter

1. Create a new adapter file in `src/db_connect_mcp/adapters/`
2. Implement the `BaseAdapter` interface
3. Define capabilities in `models/capabilities.py`
4. Add adapter to factory in `adapters/__init__.py`
5. Add tests in `tests/`

### Adding a New MCP Tool

1. Add tool definition method in `server.py` (e.g., `_create_mytool_tool()`)
2. Add handler method (e.g., `handle_mytool()`)
3. Register in `list_tools()` handler
4. Add to `call_tool()` handlers dict
5. Add tests

### Code Style Guidelines

- **Type hints**: Use type hints for all function signatures
- **Async/await**: Use async/await for I/O operations
- **Error handling**: Use specific exceptions, provide helpful messages
- **Documentation**: Add docstrings to all public functions
- **Testing**: Write tests for new functionality

## Building and Publishing

### Building Distribution

```bash
# Build source and wheel distributions
uv build

# Or using build
python -m build

# Output in dist/
# - db_connect_mcp-X.Y.Z.tar.gz  (source)
# - db_connect_mcp-X.Y.Z-py3-none-any.whl  (wheel)
```

### Version Bumping

Update version in `pyproject.toml`:

```toml
[project]
version = "0.2.0"  # Update this
```

### Publishing to PyPI

```bash
# Build first
uv build

# Publish to TestPyPI (for testing)
uv publish --publish-url https://test.pypi.org/legacy/

# Publish to PyPI (production)
uv publish
```

Or use GitHub Actions workflow (`.github/workflows/publish.yml`).

## Troubleshooting

### Import Errors

```bash
# Reinstall in editable mode
pip install -e .
# or
uv sync
```

### Type Checking Errors

```bash
# Run pyright to see all errors
uv run pyright src/

# Check specific file
uv run pyright src/db_connect_mcp/server.py
```

### Database Connection Issues

- Verify `DATABASE_URL` format
- Check database is running and accessible
- Ensure database user has SELECT permissions
- For PostgreSQL: Check SSL requirements
- For MySQL: Verify charset settings (`?charset=utf8mb4`)

### Windows-Specific Issues

- Use `python` instead of `python3`
- Use backslashes or forward slashes in paths
- Event loop policy is automatically set for Windows

## Contributing

### Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and quality checks
5. Commit with descriptive messages
6. Push to your fork
7. Open a Pull Request

### Commit Message Format

```
type(scope): short description

Longer description if needed

- Bullet points for details
- Multiple points allowed
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

## Resources

- [Project README](../README.md) - User documentation
- [Test Guide](../tests/README.md) - Testing documentation
- [CLAUDE.md](../CLAUDE.md) - Claude Code guidance
- [MCP Documentation](https://modelcontextprotocol.io/) - MCP protocol reference
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/) - Database toolkit
- [Pydantic Docs](https://docs.pydantic.dev/) - Data validation

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/yugui923/db-connect-mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yugui923/db-connect-mcp/discussions)
- **Security**: Report security issues privately

## License

MIT License - See [LICENSE](../LICENSE) file for details.

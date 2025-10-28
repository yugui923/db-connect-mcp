# Setup Guide

This guide walks you through setting up the db-connect-mcp server for use with Claude Code and ChatGPT Desktop.

## Table of Contents

- [Interactive Setup (Recommended)](#interactive-setup-recommended)
- [Manual Setup](#manual-setup)
- [Configuration File Locations](#configuration-file-locations)
- [Multiple Database Connections](#multiple-database-connections)
- [Troubleshooting Setup](#troubleshooting-setup)

## Interactive Setup (Recommended)

The easiest way to set up db-connect-mcp is using the interactive setup wizard.

### Prerequisites

1. **Python 3.10 or higher** installed
2. **Database credentials** for your PostgreSQL, MySQL, or ClickHouse database
3. **Claude Code or ChatGPT Desktop** installed

### Running the Setup Wizard

1. **Install the package:**

   ```bash
   pip install db-connect-mcp
   ```

2. **Run the setup wizard:**

   ```bash
   db-connect-mcp setup
   ```

   Or using Python module syntax:

   ```bash
   python -m db_connect_mcp setup
   ```

3. **Follow the prompts:**

   The wizard will guide you through:

   ```
   🗄️  db-connect-mcp Setup Wizard

   This wizard will help you configure the MCP server for database exploration.

   Database Connection Setup
   ℹ Enter your database connection string.
   ℹ Supported formats:
     • PostgreSQL: postgresql+asyncpg://user:pass@host:port/dbname
     • MySQL:      mysql+aiomysql://user:pass@host:port/dbname
     • ClickHouse: clickhouse+asynch://user:pass@host:port/dbname

   Database URL: _
   ```

4. **Connection validation:**

   The wizard will attempt to connect to your database:

   ```
   ℹ Validating database connection...
   ✓ Connection successful!
   ℹ Connected to: PostgreSQL 14.5
   ```

5. **Choose clients to configure:**

   ```
   ℹ Which MCP clients would you like to configure?
     1. Claude Code (recommended)
     2. ChatGPT
     3. Both

   Choose (1/2/3): _
   ```

6. **Configuration saved:**

   ```
   Saving Configuration Files
   ℹ Creating backup: /path/to/config.json.backup
   ℹ Merged with existing configuration
   ✓ Config saved to: /path/to/config.json

   ✅ Setup Complete!

   ℹ Next steps:
     1. Restart Claude Code
     2. The 'db-connect' MCP server should appear in your tools

   ℹ To test the connection, try asking:
     "What databases are available?" or "Show me the schema"
   ```

7. **Restart your MCP client** (Claude Code or ChatGPT Desktop)

### What the Wizard Does

The setup wizard:

1. **Validates your database connection** by attempting to connect
2. **Detects your platform** (Windows, macOS, Linux) for correct config paths
3. **Backs up existing configurations** before making changes
4. **Merges with existing MCP servers** rather than overwriting
5. **Uses the correct Python executable** from your environment
6. **Sets the working directory** to the installed package location

## Manual Setup

If you prefer to configure manually or need more control:

### Step 1: Prepare Your Database URL

Format your connection string with the appropriate async driver:

**PostgreSQL:**
```
postgresql+asyncpg://user:password@host:5432/database
```

**MySQL:**
```
mysql+aiomysql://user:password@host:3306/database
```

**ClickHouse:**
```
clickhouse+asynch://user:password@host:9000/database
```

### Step 2: Locate Your Config File

**Claude Code:**

| Platform | Config Path |
|----------|-------------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

**ChatGPT Desktop:**

| Platform | Config Path |
|----------|-------------|
| Windows | `%USERPROFILE%\.chatgpt\mcp_config.json` |
| macOS | `~/Library/Application Support/ChatGPT/mcp_config.json` |
| Linux | `~/.config/chatgpt/mcp_config.json` |

### Step 3: Edit the Config File

1. **Open the config file** in your text editor

2. **Add or modify the mcpServers section:**

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

3. **Save the file**

4. **Restart Claude Code or ChatGPT Desktop**

## Configuration File Locations

### Windows

**Claude Code:**
```
C:\Users\YourUsername\AppData\Roaming\Claude\claude_desktop_config.json
```

**ChatGPT:**
```
C:\Users\YourUsername\.chatgpt\mcp_config.json
```

### macOS

**Claude Code:**
```
/Users/YourUsername/Library/Application Support/Claude/claude_desktop_config.json
```

**ChatGPT:**
```
/Users/YourUsername/Library/Application Support/ChatGPT/mcp_config.json
```

### Linux

**Claude Code:**
```
/home/yourusername/.config/Claude/claude_desktop_config.json
```

**ChatGPT:**
```
/home/yourusername/.config/chatgpt/mcp_config.json
```

## Multiple Database Connections

You can configure multiple database connections by adding more entries to the `mcpServers` object:

```json
{
  "mcpServers": {
    "postgres-prod": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@prod-host:5432/proddb"
      }
    },
    "mysql-analytics": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "mysql+aiomysql://user:pass@analytics-host:3306/analytics"
      }
    },
    "clickhouse-logs": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "clickhouse+asynch://default:@logs-host:9000/logs"
      }
    }
  }
}
```

Each server will appear as a separate tool in your MCP client with its own name.

## Troubleshooting Setup

### Connection Validation Fails

**Problem:** The wizard reports "Connection failed"

**Solutions:**

1. **Check your connection string format:**
   - Ensure you're using the correct async driver (`+asyncpg`, `+aiomysql`, `+asynch`)
   - Verify username, password, host, port, and database name are correct

2. **Test network connectivity:**
   ```bash
   # PostgreSQL
   telnet host 5432

   # MySQL
   telnet host 3306

   # ClickHouse
   telnet host 9000
   ```

3. **Check database permissions:**
   - Ensure the user has at least SELECT permissions
   - Try connecting with a database client first

4. **Verify SSL requirements:**
   - PostgreSQL: Add `?ssl=require` if SSL is mandatory
   - MySQL: Check if SSL certificates are needed

### Config File Not Found

**Problem:** The wizard can't find your config file

**Solutions:**

1. **Create the directory manually:**
   ```bash
   # Windows (PowerShell)
   mkdir "$env:APPDATA\Claude" -Force

   # macOS/Linux
   mkdir -p ~/Library/Application\ Support/Claude
   ```

2. **Use manual setup** and create the config file yourself

### Server Doesn't Appear in Claude Code

**Problem:** After setup, the server isn't visible

**Solutions:**

1. **Verify config file was created:**
   - Check the path shown by the wizard
   - Ensure the file contains valid JSON

2. **Restart Claude Code completely:**
   - Quit the application (not just close the window)
   - Start it again

3. **Check logs:**
   - Claude Code logs are in the same directory as the config
   - Look for errors related to "db-connect"

4. **Verify Python is accessible:**
   ```bash
   python --version
   python -m db_connect_mcp --help
   ```

### Permission Errors

**Problem:** Permission denied when saving config

**Solutions:**

1. **Run with appropriate permissions:**
   ```bash
   # Windows: Run as Administrator
   # macOS/Linux: Use sudo if necessary
   sudo python setup.py
   ```

2. **Check file permissions:**
   ```bash
   # Make config directory writable
   chmod u+w ~/.config/Claude
   ```

### Multiple Python Versions

**Problem:** Wrong Python version used

**Solutions:**

1. **Specify Python version explicitly:**
   ```bash
   python3.10 setup.py
   ```

2. **Use virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install db-connect-mcp
   python setup.py
   ```

3. **Edit config to use specific Python:**
   ```json
   {
     "mcpServers": {
       "db-connect": {
         "command": "/usr/bin/python3.10",
         "args": ["-m", "db_connect_mcp"],
         "env": {
           "DATABASE_URL": "..."
         }
       }
     }
   }
   ```

### JSON Syntax Errors

**Problem:** Config file is invalid JSON

**Solutions:**

1. **Validate JSON syntax:**
   - Use a JSON validator like https://jsonlint.com
   - Check for missing commas, quotes, or brackets

2. **Use the wizard's backup:**
   - The wizard creates `.backup` files
   - Restore from backup if needed:
     ```bash
     cp config.json.backup config.json
     ```

3. **Start fresh:**
   - Delete the config file
   - Run the wizard again

## Advanced Configuration

### Custom Working Directory

If you're running from source or need a specific working directory:

```json
{
  "mcpServers": {
    "db-connect": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "..."
      },
      "cwd": "/path/to/db-connect-mcp"
    }
  }
}
```

### Additional Environment Variables

You can add more environment variables for configuration:

```json
{
  "mcpServers": {
    "db-connect": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "...",
        "DB_POOL_SIZE": "10",
        "DB_MAX_OVERFLOW": "20",
        "DB_POOL_TIMEOUT": "60"
      }
    }
  }
}
```

### Using UV for Development

If you're developing or contributing:

```json
{
  "mcpServers": {
    "db-connect": {
      "command": "uv",
      "args": ["run", "python", "-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "..."
      },
      "cwd": "/path/to/db-connect-mcp/source"
    }
  }
}
```

## Verification

After setup, verify the server is working:

1. **Open Claude Code or ChatGPT Desktop**

2. **Start a new conversation**

3. **Ask a test question:**
   ```
   "What databases are available in the db-connect server?"
   ```

4. **The server should respond** with database information

5. **Try more complex queries:**
   ```
   "List all schemas"
   "Show me the tables in the public schema"
   "Describe the structure of the users table"
   ```

## Getting Help

If you encounter issues not covered here:

1. **Check the main README:** [README.md](../README.md)
2. **Review development docs:** [DEVELOPMENT.md](DEVELOPMENT.md)
3. **File an issue:** [GitHub Issues](https://github.com/yourusername/db-connect-mcp/issues)
4. **Check MCP documentation:** [Model Context Protocol Docs](https://modelcontextprotocol.io)

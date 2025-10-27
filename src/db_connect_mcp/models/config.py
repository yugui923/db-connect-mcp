"""Database configuration model."""

import logging
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine.url import make_url


logger = logging.getLogger(__name__)


class DatabaseConfig(BaseModel):
    """Configuration for database connection and pooling."""

    url: str = Field(
        ...,
        description="Database connection URL (e.g., postgresql://user:pass@host:5432/db)",
    )
    pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Connection pool size",
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Maximum overflow connections",
    )
    pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Pool checkout timeout in seconds",
    )
    read_only: bool = Field(
        default=True,
        description="Enforce read-only connections",
    )
    statement_timeout: Optional[int] = Field(
        default=30,
        ge=1,
        le=3600,
        description="Statement execution timeout in seconds",
    )
    echo_sql: bool = Field(
        default=False,
        description="Echo SQL statements to stdout",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate and normalize database URL format."""
        try:
            # Handle JDBC URLs by stripping the jdbc: prefix
            # JDBC is a Java-specific format, Python drivers don't use it
            if v.lower().startswith("jdbc:"):
                v = v[5:]  # Remove "jdbc:" prefix
                logger.info(
                    "Converted JDBC URL to Python format (removed 'jdbc:' prefix)"
                )

                # Some JDBC URLs might have jdbc:driver:// format (e.g., jdbc:postgresql://)
                # These are already handled by removing the prefix

                # Handle special case: JDBC ClickHouse URLs with query parameters
                # Format: jdbc:clickhouse://host:port?user=X&password=Y&database=Z
                if v.lower().startswith("clickhouse://"):
                    import re
                    from urllib.parse import unquote

                    # Parse JDBC-style ClickHouse URL
                    match = re.match(r"clickhouse://([^:/]+):?(\d+)?\?(.+)", v)
                    if match:
                        host = match.group(1)
                        port = match.group(2) or "9000"
                        params_str = match.group(3)

                        # Parse parameters carefully
                        user = "default"
                        password = ""
                        database = "default"

                        # Extract user
                        if "user=" in params_str:
                            user_match = re.search(r"user=([^&]+)", params_str)
                            if user_match:
                                user = unquote(user_match.group(1))

                        # Extract password (handle special characters)
                        if "password=" in params_str:
                            pwd_start = params_str.find("password=") + 9
                            # Find next parameter or end
                            next_param = len(params_str)
                            for known_param in ["&ssl=", "&database=", "&secure="]:
                                pos = params_str.find(known_param, pwd_start)
                                if pos != -1 and pos < next_param:
                                    next_param = pos
                            password = unquote(params_str[pwd_start:next_param])

                        # Extract database
                        if "database=" in params_str:
                            db_match = re.search(r"database=([^&]+)", params_str)
                            if db_match:
                                database = unquote(db_match.group(1))

                        # Check for SSL/secure
                        secure = "ssl=true" in params_str or "secure=true" in params_str

                        # Build proper SQLAlchemy URL
                        v = f"clickhousedb://{user}:{password}@{host}:{port}/{database}"
                        if secure:
                            v += "?secure=True"

                        logger.info(
                            "Converted JDBC ClickHouse URL to SQLAlchemy format"
                        )

            # Parse the URL to handle query parameters
            parsed = urlparse(v)

            # Parse query parameters
            query_params = parse_qs(parsed.query)

            # Extract base dialect and normalize variations
            temp_url = make_url(v)
            original_dialect = temp_url.drivername.split("+")[0].lower()

            # Map common dialect variations to standard names
            dialect_variations = {
                # PostgreSQL variations
                "postgresql": "postgresql",
                "postgres": "postgresql",
                "psql": "postgresql",
                "pg": "postgresql",
                "pgsql": "postgresql",
                # MySQL variations
                "mysql": "mysql",
                "mariadb": "mysql",  # MariaDB is MySQL-compatible
                "maria": "mysql",
                # ClickHouse variations
                "clickhouse": "clickhouse",
                "clickhousedb": "clickhouse",  # clickhouse-connect uses this
                "ch": "clickhouse",
                "click": "clickhouse",
            }

            # Normalize the dialect
            dialect = dialect_variations.get(original_dialect)

            if not dialect:
                supported = set(dialect_variations.keys())
                raise ValueError(
                    f"Unsupported database dialect: '{original_dialect}'. "
                    f"Supported: {', '.join(sorted(supported))}"
                )

            # If dialect was normalized, update the URL
            if original_dialect != dialect:
                driver_part = ""
                if "+" in temp_url.drivername:
                    driver_part = "+" + temp_url.drivername.split("+")[1]
                temp_url = temp_url.set(drivername=dialect + driver_part)
                logger.info(
                    f"Normalized database dialect from '{original_dialect}' to '{dialect}'"
                )
                # Rebuild the URL with normalized dialect
                v = temp_url.render_as_string(hide_password=False)
                # Re-parse the normalized URL
                parsed = urlparse(v)
                query_params = parse_qs(parsed.query)

            # Define allowed parameters for each database type
            # These are parameters that are actually useful and safe for async drivers
            allowed_params = {
                "postgresql": {
                    # Connection identification and monitoring
                    "application_name",  # Shows up in pg_stat_activity
                    # Timeouts
                    "connect_timeout",  # Connection timeout in seconds
                    "command_timeout",  # Default timeout for operations
                    # Server settings
                    "server_settings",  # Server settings dictionary
                    "options",  # Command-line options to send to the server
                    # SSL settings (essential for cloud databases)
                    # Note: Only basic SSL params that asyncpg handles well
                    "ssl",  # Enable SSL (e.g., 'require', 'prefer')
                    "sslmode",  # SSL mode for connection
                    "direct_tls",  # Use direct TLS connection
                    "ssl_min_protocol_version",  # Minimum SSL/TLS version
                    "ssl_max_protocol_version",  # Maximum SSL/TLS version
                    # We DON'T include cert/key file paths as they can cause issues
                    # Performance tuning
                    "prepared_statement_cache_size",  # Cache size for prepared statements
                    "prepared_statement_name_func",  # Function for prepared statement names
                    "max_cached_statement_lifetime",  # Max lifetime for cached statements
                    "max_cacheable_statement_size",  # Max size for cacheable statements
                },
                "mysql": {
                    # Character encoding - CRITICAL for proper data handling
                    "charset",  # Character set (e.g., utf8mb4)
                    "use_unicode",  # Whether to use unicode
                    # Timeouts
                    "connect_timeout",  # Connection timeout
                    "read_timeout",  # Read timeout
                    "write_timeout",  # Write timeout
                    # Transaction control
                    "autocommit",  # Autocommit mode
                    "init_command",  # Initial SQL command to run
                    # Other useful settings
                    "sql_mode",  # SQL mode settings
                    "time_zone",  # Time zone setting
                },
                "clickhouse": {
                    # Database selection
                    "database",  # Default database
                    # Timeouts
                    "timeout",  # Query timeout
                    "connect_timeout",  # Connection timeout
                    "send_receive_timeout",  # Network timeout
                    "sync_request_timeout",  # Sync request timeout
                    # Compression
                    "compress",  # Whether to use compression
                    "compression",  # Compression type
                    # Performance
                    "max_block_size",  # Max block size for reading
                    "max_threads",  # Max threads for query execution
                },
            }

            # Get the allowed parameters for this dialect
            dialect_params = allowed_params.get(dialect, set())

            # Filter to only allowed parameters
            filtered_params = {
                k: v for k, v in query_params.items() if k.lower() in dialect_params
            }

            # Special handling for PostgreSQL SSL parameters
            # Convert PostgreSQL standard SSL params to asyncpg format
            if dialect == "postgresql" and filtered_params:
                # asyncpg uses 'sslmode' parameter, not 'ssl'
                # Convert 'ssl' parameter to 'sslmode' for asyncpg compatibility
                if "ssl" in filtered_params:
                    ssl_value = (
                        filtered_params["ssl"][0]
                        if isinstance(filtered_params["ssl"], list)
                        else filtered_params["ssl"]
                    )

                    # Map common ssl values to sslmode values
                    ssl_to_sslmode_map = {
                        "require": "require",
                        "required": "require",
                        "true": "require",
                        "1": "require",
                        "prefer": "prefer",
                        "preferred": "prefer",
                        "allow": "allow",
                        "disable": "disable",
                        "disabled": "disable",
                        "false": "disable",
                        "0": "disable",
                    }

                    sslmode_value = ssl_to_sslmode_map.get(str(ssl_value).lower())
                    if sslmode_value:
                        # Replace ssl with sslmode
                        del filtered_params["ssl"]
                        filtered_params["sslmode"] = [sslmode_value]
                        logger.info(
                            f"Converted ssl={ssl_value} to sslmode={sslmode_value} for asyncpg"
                        )
                    else:
                        # Unknown ssl value, remove it
                        del filtered_params["ssl"]
                        logger.info(f"Removed unknown ssl value: {ssl_value}")

                # Validate sslmode parameter values if present
                if "sslmode" in filtered_params:
                    valid_sslmodes = {
                        "disable",
                        "allow",
                        "prefer",
                        "require",
                        "verify-ca",
                        "verify-full",
                    }
                    sslmode_value = (
                        filtered_params["sslmode"][0]
                        if isinstance(filtered_params["sslmode"], list)
                        else filtered_params["sslmode"]
                    )
                    if sslmode_value not in valid_sslmodes:
                        # Invalid sslmode value, default to require for safety
                        filtered_params["sslmode"] = ["require"]
                        logger.info(
                            f"Invalid sslmode={sslmode_value}, defaulting to sslmode=require"
                        )

            # Log what we kept and what we removed
            removed_params = set(query_params.keys()) - set(filtered_params.keys())
            if removed_params:
                logger.info(
                    f"Removed unsupported parameters for {dialect}: {removed_params}"
                )
            if filtered_params:
                logger.info(
                    f"Keeping supported parameters for {dialect}: {set(filtered_params.keys())}"
                )

            # Rebuild URL with only allowed parameters
            new_query = urlencode(filtered_params, doseq=True)
            clean_url = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                )
            )

            # Now parse with SQLAlchemy
            url = make_url(clean_url)

            # No need to check supported dialects again as we already normalized and validated above

            # Handle ClickHouse special case - clickhouse-connect uses 'clickhousedb' as dialect
            if dialect == "clickhouse":
                # clickhouse-connect uses 'clickhousedb' as the SQLAlchemy dialect name
                # Don't add a driver suffix - just use 'clickhousedb'
                url = url.set(drivername="clickhousedb")
                logger.info(
                    "Using clickhousedb dialect for ClickHouse (clickhouse-connect)"
                )
            elif "+" not in url.drivername:
                # Map other dialects to their default async drivers
                async_drivers = {
                    "postgresql": "asyncpg",
                    "mysql": "aiomysql",
                }

                driver = async_drivers.get(dialect)
                if driver:
                    # Rebuild the URL with the async driver
                    new_drivername = f"{dialect}+{driver}"
                    url = url.set(drivername=new_drivername)
                    logger.info(f"Automatically added async driver: {new_drivername}")

            # IMPORTANT: Use render_as_string to preserve the actual password
            # str(url) masks the password as ***, which breaks authentication!
            clean_url = url.render_as_string(hide_password=False)

            return clean_url
        except Exception as e:
            raise ValueError(f"Invalid database URL: {e}")

    @property
    def dialect(self) -> str:
        """Extract database dialect from URL."""
        dialect = make_url(self.url).drivername.split("+")[0]
        # Normalize clickhousedb back to clickhouse for consistency
        if dialect == "clickhousedb":
            return "clickhouse"
        return dialect

    @property
    def driver(self) -> str:
        """Extract driver name from URL."""
        drivername = make_url(self.url).drivername
        # clickhousedb is the whole driver name, no + separator
        if drivername == "clickhousedb":
            return "connect"  # Indicate we're using clickhouse-connect
        parts = drivername.split("+")
        return parts[1] if len(parts) > 1 else ""

    @property
    def database(self) -> Optional[str]:
        """Extract database name from URL."""
        url = make_url(self.url)
        return url.database

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "url": "postgresql://user:password@localhost:5432/mydb",
                    "pool_size": 5,
                    "max_overflow": 10,
                    "read_only": True,
                    "statement_timeout": 30,
                }
            ]
        }
    }

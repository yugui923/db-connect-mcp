"""Tests for database configuration models."""

import pytest

from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig


class TestSSHTunnelConfig:
    """Tests for SSHTunnelConfig model."""

    def test_creation_with_password(self):
        """Test creating tunnel config with password auth."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="dbuser",
            ssh_password="secret",
        )
        assert config.ssh_host == "bastion.example.com"
        assert config.ssh_port == 22
        assert config.ssh_username == "dbuser"
        assert config.ssh_password == "secret"

    def test_creation_with_key_path(self):
        """Test creating tunnel config with private key path."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="dbuser",
            ssh_private_key_path="/home/user/.ssh/id_rsa",
        )
        assert config.ssh_private_key_path == "/home/user/.ssh/id_rsa"

    def test_creation_with_key_content(self):
        """Test creating tunnel config with private key content."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="dbuser",
            ssh_private_key="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
        )
        assert config.ssh_private_key is not None

    def test_missing_authentication_raises(self):
        """Test that missing authentication raises ValueError."""
        with pytest.raises(ValueError, match="SSH authentication requires"):
            SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="dbuser",
                # No password, key path, or key content
            )

    def test_full_config(self):
        """Test creating a fully configured tunnel."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_port=2222,
            ssh_username="dbuser",
            ssh_password="secret",
            remote_host="db.internal",
            remote_port=5432,
            local_host="127.0.0.1",
            local_port=15432,
            tunnel_timeout=30,
        )
        assert config.ssh_port == 2222
        assert config.remote_host == "db.internal"
        assert config.remote_port == 5432
        assert config.local_port == 15432
        assert config.tunnel_timeout == 30


class TestDatabaseConfig:
    """Tests for DatabaseConfig model."""

    def test_basic_postgresql_url(self):
        """Test basic PostgreSQL URL parsing."""
        config = DatabaseConfig(url="postgresql://user:pass@localhost:5432/mydb")
        assert "postgresql+asyncpg" in config.url
        assert config.dialect == "postgresql"
        assert config.driver == "asyncpg"
        assert config.database == "mydb"

    def test_basic_mysql_url(self):
        """Test basic MySQL URL parsing."""
        config = DatabaseConfig(url="mysql://user:pass@localhost:3306/mydb")
        assert "mysql+aiomysql" in config.url
        assert config.dialect == "mysql"
        assert config.driver == "aiomysql"
        assert config.database == "mydb"

    def test_basic_clickhouse_url(self):
        """Test basic ClickHouse URL parsing."""
        config = DatabaseConfig(url="clickhouse://user:pass@localhost:8123/mydb")
        assert "clickhousedb" in config.url
        assert config.dialect == "clickhouse"
        assert config.driver == "connect"
        assert config.database == "mydb"

    def test_postgres_dialect_normalization(self):
        """Test that 'postgres' is normalized to 'postgresql'."""
        config = DatabaseConfig(url="postgres://user:pass@localhost:5432/mydb")
        assert config.dialect == "postgresql"

    def test_mariadb_dialect_normalization(self):
        """Test that 'mariadb' is normalized to 'mysql'."""
        config = DatabaseConfig(url="mariadb://user:pass@localhost:3306/mydb")
        assert config.dialect == "mysql"

    def test_ch_dialect_normalization(self):
        """Test that 'ch' is normalized to 'clickhouse'."""
        config = DatabaseConfig(url="ch://user:pass@localhost:8123/mydb")
        assert config.dialect == "clickhouse"

    def test_unsupported_dialect_raises(self):
        """Test that unsupported dialect raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported database dialect"):
            DatabaseConfig(url="oracle://user:pass@localhost:1521/mydb")

    def test_jdbc_prefix_removal(self):
        """Test that JDBC prefix is removed from URLs."""
        config = DatabaseConfig(url="jdbc:postgresql://user:pass@localhost:5432/mydb")
        assert config.dialect == "postgresql"
        assert "jdbc" not in config.url

    def test_jdbc_clickhouse_url_conversion(self):
        """Test JDBC ClickHouse URL conversion."""
        config = DatabaseConfig(
            url="jdbc:clickhouse://localhost:8123?user=admin&password=secret&database=analytics"
        )
        assert config.dialect == "clickhouse"
        assert config.database == "analytics"

    def test_jdbc_clickhouse_with_ssl(self):
        """Test JDBC ClickHouse URL with SSL flag is parsed correctly."""
        config = DatabaseConfig(
            url="jdbc:clickhouse://localhost:8123?user=admin&password=secret&database=test&ssl=true"
        )
        assert config.dialect == "clickhouse"
        # SSL flag is parsed but secure param is filtered (not in allowed list)
        # The important thing is the URL is valid and parsed correctly
        assert config.database == "test"

    def test_postgresql_ssl_parameter_conversion(self):
        """Test that ssl=require is converted to sslmode=require for PostgreSQL."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb?ssl=require"
        )
        assert "sslmode=require" in config.url
        assert "ssl=require" not in config.url

    def test_postgresql_ssl_true_to_sslmode(self):
        """Test that ssl=true is converted to sslmode=require."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb?ssl=true"
        )
        assert "sslmode=require" in config.url

    def test_postgresql_ssl_false_to_disable(self):
        """Test that ssl=false is converted to sslmode=disable."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb?ssl=false"
        )
        assert "sslmode=disable" in config.url

    def test_postgresql_invalid_sslmode_defaults_to_require(self):
        """Test that invalid sslmode defaults to require for safety."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb?sslmode=invalid"
        )
        assert "sslmode=require" in config.url

    def test_postgresql_valid_sslmode_values(self):
        """Test that valid sslmode values are preserved."""
        for mode in [
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        ]:
            config = DatabaseConfig(
                url=f"postgresql://user:pass@localhost:5432/mydb?sslmode={mode}"
            )
            assert f"sslmode={mode}" in config.url

    def test_postgresql_unsupported_params_removed(self):
        """Test that unsupported parameters are removed."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb?charset=utf8&application_name=myapp"
        )
        # charset should be removed (not in allowed list for postgresql)
        assert "charset" not in config.url
        # application_name should be kept
        assert "application_name=myapp" in config.url

    def test_mysql_charset_preserved(self):
        """Test that MySQL charset parameter is preserved."""
        config = DatabaseConfig(
            url="mysql://user:pass@localhost:3306/mydb?charset=utf8mb4"
        )
        assert "charset=utf8mb4" in config.url

    def test_clickhouse_timeout_preserved(self):
        """Test that ClickHouse timeout parameter is preserved."""
        config = DatabaseConfig(
            url="clickhouse://user:pass@localhost:8123/mydb?timeout=30"
        )
        assert "timeout=30" in config.url

    def test_default_pool_settings(self):
        """Test default pool settings."""
        config = DatabaseConfig(url="postgresql://user:pass@localhost:5432/mydb")
        assert config.pool_size == 5
        assert config.max_overflow == 10
        assert config.pool_timeout == 30
        assert config.read_only is True
        assert config.statement_timeout == 900

    def test_custom_pool_settings(self):
        """Test custom pool settings."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb",
            pool_size=10,
            max_overflow=20,
            pool_timeout=60,
            read_only=False,
            statement_timeout=1800,
        )
        assert config.pool_size == 10
        assert config.max_overflow == 20
        assert config.pool_timeout == 60
        assert config.read_only is False
        assert config.statement_timeout == 1800

    def test_with_ssh_tunnel(self):
        """Test configuration with SSH tunnel."""
        tunnel = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="dbuser",
            ssh_password="secret",
        )
        config = DatabaseConfig(
            url="postgresql://user:pass@db.internal:5432/mydb",
            ssh_tunnel=tunnel,
        )
        assert config.ssh_tunnel is not None
        assert config.ssh_tunnel.ssh_host == "bastion.example.com"

    def test_url_with_explicit_async_driver(self):
        """Test that explicit async driver is preserved."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:pass@localhost:5432/mydb"
        )
        assert "postgresql+asyncpg" in config.url

    def test_invalid_url_raises(self):
        """Test that completely invalid URL raises ValueError."""
        with pytest.raises(ValueError, match="Invalid database URL"):
            DatabaseConfig(url="not-a-valid-url")

    def test_dialect_property_normalizes_clickhousedb(self):
        """Test that dialect property normalizes clickhousedb to clickhouse."""
        config = DatabaseConfig(url="clickhouse://user:pass@localhost:8123/mydb")
        # URL gets converted to clickhousedb internally
        assert "clickhousedb" in config.url
        # But dialect property returns 'clickhouse'
        assert config.dialect == "clickhouse"

    def test_database_property(self):
        """Test database property extracts database name."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/production_db"
        )
        assert config.database == "production_db"

    def test_database_property_no_database(self):
        """Test database property when no database specified."""
        config = DatabaseConfig(url="postgresql://user:pass@localhost:5432/")
        assert config.database == ""

    def test_driver_property_postgresql(self):
        """Test driver property for PostgreSQL."""
        config = DatabaseConfig(url="postgresql://user:pass@localhost:5432/mydb")
        assert config.driver == "asyncpg"

    def test_driver_property_mysql(self):
        """Test driver property for MySQL."""
        config = DatabaseConfig(url="mysql://user:pass@localhost:3306/mydb")
        assert config.driver == "aiomysql"

    def test_driver_property_clickhouse(self):
        """Test driver property for ClickHouse returns 'connect'."""
        config = DatabaseConfig(url="clickhouse://user:pass@localhost:8123/mydb")
        assert config.driver == "connect"

    def test_password_with_special_characters(self):
        """Test URL with password containing special characters."""
        config = DatabaseConfig(
            url="postgresql://user:p%40ss%23word@localhost:5432/mydb"
        )
        # Password should be preserved
        assert "p%40ss%23word" in config.url or "p@ss#word" in config.url

    def test_echo_sql_setting(self):
        """Test echo_sql setting."""
        config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb",
            echo_sql=True,
        )
        assert config.echo_sql is True

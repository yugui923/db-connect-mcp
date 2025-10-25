"""Database configuration model."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine.url import make_url


class DatabaseConfig(BaseModel):
    """Configuration for database connection and pooling."""

    url: str = Field(
        ...,
        description="Database connection URL (e.g., postgresql+asyncpg://user:pass@host:5432/db)",
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
        """Validate database URL format."""
        try:
            url = make_url(v)
            # Extract base dialect (e.g., "postgresql" from "postgresql+asyncpg")
            dialect = url.drivername.split("+")[0]

            supported_dialects = {"postgresql", "mysql", "clickhouse"}
            if dialect not in supported_dialects:
                raise ValueError(
                    f"Unsupported database dialect: {dialect}. "
                    f"Supported: {', '.join(supported_dialects)}"
                )

            # Ensure async driver is specified
            if "+" not in url.drivername:
                raise ValueError(
                    "Async driver required. Examples: "
                    "postgresql+asyncpg://, mysql+aiomysql://, clickhouse+asynch://"
                )

            return v
        except Exception as e:
            raise ValueError(f"Invalid database URL: {e}")

    @property
    def dialect(self) -> str:
        """Extract database dialect from URL."""
        return make_url(self.url).drivername.split("+")[0]

    @property
    def driver(self) -> str:
        """Extract driver name from URL."""
        parts = make_url(self.url).drivername.split("+")
        return parts[1] if len(parts) > 1 else ""

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "url": "postgresql+asyncpg://user:password@localhost:5432/mydb",
                    "pool_size": 5,
                    "max_overflow": 10,
                    "read_only": True,
                    "statement_timeout": 30,
                }
            ]
        }
    }

"""Database capabilities model."""

from pydantic import BaseModel, Field


class DatabaseCapabilities(BaseModel):
    """Flags indicating what features a database supports."""

    foreign_keys: bool = Field(
        default=False,
        description="Database supports foreign key constraints",
    )
    indexes: bool = Field(
        default=True,
        description="Database supports indexes",
    )
    views: bool = Field(
        default=True,
        description="Database supports views",
    )
    materialized_views: bool = Field(
        default=False,
        description="Database supports materialized views",
    )
    partitions: bool = Field(
        default=False,
        description="Database supports table partitioning",
    )
    advanced_stats: bool = Field(
        default=False,
        description="Database supports advanced statistics (percentiles, distributions)",
    )
    explain_plans: bool = Field(
        default=True,
        description="Database supports EXPLAIN for query plans",
    )
    profiling: bool = Field(
        default=False,
        description="Database supports profiling and performance metrics",
    )
    comments: bool = Field(
        default=False,
        description="Database supports table/column comments",
    )
    schemas: bool = Field(
        default=True,
        description="Database supports schemas/namespaces",
    )
    transactions: bool = Field(
        default=True,
        description="Database supports transactions",
    )
    stored_procedures: bool = Field(
        default=False,
        description="Database supports stored procedures",
    )
    triggers: bool = Field(
        default=False,
        description="Database supports triggers",
    )

    def get_supported_features(self) -> list[str]:
        """Get list of supported feature names."""
        return [
            field_name
            for field_name, value in self.model_dump().items()
            if value is True
        ]

    def get_unsupported_features(self) -> list[str]:
        """Get list of unsupported feature names."""
        return [
            field_name
            for field_name, value in self.model_dump().items()
            if value is False
        ]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "foreign_keys": True,
                    "indexes": True,
                    "views": True,
                    "materialized_views": True,
                    "partitions": True,
                    "advanced_stats": True,
                    "explain_plans": True,
                    "profiling": True,
                    "comments": True,
                    "schemas": True,
                    "transactions": True,
                    "stored_procedures": True,
                    "triggers": True,
                }
            ]
        }
    }

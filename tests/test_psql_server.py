#!/usr/bin/env python
"""Test PostgreSQL adapter and new package structure"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()

# Fix for Windows: asyncpg requires SelectorEventLoop on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


async def test_server():
    """Test PostgreSQL adapter and core components"""
    print("Testing PostgreSQL Data Analyst - New Package Structure")
    print("=" * 60)

    # Test imports
    try:
        from src.adapters import create_adapter
        from src.core import (
            DatabaseConnection,
            MetadataInspector,
            StatisticsAnalyzer,
        )
        from src.models.config import DatabaseConfig

        print("[OK] Imports successful: adapters, core, models")
    except ImportError as e:
        print(f"[ERROR] Failed to import modules: {e}")
        return False

    # Check environment
    database_url = os.getenv("PG_TEST_DATABASE_URL")
    if not database_url:
        print("[ERROR] PG_TEST_DATABASE_URL not set in environment")
        print("  Please create a .env file with your PostgreSQL connection")
        print(
            "  Example: PG_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/db"
        )
        return False

    try:
        # Initialize configuration
        config = DatabaseConfig(url=database_url)
        print(f"[OK] Database config created: {config.dialect} driver={config.driver}")

        # Create PostgreSQL adapter
        adapter = create_adapter(config)
        print("[OK] PostgreSQL adapter created")
        print(
            f"  Capabilities: {len(adapter.capabilities.get_supported_features())} features"
        )

        # Test connection
        connection = DatabaseConnection(config)
        await connection.initialize()
        print("[OK] Database connection initialized")

        # Test connectivity - use context manager for proper connection handling
        try:
            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT version()"))
                row = result.fetchone()
                if row:
                    version = str(row[0])
                    print(f"[OK] Connected to PostgreSQL: {version[:60]}...")
                else:
                    print("[ERROR] No version returned")
                    return False
        except Exception as e:
            print(f"[ERROR] Connection test exception: {e}")
            import traceback

            traceback.print_exc()
            return False

        # Test read-only enforcement
        if config.read_only:
            print("[OK] Read-only mode enabled (safe mode)")
        else:
            print("[WARNING] Read-only mode disabled")

        # Test MetadataInspector
        inspector = MetadataInspector(connection, adapter)
        print("[OK] MetadataInspector created")

        # List schemas
        schemas = await inspector.get_schemas()
        print(f"[OK] Found {len(schemas)} user schemas")
        if schemas:
            schema_names = [s.name for s in schemas[:5]]
            print(f"  Schemas: {', '.join(schema_names)}")
            if schemas[0].table_count is not None:
                print(f"  First schema table count: {schemas[0].table_count}")

        # List tables in public schema
        tables = await inspector.get_tables("public")
        print(f"[OK] Found {len(tables)} tables in 'public' schema")
        if tables:
            print(f"  Sample table: {tables[0].name} (type: {tables[0].table_type})")
            if tables[0].row_count:
                print(f"  Row count: {tables[0].row_count:,}")

        # Test detailed table description
        if tables:
            table_name = tables[0].name
            detailed_table = await inspector.describe_table(table_name, "public")
            print(f"[OK] Detailed table info for '{table_name}':")
            print(f"  Columns: {len(detailed_table.columns)}")
            print(f"  Indexes: {len(detailed_table.indexes)}")
            print(f"  Constraints: {len(detailed_table.constraints)}")

            if detailed_table.columns:
                col = detailed_table.columns[0]
                print(
                    f"  Sample column: {col.name} ({col.data_type}, nullable={col.nullable})"
                )

        # Test relationships (if supported and table has FKs)
        if adapter.capabilities.foreign_keys and tables:
            for table in tables[:3]:  # Check first 3 tables
                relationships = await inspector.get_relationships(table.name, "public")
                if relationships:
                    print(
                        f"[OK] Found {len(relationships)} relationships for '{table.name}'"
                    )
                    rel = relationships[0]
                    print(
                        f"  {rel.from_table}.{','.join(rel.from_columns)} -> "
                        f"{rel.to_table}.{','.join(rel.to_columns)}"
                    )
                    break

        # Test StatisticsAnalyzer
        if tables and tables[0].columns:
            analyzer = StatisticsAnalyzer(connection, adapter)
            print("[OK] StatisticsAnalyzer created")

            # Get column statistics
            table_name = tables[0].name
            column_name = tables[0].columns[0].name

            stats = await analyzer.analyze_column(table_name, column_name, "public")
            print(f"[OK] Column statistics for '{table_name}.{column_name}':")
            print(f"  Data type: {stats.data_type}")
            print(f"  Total rows: {stats.total_rows:,}")
            print(f"  Null count: {stats.null_count:,}")
            if stats.distinct_count:
                print(f"  Distinct values: {stats.distinct_count:,}")
            if stats.avg_value is not None:
                print(f"  Average: {stats.avg_value:.2f}")

        # Cleanup
        await connection.dispose()
        print("[OK] Connection closed")

    except Exception as e:
        print(f"[ERROR] Error during testing: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("=" * 60)
    print("[OK] All PostgreSQL adapter tests passed!")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_server())
    exit(0 if success else 1)

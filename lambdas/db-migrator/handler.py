"""Database migration runner for CI/CD pipelines."""

import json
import os
import re
import boto3


def get_connection():
    """Get database connection using credentials from Secrets Manager."""
    import psycopg2

    secrets = boto3.client("secretsmanager")
    secret_value = secrets.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])
    secret = json.loads(secret_value["SecretString"])

    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        database="second_brain",
        user=secret["username"],
        password=secret["password"],
        port=5432,
    )


def ensure_migrations_table(conn):
    """Create the schema_migrations table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    conn.commit()


def get_applied_migrations(conn):
    """Get set of already applied migration versions."""
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn, version, sql):
    """Apply a single migration and record it."""
    print(f"Applying migration: {version}")
    with conn.cursor() as cur:
        # Execute the migration SQL
        cur.execute(sql)
        # Record the migration
        cur.execute(
            "INSERT INTO schema_migrations (version) VALUES (%s)",
            (version,)
        )
    conn.commit()
    print(f"Successfully applied: {version}")


def handler(event, context):
    """
    Run pending database migrations.

    Event options:
    - {"action": "status"} - List applied and pending migrations
    - {"action": "migrate"} - Run all pending migrations (default)
    - {"action": "migrate", "version": "001"} - Run specific migration
    - {"action": "execute", "sql": "..."} - Execute arbitrary SQL (admin use)

    CI/CD usage:
        aws lambda invoke --function-name second-brain-db-migrator \\
            --payload '{"action": "migrate"}' response.json
    """
    action = event.get("action", "migrate")

    # Handle execute action separately (doesn't need migrations)
    if action == "execute":
        sql = event.get("sql", "")
        if not sql:
            return {"statusCode": 400, "error": "No SQL provided"}
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(sql)
                if cur.description:  # SELECT query
                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    # Convert non-serializable types
                    result = []
                    for row in rows:
                        row_dict = {}
                        for col, val in zip(columns, row):
                            if hasattr(val, 'isoformat'):
                                row_dict[col] = val.isoformat()
                            else:
                                row_dict[col] = str(val) if val is not None else None
                        result.append(row_dict)
                    conn.commit()
                    conn.close()
                    return {"statusCode": 200, "rows": result, "count": len(result)}
                else:  # INSERT/UPDATE/DELETE
                    affected = cur.rowcount
                    conn.commit()
                    conn.close()
                    return {"statusCode": 200, "affected_rows": affected}
        except Exception as e:
            return {"statusCode": 500, "error": str(e)}

    # Load migrations from bundled files
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")

    if not os.path.exists(migrations_dir):
        return {
            "statusCode": 500,
            "error": f"Migrations directory not found: {migrations_dir}"
        }

    # Parse migration files (format: 001_name.sql)
    migration_pattern = re.compile(r"^(\d{3})_.*\.sql$")
    migrations = {}

    for filename in sorted(os.listdir(migrations_dir)):
        match = migration_pattern.match(filename)
        if match:
            version = match.group(1)
            filepath = os.path.join(migrations_dir, filename)
            with open(filepath, "r") as f:
                migrations[version] = {
                    "filename": filename,
                    "sql": f.read()
                }

    print(f"Found {len(migrations)} migration files")

    # Connect to database
    try:
        conn = get_connection()
    except Exception as e:
        return {
            "statusCode": 500,
            "error": f"Database connection failed: {str(e)}"
        }

    ensure_migrations_table(conn)
    applied = get_applied_migrations(conn)

    print(f"Already applied: {sorted(applied)}")

    pending = sorted(set(migrations.keys()) - applied)

    if action == "status":
        conn.close()
        return {
            "statusCode": 200,
            "applied": sorted(applied),
            "pending": pending,
            "total": len(migrations)
        }

    # Run migrations
    target_version = event.get("version")

    if target_version:
        # Run specific migration
        if target_version in applied:
            conn.close()
            return {
                "statusCode": 200,
                "message": f"Migration {target_version} already applied"
            }
        if target_version not in migrations:
            conn.close()
            return {
                "statusCode": 404,
                "error": f"Migration {target_version} not found"
            }
        apply_migration(conn, target_version, migrations[target_version]["sql"])
        conn.close()
        return {
            "statusCode": 200,
            "applied": [target_version]
        }

    # Run all pending migrations
    newly_applied = []
    errors = []

    for version in pending:
        try:
            apply_migration(conn, version, migrations[version]["sql"])
            newly_applied.append(version)
        except Exception as e:
            error_msg = f"Error applying {version}: {str(e)}"
            print(error_msg)
            errors.append(error_msg)
            conn.rollback()
            # Stop on first error
            break

    conn.close()

    result = {
        "statusCode": 200 if not errors else 500,
        "applied": newly_applied,
        "pending_remaining": [v for v in pending if v not in newly_applied],
    }

    if errors:
        result["errors"] = errors

    return result

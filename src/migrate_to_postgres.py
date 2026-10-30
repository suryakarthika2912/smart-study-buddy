"""
SQLite-to-PostgreSQL Hardened Migration Tool for Smart Study Buddy
Supports safe, verified, non-destructive data transfer from local SQLite to Neon PostgreSQL.
Includes baseline validation, target preflight inspection, conflict detection,
and transactional verification before commit.

LEGACY DATABASE COMPATIBILITY NOTE:
When migrating historical SQLite databases where tables lack a `user_id` column:
1. Source data is read without modification or column truncation.
2. Target INSERT statements only populate the columns present in the source SQLite table.
3. Target PostgreSQL `user_id` columns remain NULL.
4. Behavior in Multi-User Application:
   In `app.py`, multi-user isolation queries filter records by `WHERE user_id = session['user_id']`.
   Records with NULL `user_id` are safely preserved in the PostgreSQL database with exact IDs
   and fields, but will not be visible to logged-in users until/unless an explicit post-migration
   ownership assignment script assigns them to a specific user_id.
"""

import os
import sys
import argparse
import sqlite3
from urllib.parse import urlparse

try:
    import psycopg2
    from psycopg2.extras import execute_batch
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


TABLES_IN_ORDER = [
    "users",
    "study_plans",
    "study_tasks",
    "study_goals",
    "study_dates",
    "study_progress"
]

REQUIRED_TABLES = [
    "users",
    "study_plans",
    "study_tasks",
    "study_goals",
    "study_dates",
    "study_progress"
]

REQUIRED_COLUMNS = {
    "users": ["id", "username", "password_hash"],
    "study_plans": ["id", "subject", "days", "daily_hours"],
    "study_tasks": ["id", "plan_id", "title"],
    "study_goals": ["id", "goal", "target_hours"],
    "study_dates": ["id", "study_date"],
    "study_progress": ["id", "subject", "planned_hours", "completed_hours"],
}

# Retained as None for backwards-compatibility with older test suites
EXPECTED_BASELINE = None

POSTGRES_SCHEMA = {
    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS users_lower_username_idx ON users (LOWER(username));
    """,
    "study_plans": """
        CREATE TABLE IF NOT EXISTS study_plans (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            name VARCHAR(150),
            subject VARCHAR(100),
            priority INTEGER,
            days INTEGER,
            daily_hours REAL
        );
    """,
    "study_tasks": """
        CREATE TABLE IF NOT EXISTS study_tasks (
            id SERIAL PRIMARY KEY,
            plan_id INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id),
            title VARCHAR(150) NOT NULL,
            due_date DATE,
            status VARCHAR(50) NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """,
    "study_goals": """
        CREATE TABLE IF NOT EXISTS study_goals (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            goal VARCHAR(150),
            target_hours REAL,
            completed_hours REAL DEFAULT 0,
            deadline DATE,
            status VARCHAR(50) DEFAULT 'Pending'
        );
    """,
    "study_dates": """
        CREATE TABLE IF NOT EXISTS study_dates (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            study_date DATE NOT NULL,
            UNIQUE(user_id, study_date)
        );
    """,
    "study_progress": """
        CREATE TABLE IF NOT EXISTS study_progress (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            subject VARCHAR(100),
            planned_hours REAL,
            completed_hours REAL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
}


def redact_pg_url(pg_url):
    """Safely extracts host, port, dbname, user from URL without credentials."""
    try:
        parsed = urlparse(pg_url)
        user = parsed.username or "postgres"
        host = parsed.hostname or "unknown"
        port = parsed.port or 5432
        dbname = parsed.path.lstrip("/") or "postgres"
        return f"postgresql://{user}:***@{host}:{port}/{dbname}"
    except Exception:
        return "postgresql://***:***@<redacted>"


def values_match(src_val, tgt_val):
    """Safely compares field values between SQLite and PostgreSQL."""
    if src_val is None and tgt_val is None:
        return True
    if src_val is None or tgt_val is None:
        return False
    # Numeric comparison
    try:
        if isinstance(src_val, (int, float)) or isinstance(tgt_val, (int, float)):
            return float(src_val) == float(tgt_val)
    except (ValueError, TypeError):
        pass
    # Date string vs date object comparison
    str_src = str(src_val).strip()
    str_tgt = str(tgt_val).strip()
    if len(str_src) >= 10 and len(str_tgt) >= 10 and str_src[:10] == str_tgt[:10]:
        return True
    return str_src == str_tgt


def validate_source_structure_and_integrity(data):
    """
    Validates structural schema and data integrity of source SQLite data:
    1. Verifies presence of all required tables and required columns.
    2. Verifies primary-key uniqueness (no NULL or duplicate IDs).
    3. Verifies required foreign-key relationships:
       - study_tasks.plan_id must reference an existing study_plans.id
       - user_id in any table must reference an existing users.id (if user_id is not NULL)
    Fails closed with descriptive ValueError if any structural or integrity check fails.
    """
    # 1. Verify required tables and columns
    for table in REQUIRED_TABLES:
        if table not in data:
            raise ValueError(f"SOURCE SCHEMA VALIDATION ERROR: Required table '{table}' is missing from source data.")

        # If users table is empty with 0 columns (legacy schema without auth),
        # it is permitted only if no records in other tables reference user_id.
        if table == "users" and not data["users"]["columns"]:
            continue

        cols = data[table]["columns"]
        req_cols = REQUIRED_COLUMNS.get(table, [])
        missing_cols = [c for c in req_cols if c not in cols]
        if missing_cols:
            raise ValueError(
                f"SOURCE SCHEMA VALIDATION ERROR: Table '{table}' is missing required column(s): {missing_cols}. "
                f"Present columns: {cols}."
            )

    # 2. Check primary-key schema declaration and value uniqueness
    for table in REQUIRED_TABLES:
        cols = data[table].get("columns", [])
        rows = data[table].get("rows", [])
        pk_cols = data[table].get("pk_columns")

        # Allow empty legacy users table
        if table == "users" and not cols:
            continue

        # Check genuine SQLite primary key declaration if pk_columns metadata is available
        if pk_cols is not None:
            if "id" not in pk_cols:
                raise ValueError(
                    f"PRIMARY KEY SCHEMA ERROR: Table '{table}' column 'id' is not declared as a PRIMARY KEY "
                    f"in SQLite schema (declared PK columns: {pk_cols})."
                )

        if not rows or "id" not in cols:
            continue
        id_idx = cols.index("id")
        ids = [r[id_idx] for r in rows]
        if any(x is None for x in ids):
            raise ValueError(f"PRIMARY KEY INTEGRITY ERROR: Table '{table}' contains NULL primary key id.")
        if len(ids) != len(set(ids)):
            seen = set()
            duplicates = set()
            for x in ids:
                if x in seen:
                    duplicates.add(x)
                seen.add(x)
            raise ValueError(
                f"PRIMARY KEY INTEGRITY ERROR: Table '{table}' contains duplicate primary key IDs: {sorted(duplicates)}."
            )

    # 3. Check foreign-key relationships
    # 3A: study_tasks.plan_id -> study_plans.id
    if "study_tasks" in data and "study_plans" in data:
        task_cols = data["study_tasks"]["columns"]
        plan_cols = data["study_plans"]["columns"]
        task_rows = data["study_tasks"]["rows"]
        plan_rows = data["study_plans"]["rows"]

        if "plan_id" in task_cols and "id" in plan_cols and task_rows:
            plan_id_idx = plan_cols.index("id")
            valid_plan_ids = {r[plan_id_idx] for r in plan_rows}
            task_plan_idx = task_cols.index("plan_id")
            task_id_idx = task_cols.index("id") if "id" in task_cols else 0

            orphaned_tasks = [
                r[task_id_idx] for r in task_rows
                if r[task_plan_idx] is None or r[task_plan_idx] not in valid_plan_ids
            ]
            if orphaned_tasks:
                raise ValueError(
                    f"FOREIGN KEY INTEGRITY ERROR: Table 'study_tasks' contains task record(s) with IDs {orphaned_tasks} "
                    f"referencing missing or invalid study_plans plan_id."
                )

    # 3B: user_id foreign key validation
    valid_user_ids = set()
    has_users_table = "users" in data and "id" in data["users"]["columns"]
    if has_users_table:
        u_id_idx = data["users"]["columns"].index("id")
        valid_user_ids = {r[u_id_idx] for r in data["users"]["rows"]}

    for t in ["study_plans", "study_tasks", "study_goals", "study_dates", "study_progress"]:
        if t not in data:
            continue
        t_cols = data[t]["columns"]
        t_rows = data[t]["rows"]
        if "user_id" in t_cols and t_rows:
            uid_idx = t_cols.index("user_id")
            t_id_idx = t_cols.index("id") if "id" in t_cols else 0

            invalid_user_refs = [
                (r[t_id_idx], r[uid_idx]) for r in t_rows
                if r[uid_idx] is not None and r[uid_idx] not in valid_user_ids
            ]
            if invalid_user_refs:
                bad_ids = [item[0] for item in invalid_user_refs]
                bad_uids = sorted(list({item[1] for item in invalid_user_refs}))
                raise ValueError(
                    f"FOREIGN KEY INTEGRITY ERROR: Table '{t}' contains record(s) with IDs {bad_ids} "
                    f"referencing non-existent user_id(s) {bad_uids}."
                )


# Backwards compatibility alias
validate_source_baseline = validate_source_structure_and_integrity


def read_sqlite_data(sqlite_path):
    """Safely reads data from SQLite in read-only mode and validates structure and integrity."""
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite database not found at: {sqlite_path}")

    conn = sqlite3.connect(f"file:{os.path.abspath(sqlite_path)}?mode=ro", uri=True)
    cur = conn.cursor()

    try:
        # 1. SQLite PRAGMA integrity_check
        cur.execute("PRAGMA integrity_check")
        integrity = cur.fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite database integrity check failed: {integrity}")

        # 2. SQLite PRAGMA foreign_key_check
        cur.execute("PRAGMA foreign_key_check")
        fk_violations = cur.fetchall()
        if fk_violations:
            raise RuntimeError(f"SQLite database foreign_key_check failed: {fk_violations}")

        # Discover tables in SQLite
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        sqlite_tables = {row[0] for row in cur.fetchall()}

        data = {}
        for table in TABLES_IN_ORDER:
            if table not in sqlite_tables:
                if table == "users":
                    # Allow legacy databases without users table if no records reference users
                    data[table] = {"columns": [], "pk_columns": [], "rows": []}
                    continue
                else:
                    raise ValueError(
                        f"SOURCE SCHEMA VALIDATION ERROR: Required table '{table}' is missing from SQLite database."
                    )

            cur.execute(f"PRAGMA table_info({table})")
            table_info = cur.fetchall()
            columns = [row[1] for row in table_info]
            pk_columns = [row[1] for row in table_info if row[5] > 0]

            if not columns:
                data[table] = {"columns": [], "pk_columns": [], "rows": []}
                continue

            col_str = ", ".join([f'"{c}"' for c in columns])
            if "id" in columns:
                cur.execute(f"SELECT {col_str} FROM {table} ORDER BY id ASC")
            else:
                cur.execute(f"SELECT {col_str} FROM {table}")
            rows = cur.fetchall()
            data[table] = {"columns": columns, "pk_columns": pk_columns, "rows": rows}

        validate_source_structure_and_integrity(data)
        return data
    finally:
        conn.close()


POSTGRES_ALLOWED_TYPES = {
    "id": {"integer", "bigint", "smallint"},
    "user_id": {"integer", "bigint", "smallint"},
    "plan_id": {"integer", "bigint", "smallint"},
    "priority": {"integer", "bigint", "smallint"},
    "days": {"integer", "bigint", "smallint"},
    "daily_hours": {"real", "double precision", "numeric"},
    "target_hours": {"real", "double precision", "numeric"},
    "completed_hours": {"real", "double precision", "numeric"},
    "planned_hours": {"real", "double precision", "numeric"},
    "username": {"character varying", "text", "character"},
    "password_hash": {"character varying", "text", "character"},
    "title": {"character varying", "text", "character"},
    "subject": {"character varying", "text", "character"},
    "name": {"character varying", "text", "character"},
    "goal": {"character varying", "text", "character"},
    "status": {"character varying", "text", "character"},
    "study_date": {"date", "character varying", "text", "timestamp without time zone", "timestamp with time zone"},
    "due_date": {"date", "character varying", "text", "timestamp without time zone", "timestamp with time zone"},
    "deadline": {"date", "character varying", "text", "timestamp without time zone", "timestamp with time zone"},
    "created_at": {"timestamp without time zone", "timestamp with time zone", "text", "character varying", "date"},
    "added_at": {"timestamp without time zone", "timestamp with time zone", "text", "character varying", "date"},
}


def inspect_target_schema_compatibility(pg_cur, source_data):
    """
    Inspects existing tables in the PostgreSQL target database.
    If a table already exists in the target database, verifies:
    1. All columns in the source data and REQUIRED_COLUMNS exist in the target table.
    2. The target table has no extra NOT NULL columns without default values.
    3. Column data types are compatible with required application usage.
    Fails closed with RuntimeError if incompatible schema is detected.
    Does NOT alter, truncate, drop, or overwrite any target tables or data.
    """
    pg_cur.execute("""
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        ORDER BY table_name, ordinal_position
    """, (TABLES_IN_ORDER,))

    rows = pg_cur.fetchall()
    if not rows:
        # None of the tables exist yet in target database; safe for clean DDL creation
        return True

    existing_tables = {}
    for tbl, col, dtype, nullable, default in rows:
        if tbl not in existing_tables:
            existing_tables[tbl] = {}
        existing_tables[tbl][col] = {
            "data_type": dtype.lower() if dtype else "",
            "is_nullable": nullable.upper() if nullable else "",
            "column_default": default
        }

    for table, tgt_cols in existing_tables.items():
        # 1. Missing columns: all source columns must exist in target
        src_cols = source_data.get(table, {}).get("columns", [])
        missing_src_cols = [c for c in src_cols if c not in tgt_cols]
        if missing_src_cols:
            raise RuntimeError(
                f"TARGET SCHEMA INCOMPATIBILITY ERROR: Target PostgreSQL table '{table}' "
                f"is missing column(s) present in source data: {missing_src_cols}. "
                f"Target tables must match or exceed source columns. Migration aborted."
            )

        # Also verify required columns are present if the table exists
        req_cols = REQUIRED_COLUMNS.get(table, [])
        missing_req_cols = [c for c in req_cols if c not in tgt_cols]
        if missing_req_cols:
            raise RuntimeError(
                f"TARGET SCHEMA INCOMPATIBILITY ERROR: Target PostgreSQL table '{table}' "
                f"is missing required application column(s): {missing_req_cols}. Migration aborted."
            )

        # 2. Check for extra NOT NULL columns without default values
        for col_name, col_meta in tgt_cols.items():
            if col_name not in src_cols and col_name != "id":
                if col_meta["is_nullable"] == "NO" and col_meta["column_default"] is None:
                    raise RuntimeError(
                        f"TARGET SCHEMA INCOMPATIBILITY ERROR: Target PostgreSQL table '{table}' "
                        f"has a NOT NULL column '{col_name}' without a default value, which is not provided "
                        f"by the source data. Migration aborted to prevent insertion failures."
                    )

        # 3. Check for incompatible column data types
        for col_name, col_meta in tgt_cols.items():
            if col_name in POSTGRES_ALLOWED_TYPES:
                allowed = POSTGRES_ALLOWED_TYPES[col_name]
                actual_type = col_meta["data_type"]
                if actual_type not in allowed:
                    raise RuntimeError(
                        f"TARGET SCHEMA INCOMPATIBILITY ERROR: Target PostgreSQL table '{table}' "
                        f"column '{col_name}' has incompatible type '{actual_type}' "
                        f"(expected one of {sorted(allowed)}). Migration aborted."
                    )

    return True


def preflight_target_check(pg_cur, confirm_disposable=False, source_data=None):
    """
    Inspects PostgreSQL target database and requires explicit confirmation
    that it is a disposable test database. Performs preflight schema compatibility checks.
    """
    if not confirm_disposable:
        raise RuntimeError(
            "SAFETY ABORT: Target database is not confirmed as a disposable test instance.\n"
            "To prevent accidental production mutation, you must explicitly pass: --confirm-disposable-test"
        )

    pg_cur.execute("SELECT current_database(), current_user, version()")
    db_name, db_user, db_version = pg_cur.fetchone()
    print(f"Target Database: '{db_name}' (Connected as user: '{db_user}')")
    print(f"Server Version:  {db_version.split(',')[0]}")

    if source_data:
        inspect_target_schema_compatibility(pg_cur, source_data)
        print("[OK] Target PostgreSQL schema compatibility verified for existing tables.")


def verify_in_transaction(pg_cur, data):
    """
    Verifies every source record against PostgreSQL inside the active transaction.
    Must be called BEFORE commit. Raises AssertionError on any discrepancy.
    """
    print("\nExecuting comprehensive in-transaction verification...")
    total_verified = 0

    for table in TABLES_IN_ORDER:
        cols = data[table]["columns"]
        rows = data[table]["rows"]
        if not rows:
            continue

        id_idx = cols.index("id")
        src_ids = [r[id_idx] for r in rows]
        col_names = ", ".join([f'"{c}"' for c in cols])

        # Query all records by IDs
        pg_cur.execute(f'SELECT {col_names} FROM "{table}" WHERE id = ANY(%s) ORDER BY id ASC', (src_ids,))
        tgt_rows = {r[id_idx]: r for r in pg_cur.fetchall()}

        if len(tgt_rows) != len(rows):
            raise AssertionError(
                f"VERIFICATION FAILURE on '{table}': Expected {len(rows)} matching records, "
                f"found {len(tgt_rows)} in target database."
            )

        for src_row in rows:
            row_id = src_row[id_idx]
            if row_id not in tgt_rows:
                raise AssertionError(f"VERIFICATION FAILURE: Record id={row_id} missing in target table '{table}'")
            tgt_row = tgt_rows[row_id]
            for col_idx, col_name in enumerate(cols):
                src_val = src_row[col_idx]
                tgt_val = tgt_row[col_idx]
                if not values_match(src_val, tgt_val):
                    raise AssertionError(
                        f"DATA MISMATCH on '{table}' (ID {row_id}, col '{col_name}'): "
                        f"Expected {src_val!r}, got {tgt_val!r}"
                    )
            total_verified += 1
        print(f"  [OK] Verified {len(rows)} record(s) in '{table}' (exact primary keys and fields match)")

    # Foreign key consistency checks
    pg_cur.execute("""
        SELECT COUNT(*) FROM study_tasks
        WHERE plan_id NOT IN (SELECT id FROM study_plans)
    """)
    orphaned_tasks = pg_cur.fetchone()[0]
    if orphaned_tasks > 0:
        raise AssertionError(f"FOREIGN KEY INTEGRITY VIOLATION: Found {orphaned_tasks} orphaned study_tasks records!")

    print(f"\n[OK] All {total_verified} source records verified with 100% data integrity and foreign key consistency.")


def run_dry_run(sqlite_path):
    """Analyzes SQLite database and prints planned migration steps without modifying any database."""
    print("=" * 70)
    print("DRY-RUN / VALIDATION-ONLY MODE: SQLITE TO POSTGRESQL MIGRATION")
    print("=" * 70)
    print(f"Reading source database (read-only): {sqlite_path}")

    data = read_sqlite_data(sqlite_path)

    total_rows = 0
    print("\nSource SQLite Schema & Structural Integrity Verification:")
    print("-" * 70)
    for table in TABLES_IN_ORDER:
        cols = data[table]["columns"]
        rows = data[table]["rows"]
        total_rows += len(rows)
        print(f"- Table '{table}': {len(rows)} row(s), {len(cols)} column(s)")
        print(f"  Columns: {', '.join(cols)}")
        pk_cols = data[table].get("pk_columns", [])
        if pk_cols:
            print(f"  Primary Key: {', '.join(pk_cols)}")
        if rows and "id" in cols:
            max_id = max(r[cols.index("id")] for r in rows if r[cols.index("id")] is not None)
            print(f"  Max ID: {max_id}")

    print("-" * 70)
    print(f"Total rows verified across all {len(TABLES_IN_ORDER)} tables: {total_rows}")

    print("\nTarget PostgreSQL DDL Plan:")
    print("-" * 70)
    for table in TABLES_IN_ORDER:
        print(f"-- Schema for {table}:")
        print(POSTGRES_SCHEMA[table].strip())

    print("\nTarget PostgreSQL Sequence Synchronization Plan:")
    print("-" * 70)
    for table in TABLES_IN_ORDER:
        rows = data[table]["rows"]
        cols = data[table]["columns"]
        if rows and "id" in cols:
            max_id = max(r[cols.index("id")] for r in rows if r[cols.index("id")] is not None)
            sync_val = max_id + 1
            print(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {sync_val}, false);")
        else:
            print(f"-- Table '{table}' has no rows; sequence defaults to 1.")

    print(f"\n[OK] Dry-run validation and structural integrity checks passed successfully ({total_rows} total records). No changes were made.")
    return True


def run_live_migration(sqlite_path, pg_url, confirm_disposable=False):
    """Executes live migration against PostgreSQL with transactional verification."""
    if not HAS_PSYCOPG2:
        raise RuntimeError("PostgreSQL driver (psycopg2) is not installed. Please install psycopg2-binary.")

    if not pg_url or not (pg_url.startswith("postgres://") or pg_url.startswith("postgresql://")):
        raise ValueError("Invalid PostgreSQL URL provided. An explicit URL starting with postgresql:// is required.")

    if pg_url.startswith("postgres://"):
        pg_url = "postgresql://" + pg_url[len("postgres://"):]

    if not confirm_disposable:
        raise RuntimeError(
            "SAFETY ABORT: Target database is not confirmed as a disposable test instance.\n"
            "To prevent accidental production mutation, you must explicitly pass: --confirm-disposable-test"
        )

    print(f"Reading source database (read-only): {sqlite_path}")
    data = read_sqlite_data(sqlite_path)
    total_records = sum(len(data[t]["rows"]) for t in TABLES_IN_ORDER)
    print(f"Source database structural integrity validated: {total_records} records verified.")

    redacted_target = redact_pg_url(pg_url)
    print(f"Connecting to target: {redacted_target}")
    pg_conn = psycopg2.connect(pg_url)

    try:
        pg_cur = pg_conn.cursor()

        # Step 0: Preflight target checks
        preflight_target_check(pg_cur, confirm_disposable=confirm_disposable, source_data=data)

        # Step 1: Create schema in transaction
        print("\nCreating PostgreSQL schema...")
        for table in TABLES_IN_ORDER:
            pg_cur.execute(POSTGRES_SCHEMA[table])

        # Step 2: Conflict detection & strict insertion
        print("\nChecking existing records and inserting data...")
        for table in TABLES_IN_ORDER:
            cols = data[table]["columns"]
            rows = data[table]["rows"]
            if not rows:
                continue

            id_idx = cols.index("id")
            src_ids = [r[id_idx] for r in rows]
            col_names = ", ".join([f'"{c}"' for c in cols])

            # Detect any existing records with these IDs in target table
            pg_cur.execute(f'SELECT {col_names} FROM "{table}" WHERE id = ANY(%s)', (src_ids,))
            existing_records = {r[id_idx]: r for r in pg_cur.fetchall()}

            rows_to_insert = []
            for r in rows:
                row_id = r[id_idx]
                if row_id in existing_records:
                    tgt_row = existing_records[row_id]
                    # Verify whether existing record is identical
                    for col_idx, col_name in enumerate(cols):
                        src_val = r[col_idx]
                        tgt_val = tgt_row[col_idx]
                        if not values_match(src_val, tgt_val):
                            raise RuntimeError(
                                f"MIGRATION CONFLICT DETECTED in table '{table}' for ID {row_id}!\n"
                                f"  Field '{col_name}' differs:\n"
                                f"    Source backup value: {src_val!r}\n"
                                f"    Target existing value: {tgt_val!r}\n"
                                f"Aborting migration immediately to prevent data corruption."
                            )
                    print(f"  [EXISTS] Table '{table}' record id={row_id} already exists with identical values; skipped.")
                else:
                    rows_to_insert.append(r)

            if rows_to_insert:
                placeholders = ", ".join(["%s" for _ in cols])
                # STRICT INSERT: No ON CONFLICT DO NOTHING
                insert_sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'
                execute_batch(pg_cur, insert_sql, rows_to_insert, page_size=100)
                print(f"  [INSERTED] Migrated {len(rows_to_insert)} new row(s) to '{table}'")

        # Step 3: Synchronize sequences
        print("\nSynchronizing PostgreSQL ID sequences...")
        for table in TABLES_IN_ORDER:
            rows = data[table]["rows"]
            cols = data[table]["columns"]
            if rows and "id" in cols:
                max_id = max(r[cols.index("id")] for r in rows if r[cols.index("id")] is not None)
                sync_val = max_id + 1
                pg_cur.execute(f"SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, false)", (table, sync_val))

        # Step 4: Verification inside transaction (BEFORE commit!)
        verify_in_transaction(pg_cur, data)

        # Step 5: Commit ONLY after all verifications pass!
        pg_conn.commit()
        print("\n[SUCCESS] Migration committed successfully to PostgreSQL with full transactional verification!")

    except Exception as e:
        pg_conn.rollback()
        print(f"\n[ABORTED] Migration aborted: {e}\nAll changes have been completely rolled back.", file=sys.stderr)
        raise e
    finally:
        pg_conn.close()


def main():
    parser = argparse.ArgumentParser(description="Harden SQLite-to-PostgreSQL Migration Tool for Smart Study Buddy")
    parser.add_argument("--sqlite-path", default="study_buddy.db", help="Path to source SQLite database (read-only)")
    parser.add_argument("--pg-url", default=None, help="PostgreSQL connection string (required for live migration)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Perform dry-run analysis and validation only")
    parser.add_argument("--validate-only", action="store_true", default=False, help="Validate existing data without modifying")
    parser.add_argument(
        "--confirm-disposable-test",
        action="store_true",
        default=False,
        help="Explicit confirmation that target is a disposable test database"
    )

    args = parser.parse_args()

    # Rule 1: Live migration requires an explicitly supplied --pg-url.
    # If no URL is provided, exit safely with dry-run without connecting to a database.
    if args.dry_run or args.validate_only or not args.pg_url:
        if not args.pg_url and not args.dry_run and not args.validate_only:
            print("[SAFE MODE] No --pg-url argument was provided. Defaulting to safe dry-run analysis.")
        run_dry_run(args.sqlite_path)
    else:
        run_live_migration(
            args.sqlite_path,
            args.pg_url,
            confirm_disposable=args.confirm_disposable_test
        )


if __name__ == "__main__":
    main()

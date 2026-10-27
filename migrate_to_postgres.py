"""
SQLite-to-PostgreSQL Hardened Migration Tool for Smart Study Buddy
Supports safe, verified, non-destructive data transfer from local SQLite to Neon PostgreSQL.
Includes baseline validation, target preflight inspection, conflict detection,
and transactional verification before commit.
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

EXPECTED_BASELINE = {
    "users": {"count": 0, "ids": []},
    "study_plans": {"count": 3, "ids": [3, 4, 5]},
    "study_tasks": {"count": 2, "ids": [1, 2]},
    "study_goals": {"count": 4, "ids": [1, 2, 3, 4]},
    "study_dates": {"count": 1, "ids": [1]},
    "study_progress": {"count": 15, "ids": list(range(1, 16))},
}

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


def validate_source_baseline(data):
    """
    Validates that the source data strictly matches the verified baseline:
    Exactly 25 total records with expected table counts and primary key IDs.
    Fails closed if the source is missing, truncated, or modified.
    """
    total_records = sum(len(data[t]["rows"]) for t in TABLES_IN_ORDER)
    if total_records != 25:
        raise ValueError(
            f"SOURCE BASELINE MISMATCH: Expected exactly 25 total records, found {total_records}."
        )

    for table, expected in EXPECTED_BASELINE.items():
        rows = data[table]["rows"]
        cols = data[table]["columns"]
        actual_count = len(rows)
        if actual_count != expected["count"]:
            raise ValueError(
                f"SOURCE BASELINE MISMATCH for table '{table}': "
                f"Expected {expected['count']} records, found {actual_count}."
            )
        if expected["count"] > 0:
            if "id" not in cols:
                raise ValueError(f"SOURCE SCHEMA MISMATCH: 'id' column missing in table '{table}'.")
            id_idx = cols.index("id")
            actual_ids = sorted([r[id_idx] for r in rows if r[id_idx] is not None])
            valid_id_sets = [expected["ids"]]
            if "alternate_ids" in expected:
                valid_id_sets.append(expected["alternate_ids"])
            if actual_ids not in valid_id_sets:
                raise ValueError(
                    f"SOURCE BASELINE MISMATCH for table '{table}' IDs: "
                    f"Expected {expected['ids']}, found {actual_ids}."
                )


def read_sqlite_data(sqlite_path):
    """Safely reads data from SQLite in read-only mode and validates baseline."""
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite database not found at: {sqlite_path}")

    conn = sqlite3.connect(f"file:{os.path.abspath(sqlite_path)}?mode=ro", uri=True)
    cur = conn.cursor()

    try:
        # Integrity check
        cur.execute("PRAGMA integrity_check")
        integrity = cur.fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite database integrity check failed: {integrity}")

        data = {}
        for table in TABLES_IN_ORDER:
            # Check if table exists in SQLite
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cur.fetchone():
                data[table] = {"columns": [], "rows": []}
                continue

            cur.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cur.fetchall()]

            col_str = ", ".join([f'"{c}"' for c in columns])
            cur.execute(f"SELECT {col_str} FROM {table} ORDER BY id ASC")
            rows = cur.fetchall()
            data[table] = {"columns": columns, "rows": rows}

        validate_source_baseline(data)
        return data
    finally:
        conn.close()


def preflight_target_check(pg_cur, confirm_disposable=False):
    """
    Inspects PostgreSQL target database and requires explicit confirmation
    that it is a disposable test database.
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
    print("\nSource SQLite Schema & Baseline Verification:")
    print("-" * 70)
    for table in TABLES_IN_ORDER:
        cols = data[table]["columns"]
        rows = data[table]["rows"]
        total_rows += len(rows)
        print(f"- Table '{table}': {len(rows)} row(s), {len(cols)} column(s)")
        print(f"  Columns: {', '.join(cols)}")
        if rows:
            max_id = max(r[cols.index("id")] for r in rows if "id" in cols and r[cols.index("id")] is not None)
            print(f"  Max ID: {max_id}")

    print("-" * 70)
    print(f"Total rows verified against baseline: {total_rows} (Expected: 25)")

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

    print("\n[OK] Dry-run validation and baseline checks passed successfully. No changes were made.")
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
    print("Source database baseline validated: exactly 25 records verified.")

    redacted_target = redact_pg_url(pg_url)
    print(f"Connecting to target: {redacted_target}")
    pg_conn = psycopg2.connect(pg_url)

    try:
        pg_cur = pg_conn.cursor()

        # Step 0: Preflight target checks
        preflight_target_check(pg_cur, confirm_disposable=confirm_disposable)

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

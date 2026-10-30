
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

# Use the database in the current project folder
db_path = Path("study_buddy.db").resolve()

if not db_path.exists():
    raise FileNotFoundError(
        f"Database not found: {db_path}\n"
        "Open the terminal in your project folder and try again."
    )

# Create a timestamped backup before making changes
backup_path = db_path.with_name(
    f"study_buddy_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
)
shutil.copy2(db_path, backup_path)

print(f"Backup created: {backup_path}")

conn = sqlite3.connect(db_path)

try:
    # Start a transaction so the changes can be rolled back
    conn.execute("BEGIN")

    cursor = conn.cursor()

    # Preview exactly what will be affected
    cursor.execute("""
        SELECT COUNT(*)
        FROM study_plans
        WHERE TRIM(subject) = 'eng' COLLATE NOCASE
    """)
    plan_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM study_progress
        WHERE TRIM(subject) = 'eng' COLLATE NOCASE
    """)
    progress_count = cursor.fetchone()[0]

    print(f"eng plans to delete: {plan_count}")
    print(f"eng progress records to delete: {progress_count}")

    # Delete only eng progress records
    cursor.execute("""
        DELETE FROM study_progress
        WHERE TRIM(subject) = 'eng' COLLATE NOCASE
    """)

    # Delete only eng study plans
    cursor.execute("""
        DELETE FROM study_plans
        WHERE TRIM(subject) = 'eng' COLLATE NOCASE
    """)

    # Verify that no matching records remain
    cursor.execute("""
        SELECT COUNT(*)
        FROM study_plans
        WHERE TRIM(subject) = 'eng' COLLATE NOCASE
    """)
    remaining_plans = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM study_progress
        WHERE TRIM(subject) = 'eng' COLLATE NOCASE
    """)
    remaining_progress = cursor.fetchone()[0]

    if remaining_plans != 0 or remaining_progress != 0:
        raise RuntimeError("Verification failed; changes will be rolled back.")

    conn.commit()

    print("\nSUCCESS: eng records removed.")
    print(f"Study plans deleted: {plan_count}")
    print(f"Progress records deleted: {progress_count}")
    print("Other subjects were not targeted.")
    print(f"Backup available at: {backup_path}")

except Exception:
    conn.rollback()
    print("\nERROR: Changes were rolled back.")
    raise

finally:
    conn.close()
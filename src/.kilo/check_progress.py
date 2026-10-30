
import sqlite3
from pathlib import Path

# Your database is in the main project folder
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_DIR / "study_buddy.db"

if not DATABASE_PATH.exists():
    print("Database not found at:", DATABASE_PATH)
    print("Check the database filename in your project folder.")
    raise SystemExit

# Open database in read-only mode
connection = sqlite3.connect(
    DATABASE_PATH.as_uri() + "?mode=ro",
    uri=True
)

cursor = connection.cursor()

print("\n--- Individual Progress Records ---")

cursor.execute("""
    SELECT id, subject, planned_hours, completed_hours, added_at
    FROM study_progress
    ORDER BY id
""")

rows = cursor.fetchall()

if rows:
    for row in rows:
        print(row)
else:
    print("No progress records found.")

print("\n--- Totals by Subject ---")

cursor.execute("""
    SELECT
        subject,
        COUNT(*) AS entries,
        SUM(planned_hours) AS planned_hours,
        SUM(completed_hours) AS completed_hours
    FROM study_progress
    GROUP BY subject
""")

for row in cursor.fetchall():
    print(row)
print("\n--- Study Plans ---")

cursor.execute("""
    SELECT id, name, subject, priority, days, daily_hours
    FROM study_plans
    ORDER BY id
""")

for row in cursor.fetchall():
    print(row)
connection.close()
print("\nInspection complete. No records were changed.")
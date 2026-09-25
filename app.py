from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import date, timedelta

app = Flask(__name__)

DATABASE = "study_buddy.db"


# ==================================================
# DATABASE CONNECTION
# ==================================================

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ==================================================
# DATABASE SETUP
# ==================================================

def setup_database():

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            subject TEXT,
            priority INTEGER,
            days INTEGER,
            daily_hours REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            planned_hours REAL,
            completed_hours REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal TEXT,
            target_hours REAL,
            completed_hours REAL DEFAULT 0,
            deadline TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)

    # Add added_at column if it does not exist
    try:
        cursor.execute("""
            ALTER TABLE study_progress
            ADD COLUMN added_at TEXT
        """)
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_date TEXT UNIQUE
        )
    """)

    conn.commit()
    conn.close()


# ==================================================
# STUDY STREAK
# ==================================================

def get_study_streak(cursor):

    cursor.execute("""
        SELECT study_date
        FROM study_dates
        ORDER BY study_date ASC
    """)

    rows = cursor.fetchall()

    study_dates = set()

    for row in rows:

        try:
            study_date = date.fromisoformat(row[0])
            study_dates.add(study_date)

        except (ValueError, TypeError):
            continue

    if not study_dates:

        return {
            "current": 0,
            "longest": 0,
            "total_days": 0
        }

    total_days = len(study_dates)

    # --------------------------------------------------
    # LONGEST STREAK
    # --------------------------------------------------

    sorted_dates = sorted(study_dates)

    longest_streak = 1
    current_streak = 1

    for i in range(1, len(sorted_dates)):

        difference = (
            sorted_dates[i]
            - sorted_dates[i - 1]
        ).days

        if difference == 1:

            current_streak += 1

            if current_streak > longest_streak:
                longest_streak = current_streak

        else:

            current_streak = 1

    # --------------------------------------------------
    # CURRENT STREAK
    # --------------------------------------------------

    today = date.today()

    current_streak = 0
    check_date = today

    if today not in study_dates:

        yesterday = today - timedelta(days=1)

        if yesterday in study_dates:
            check_date = yesterday

        else:
            check_date = None

    if check_date is not None:

        while check_date in study_dates:

            current_streak += 1

            check_date = (
                check_date
                - timedelta(days=1)
            )

    return {
        "current": current_streak,
        "longest": longest_streak,
        "total_days": total_days
    }


# ==================================================
# DEADLINE STATUS
# ==================================================

def get_deadline_status(deadline, status):

    if status == "Completed":
        return "Completed"

    try:

        deadline_date = date.fromisoformat(deadline)

    except (ValueError, TypeError):

        return "No Deadline"

    today = date.today()

    remaining_days = (
        deadline_date - today
    ).days

    if remaining_days < 0:
        return "Overdue"

    elif remaining_days == 0:
        return "Due Today"

    elif remaining_days <= 3:
        return "Due Soon"

    else:
        return "In Progress"


# ==================================================
# GOAL RECOMMENDATION
# ==================================================

def get_goal_recommendation(
    target,
    completed,
    deadline,
    status
):

    if status == "Completed":

        return {
            "days_left": 0,
            "remaining_hours": 0,
            "daily_hours": 0,
            "recommendation":
                "🎉 Goal completed! Great work!"
        }

    try:

        deadline_date = date.fromisoformat(
            deadline
        )

    except (ValueError, TypeError):

        return {
            "days_left": None,
            "remaining_hours":
                max(target - completed, 0),
            "daily_hours": 0,
            "recommendation":
                "📅 Add a valid deadline to get a daily study recommendation."
        }

    today = date.today()

    days_left = (
        deadline_date - today
    ).days

    remaining_hours = max(
        target - completed,
        0
    )

    if days_left < 0:

        return {
            "days_left": days_left,
            "remaining_hours": remaining_hours,
            "daily_hours": 0,
            "recommendation":
                f"🔴 This goal is overdue with "
                f"{remaining_hours:.1f} hours remaining."
        }

    if days_left == 0:

        return {
            "days_left": 0,
            "remaining_hours": remaining_hours,
            "daily_hours": remaining_hours,
            "recommendation":
                f"⚠️ Deadline is today. "
                f"Complete {remaining_hours:.1f} more hours."
        }

    if remaining_hours <= 0:

        return {
            "days_left": days_left,
            "remaining_hours": 0,
            "daily_hours": 0,
            "recommendation":
                "🎉 Goal requirements completed!"
        }

    daily_hours = (
        remaining_hours / days_left
    )

    return {
        "days_left": days_left,
        "remaining_hours": remaining_hours,
        "daily_hours": daily_hours,
        "recommendation":
            f"💡 Study {daily_hours:.1f} hours/day "
            f"to complete this goal on time."
    }


# ==================================================
# DASHBOARD RECOMMENDATION
# ==================================================

def get_dashboard_recommendation(cursor):

    cursor.execute("""
        SELECT
            goal,
            target_hours,
            completed_hours,
            deadline,
            status
        FROM study_goals
        WHERE status != 'Completed'
        ORDER BY id DESC
    """)

    goals = cursor.fetchall()

    if not goals:

        return (
            "📚 No active goals right now. "
            "Create a study goal to get smart recommendations!"
        )

    # --------------------------------------------------
    # OVERDUE GOALS
    # --------------------------------------------------

    for goal in goals:

        goal_name = goal[0]
        target = goal[1]
        completed = goal[2]
        deadline = goal[3]
        status = goal[4]

        recommendation = get_goal_recommendation(
            target,
            completed,
            deadline,
            status
        )

        if recommendation["days_left"] is not None:

            if recommendation["days_left"] < 0:

                return (
                    f"🔴 Attention Needed: "
                    f"'{goal_name}' is overdue with "
                    f"{recommendation['remaining_hours']:.1f} "
                    f"hours remaining."
                )

    # --------------------------------------------------
    # DEADLINE TODAY
    # --------------------------------------------------

    for goal in goals:

        goal_name = goal[0]
        target = goal[1]
        completed = goal[2]
        deadline = goal[3]
        status = goal[4]

        recommendation = get_goal_recommendation(
            target,
            completed,
            deadline,
            status
        )

        if recommendation["days_left"] == 0:

            return (
                f"⚠️ Deadline Today: "
                f"'{goal_name}' has "
                f"{recommendation['remaining_hours']:.1f} "
                f"hours remaining."
            )

    # --------------------------------------------------
    # NEAREST UPCOMING GOAL
    # --------------------------------------------------

    urgent_goal = None
    urgent_days = None

    for goal in goals:

        target = goal[1]
        completed = goal[2]
        deadline = goal[3]
        status = goal[4]

        recommendation = get_goal_recommendation(
            target,
            completed,
            deadline,
            status
        )

        days_left = recommendation["days_left"]

        if days_left is None:
            continue

        if days_left > 0:

            if (
                urgent_days is None
                or days_left < urgent_days
            ):

                urgent_days = days_left

                urgent_goal = (
                    goal,
                    recommendation
                )

    if urgent_goal:

        goal = urgent_goal[0]
        recommendation = urgent_goal[1]

        goal_name = goal[0]

        return (
            f"💡 Smart Plan: Study "
            f"{recommendation['daily_hours']:.1f} "
            f"hours/day for '{goal_name}' "
            f"to finish it in time."
        )

    return (
        "📚 Keep going! "
        "Continue following your study schedule."
    )


# ==================================================
# DASHBOARD DATA
# ==================================================

def get_dashboard_data():

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    # Total subjects
    cursor.execute("""
        SELECT DISTINCT subject
        FROM study_plans
    """)

    subjects = cursor.fetchall()

    total_subjects = len(subjects)

    # Planned hours
    cursor.execute("""
        SELECT SUM(days * daily_hours)
        FROM study_plans
    """)

    planned_result = cursor.fetchone()[0]

    planned_hours = planned_result or 0

    # Completed hours
    cursor.execute("""
        SELECT SUM(completed_hours)
        FROM study_progress
    """)

    completed_result = cursor.fetchone()[0]

    completed_hours = completed_result or 0

    # Overall progress
    if planned_hours > 0:

        overall_progress = (
            completed_hours /
            planned_hours
        ) * 100

    else:

        overall_progress = 0

    # Prevent progress from going above 100
    overall_progress = min(
        overall_progress,
        100
    )

    # Active goals
    cursor.execute("""
        SELECT COUNT(*)
        FROM study_goals
        WHERE status != 'Completed'
    """)

    active_goals = cursor.fetchone()[0]

    # Completed goals
    cursor.execute("""
        SELECT COUNT(*)
        FROM study_goals
        WHERE status = 'Completed'
    """)

    completed_goals = cursor.fetchone()[0]

    # Recommendation
    recommendation = (
        get_dashboard_recommendation(cursor)
    )

    # Study streak
    streak = get_study_streak(cursor)

    conn.close()

    return {
        "total_subjects": total_subjects,
        "planned_hours": planned_hours,
        "completed_hours": completed_hours,
        "overall_progress": overall_progress,
        "active_goals": active_goals,
        "completed_goals": completed_goals,
        "recommendation": recommendation,
        "streak": streak
    }


# ==================================================
# DASHBOARD
# ==================================================

@app.route("/")
def index():

    data = get_dashboard_data()

    return render_template(
        "index.html",
        data=data,
        total_subjects=data["total_subjects"],
        planned_hours=data["planned_hours"],
        completed_hours=data["completed_hours"],
        overall_progress=data["overall_progress"],
        active_goals=data["active_goals"],
        completed_goals=data["completed_goals"],
        recommendation=data["recommendation"],
        streak=data["streak"]
    )


# ==================================================
# ADD STUDY PLAN
# ==================================================

@app.route(
    "/add-plan",
    methods=["POST"]
)
def add_plan():

    name = request.form["name"]

    subject = request.form["subject"]

    priority = int(
        request.form["priority"]
    )

    days = int(
        request.form["days"]
    )

    daily_hours = float(
        request.form["daily_hours"]
    )

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO study_plans
        (
            name,
            subject,
            priority,
            days,
            daily_hours
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        subject,
        priority,
        days,
        daily_hours
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("plans")
    )


# ==================================================
# STUDY PLANS
# ==================================================

@app.route("/plans")
def plans():

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            subject,
            priority,
            days,
            daily_hours
        FROM study_plans
        ORDER BY id DESC
    """)

    plans_data = cursor.fetchall()

    conn.close()

    return render_template(
        "plans.html",
        plans=plans_data
    )


# ==================================================
# DELETE PLAN
# ==================================================

@app.route(
    "/delete-plan/<int:plan_id>"
)
def delete_plan(plan_id):

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    # Find the subject before deleting
    cursor.execute("""
        SELECT subject
        FROM study_plans
        WHERE id = ?
    """, (plan_id,))

    result = cursor.fetchone()

    cursor.execute("""
        DELETE FROM study_plans
        WHERE id = ?
    """, (plan_id,))

    conn.commit()
    conn.close()

    return redirect(
        url_for("plans")
    )


# ==================================================
# UPDATE PLAN
# ==================================================

@app.route(
    "/update-plan/<int:plan_id>",
    methods=["GET", "POST"]
)
def update_plan(plan_id):

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    if request.method == "POST":

        priority = int(
            request.form["priority"]
        )

        days = int(
            request.form["days"]
        )

        daily_hours = float(
            request.form["daily_hours"]
        )

        cursor.execute("""
            UPDATE study_plans
            SET
                priority = ?,
                days = ?,
                daily_hours = ?
            WHERE id = ?
        """, (
            priority,
            days,
            daily_hours,
            plan_id
        ))

        conn.commit()
        conn.close()

        return redirect(
            url_for("plans")
        )

    cursor.execute("""
        SELECT *
        FROM study_plans
        WHERE id = ?
    """, (plan_id,))

    plan = cursor.fetchone()

    conn.close()

    return render_template(
        "update_plan.html",
        plan=plan
    )


# ==================================================
# PROGRESS PAGE
# ==================================================

@app.route("/progress")
def progress():

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            subject,
            SUM(planned_hours),
            SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)

    progress_rows = cursor.fetchall()

    subjects = []

    for row in progress_rows:

        subject = row[0]

        planned = row[1] or 0

        completed = row[2] or 0

        if planned > 0:

            percentage = (
                completed /
                planned
            ) * 100

        else:

            percentage = 0

        percentage = min(
            percentage,
            100
        )

        subjects.append((
            subject,
            planned,
            completed,
            percentage
        ))

    # Subjects from study plans
    cursor.execute("""
        SELECT DISTINCT subject
        FROM study_plans
    """)

    planned_subjects = [
        row[0]
        for row in cursor.fetchall()
    ]

    existing_subjects = [
        row[0]
        for row in subjects
    ]

    for subject in planned_subjects:

        if subject not in existing_subjects:

            cursor.execute("""
                SELECT
                    SUM(days * daily_hours)
                FROM study_plans
                WHERE subject = ?
            """, (subject,))

            planned = (
                cursor.fetchone()[0] or 0
            )

            subjects.append((
                subject,
                planned,
                0,
                0
            ))

    # Progress history
    cursor.execute("""
        SELECT
            subject,
            completed_hours,
            added_at
        FROM study_progress
        ORDER BY id DESC
    """)

    history = cursor.fetchall()

    conn.close()

    return render_template(
        "progress.html",
        subjects=subjects,
        history=history
    )


# ==================================================
# ADD PROGRESS
# ==================================================

@app.route(
    "/add-progress",
    methods=["POST"]
)
def add_progress():

    subject = request.form["subject"]

    completed_hours = float(
        request.form["completed_hours"]
    )

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    # Planned hours
    cursor.execute("""
        SELECT
            SUM(days * daily_hours)
        FROM study_plans
        WHERE subject = ?
    """, (subject,))

    planned_result = cursor.fetchone()[0]

    planned = planned_result or 0

    # Completed hours
    cursor.execute("""
        SELECT
            SUM(completed_hours)
        FROM study_progress
        WHERE subject = ?
    """, (subject,))

    completed_result = cursor.fetchone()[0]

    completed = completed_result or 0

    remaining = planned - completed

    # Prevent invalid negative values
    if completed_hours <= 0:

        conn.close()

        return redirect(
            url_for("progress")
        )

    # Prevent exceeding planned hours
    if completed_hours > remaining:

        conn.close()

        return render_template(
            "progress_error.html",
            subject=subject,
            attempted=completed_hours,
            planned=planned,
            completed=completed,
            remaining=remaining
        )

    # Save progress
    today = date.today().isoformat()

    cursor.execute("""
        INSERT INTO study_progress
        (
            subject,
            planned_hours,
            completed_hours,
            added_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        subject,
        planned,
        completed_hours,
        today
    ))

    # Save study date
    cursor.execute("""
        INSERT OR IGNORE INTO study_dates
        (
            study_date
        )
        VALUES (?)
    """, (today,))

    conn.commit()
    conn.close()

    return redirect(
        url_for("progress")
    )


# ==================================================
# GOALS PAGE
# ==================================================

@app.route("/goals")
def goals():

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            goal,
            target_hours,
            completed_hours,
            deadline,
            status
        FROM study_goals
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()

    goals_data = []

    for row in rows:

        goal_id = row[0]
        goal_name = row[1]
        target = row[2]
        completed = row[3]
        deadline = row[4]
        status = row[5]

        remaining = max(
            target - completed,
            0
        )

        recommendation = (
            get_goal_recommendation(
                target,
                completed,
                deadline,
                status
            )
        )

        deadline_status = (
            get_deadline_status(
                deadline,
                status
            )
        )

        if target > 0:

            percentage = (
                completed /
                target
            ) * 100

        else:

            percentage = 0

        percentage = min(
            percentage,
            100
        )

        goals_data.append({

            "id": goal_id,

            "goal": goal_name,

            "target_hours": target,

            "completed_hours": completed,

            "remaining_hours": remaining,

            "deadline": deadline,

            "status": status,

            "deadline_status":
                deadline_status,

            "days_left":
                recommendation["days_left"],

            "daily_hours":
                recommendation["daily_hours"],

            "recommendation":
                recommendation["recommendation"],

            "percentage": percentage,

            "progress": percentage
        })

    conn.close()

    return render_template(
        "goals.html",
        goals=goals_data
    )


# ==================================================
# ADD GOAL
# ==================================================

@app.route(
    "/add-goal",
    methods=["POST"]
)
def add_goal():

    goal = request.form["goal"]

    target_hours = float(
        request.form["target_hours"]
    )

    deadline = request.form["deadline"]

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO study_goals
        (
            goal,
            target_hours,
            completed_hours,
            deadline,
            status
        )
        VALUES (?, ?, 0, ?, 'Pending')
    """, (
        goal,
        target_hours,
        deadline
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("goals")
    )


# ==================================================
# ADD GOAL PROGRESS
# ==================================================

@app.route(
    "/add-goal-progress",
    methods=["POST"]
)
def add_goal_progress():

    goal_id = request.form.get(
        "goal_id"
    )

    # Compatibility with older HTML
    if goal_id:

        goal_id = int(goal_id)

    else:

        goal_name = request.form.get(
            "goal"
        )

        conn = sqlite3.connect(
            DATABASE
        )

        cursor = conn.cursor()

        cursor.execute("""
            SELECT id
            FROM study_goals
            WHERE goal = ?
            ORDER BY id DESC
            LIMIT 1
        """, (goal_name,))

        result = cursor.fetchone()

        if result is None:

            conn.close()

            return redirect(
                url_for("goals")
            )

        goal_id = result[0]

        conn.close()

    hours = float(
        request.form["completed_hours"]
    )

    if hours <= 0:

        return redirect(
            url_for("goals")
        )

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            target_hours,
            completed_hours,
            status
        FROM study_goals
        WHERE id = ?
    """, (goal_id,))

    result = cursor.fetchone()

    if result is None:

        conn.close()

        return redirect(
            url_for("goals")
        )

    target = result[0]
    completed = result[1]
    status = result[2]

    remaining = (
        target - completed
    )

    # Completed goal
    if status == "Completed":

        conn.close()

        return redirect(
            url_for("goals")
        )

    # Prevent exceeding target
    if hours > remaining:

        conn.close()

        return redirect(
            url_for("goals")
        )

    new_completed = (
        completed + hours
    )

    if new_completed >= target:

        new_status = "Completed"

    elif new_completed > 0:

        new_status = "In Progress"

    else:

        new_status = "Pending"

    cursor.execute("""
        UPDATE study_goals
        SET
            completed_hours = ?,
            status = ?
        WHERE id = ?
    """, (
        new_completed,
        new_status,
        goal_id
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("goals")
    )


# ==================================================
# SUBJECT-WISE ANALYTICS
# STEP 74
# ==================================================

@app.route("/analytics")
def analytics():

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    # --------------------------------------------------
    # GET ALL SUBJECTS
    # --------------------------------------------------

    cursor.execute("""
        SELECT DISTINCT subject
        FROM study_plans
        ORDER BY subject
    """)

    subject_rows = cursor.fetchall()

    analytics_data = []

    for row in subject_rows:

        subject = row[0]

        # Planned hours
        cursor.execute("""
            SELECT
                SUM(days * daily_hours)
            FROM study_plans
            WHERE subject = ?
        """, (subject,))

        planned_result = cursor.fetchone()[0]

        planned = planned_result or 0

        # Completed hours
        cursor.execute("""
            SELECT
                SUM(completed_hours)
            FROM study_progress
            WHERE subject = ?
        """, (subject,))

        completed_result = cursor.fetchone()[0]

        completed = completed_result or 0

        # Remaining hours
        remaining = max(
            planned - completed,
            0
        )

        # Percentage
        if planned > 0:

            percentage = (
                completed /
                planned
            ) * 100

        else:

            percentage = 0

        percentage = min(
            percentage,
            100
        )

        analytics_data.append({

            "subject": subject,

            "planned": planned,

            "completed": completed,

            "remaining": remaining,

            "percentage": percentage
        })

    conn.close()

    # --------------------------------------------------
    # ANALYTICS INSIGHTS
    # --------------------------------------------------

    total_planned = sum(
        item["planned"]
        for item in analytics_data
    )

    total_completed = sum(
        item["completed"]
        for item in analytics_data
    )

    total_remaining = sum(
        item["remaining"]
        for item in analytics_data
    )

    if total_planned > 0:

        overall_percentage = (
            total_completed /
            total_planned
        ) * 100

    else:

        overall_percentage = 0

    overall_percentage = min(
        overall_percentage,
        100
    )

    if analytics_data:

        most_planned = max(
            analytics_data,
            key=lambda item: item["planned"]
        )

        most_completed = max(
            analytics_data,
            key=lambda item: item["completed"]
        )

        most_remaining = max(
            analytics_data,
            key=lambda item: item["remaining"]
        )

    else:

        most_planned = None
        most_completed = None
        most_remaining = None

    return render_template(
        "analytics.html",
        subjects=analytics_data,
        total_planned=total_planned,
        total_completed=total_completed,
        total_remaining=total_remaining,
        overall_percentage=overall_percentage,
        most_planned=most_planned,
        most_completed=most_completed,
        most_remaining=most_remaining
    )


# ==================================================
# STUDY CALENDAR
# ==================================================

@app.route("/calendar")
def calendar():

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT study_date
        FROM study_dates
        ORDER BY study_date
    """)

    rows = cursor.fetchall()

    conn.close()

    study_dates = set()

    for row in rows:

        try:

            study_dates.add(
                date.fromisoformat(row[0])
            )

        except (ValueError, TypeError):

            continue

    # Current month
    today = date.today()

    year = today.year
    month = today.month

    # First day
    first_day = date(
        year,
        month,
        1
    )

    # Weekday
    start_weekday = (
        first_day.weekday()
    )

    # Number of days
    if month == 12:

        next_month = date(
            year + 1,
            1,
            1
        )

    else:

        next_month = date(
            year,
            month + 1,
            1
        )

    days_in_month = (
        next_month - first_day
    ).days

    calendar_days = []

    # Empty cells
    for _ in range(start_weekday):

        calendar_days.append(None)

    # Actual days
    for day_number in range(
        1,
        days_in_month + 1
    ):

        current_date = date(
            year,
            month,
            day_number
        )

        calendar_days.append({

            "day": day_number,

            "date":
                current_date.isoformat(),

            "studied":
                current_date in study_dates,

            "today":
                current_date == today
        })

    return render_template(
        "calendar.html",
        calendar_days=calendar_days,
        month_name=first_day.strftime("%B"),
        year=year
    )


# ==================================================
# START APPLICATION
# ==================================================

if __name__ == "__main__":

    setup_database()

    app.run(
        debug=True
    )
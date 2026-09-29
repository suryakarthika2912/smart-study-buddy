from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime, date, timedelta
import calendar as pycalendar

app = Flask(__name__)

DATABASE = "study_buddy.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# DATABASE SETUP
# ============================================================

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_date TEXT UNIQUE
        )
    """)

    # Added in the progress-history feature.
    try:
        cursor.execute("""
            ALTER TABLE study_progress
            ADD COLUMN added_at TEXT
        """)
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# ============================================================
# SMALL HELPERS
# ============================================================

def safe_percentage(completed, planned):
    if planned and planned > 0:
        return min((completed / planned) * 100, 100)
    return 0


def get_study_streak(cursor):
    cursor.execute("""
        SELECT study_date
        FROM study_dates
        ORDER BY study_date
    """)

    rows = cursor.fetchall()
    dates = set()

    for row in rows:
        try:
            dates.add(date.fromisoformat(row[0]))
        except (ValueError, TypeError):
            pass

    if not dates:
        return {
            "current": 0,
            "longest": 0,
            "total_days": 0
        }

    sorted_dates = sorted(dates)

    longest = 1
    running = 1

    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
            running += 1
            longest = max(longest, running)
        else:
            running = 1

    today = date.today()

    if today in dates:
        check = today
    elif today - timedelta(days=1) in dates:
        check = today - timedelta(days=1)
    else:
        check = None

    current = 0

    while check is not None and check in dates:
        current += 1
        check -= timedelta(days=1)

    return {
        "current": current,
        "longest": longest,
        "total_days": len(dates)
    }


def get_deadline_status(deadline, status):
    if status == "Completed":
        return "Completed"

    if not deadline:
        return "No Deadline"

    try:
        deadline_date = date.fromisoformat(deadline)
    except (ValueError, TypeError):
        return "No Deadline"

    days_left = (deadline_date - date.today()).days

    if days_left < 0:
        return "Overdue"
    if days_left == 0:
        return "Due Today"
    if days_left <= 3:
        return "Due Soon"

    return "In Progress"


def get_goal_recommendation(target, completed, deadline, status):
    remaining = max((target or 0) - (completed or 0), 0)

    if status == "Completed":
        return {
            "days_left": 0,
            "remaining_hours": 0,
            "daily_hours": 0,
            "recommendation": "🎉 Goal completed! Great work!"
        }

    if not deadline:
        return {
            "days_left": None,
            "remaining_hours": remaining,
            "daily_hours": 0,
            "recommendation":
                "📅 Add a deadline to get a daily study recommendation."
        }

    try:
        deadline_date = date.fromisoformat(deadline)
    except (ValueError, TypeError):
        return {
            "days_left": None,
            "remaining_hours": remaining,
            "daily_hours": 0,
            "recommendation":
                "📅 Add a valid deadline to get a daily recommendation."
        }

    days_left = (deadline_date - date.today()).days

    if remaining <= 0:
        return {
            "days_left": days_left,
            "remaining_hours": 0,
            "daily_hours": 0,
            "recommendation": "🎉 Goal requirements completed!"
        }

    if days_left < 0:
        return {
            "days_left": days_left,
            "remaining_hours": remaining,
            "daily_hours": 0,
            "recommendation":
                f"🔴 This goal is overdue with {remaining:.1f} hours remaining."
        }

    if days_left == 0:
        return {
            "days_left": 0,
            "remaining_hours": remaining,
            "daily_hours": remaining,
            "recommendation":
                f"⚠️ Deadline is today. Complete {remaining:.1f} more hours."
        }

    daily = remaining / days_left

    return {
        "days_left": days_left,
        "remaining_hours": remaining,
        "daily_hours": daily,
        "recommendation":
            f"💡 Study {daily:.1f} hours/day to complete this goal on time."
    }


# ============================================================
# GOAL DATA
# ============================================================

def get_goals_data(cursor=None):
    own_connection = cursor is None

    if own_connection:
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
    result = []

    for row in rows:
        goal_id = row[0]
        goal_name = row[1]
        target = row[2] or 0
        completed = row[3] or 0
        deadline = row[4]
        status = row[5]

        recommendation = get_goal_recommendation(
            target,
            completed,
            deadline,
            status
        )

        percentage = safe_percentage(completed, target)

        result.append({
            "id": goal_id,
            "goal": goal_name,
            "target": target,
            "target_hours": target,
            "completed": completed,
            "completed_hours": completed,
            "remaining": max(target - completed, 0),
            "remaining_hours": max(target - completed, 0),
            "deadline": deadline,
            "status": status,
            "deadline_status":
                get_deadline_status(deadline, status),
            "days_left":
                recommendation["days_left"],
            "daily_hours":
                recommendation["daily_hours"],
            "recommendation":
                recommendation["recommendation"],
            "percentage": percentage,
            "progress": percentage
        })

    if own_connection:
        conn.close()

    return result


def get_dashboard_recommendation(cursor):
    goals = get_goals_data(cursor)

    active = [
        goal for goal in goals
        if goal["status"] != "Completed"
    ]

    if not active:
        return (
            "📚 No active goals right now. "
            "Create a study goal to get smart recommendations!"
        )

    overdue = [
        goal for goal in active
        if goal["deadline_status"] == "Overdue"
    ]

    if overdue:
        goal = overdue[0]
        return (
            f"🔴 Attention Needed: '{goal['goal']}' is overdue with "
            f"{goal['remaining_hours']:.1f} hours remaining."
        )

    today_goals = [
        goal for goal in active
        if goal["deadline_status"] == "Due Today"
    ]

    if today_goals:
        goal = today_goals[0]
        return (
            f"⚠️ Deadline Today: '{goal['goal']}' has "
            f"{goal['remaining_hours']:.1f} hours remaining."
        )

    upcoming = [
        goal for goal in active
        if goal["days_left"] is not None
        and goal["days_left"] > 0
    ]

    if upcoming:
        goal = min(upcoming, key=lambda item: item["days_left"])
        return (
            f"💡 Smart Plan: Study {goal['daily_hours']:.1f} hours/day "
            f"for '{goal['goal']}' to finish it in time."
        )

    return "📚 Keep going! Continue following your study schedule."


# ============================================================
# SUBJECT DATA
# ============================================================

def get_subject_data(cursor):
    cursor.execute("""
        SELECT
            subject,
            SUM(days * daily_hours) AS planned
        FROM study_plans
        GROUP BY subject
        ORDER BY subject
    """)

    planned_rows = cursor.fetchall()

    cursor.execute("""
        SELECT
            subject,
            SUM(completed_hours) AS completed
        FROM study_progress
        GROUP BY subject
    """)

    completed_rows = cursor.fetchall()

    completed_map = {
        row[0]: (row[1] or 0)
        for row in completed_rows
    }

    subjects = []

    for row in planned_rows:
        subject = row[0]
        planned = row[1] or 0
        completed = completed_map.get(subject, 0)
        progress = safe_percentage(completed, planned)

        if progress >= 70:
            status = "On Track"
            status_icon = "🟢"
        elif progress >= 30:
            status = "Needs Attention"
            status_icon = "🟡"
        elif progress > 0:
            status = "Behind"
            status_icon = "🔴"
        else:
            status = "Not Started"
            status_icon = "⚪"

        subjects.append({
            "name": subject,
            "subject": subject,
            "planned": planned,
            "completed": completed,
            "remaining": max(planned - completed, 0),
            "progress": progress,
            "percentage": progress,
            "status": status,
            "status_icon": status_icon
        })

    return subjects


# ============================================================
# DASHBOARD DATA
# ============================================================

def get_dashboard_data():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    subjects = get_subject_data(cursor)

    total_subjects = len(subjects)
    planned_hours = sum(item["planned"] for item in subjects)
    completed_hours = sum(item["completed"] for item in subjects)

    overall_progress = safe_percentage(
        completed_hours,
        planned_hours
    )

    cursor.execute("""
        SELECT COUNT(*)
        FROM study_goals
        WHERE status != 'Completed'
    """)
    active_goals = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM study_goals
        WHERE status = 'Completed'
    """)
    completed_goals = cursor.fetchone()[0]

    recommendation = get_dashboard_recommendation(cursor)
    streak = get_study_streak(cursor)
    goals = get_goals_data(cursor)

    # Priority recommendation.
    recommendation_subject = ""
    recommendation_priority = 0

    cursor.execute("""
        SELECT subject, priority
        FROM study_plans
        ORDER BY priority DESC, id DESC
        LIMIT 1
    """)

    priority_row = cursor.fetchone()

    if priority_row:
        recommendation_subject = priority_row[0]
        recommendation_priority = priority_row[1] or 0

    # Today's studied hours.
    today = date.today().isoformat()

    cursor.execute("""
        SELECT SUM(completed_hours)
        FROM study_progress
        WHERE DATE(added_at) = ?
    """, (today,))

    today_hours = cursor.fetchone()[0] or 0

    # Recent progress.
    cursor.execute("""
        SELECT subject, completed_hours, added_at
        FROM study_progress
        ORDER BY id DESC
        LIMIT 5
    """)

    recent_progress = [
        {
            "subject": row[0],
            "hours": row[1] or 0,
            "added_at": row[2]
        }
        for row in cursor.fetchall()
    ]

    # Nearest active deadline.
    upcoming = [
        goal for goal in goals
        if goal["status"] != "Completed"
        and goal["days_left"] is not None
        and goal["days_left"] >= 0
    ]

    nearest_deadline = (
        min(upcoming, key=lambda item: item["days_left"])
        if upcoming else None
    )

    conn.close()

    # IMPORTANT:
    # This is a dictionary because index.html uses data.xxx.
    # It also contains both overall_progress and overall_percentage
    # for compatibility with different dashboard templates.
    return {
        "total_subjects": total_subjects,
        "planned_hours": planned_hours,
        "completed_hours": completed_hours,
        "overall_progress": overall_progress,
        "overall_percentage": overall_progress,
        "active_goals": active_goals,
        "completed_goals": completed_goals,
        "subjects": subjects,
        "goals": goals,
        "recommendation": recommendation,
        "recommendation_subject": recommendation_subject,
        "recommendation_priority": recommendation_priority,
        "current_streak": streak["current"],
        "longest_streak": streak["longest"],
        "total_study_days": streak["total_days"],
        "today_hours": today_hours,
        "recent_progress": recent_progress,
        "nearest_deadline": nearest_deadline
    }


# ============================================================
# DASHBOARD - STEP 82
# ============================================================

@app.route("/")
def index():
    data = get_dashboard_data()

    return render_template(
        "index.html",
        data=data,
        # Compatibility with older index templates.
        total_subjects=data["total_subjects"],
        planned_hours=data["planned_hours"],
        completed_hours=data["completed_hours"],
        overall_progress=data["overall_progress"],
        active_goals=data["active_goals"],
        completed_goals=data["completed_goals"],
        recommendation=data["recommendation"],
        streak=data["current_streak"]
    )


# ============================================================
# ADD STUDY PLAN
# ============================================================

@app.route("/add-plan", methods=["POST"])
def add_plan():
    try:
        name = request.form.get("name", "My Study Plan").strip()
        subject = request.form["subject"].strip()
        priority = int(request.form["priority"])
        days = int(request.form["days"])
        daily_hours = float(request.form["daily_hours"])

        if not subject or priority < 1 or priority > 5:
            return redirect(url_for("index"))

        if days < 1 or daily_hours <= 0:
            return redirect(url_for("index"))

    except (KeyError, ValueError):
        return redirect(url_for("index"))

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO study_plans
        (name, subject, priority, days, daily_hours)
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

    return redirect(url_for("plans"))


# ============================================================
# STUDY PLANS
# ============================================================

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


# ============================================================
# DELETE STUDY PLAN
# ============================================================

@app.route("/delete-plan/<int:plan_id>")
def delete_plan(plan_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT subject
        FROM study_plans
        WHERE id = ?
    """, (plan_id,))

    row = cursor.fetchone()

    if row:
        subject = row[0]

        # Delete the plan itself.
        cursor.execute("""
            DELETE FROM study_plans
            WHERE id = ?
        """, (plan_id,))

        # Remove progress only if that subject has no remaining plan.
        cursor.execute("""
            SELECT COUNT(*)
            FROM study_plans
            WHERE subject = ?
        """, (subject,))

        remaining_plans = cursor.fetchone()[0]

        if remaining_plans == 0:
            cursor.execute("""
                DELETE FROM study_progress
                WHERE subject = ?
            """, (subject,))

    conn.commit()
    conn.close()

    return redirect(url_for("plans"))


# ============================================================
# UPDATE STUDY PLAN
# ============================================================

@app.route("/update-plan/<int:plan_id>", methods=["GET", "POST"])
def update_plan(plan_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            priority = int(request.form["priority"])
            days = int(request.form["days"])
            daily_hours = float(request.form["daily_hours"])

            if not 1 <= priority <= 5:
                raise ValueError

            if days < 1 or daily_hours <= 0:
                raise ValueError

        except (KeyError, ValueError):
            conn.close()
            return redirect(url_for("plans"))

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

        return redirect(url_for("plans"))

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


# ============================================================
# PROGRESS PAGE
# ============================================================

@app.route("/progress")
def progress():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    subjects = get_subject_data(cursor)

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


# ============================================================
# ADD PROGRESS
# ============================================================

@app.route("/add-progress", methods=["POST"])
def add_progress():
    try:
        subject = request.form["subject"].strip()
        completed_hours = float(
            request.form["completed_hours"]
        )

        if not subject or completed_hours <= 0:
            return redirect(url_for("progress"))

    except (KeyError, ValueError):
        return redirect(url_for("progress"))

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT SUM(days * daily_hours)
        FROM study_plans
        WHERE subject = ?
    """, (subject,))

    planned = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT SUM(completed_hours)
        FROM study_progress
        WHERE subject = ?
    """, (subject,))

    completed = cursor.fetchone()[0] or 0

    remaining = max(planned - completed, 0)

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

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
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
        timestamp
    ))

    cursor.execute("""
        INSERT OR IGNORE INTO study_dates
        (study_date)
        VALUES (?)
    """, (today,))

    conn.commit()
    conn.close()

    return redirect(url_for("progress"))


# ============================================================
# GOALS PAGE
# ============================================================

@app.route("/goals")
def goals():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    goals_data = get_goals_data(cursor)

    conn.close()

    return render_template(
        "goals.html",
        goals=goals_data
    )


# ============================================================
# ADD GOAL
# ============================================================

@app.route("/add-goal", methods=["POST"])
def add_goal():
    try:
        goal = request.form["goal"].strip()
        target_hours = float(
            request.form["target_hours"]
        )
        deadline = request.form.get("deadline", "").strip()

        if not goal or target_hours <= 0:
            return redirect(url_for("goals"))

    except (KeyError, ValueError):
        return redirect(url_for("goals"))

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

    return redirect(url_for("goals"))


# ============================================================
# ADD GOAL PROGRESS
# ============================================================

@app.route("/add-goal-progress", methods=["POST"])
def add_goal_progress():
    goal_id = request.form.get("goal_id")

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    if goal_id:
        try:
            goal_id = int(goal_id)
        except ValueError:
            conn.close()
            return redirect(url_for("goals"))
    else:
        goal_name = request.form.get("goal", "").strip()

        cursor.execute("""
            SELECT id
            FROM study_goals
            WHERE goal = ?
            ORDER BY id DESC
            LIMIT 1
        """, (goal_name,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            return redirect(url_for("goals"))

        goal_id = row[0]

    try:
        hours = float(
            request.form["completed_hours"]
        )

        if hours <= 0:
            raise ValueError

    except (KeyError, ValueError):
        conn.close()
        return redirect(url_for("goals"))

    cursor.execute("""
        SELECT
            target_hours,
            completed_hours,
            status
        FROM study_goals
        WHERE id = ?
    """, (goal_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return redirect(url_for("goals"))

    target = row[0] or 0
    completed = row[1] or 0
    status = row[2]

    remaining = max(target - completed, 0)

    if status == "Completed" or hours > remaining:
        conn.close()
        return redirect(url_for("goals"))

    new_completed = completed + hours

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

    return redirect(url_for("goals"))


# ============================================================
# ANALYTICS - STEP 74/75
# ============================================================

@app.route("/analytics")
def analytics():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    subjects = get_subject_data(cursor)

    planned_total = sum(
        item["planned"] for item in subjects
    )

    completed_total = sum(
        item["completed"] for item in subjects
    )

    remaining_total = max(
        planned_total - completed_total,
        0
    )

    overall_percentage = safe_percentage(
        completed_total,
        planned_total
    )

    on_track = sum(
        1 for item in subjects
        if item["status"] == "On Track"
    )

    needs_attention = sum(
        1 for item in subjects
        if item["status"] == "Needs Attention"
    )

    behind = sum(
        1 for item in subjects
        if item["status"] == "Behind"
    )

    not_started = sum(
        1 for item in subjects
        if item["status"] == "Not Started"
    )

    most_planned = (
        max(subjects, key=lambda x: x["planned"])
        if subjects else None
    )

    most_completed = (
        max(subjects, key=lambda x: x["completed"])
        if subjects else None
    )

    most_remaining = (
        max(subjects, key=lambda x: x["remaining"])
        if subjects else None
    )

    conn.close()

    return render_template(
        "analytics.html",
        subjects=subjects,
        planned_total=planned_total,
        completed_total=completed_total,
        remaining_total=remaining_total,
        overall_percentage=overall_percentage,
        overall_progress=overall_percentage,
        on_track=on_track,
        needs_attention=needs_attention,
        behind=behind,
        not_started=not_started,
        most_planned=most_planned,
        most_completed=most_completed,
        most_remaining=most_remaining
    )


# ============================================================
# WEEKLY PERFORMANCE - STEP 76
# ============================================================

@app.route("/weekly-performance")
def weekly_performance():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    today = date.today()
    start_date = today - timedelta(days=6)

    weekly_data = []

    for i in range(7):
        current_date = start_date + timedelta(days=i)
        date_string = current_date.isoformat()

        cursor.execute("""
            SELECT SUM(completed_hours)
            FROM study_progress
            WHERE DATE(added_at) = ?
        """, (date_string,))

        hours = cursor.fetchone()[0] or 0

        weekly_data.append({
            "date": current_date,
            "day": current_date.strftime("%a"),
            "hours": hours
        })

    conn.close()

    total_hours = sum(
        item["hours"] for item in weekly_data
    )

    daily_average = total_hours / 7
    study_days = sum(
        1 for item in weekly_data
        if item["hours"] > 0
    )

    most_productive = (
        max(weekly_data, key=lambda item: item["hours"])
        if study_days > 0 else None
    )

    max_hours = max(
        [item["hours"] for item in weekly_data] or [0]
    )

    for item in weekly_data:
        if max_hours > 0:
            item["bar_height"] = max(
                (item["hours"] / max_hours) * 100,
                4 if item["hours"] > 0 else 0
            )
        else:
            item["bar_height"] = 0

    return render_template(
        "weekly_performance.html",
        weekly_data=weekly_data,
        total_hours=total_hours,
        daily_average=daily_average,
        study_days=study_days,
        most_productive=most_productive
    )


# ============================================================
# STEP 77 - STUDY PERFORMANCE INSIGHTS
# ============================================================

@app.route("/insights")
def insights():
    today = date.today()
    start_date = today - timedelta(days=13)

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    daily_data = []

    for i in range(14):
        current_date = start_date + timedelta(days=i)

        cursor.execute("""
            SELECT SUM(completed_hours)
            FROM study_progress
            WHERE DATE(added_at) = ?
        """, (current_date.isoformat(),))

        hours = cursor.fetchone()[0] or 0

        daily_data.append({
            "date": current_date,
            "day": current_date.strftime("%a"),
            "hours": hours
        })

    # Subject totals.
    subjects = get_subject_data(cursor)

    # Goals.
    goals_data = get_goals_data(cursor)

    conn.close()

    first_week = sum(
        item["hours"] for item in daily_data[:7]
    )

    second_week = sum(
        item["hours"] for item in daily_data[7:]
    )

    if second_week > first_week:
        trend = "Increasing"
        trend_message = (
            "📈 Your study time is increasing compared with the previous week."
        )
    elif second_week < first_week:
        trend = "Decreasing"
        trend_message = (
            "📉 Your study time is lower than the previous week."
        )
    else:
        trend = "Stable"
        trend_message = (
            "➡️ Your study time is stable compared with the previous week."
        )

    productive_day = (
        max(daily_data, key=lambda item: item["hours"])
        if daily_data else None
    )

    total_hours = sum(
        item["hours"] for item in daily_data
    )

    average = total_hours / 14

    if productive_day and productive_day["hours"] > 0:
        day_message = (
            f"🔥 {productive_day['date'].strftime('%A')} was your "
            f"most productive day with {productive_day['hours']:.1f} hours."
        )
    else:
        day_message = "📚 No study sessions have been recorded in the last 14 days."

    if second_week > 0:
        suggestion = (
            "💡 Keep your recent momentum and try to study consistently "
            "rather than relying on one long session."
        )
    elif first_week > 0:
        suggestion = (
            "💡 Try to restart your study routine with a small daily session."
        )
    else:
        suggestion = (
            "💡 Add your first progress session to start generating insights."
        )

    return render_template(
        "insights.html",
        daily_data=daily_data,
        subjects=subjects,
        goals=goals_data,
        total_hours=total_hours,
        average=average,
        first_week=first_week,
        second_week=second_week,
        trend=trend,
        trend_message=trend_message,
        productive_day=productive_day,
        day_message=day_message,
        suggestion=suggestion
    )


# ============================================================
# STEP 78 - SUBJECT-WISE INSIGHTS
# ============================================================

@app.route("/subject-insights")
def subject_insights():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    subjects = get_subject_data(cursor)

    conn.close()

    total_completed = sum(
        item["completed"] for item in subjects
    )

    for subject in subjects:
        if total_completed > 0:
            subject["share"] = (
                subject["completed"] /
                total_completed
            ) * 100
        else:
            subject["share"] = 0

    most_studied = (
        max(subjects, key=lambda x: x["completed"])
        if subjects else None
    )

    most_remaining = (
        max(subjects, key=lambda x: x["remaining"])
        if subjects else None
    )

    attention_subjects = [
        item for item in subjects
        if item["status"] in
        ("Needs Attention", "Behind", "Not Started")
    ]

    return render_template(
        "subject_insights.html",
        subjects=subjects,
        most_studied=most_studied,
        most_remaining=most_remaining,
        attention_subjects=attention_subjects,
        total_completed=total_completed
    )


# ============================================================
# STEP 79 - GOAL PERFORMANCE INSIGHTS
# ============================================================

@app.route("/goal-insights")
def goal_insights():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    goals_data = get_goals_data(cursor)

    conn.close()

    total_goals = len(goals_data)

    completed_count = sum(
        1 for goal in goals_data
        if goal["status"] == "Completed"
    )

    active_count = total_goals - completed_count

    average_progress = (
        sum(goal["percentage"] for goal in goals_data) /
        total_goals
        if total_goals else 0
    )

    overdue = [
        goal for goal in goals_data
        if goal["deadline_status"] == "Overdue"
        and goal["status"] != "Completed"
    ]

    nearest = [
        goal for goal in goals_data
        if goal["status"] != "Completed"
        and goal["days_left"] is not None
        and goal["days_left"] >= 0
    ]

    nearest_goal = (
        min(nearest, key=lambda x: x["days_left"])
        if nearest else None
    )

    if completed_count > 0:
        summary = (
            f"🏆 You have completed {completed_count} of "
            f"{total_goals} goals."
        )
    elif total_goals > 0:
        summary = (
            "🎯 Keep working on your goals and update progress regularly."
        )
    else:
        summary = (
            "📚 Create your first goal to start tracking goal performance."
        )

    return render_template(
        "goal_insights.html",
        goals=goals_data,
        total_goals=total_goals,
        completed_count=completed_count,
        active_count=active_count,
        average_progress=average_progress,
        overdue=overdue,
        nearest_goal=nearest_goal,
        summary=summary
    )


# ============================================================
# STEP 80 - CALENDAR WITH MONTH NAVIGATION
# ============================================================

@app.route("/calendar")
def calendar():
    today = date.today()

    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))

        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1

    except ValueError:
        year = today.year
        month = today.month

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT study_date
        FROM study_dates
    """)

    study_dates = set()

    for row in cursor.fetchall():
        try:
            study_dates.add(
                date.fromisoformat(row[0])
            )
        except (ValueError, TypeError):
            pass

    conn.close()

    first_day = date(year, month, 1)
    days_in_month = pycalendar.monthrange(year, month)[1]
    start_weekday = first_day.weekday()

    calendar_days = []

    for _ in range(start_weekday):
        calendar_days.append(None)

    for day_number in range(1, days_in_month + 1):
        current = date(year, month, day_number)

        calendar_days.append({
            "day": day_number,
            "date": current.isoformat(),
            "studied": current in study_dates,
            "today": current == today
        })

    if month == 1:
        previous_year = year - 1
        previous_month = 12
    else:
        previous_year = year
        previous_month = month - 1

    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    return render_template(
        "calendar.html",
        calendar_days=calendar_days,
        month_name=first_day.strftime("%B"),
        year=year,
        month=month,
        previous_year=previous_year,
        previous_month=previous_month,
        next_year=next_year,
        next_month=next_month,
        studied_days=sum(
            1 for day in calendar_days
            if day and day["studied"]
        )
    )


# ============================================================
# STEP 81 - DEADLINE REMINDERS
# ============================================================

@app.route("/reminders")
def reminders():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    goals_data = get_goals_data(cursor)

    conn.close()

    reminders_data = []

    for goal in goals_data:
        if goal["status"] == "Completed":
            continue

        status = goal["deadline_status"]

        if status in (
            "Overdue",
            "Due Today",
            "Due Soon"
        ):
            reminders_data.append(goal)

    reminders_data.sort(
        key=lambda item: (
            item["days_left"]
            if item["days_left"] is not None
            else 999999
        )
    )

    if not reminders_data:
        message = (
            "✅ No urgent deadline reminders right now. "
            "Keep following your study schedule!"
        )
    else:
        message = (
            f"🔔 You have {len(reminders_data)} "
            f"deadline reminder(s) to check."
        )

    return render_template(
        "reminders.html",
        reminders=reminders_data,
        goals=goals_data,
        message=message
    )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    setup_database()

    app.run(
        debug=True
    )

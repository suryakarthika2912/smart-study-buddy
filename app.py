from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime, date, timedelta
import calendar as pycalendar

app = Flask(__name__)
DATABASE = "study_buddy.db"


# ============================================================
# DATABASE CONNECTION AND SETUP
# ============================================================

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    """Create missing tables and add missing columns without resetting data."""
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

    # Add the progress-history column only if it is missing.
    try:
        cursor.execute("""
            ALTER TABLE study_progress ADD COLUMN added_at TEXT
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
    cursor.execute("SELECT study_date FROM study_dates ORDER BY study_date")
    dates = set()

    for row in cursor.fetchall():
        try:
            dates.add(date.fromisoformat(row[0]))
        except (ValueError, TypeError):
            pass

    if not dates:
        return {"current": 0, "longest": 0, "total_days": 0}

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

    return {"current": current, "longest": longest, "total_days": len(dates)}


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
            "days_left": 0, "remaining_hours": 0, "daily_hours": 0,
            "recommendation": "🎉 Goal completed! Great work!"
        }

    if not deadline:
        return {
            "days_left": None, "remaining_hours": remaining, "daily_hours": 0,
            "recommendation": "📅 Add a deadline to get a daily study recommendation."
        }

    try:
        deadline_date = date.fromisoformat(deadline)
    except (ValueError, TypeError):
        return {
            "days_left": None, "remaining_hours": remaining, "daily_hours": 0,
            "recommendation": "📅 Add a valid deadline to get a daily recommendation."
        }

    days_left = (deadline_date - date.today()).days

    if remaining <= 0:
        return {
            "days_left": days_left, "remaining_hours": 0, "daily_hours": 0,
            "recommendation": "🎉 Goal requirements completed!"
        }

    if days_left < 0:
        return {
            "days_left": days_left, "remaining_hours": remaining, "daily_hours": 0,
            "recommendation": f"🔴 This goal is overdue with {remaining:.1f} hours remaining."
        }

    if days_left == 0:
        return {
            "days_left": 0, "remaining_hours": remaining, "daily_hours": remaining,
            "recommendation": f"⚠️ Deadline is today. Complete {remaining:.1f} more hours."
        }

    daily = remaining / days_left
    return {
        "days_left": days_left, "remaining_hours": remaining, "daily_hours": daily,
        "recommendation": f"💡 Study {daily:.1f} hours/day to complete this goal on time."
    }


# ============================================================
# GOAL DATA
# ============================================================

def get_goals_data(cursor=None):
    own_connection = cursor is None
    conn = None

    if own_connection:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()

    cursor.execute("""
        SELECT id, goal, target_hours, completed_hours, deadline, status
        FROM study_goals
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    result = []

    for row in rows:
        goal_id, goal_name, target, completed, deadline, status = row
        target = target or 0
        completed = completed or 0
        recommendation = get_goal_recommendation(target, completed, deadline, status)
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
            "deadline_status": get_deadline_status(deadline, status),
            "days_left": recommendation["days_left"],
            "daily_hours": recommendation["daily_hours"],
            "recommendation": recommendation["recommendation"],
            "percentage": percentage,
            "progress": percentage
        })

    if own_connection:
        conn.close()

    return result


def get_dashboard_recommendation(cursor):
    goals = get_goals_data(cursor)
    active = [goal for goal in goals if goal["status"] != "Completed"]

    if not active:
        return "📚 No active goals right now. Create a study goal to get smart recommendations!"

    overdue = [goal for goal in active if goal["deadline_status"] == "Overdue"]
    if overdue:
        goal = overdue[0]
        return f"🔴 Attention Needed: '{goal['goal']}' is overdue with {goal['remaining_hours']:.1f} hours remaining."

    today_goals = [goal for goal in active if goal["deadline_status"] == "Due Today"]
    if today_goals:
        goal = today_goals[0]
        return f"⚠️ Deadline Today: '{goal['goal']}' has {goal['remaining_hours']:.1f} hours remaining."

    upcoming = [
        goal for goal in active
        if goal["days_left"] is not None and goal["days_left"] > 0
    ]
    if upcoming:
        goal = min(upcoming, key=lambda item: item["days_left"])
        return f"💡 Smart Plan: Study {goal['daily_hours']:.1f} hours/day for '{goal['goal']}' to finish it in time."

    return "📚 Keep going! Continue following your study schedule."


# ============================================================
# SUBJECT DATA
# ============================================================

def get_subject_data(cursor):
    # Planned hours from study plans.
    cursor.execute("""
        SELECT subject, SUM(days * daily_hours)
        FROM study_plans
        GROUP BY subject
        ORDER BY subject
    """)
    planned_rows = cursor.fetchall()

    # Completed hours from all saved progress records.
    cursor.execute("""
        SELECT subject, SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)
    completed_rows = cursor.fetchall()

    planned_map = {
        subject: float(hours or 0) for subject, hours in planned_rows
    }
    completed_map = {
        subject: float(hours or 0) for subject, hours in completed_rows
    }

    # Include progress-only subjects so historical records remain visible.
    all_subjects = sorted(set(planned_map) | set(completed_map))
    subjects = []

    for subject in all_subjects:
        planned = planned_map.get(subject, 0.0)
        completed = completed_map.get(subject, 0.0)
        remaining = max(planned - completed, 0)
        progress = min(safe_percentage(completed, planned), 100)

        if planned <= 0:
            status, status_icon = "Not Started", "⚪"
        elif progress >= 70:
            status, status_icon = "On Track", "🟢"
        elif progress >= 30:
            status, status_icon = "Needs Attention", "🟡"
        elif progress > 0:
            status, status_icon = "Behind", "🔴"
        else:
            status, status_icon = "Not Started", "⚪"

        subjects.append({
            "name": subject,
            "subject": subject,
            "planned": planned,
            "completed": completed,
            "remaining": remaining,
            "progress": progress,
            "percentage": progress,
            "status": status,
            "status_icon": status_icon
        })

    return subjects


# ============================================================
# DASHBOARD DATA AND PAGE
# ============================================================

def get_dashboard_data():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    subjects = get_subject_data(cursor)
    total_subjects = len(subjects)
    planned_hours = sum(item["planned"] for item in subjects)
    completed_hours = sum(item["completed"] for item in subjects)
    overall_progress = safe_percentage(completed_hours, planned_hours)

    cursor.execute("SELECT COUNT(*) FROM study_goals WHERE status != 'Completed'")
    active_goals = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM study_goals WHERE status = 'Completed'")
    completed_goals = cursor.fetchone()[0]

    recommendation = get_dashboard_recommendation(cursor)
    streak = get_study_streak(cursor)
    goals = get_goals_data(cursor)

    cursor.execute("""
        SELECT subject, priority FROM study_plans
        ORDER BY priority DESC, id DESC LIMIT 1
    """)
    priority_row = cursor.fetchone()
    recommendation_subject = priority_row[0] if priority_row else ""
    recommendation_priority = (priority_row[1] or 0) if priority_row else 0

    today = date.today().isoformat()
    cursor.execute("""
        SELECT SUM(completed_hours) FROM study_progress
        WHERE DATE(added_at) = ?
    """, (today,))
    today_hours = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT subject, completed_hours, added_at
        FROM study_progress ORDER BY id DESC LIMIT 5
    """)
    recent_progress = [
        {"subject": row[0], "hours": row[1] or 0, "added_at": row[2]}
        for row in cursor.fetchall()
    ]

    upcoming = [
        goal for goal in goals
        if goal["status"] != "Completed"
        and goal["days_left"] is not None
        and goal["days_left"] >= 0
    ]
    nearest_deadline = min(upcoming, key=lambda item: item["days_left"]) if upcoming else None

    conn.close()
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
        streak=data["current_streak"]
    )


# ============================================================
# STUDY PLANS
# ============================================================

@app.route("/plans")
def plans():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            subject,
            priority,
            days,
            daily_hours,
            COALESCE(days, 0) * COALESCE(daily_hours, 0) AS total_hours
        FROM study_plans
        ORDER BY id DESC
    """)

    plans_data = cursor.fetchall()
    conn.close()

    return render_template("plans.html", plans=plans_data)


@app.route("/add-plan", methods=["GET", "POST"])
def add_plan():
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()

        try:
            days = int(request.form.get("days", 0))
            daily_hours = float(request.form.get("daily_hours", 0))
        except (ValueError, TypeError):
            return "Please enter valid days and daily study hours.", 400

        if not subject or days <= 0 or daily_hours <= 0:
            return "Please enter a subject, positive number of days, and positive daily hours.", 400

        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO study_plans (subject, days, daily_hours)
            VALUES (?, ?, ?)
            """,
            (subject, days, daily_hours)
        )
        conn.commit()
        conn.close()

        return redirect(url_for("plans"))

    return render_template("add_plan.html")



@app.route("/delete-plan/<int:plan_id>", methods=["POST"])
def delete_plan(plan_id):
    conn = sqlite3.connect(DATABASE)

    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM study_plans WHERE id = ?",
            (plan_id,)
        )

        plan = cursor.fetchone()

        if plan is None:
            return "Study plan not found.", 404

        cursor.execute(
            "DELETE FROM study_plans WHERE id = ?",
            (plan_id,)
        )

        conn.commit()

    finally:
        conn.close()

    return redirect(url_for("plans"))


@app.route("/update-plan/<int:plan_id>", methods=["GET", "POST"])
def update_plan(plan_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            priority = int(request.form["priority"])
            days = int(request.form["days"])
            daily_hours = float(request.form["daily_hours"])
            if not 1 <= priority <= 5 or days < 1 or daily_hours <= 0:
                raise ValueError
        except (KeyError, ValueError):
            conn.close()
            return redirect(url_for("plans"))

        cursor.execute("""
            UPDATE study_plans SET priority = ?, days = ?, daily_hours = ?
            WHERE id = ?
        """, (priority, days, daily_hours, plan_id))
        conn.commit()
        conn.close()
        return redirect(url_for("plans"))

    cursor.execute("SELECT * FROM study_plans WHERE id = ?", (plan_id,))
    plan = cursor.fetchone()
    conn.close()
    return render_template("update_plan.html", plan=plan)


# ============================================================
# PROGRESS
# ============================================================

@app.route("/progress")
def progress():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    subjects = get_subject_data(cursor)
    cursor.execute("""
        SELECT subject, completed_hours, added_at
        FROM study_progress ORDER BY id DESC
    """)
    history = cursor.fetchall()
    conn.close()
    return render_template("progress.html", subjects=subjects, history=history)


@app.route("/add-progress", methods=["POST"])
def add_progress():
    try:
        subject = request.form["subject"].strip()
        completed_hours = float(request.form["completed_hours"])
        if not subject or completed_hours <= 0:
            return redirect(url_for("progress"))
    except (KeyError, ValueError):
        return redirect(url_for("progress"))

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(days * daily_hours) FROM study_plans WHERE subject = ?
    """, (subject,))
    planned = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT SUM(completed_hours) FROM study_progress WHERE subject = ?
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

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = date.today().isoformat()
    cursor.execute("""
        INSERT INTO study_progress (subject, planned_hours, completed_hours, added_at)
        VALUES (?, ?, ?, ?)
    """, (subject, planned, completed_hours, timestamp))
    cursor.execute("INSERT OR IGNORE INTO study_dates (study_date) VALUES (?)", (today,))
    conn.commit()
    conn.close()
    return redirect(url_for("progress"))


# ============================================================
# GOALS
# ============================================================

@app.route("/goals")
def goals():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    goals_data = get_goals_data(cursor)
    conn.close()
    return render_template("goals.html", goals=goals_data)


@app.route("/add-goal", methods=["POST"])
def add_goal():
    try:
        goal = request.form["goal"].strip()
        target_hours = float(request.form["target_hours"])
        deadline = request.form.get("deadline", "").strip()
        if not goal or target_hours <= 0:
            return redirect(url_for("goals"))
    except (KeyError, ValueError):
        return redirect(url_for("goals"))

    conn = sqlite3.connect(DATABASE)
    conn.execute("""
        INSERT INTO study_goals (goal, target_hours, completed_hours, deadline, status)
        VALUES (?, ?, 0, ?, 'Pending')
    """, (goal, target_hours, deadline))
    conn.commit()
    conn.close()
    return redirect(url_for("goals"))


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
            SELECT id FROM study_goals WHERE goal = ? ORDER BY id DESC LIMIT 1
        """, (goal_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return redirect(url_for("goals"))
        goal_id = row[0]

    try:
        hours = float(request.form["completed_hours"])
        if hours <= 0:
            raise ValueError
    except (KeyError, ValueError):
        conn.close()
        return redirect(url_for("goals"))

    cursor.execute("""
        SELECT target_hours, completed_hours, status
        FROM study_goals WHERE id = ?
    """, (goal_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return redirect(url_for("goals"))

    target, completed, status = row
    target = target or 0
    completed = completed or 0
    remaining = max(target - completed, 0)

    if status == "Completed" or hours > remaining:
        conn.close()
        return redirect(url_for("goals"))

    new_completed = completed + hours
    new_status = "Completed" if new_completed >= target else (
        "In Progress" if new_completed > 0 else "Pending"
    )
    cursor.execute("""
        UPDATE study_goals SET completed_hours = ?, status = ? WHERE id = ?
    """, (new_completed, new_status, goal_id))
    conn.commit()
    conn.close()
    return redirect(url_for("goals"))


# ============================================================
# ANALYTICS
# ============================================================

@app.route("/analytics")
def analytics():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    subjects = get_subject_data(cursor)
    total_planned = sum(s["planned"] for s in subjects)
    total_completed = sum(s["completed"] for s in subjects)
    total_remaining = max(total_planned - total_completed, 0)
    overall_percentage = safe_percentage(total_completed, total_planned)
    hours_over_plan = max(total_completed - total_planned, 0)

    status_counts = {
        "On Track": sum(s["status"] == "On Track" for s in subjects),
        "Needs Attention": sum(s["status"] == "Needs Attention" for s in subjects),
        "Behind": sum(s["status"] == "Behind" for s in subjects),
        "Not Started": sum(s["status"] == "Not Started" for s in subjects)
    }

    for subject in subjects:
        subject["status_class"] = subject["status"].lower().replace(" ", "-")

    most_planned = max(subjects, key=lambda s: s["planned"], default=None)
    most_completed = max(subjects, key=lambda s: s["completed"], default=None)
    most_remaining = max(subjects, key=lambda s: s["remaining"], default=None)

    conn.close()

    return render_template(
        "analytics.html",
        subjects=subjects,
        total_planned=total_planned,
        total_completed=total_completed,
        total_remaining=total_remaining,
        overall_percentage=overall_percentage,
        hours_over_plan=hours_over_plan,
        on_track_count=status_counts["On Track"],
        needs_attention_count=status_counts["Needs Attention"],
        behind_count=status_counts["Behind"],
        not_started_count=status_counts["Not Started"],
        planned_total=total_planned,
        completed_total=total_completed,
        remaining_total=total_remaining,
        overall_progress=overall_percentage,
        on_track=status_counts["On Track"],
        needs_attention=status_counts["Needs Attention"],
        behind=status_counts["Behind"],
        not_started=status_counts["Not Started"],
        status_counts=status_counts,
        most_planned=most_planned,
        most_completed=most_completed,
        most_remaining=most_remaining
    )


# ============================================================
# STUDY INSIGHTS
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
            SELECT COALESCE(SUM(completed_hours), 0)
            FROM study_progress WHERE DATE(added_at) = ?
        """, (current_date.isoformat(),))
        hours = cursor.fetchone()[0] or 0
        daily_data.append({
            "date": current_date,
            "day": current_date.strftime("%a"),
            "hours": hours
        })

    subjects = get_subject_data(cursor)
    goals_data = get_goals_data(cursor)
    conn.close()

    first_week = sum(x["hours"] for x in daily_data[:7])
    second_week = sum(x["hours"] for x in daily_data[7:])
    total_hours = sum(x["hours"] for x in daily_data)
    average = total_hours / 14

    if second_week > first_week:
        trend = "Increasing"
        trend_message = "Your study time is increasing compared with the previous week."
    elif second_week < first_week:
        trend = "Decreasing"
        trend_message = "Your study time is lower than the previous week."
    else:
        trend = "Stable"
        trend_message = "Your study time is stable compared with the previous week."

    productive_day = max(daily_data, key=lambda x: x["hours"], default=None)
    study_days = sum(1 for x in daily_data[7:] if x["hours"] > 0)
    top_subject = max(subjects, key=lambda x: x["completed"], default=None)
    overdue_goals = [
        g for g in goals_data
        if g["status"] != "Completed" and g["deadline_status"] == "Overdue"
    ]

    if overdue_goals:
        suggestion = f"Prioritize the overdue goal: {overdue_goals[0]['goal']}."
    elif total_hours == 0:
        suggestion = "Record a study session to begin generating study insights."
    elif study_days < 3:
        suggestion = "Try spreading your study sessions across more days."
    else:
        suggestion = "Keep updating your progress and maintain your study routine."

    day_message = (
        f"{productive_day['date'].strftime('%A')} was your most productive day "
        f"with {productive_day['hours']:.1f} hours."
        if productive_day and productive_day["hours"] > 0
        else "No study sessions have been recorded in the last 14 days."
    )

    current_week = daily_data[7:]
    previous_week = daily_data[:7]
    current_total = second_week
    previous_total = first_week
    current_avg = second_week / 7
    previous_avg = first_week / 7
    most_productive = productive_day

    return render_template(
        "insights.html",
        daily_data=daily_data,
        current_week=current_week,
        previous_week=previous_week,
        subjects=subjects,
        goals=goals_data,
        total_hours=total_hours,
        average=average,
        first_week=first_week,
        second_week=second_week,
        current_total=current_total,
        previous_total=previous_total,
        current_avg=current_avg,
        previous_avg=previous_avg,
        trend=trend,
        trend_message=trend_message,
        productive_day=productive_day,
        most_productive=most_productive,
        study_days=study_days,
        top_subject=top_subject,
        suggestion=suggestion,
        day_message=day_message
    )


# ============================================================
# SUBJECT INSIGHTS
# ============================================================

@app.route("/subject-insights")
def subject_insights():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    subjects = get_subject_data(cursor)
    conn.close()

    total_completed = sum(s["completed"] for s in subjects)
    for subject in subjects:
        subject["share"] = (
            subject["completed"] / total_completed * 100
            if total_completed > 0 else 0
        )

    most_studied = max(subjects, key=lambda s: s["completed"], default=None)
    candidates = [s for s in subjects if s["remaining"] > 0]
    most_remaining = max(candidates, key=lambda s: s["remaining"], default=None)
    attention_subjects = [
        s for s in subjects
        if s["status"] in ("Needs Attention", "Behind", "Not Started")
    ]

    return render_template(
        "subject_insights.html",
        subjects=subjects,
        total_completed=total_completed,
        most_studied=most_studied,
        most_remaining=most_remaining,
        attention_subjects=attention_subjects,
        focus_subject=most_remaining
    )


# ============================================================
# GOAL INSIGHTS
# ============================================================

@app.route("/goal-insights")
def goal_insights():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    goals_data = get_goals_data(cursor)
    conn.close()

    total_goals = len(goals_data)
    total_target = sum(g["target_hours"] for g in goals_data)
    total_completed = sum(g["completed_hours"] for g in goals_data)
    completed_count = sum(1 for g in goals_data if g["status"] == "Completed")
    active_count = total_goals - completed_count
    overdue = [
        g for g in goals_data
        if g["status"] != "Completed" and g["deadline_status"] == "Overdue"
    ]
    nearest = [
        g for g in goals_data
        if g["status"] != "Completed"
        and g["days_left"] is not None
        and g["days_left"] >= 0
    ]
    nearest_goal = min(nearest, key=lambda g: g["days_left"], default=None)
    overall_percentage = safe_percentage(total_completed, total_target)
    average_progress = (
        sum(g["percentage"] for g in goals_data) / total_goals
        if total_goals else 0
    )

    if completed_count:
        summary = f"You have completed {completed_count} of {total_goals} goals."
    elif total_goals:
        summary = "Keep working on your goals and update progress regularly."
    else:
        summary = "Create your first goal to track goal performance."

    return render_template(
        "goal_insights.html",
        goals=goals_data,
        total_goals=total_goals,
        total_target=total_target,
        total_completed=total_completed,
        overall_percentage=overall_percentage,
        completed_count=completed_count,
        active_count=active_count,
        overdue_count=len(overdue),
        average_progress=average_progress,
        overdue=overdue,
        nearest_goal=nearest_goal,
        summary=summary
    )


# ============================================================
# STUDY CALENDAR
# ============================================================

@app.route("/calendar")
def calendar():
    today = date.today()

    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT study_date FROM study_dates")
    study_dates = set()

    for row in cursor.fetchall():
        try:
            study_dates.add(date.fromisoformat(row[0]))
        except (ValueError, TypeError):
            pass
    conn.close()

    first_day = date(year, month, 1)
    days_in_month = pycalendar.monthrange(year, month)[1]
    calendar_days = [None] * first_day.weekday()

    for number in range(1, days_in_month + 1):
        current = date(year, month, number)
        calendar_days.append({
            "day": number,
            "date": current.isoformat(),
            "studied": current in study_dates,
            "today": current == today
        })

    previous_year, previous_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    studied_days = sum(1 for item in calendar_days if item and item["studied"])

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
        studied_days=studied_days
    )


# ============================================================
# DEADLINE REMINDERS
# ============================================================

@app.route("/reminders")
def reminders():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    goals_data = get_goals_data(cursor)
    conn.close()

    reminders_data = [
        goal for goal in goals_data
        if goal["status"] != "Completed"
        and goal["deadline_status"] in ("Overdue", "Due Today", "Due Soon")
    ]
    reminders_data.sort(
        key=lambda g: g["days_left"] if g["days_left"] is not None else 999999
    )

    if reminders_data:
        message = f"You have {len(reminders_data)} deadline reminder(s) to check."
    else:
        message = "No urgent deadline reminders right now. Keep following your study schedule!"

    return render_template(
        "reminders.html",
        reminders=reminders_data,
        reminders_data=reminders_data,
        goals=goals_data,
        message=message
    )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":
    setup_database()
    app.run(debug=True)

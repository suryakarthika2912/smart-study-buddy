import os
import re
import sys
import sqlite3
from db import get_db_connection, setup_database_schema, get_database_uri, is_postgres_uri
from datetime import datetime, date, timedelta
import calendar as pycalendar
from functools import wraps
from urllib.parse import urlparse, urljoin
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)

# Security & Session Configuration
is_production = (
    os.environ.get("RENDER") is not None
    or os.environ.get("VERCEL") is not None
    or os.environ.get("VERCEL_ENV") == "production"
    or os.environ.get("FLASK_ENV") == "production"
)

secret_key = os.environ.get("SECRET_KEY", "").strip()
if not secret_key:
    if is_production:
        raise RuntimeError("CRITICAL CONFIGURATION ERROR: SECRET_KEY environment variable is required in production.")
    secret_key = "dev-insecure-secret-key-change-in-production"

app.secret_key = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

default_cookie_secure = "True" if is_production else "False"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", default_cookie_secure).lower() in ("true", "1", "t")

csrf = CSRFProtect(app)
DATABASE = get_database_uri()
if is_production and not is_postgres_uri(DATABASE):
    import logging
    logging.getLogger("app").warning(
        "Production environment detected (VERCEL/RENDER) but no PostgreSQL URI (DATABASE_URL/POSTGRES_URL) is set. "
        "SQLite cannot persist data on a read-only serverless filesystem."
    )


# ============================================================
# DATABASE CONNECTION AND SETUP
# ============================================================

def setup_database():
    """Initializes tables and columns safely on the configured database engine."""
    setup_database_schema()


# Protect database from unapproved automatic schema modification on serverless cold starts
if os.environ.get("AUTO_SETUP_DB") == "1" or os.environ.get("ALLOW_DEFAULT_DB_SETUP") == "1":
    setup_database()


def claim_legacy_records(username):
    """Explicitly assign unowned legacy records to the designated user account."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"User '{username}' does not exist.")
        user_id = row[0]

        cursor.execute("BEGIN IMMEDIATE")
        summary = {}
        for tbl in ("study_plans", "study_tasks", "study_goals", "study_progress"):
            cursor.execute(f"UPDATE {tbl} SET user_id = ? WHERE user_id IS NULL", (user_id,))
            summary[tbl] = cursor.rowcount

        cursor.execute("""
            UPDATE study_dates
            SET user_id = ?
            WHERE user_id IS NULL
              AND study_date NOT IN (SELECT study_date FROM study_dates WHERE user_id = ?)
        """, (user_id, user_id))
        dates_updated = cursor.rowcount
        cursor.execute("DELETE FROM study_dates WHERE user_id IS NULL")
        summary["study_dates"] = dates_updated

        conn.commit()
        return summary
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ============================================================
# AUTHENTICATION HELPERS & GUARDS
# ============================================================

def is_safe_url(target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_auth_context():
    return {
        "current_user": session.get("username"),
        "current_user_id": session.get("user_id"),
        "is_authenticated": "user_id" in session
    }


# ============================================================
# SMALL HELPERS (SCOPED)
# ============================================================

def parse_date(val):
    """
    Safely parses a date input into a datetime.date object.
    Accepts datetime.date, datetime.datetime, ISO date strings, or None.
    Returns datetime.date if valid, None otherwise.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            return None
        try:
            return date.fromisoformat(val_str)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(val_str).date()
        except ValueError:
            pass
        if len(val_str) >= 10 and val_str[4] == '-' and val_str[7] == '-':
            try:
                return date.fromisoformat(val_str[:10])
            except ValueError:
                pass
    return None


def safe_percentage(completed, planned):
    if planned and planned > 0:
        return min((completed / planned) * 100, 100)
    return 0


def get_study_streak(cursor, user_id):
    cursor.execute("SELECT study_date FROM study_dates WHERE user_id = ? ORDER BY study_date", (user_id,))
    dates = set()

    for row in cursor.fetchall():
        d = parse_date(row[0])
        if d:
            dates.add(d)

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

    deadline_date = parse_date(deadline)
    if not deadline_date:
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

    deadline_date = parse_date(deadline)
    if not deadline_date:
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
# GOAL DATA (SCOPED)
# ============================================================

def get_goals_data(cursor=None, user_id=None):
    own_connection = cursor is None
    conn = None

    if own_connection:
        conn = get_db_connection()
        cursor = conn.cursor()

    cursor.execute("""
        SELECT id, goal, target_hours, completed_hours, deadline, status
        FROM study_goals
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))
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


def get_dashboard_recommendation(cursor, user_id):
    goals = get_goals_data(cursor, user_id=user_id)
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
# SUBJECT DATA (SCOPED)
# ============================================================

def get_subject_data(cursor, user_id):
    cursor.execute("""
        SELECT subject, SUM(days * daily_hours)
        FROM study_plans
        WHERE user_id = ?
        GROUP BY subject
        ORDER BY subject
    """, (user_id,))
    planned_rows = cursor.fetchall()

    cursor.execute("""
        SELECT subject, SUM(completed_hours)
        FROM study_progress
        WHERE user_id = ?
        GROUP BY subject
    """, (user_id,))
    completed_rows = cursor.fetchall()

    planned_map = {
        subject: float(hours or 0) for subject, hours in planned_rows
    }
    completed_map = {
        subject: float(hours or 0) for subject, hours in completed_rows
    }

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
# DASHBOARD DATA (SCOPED)
# ============================================================

def get_dashboard_data(user_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        subjects = get_subject_data(cursor, user_id)
        total_subjects = len(subjects)
        planned_hours = sum(item["planned"] for item in subjects)
        completed_hours = sum(item["completed"] for item in subjects)
        overall_progress = safe_percentage(completed_hours, planned_hours)

        cursor.execute("SELECT COUNT(*) FROM study_goals WHERE status != 'Completed' AND user_id = ?", (user_id,))
        active_goals = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM study_goals WHERE status = 'Completed' AND user_id = ?", (user_id,))
        completed_goals = cursor.fetchone()[0]

        cursor.execute("""
            SELECT
                COUNT(CASE WHEN study_tasks.status = 'Completed' THEN 1 END),
                COUNT(*)
            FROM study_tasks
            JOIN study_plans ON study_tasks.plan_id = study_plans.id
            WHERE (study_tasks.user_id = ? OR (study_tasks.user_id IS NULL AND study_plans.user_id = ?))
        """, (user_id, user_id))
        task_row = cursor.fetchone()
        completed_tasks = (task_row[0] or 0) if task_row else 0
        total_tasks = (task_row[1] or 0) if task_row else 0

        recommendation = get_dashboard_recommendation(cursor, user_id)
        streak = get_study_streak(cursor, user_id)
        goals = get_goals_data(cursor, user_id)

        cursor.execute("""
            SELECT subject, priority FROM study_plans
            WHERE user_id = ?
            ORDER BY priority DESC, id DESC LIMIT 1
        """, (user_id,))
        priority_row = cursor.fetchone()
        recommendation_subject = priority_row[0] if priority_row else ""
        recommendation_priority = (priority_row[1] or 0) if priority_row else 0

        today = date.today().isoformat()
        cursor.execute("""
            SELECT SUM(completed_hours) FROM study_progress
            WHERE DATE(added_at) = ? AND user_id = ?
        """, (today, user_id))
        today_hours = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT subject, completed_hours, added_at
            FROM study_progress
            WHERE user_id = ?
            ORDER BY id DESC LIMIT 5
        """, (user_id,))
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

        return {
            "total_subjects": total_subjects,
            "planned_hours": planned_hours,
            "completed_hours": completed_hours,
            "overall_progress": overall_progress,
            "overall_percentage": overall_progress,
            "active_goals": active_goals,
            "completed_goals": completed_goals,
            "completed_tasks": completed_tasks,
            "total_tasks": total_tasks,
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
    finally:
        conn.close()


# ============================================================
# AUTHENTICATION ROUTES
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or len(username) < 3 or len(username) > 50:
            error = "Username must be between 3 and 50 characters."
        elif not re.match(r"^[a-zA-Z0-9_-]+$", username):
            error = "Username can only contain letters, numbers, hyphens, and underscores."
        elif not password or len(password) < 8 or len(password) > 128:
            error = "Password must be between 8 and 128 characters."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
                if cursor.fetchone():
                    error = "Username is already taken. Please choose another."
                else:
                    pw_hash = generate_password_hash(password)
                    cursor.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, pw_hash)
                    )
                    conn.commit()
                    flash("Account created successfully! Please sign in.", "success")
                    return redirect(url_for("login"))
            except Exception as ex:
                app.logger.error(f"Database error during registration: {ex}", exc_info=True)
                error = "Database service error. Please verify database initialization and try again."
            finally:
                if conn is not None:
                    conn.close()

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password_hash FROM users WHERE LOWER(username) = LOWER(?)", (username,))
            user = cursor.fetchone()

            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]

                next_url = request.args.get("next")
                if next_url and is_safe_url(next_url):
                    return redirect(next_url)
                return redirect(url_for("index"))
            else:
                error = "Invalid username or password."
        except Exception as ex:
            app.logger.error(f"Database error during login: {ex}", exc_info=True)
            error = "Database service error. Please verify database initialization and try again."
        finally:
            if conn is not None:
                conn.close()

    return render_template("login.html", error=error)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
@login_required
def index():
    user_id = session["user_id"]
    data = get_dashboard_data(user_id)
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
        streak=data["current_streak"],
        completed_tasks=data["completed_tasks"],
        total_tasks=data["total_tasks"]
    )


# ============================================================
# STUDY PLANS
# ============================================================

@app.route("/plans")
@login_required
def plans():
    user_id = session["user_id"]
    conn = get_db_connection()
    try:
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
            WHERE user_id = ?
            ORDER BY id DESC
        """, (user_id,))

        plans_data = cursor.fetchall()
    finally:
        conn.close()

    return render_template("plans.html", plans=plans_data)


@app.route("/study-tasks", methods=["GET", "POST"])
@login_required
def study_tasks():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    error = None

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        plan_id = request.form.get("plan_id", "").strip()
        due_date = request.form.get("due_date", "").strip() or None

        if not title:
            error = "Task title is required."
        elif len(title) > 150:
            error = "Task title must not exceed 150 characters."
        elif not plan_id:
            error = "Please select a study plan."
        else:
            try:
                plan_id_int = int(plan_id)
            except ValueError:
                plan_id_int = None

            if plan_id_int is not None:
                # Verify that the plan belongs to the logged-in user (prevents cross-user injection)
                cursor.execute(
                    "SELECT id FROM study_plans WHERE id = ? AND user_id = ?",
                    (plan_id_int, user_id)
                )
                plan = cursor.fetchone()

                if plan:
                    if due_date:
                        try:
                            date.fromisoformat(due_date)
                        except (ValueError, TypeError):
                            error = "Invalid due date format. Please use YYYY-MM-DD."

                    if not error:
                        cursor.execute("""
                            INSERT INTO study_tasks (plan_id, user_id, title, due_date, status)
                            VALUES (?, ?, ?, ?, 'Pending')
                        """, (plan_id_int, user_id, title, due_date))
                        conn.commit()
                        conn.close()
                        return redirect(url_for("study_tasks"))
                else:
                    error = "Selected study plan does not exist or is not owned by you."
            else:
                error = "Invalid study plan selection."

    cursor.execute("""
        SELECT id, subject
        FROM study_plans
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))
    user_plans = cursor.fetchall()

    cursor.execute("""
        SELECT
            study_tasks.id,
            study_tasks.plan_id,
            study_tasks.title,
            study_tasks.due_date,
            study_tasks.status,
            study_plans.subject
        FROM study_tasks
        JOIN study_plans
            ON study_tasks.plan_id = study_plans.id
        WHERE study_plans.user_id = ?
        ORDER BY study_tasks.id DESC
    """, (user_id,))
    tasks = cursor.fetchall()

    total_tasks = len(tasks)
    pending_tasks = sum(1 for t in tasks if t["status"] == "Pending")
    completed_tasks = sum(1 for t in tasks if t["status"] == "Completed")

    conn.close()

    return render_template(
        "study_tasks.html",
        tasks=tasks,
        plans=user_plans,
        total_tasks=total_tasks,
        pending_tasks=pending_tasks,
        completed_tasks=completed_tasks,
        error=error
    )


@app.route("/update-task-status/<int:task_id>", methods=["POST"])
@login_required
def update_task_status(task_id):
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify task ownership through parent study plan
    cursor.execute("""
        SELECT study_tasks.id, study_tasks.status
        FROM study_tasks
        JOIN study_plans ON study_tasks.plan_id = study_plans.id
        WHERE study_tasks.id = ? AND study_plans.user_id = ?
    """, (task_id, user_id))
    task = cursor.fetchone()

    if not task:
        conn.close()
        abort(404)

    new_status = "Completed" if task["status"] == "Pending" else "Pending"

    cursor.execute(
        "UPDATE study_tasks SET status = ? WHERE id = ? AND user_id = ?",
        (new_status, task_id, user_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("study_tasks"))


@app.route("/add-plan", methods=["GET", "POST"])
@login_required
def add_plan():
    user_id = session["user_id"]
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()

        try:
            days = int(request.form.get("days", 0))
            daily_hours = float(request.form.get("daily_hours", 0))
        except (ValueError, TypeError):
            return "Please enter valid days and daily study hours.", 400

        if not subject or days <= 0 or daily_hours <= 0:
            return "Please enter a subject, positive number of days, and positive daily hours.", 400

        if len(subject) > 100:
            return "Subject must not exceed 100 characters.", 400
        if days > 3650:
            return "Days must not exceed 3,650.", 400
        if daily_hours > 24.0:
            return "Daily hours cannot exceed 24.", 400

        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO study_plans (user_id, subject, days, daily_hours)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, subject, days, daily_hours)
        )
        conn.commit()
        conn.close()

        return redirect(url_for("plans"))

    return render_template("add_plan.html")


@app.route("/delete-plan/<int:plan_id>", methods=["POST"])
@login_required
def delete_plan(plan_id):
    user_id = session["user_id"]
    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Check ownership
        cursor.execute(
            "SELECT id FROM study_plans WHERE id = ? AND user_id = ?",
            (plan_id, user_id)
        )
        plan = cursor.fetchone()

        if plan is None:
            conn.close()
            abort(404)

        cursor.execute(
            "DELETE FROM study_tasks WHERE plan_id = ?",
            (plan_id,)
        )

        cursor.execute(
            "DELETE FROM study_plans WHERE id = ? AND user_id = ?",
            (plan_id, user_id)
        )

        conn.commit()

    finally:
        conn.close()

    return redirect(url_for("plans"))


@app.route("/update-plan/<int:plan_id>", methods=["GET", "POST"])
@login_required
def update_plan(plan_id):
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM study_plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
    plan = cursor.fetchone()

    if plan is None:
        conn.close()
        abort(404)

    error = None
    if request.method == "POST":
        priority_raw = request.form.get("priority", "").strip()
        days_raw = request.form.get("days", "").strip()
        daily_hours_raw = request.form.get("daily_hours", "").strip()

        try:
            priority = int(priority_raw)
            days = int(days_raw)
            daily_hours = float(daily_hours_raw)
            if not 1 <= priority <= 5:
                error = "Priority must be between 1 and 5."
            elif days < 1 or days > 3650:
                error = "Days must be between 1 and 3,650."
            elif daily_hours <= 0 or daily_hours > 24.0:
                error = "Daily hours must be a positive number up to 24."
        except (ValueError, TypeError):
            error = "Please enter valid numeric values for priority, days, and daily hours."

        if not error:
            cursor.execute("""
                UPDATE study_plans SET priority = ?, days = ?, daily_hours = ?
                WHERE id = ? AND user_id = ?
            """, (priority, days, daily_hours, plan_id, user_id))
            conn.commit()
            conn.close()
            return redirect(url_for("plans"))

    conn.close()
    return render_template("update_plan.html", plan=plan, error=error)


# ============================================================
# PROGRESS (SCOPED)
# ============================================================

@app.route("/progress")
@login_required
def progress():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    subjects = get_subject_data(cursor, user_id)
    cursor.execute("""
        SELECT subject, completed_hours, added_at
        FROM study_progress
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))
    history = cursor.fetchall()
    conn.close()
    return render_template("progress.html", subjects=subjects, history=history)


@app.route("/add-progress", methods=["POST"])
@login_required
def add_progress():
    user_id = session["user_id"]
    try:
        subject = request.form["subject"].strip()
        completed_hours = float(request.form["completed_hours"])
        if not subject or completed_hours <= 0 or completed_hours > 24.0:
            return redirect(url_for("progress"))
    except (KeyError, ValueError):
        return redirect(url_for("progress"))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(days * daily_hours) FROM study_plans WHERE subject = ? AND user_id = ?
    """, (subject, user_id))
    planned = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT SUM(completed_hours) FROM study_progress WHERE subject = ? AND user_id = ?
    """, (subject, user_id))
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
        INSERT INTO study_progress (user_id, subject, planned_hours, completed_hours, added_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, subject, planned, completed_hours, timestamp))
    cursor.execute("INSERT INTO study_dates (user_id, study_date) VALUES (?, ?) ON CONFLICT DO NOTHING", (user_id, today))
    conn.commit()
    conn.close()
    return redirect(url_for("progress"))


# ============================================================
# GOALS (SCOPED)
# ============================================================

@app.route("/goals")
@login_required
def goals():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    goals_data = get_goals_data(cursor, user_id=user_id)
    conn.close()
    error = request.args.get("error")
    return render_template("goals.html", goals=goals_data, error=error)


@app.route("/add-goal", methods=["POST"])
@login_required
def add_goal():
    user_id = session["user_id"]
    try:
        goal = request.form["goal"].strip()
        target_hours = float(request.form["target_hours"])
        deadline = request.form.get("deadline", "").strip() or None
        if not goal:
            return redirect(url_for("goals", error="Goal title is required."))
        if len(goal) > 150:
            return redirect(url_for("goals", error="Goal title must not exceed 150 characters."))
        if target_hours <= 0 or target_hours > 100000.0:
            return redirect(url_for("goals", error="Target hours must be a positive number up to 100,000."))
    except (KeyError, ValueError):
        return redirect(url_for("goals", error="Please enter valid goal details."))

    if deadline:
        try:
            date.fromisoformat(deadline)
        except (ValueError, TypeError):
            return redirect(url_for("goals", error="Invalid deadline date format. Please use YYYY-MM-DD."))

    conn = get_db_connection()
    conn.execute("""
        INSERT INTO study_goals (user_id, goal, target_hours, completed_hours, deadline, status)
        VALUES (?, ?, ?, 0, ?, 'Pending')
    """, (user_id, goal, target_hours, deadline))
    conn.commit()
    conn.close()
    return redirect(url_for("goals"))


@app.route("/add-goal-progress", methods=["POST"])
@login_required
def add_goal_progress():
    user_id = session["user_id"]
    goal_id_raw = request.form.get("goal_id", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()

    goal_id = None
    if goal_id_raw:
        try:
            goal_id = int(goal_id_raw)
        except ValueError:
            goal_id = None

    if not goal_id:
        goal_name = request.form.get("goal", "").strip()
        if goal_name:
            cursor.execute("""
                SELECT id FROM study_goals WHERE goal = ? AND user_id = ? ORDER BY id DESC LIMIT 1
            """, (goal_name, user_id))
            row = cursor.fetchone()
            if row:
                goal_id = row[0]

    if not goal_id:
        conn.close()
        return redirect(url_for("goals", error="Invalid study goal selected."))

    try:
        hours = float(request.form.get("completed_hours", 0))
        if hours <= 0 or hours > 24.0:
            raise ValueError
    except (ValueError, TypeError):
        conn.close()
        return redirect(url_for("goals", error="Please enter a valid positive number of hours up to 24."))

    cursor.execute("""
        SELECT id, goal, target_hours, completed_hours, status
        FROM study_goals WHERE id = ? AND user_id = ?
    """, (goal_id, user_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return redirect(url_for("goals", error="Goal not found."))

    goal_title = row["goal"]
    target = float(row["target_hours"] or 0)
    completed = float(row["completed_hours"] or 0)
    status = row["status"]
    remaining = max(target - completed, 0)

    if status == "Completed":
        conn.close()
        return redirect(url_for("goals", error=f"'{goal_title}' is already completed."))

    if hours > remaining:
        conn.close()
        return redirect(url_for("goals", error=f"Cannot add {hours:.1f} hours to '{goal_title}'. Only {remaining:.1f} hours remaining."))

    new_completed = completed + hours
    new_status = "Completed" if new_completed >= target else (
        "In Progress" if new_completed > 0 else "Pending"
    )
    cursor.execute("""
        UPDATE study_goals SET completed_hours = ?, status = ? WHERE id = ? AND user_id = ?
    """, (new_completed, new_status, goal_id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for("goals"))


# ============================================================
# ANALYTICS & INSIGHTS (SCOPED)
# ============================================================

@app.route("/analytics")
@login_required
def analytics():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    subjects = get_subject_data(cursor, user_id)
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

    cursor.execute("""
        SELECT
            COUNT(CASE WHEN study_tasks.status = 'Completed' THEN 1 END),
            COUNT(*)
        FROM study_tasks
        JOIN study_plans ON study_tasks.plan_id = study_plans.id
        WHERE (study_tasks.user_id = ? OR (study_tasks.user_id IS NULL AND study_plans.user_id = ?))
    """, (user_id, user_id))
    task_row = cursor.fetchone()
    completed_tasks = (task_row[0] or 0) if task_row else 0
    total_tasks = (task_row[1] or 0) if task_row else 0

    cursor.execute("SELECT COUNT(*) FROM study_goals WHERE status != 'Completed' AND user_id = ?", (user_id,))
    active_goals = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM study_goals WHERE status = 'Completed' AND user_id = ?", (user_id,))
    completed_goals = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM study_plans WHERE user_id = ?", (user_id,))
    total_plans = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "analytics.html",
        subjects=subjects,
        completed_tasks=completed_tasks,
        total_tasks=total_tasks,
        active_goals=active_goals,
        completed_goals=completed_goals,
        total_plans=total_plans,
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


@app.route("/insights")
@login_required
def insights():
    user_id = session["user_id"]
    today = date.today()
    start_date = today - timedelta(days=13)
    conn = get_db_connection()
    cursor = conn.cursor()
    daily_data = []

    for i in range(14):
        current_date = start_date + timedelta(days=i)
        cursor.execute("""
            SELECT COALESCE(SUM(completed_hours), 0)
            FROM study_progress WHERE DATE(added_at) = ? AND user_id = ?
        """, (current_date.isoformat(), user_id))
        hours = cursor.fetchone()[0] or 0
        daily_data.append({
            "date": current_date,
            "day": current_date.strftime("%a"),
            "hours": hours
        })

    subjects = get_subject_data(cursor, user_id)
    goals_data = get_goals_data(cursor, user_id=user_id)
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


@app.route("/subject-insights")
@login_required
def subject_insights():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    subjects = get_subject_data(cursor, user_id)
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


@app.route("/goal-insights")
@login_required
def goal_insights():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    goals_data = get_goals_data(cursor, user_id=user_id)
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
# STUDY CALENDAR (SCOPED)
# ============================================================

@app.route("/calendar")
@login_required
def calendar():
    user_id = session["user_id"]
    today = date.today()

    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    year_delta, normalized_month = divmod(month - 1, 12)
    year += year_delta
    month = normalized_month + 1

    if not (1 <= year <= 9999):
        year = today.year
        month = today.month

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT study_date FROM study_dates WHERE user_id = ?", (user_id,))
    study_dates = set()

    for row in cursor.fetchall():
        d = parse_date(row[0])
        if d:
            study_dates.add(d)
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
    if previous_year < 1:
        previous_year, previous_month = 1, 1
    if next_year > 9999:
        next_year, next_month = 9999, 12

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
# DEADLINE REMINDERS (SCOPED)
# ============================================================

@app.route("/reminders")
@login_required
def reminders():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    goals_data = get_goals_data(cursor, user_id=user_id)
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
# WEEKLY PERFORMANCE (SCOPED)
# ============================================================

@app.route("/weekly-performance")
@login_required
def weekly_performance():
    user_id = session["user_id"]
    conn = get_db_connection()
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
            WHERE DATE(added_at) = ? AND user_id = ?
        """, (date_string, user_id))

        row = cursor.fetchone()
        hours = float(row[0] or 0) if row else 0.0

        weekly_data.append({
            "date": current_date,
            "day": current_date.strftime("%a"),
            "hours": hours
        })

    conn.close()

    total_hours = sum(item["hours"] for item in weekly_data)
    daily_average = total_hours / 7.0
    study_days = sum(1 for item in weekly_data if item["hours"] > 0)

    most_productive = (
        max(weekly_data, key=lambda item: item["hours"])
        if study_days > 0 else None
    )

    return render_template(
        "weekly_performance.html",
        weekly_data=weekly_data,
        total_hours=total_hours,
        daily_average=daily_average,
        study_days=study_days,
        most_productive=most_productive
    )


# ============================================================
# RUN APPLICATION / CLI COMMANDS
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] in ("init-db", "migrate"):
        setup_database()
        print("Database schema initialization complete.")
        sys.exit(0)

    if len(sys.argv) >= 3 and sys.argv[1] == "claim-legacy":
        target_username = sys.argv[2]
        try:
            setup_database()
            res = claim_legacy_records(target_username)
            print(f"Successfully claimed legacy records for user '{target_username}': {res}")
            sys.exit(0)
        except Exception as ex:
            print(f"Error claiming legacy records: {ex}", file=sys.stderr)
            sys.exit(1)

    setup_database()
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host=host, port=port, debug=debug)

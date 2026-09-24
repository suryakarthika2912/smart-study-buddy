from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

DATABASE = "study_buddy.db"


# ==================================================
# DATABASE SETUP
# ==================================================

def setup_database():

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Check study_progress columns
    cursor.execute("PRAGMA table_info(study_progress)")

    columns = [row[1] for row in cursor.fetchall()]

    # Add date/time column if it does not exist
    if "added_at" not in columns:

        cursor.execute("""
            ALTER TABLE study_progress
            ADD COLUMN added_at TEXT
        """)

    conn.commit()
    conn.close()


# ==================================================
# DASHBOARD DATA
# ==================================================

def get_dashboard_data():

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # --------------------------------------------------
    # TOTAL SUBJECTS
    # --------------------------------------------------

    cursor.execute("""
        SELECT COUNT(DISTINCT subject)
        FROM study_plans
    """)

    total_subjects = cursor.fetchone()[0]


    # --------------------------------------------------
    # PLANNED HOURS
    # --------------------------------------------------

    cursor.execute("""
        SELECT SUM(days * daily_hours)
        FROM study_plans
    """)

    planned_hours = cursor.fetchone()[0] or 0


    # --------------------------------------------------
    # COMPLETED HOURS
    # --------------------------------------------------

    cursor.execute("""
        SELECT SUM(completed_hours)
        FROM study_progress
    """)

    completed_hours = cursor.fetchone()[0] or 0


    # --------------------------------------------------
    # OVERALL PROGRESS
    # --------------------------------------------------

    if planned_hours > 0:

        overall_progress = (
            completed_hours / planned_hours
        ) * 100

    else:

        overall_progress = 0


    if overall_progress > 100:

        overall_progress = 100


    # --------------------------------------------------
    # ACTIVE GOALS
    # --------------------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM study_goals
        WHERE status != 'Completed'
    """)

    active_goals = cursor.fetchone()[0]


    # --------------------------------------------------
    # COMPLETED GOALS
    # --------------------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM study_goals
        WHERE status = 'Completed'
    """)

    completed_goals = cursor.fetchone()[0]


    # --------------------------------------------------
    # SUBJECT PLAN DATA
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            subject,
            SUM(days * daily_hours)
        FROM study_plans
        GROUP BY subject
    """)

    plan_rows = cursor.fetchall()


    # --------------------------------------------------
    # SUBJECT PROGRESS DATA
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            subject,
            SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)

    progress_rows = cursor.fetchall()


    progress_data = {}

    for subject, completed in progress_rows:

        progress_data[subject] = completed


    subjects = []


    for subject, planned in plan_rows:

        completed = progress_data.get(
            subject,
            0
        )


        if planned > 0:

            progress = (
                completed / planned
            ) * 100

        else:

            progress = 0


        if progress > 100:

            progress = 100


        subjects.append({
            "name": subject,
            "planned": planned,
            "completed": completed,
            "progress": progress
        })


    # --------------------------------------------------
    # GOALS
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            goal,
            target_hours,
            completed_hours,
            deadline,
            status
        FROM study_goals
        ORDER BY id DESC
    """)

    goal_rows = cursor.fetchall()


    goals = []


    for goal, target, completed, deadline, status in goal_rows:

        if target > 0:

            progress = (
                completed / target
            ) * 100

        else:

            progress = 0


        if progress > 100:

            progress = 100


        goals.append({
            "goal": goal,
            "target": target,
            "completed": completed,
            "deadline": deadline,
            "status": status,
            "progress": progress
        })


    # --------------------------------------------------
    # RECOMMENDATION
    # --------------------------------------------------

    cursor.execute("""
        SELECT subject, priority
        FROM study_plans
        ORDER BY priority DESC
        LIMIT 1
    """)

    recommendation = cursor.fetchone()


    if recommendation:

        recommendation_subject = recommendation[0]
        recommendation_priority = recommendation[1]

    else:

        recommendation_subject = "No subject yet"
        recommendation_priority = 0


    conn.close()


    return {

        "total_subjects": total_subjects,

        "planned_hours": planned_hours,

        "completed_hours": completed_hours,

        "overall_progress": overall_progress,

        "active_goals": active_goals,

        "completed_goals": completed_goals,

        "subjects": subjects,

        "goals": goals,

        "recommendation_subject":
            recommendation_subject,

        "recommendation_priority":
            recommendation_priority

    }


# ==================================================
# HOME / DASHBOARD
# ==================================================

@app.route("/")
def home():

    data = get_dashboard_data()

    return render_template(
        "index.html",
        data=data
    )


# ==================================================
# ADD STUDY PLAN
# ==================================================

@app.route(
    "/add-plan",
    methods=["POST"]
)
def add_plan():

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
        (name, subject, priority, days, daily_hours)
        VALUES (?, ?, ?, ?, ?)
    """, (
        "Web Study Plan",
        subject,
        priority,
        days,
        daily_hours
    ))


    conn.commit()
    conn.close()


    return redirect(
        url_for("home")
    )


# ==================================================
# STUDY PLANS PAGE
# ==================================================

@app.route("/plans")
def study_plans():

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            id,
            subject,
            priority,
            days,
            daily_hours
        FROM study_plans
        ORDER BY id DESC
    """)


    plans = cursor.fetchall()

    conn.close()


    return render_template(
        "plans.html",
        plans=plans
    )


# ==================================================
# PROGRESS PAGE
# ==================================================

@app.route("/progress")
def progress():

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()


    # --------------------------------------------------
    # PLANNED HOURS
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            subject,
            SUM(days * daily_hours)
        FROM study_plans
        GROUP BY subject
    """)


    plan_rows = cursor.fetchall()


    # --------------------------------------------------
    # COMPLETED HOURS
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            subject,
            SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)


    progress_rows = cursor.fetchall()


    progress_data = {}


    for subject, completed in progress_rows:

        progress_data[subject] = completed


    subjects = []


    for subject, planned in plan_rows:

        completed = progress_data.get(
            subject,
            0
        )


        if planned > 0:

            percentage = (
                completed / planned
            ) * 100

        else:

            percentage = 0


        if percentage > 100:

            percentage = 100


        subjects.append((
            subject,
            planned,
            completed,
            percentage
        ))


    # --------------------------------------------------
    # PROGRESS HISTORY
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            subject,
            completed_hours,
            added_at
        FROM study_progress
        WHERE added_at IS NOT NULL
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


    new_hours = float(
        request.form["completed_hours"]
    )


    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()


    # --------------------------------------------------
    # GET PLANNED HOURS
    # --------------------------------------------------

    cursor.execute("""
        SELECT SUM(days * daily_hours)
        FROM study_plans
        WHERE subject = ?
    """, (subject,))


    planned_hours = cursor.fetchone()[0] or 0


    # --------------------------------------------------
    # GET COMPLETED HOURS
    # --------------------------------------------------

    cursor.execute("""
        SELECT SUM(completed_hours)
        FROM study_progress
        WHERE subject = ?
    """, (subject,))


    completed_hours = cursor.fetchone()[0] or 0


    remaining_hours = (
        planned_hours - completed_hours
    )


    # --------------------------------------------------
    # PREVENT EXCEEDING PLANNED HOURS
    # --------------------------------------------------

    if new_hours > remaining_hours:

        conn.close()


        return render_template(
            "progress_error.html",

            subject=subject,

            planned=planned_hours,

            completed=completed_hours,

            remaining=remaining_hours,

            attempted=new_hours
        )


    # --------------------------------------------------
    # SAVE PROGRESS
    # --------------------------------------------------

    cursor.execute("""
        INSERT INTO study_progress
        (
            subject,
            planned_hours,
            completed_hours,
            added_at
        )
        VALUES (?, ?, ?, datetime('now', 'localtime'))
    """, (
        subject,
        planned_hours,
        new_hours
    ))


    conn.commit()
    conn.close()


    return redirect(
        url_for("progress")
    )


# ==================================================
# DELETE STUDY PLAN
# ==================================================

@app.route(
    "/delete-plan/<int:plan_id>"
)
def delete_plan(plan_id):

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()


    cursor.execute("""
        DELETE FROM study_plans
        WHERE id = ?
    """, (plan_id,))


    conn.commit()
    conn.close()


    return redirect(
        url_for("study_plans")
    )


# ==================================================
# UPDATE STUDY PLAN
# ==================================================

@app.route(
    "/update-plan/<int:plan_id>",
    methods=["GET", "POST"]
)
def update_plan(plan_id):

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()


    # --------------------------------------------------
    # UPDATE
    # --------------------------------------------------

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
            url_for("study_plans")
        )


    # --------------------------------------------------
    # GET PLAN
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            subject,
            priority,
            days,
            daily_hours
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
# GOALS PAGE
# ==================================================

@app.route("/goals")
def goals():

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            goal,
            target_hours,
            completed_hours,
            deadline,
            status
        FROM study_goals
        ORDER BY id DESC
    """)


    goal_rows = cursor.fetchall()


    goals = []


    for goal, target, completed, deadline, status in goal_rows:

        if target > 0:

            progress = (
                completed / target
            ) * 100

        else:

            progress = 0


        if progress > 100:

            progress = 100


        goals.append({

            "goal": goal,

            "target": target,

            "completed": completed,

            "deadline": deadline,

            "status": status,

            "progress": progress

        })


    conn.close()


    return render_template(
        "goals.html",
        goals=goals
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
        VALUES (?, ?, ?, ?, ?)
    """, (
        goal,
        target_hours,
        0,
        deadline,
        "Pending"
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

    goal = request.form["goal"]

    new_hours = float(
        request.form["completed_hours"]
    )


    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()


    # --------------------------------------------------
    # GET CURRENT GOAL
    # --------------------------------------------------

    cursor.execute("""
        SELECT
            id,
            target_hours,
            completed_hours,
            status
        FROM study_goals
        WHERE goal = ?
        ORDER BY id DESC
        LIMIT 1
    """, (goal,))


    result = cursor.fetchone()


    if result is None:

        conn.close()

        return redirect(
            url_for("goals")
        )


    goal_id = result[0]

    target_hours = result[1]

    completed_hours = result[2]

    status = result[3]


    # --------------------------------------------------
    # CALCULATE REMAINING HOURS
    # --------------------------------------------------

    remaining_hours = (
        target_hours - completed_hours
    )


    # --------------------------------------------------
    # PREVENT EXCEEDING TARGET
    # --------------------------------------------------

    if new_hours > remaining_hours:

        conn.close()

        return redirect(
            url_for("goals")
        )


    # --------------------------------------------------
    # UPDATE COMPLETED HOURS
    # --------------------------------------------------

    new_completed_hours = (
        completed_hours + new_hours
    )


    # --------------------------------------------------
    # CHECK COMPLETION
    # --------------------------------------------------

    if new_completed_hours >= target_hours:

        new_completed_hours = target_hours

        new_status = "Completed"

    else:

        new_status = "Pending"


    # --------------------------------------------------
    # SAVE GOAL PROGRESS
    # --------------------------------------------------

    cursor.execute("""
        UPDATE study_goals
        SET
            completed_hours = ?,
            status = ?
        WHERE id = ?
    """, (
        new_completed_hours,
        new_status,
        goal_id
    ))


    conn.commit()
    conn.close()


    return redirect(
        url_for("goals")
    )


# ==================================================
# START APPLICATION
# ==================================================

if __name__ == "__main__":

    setup_database()

    app.run(debug=True)
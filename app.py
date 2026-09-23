from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

DATABASE = "study_buddy.db"


# --------------------------------------------------
# DASHBOARD DATA
# --------------------------------------------------

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
    # PLANNED STUDY HOURS
    # --------------------------------------------------

    cursor.execute("""
        SELECT SUM(days * daily_hours)
        FROM study_plans
    """)

    planned_hours = cursor.fetchone()[0] or 0


    # --------------------------------------------------
    # COMPLETED STUDY HOURS
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
    # SUBJECT PROGRESS
    # --------------------------------------------------

    # Get planned hours from study plans

    cursor.execute("""
        SELECT
            subject,
            SUM(days * daily_hours)
        FROM study_plans
        GROUP BY subject
    """)

    plan_rows = cursor.fetchall()


    # Get completed hours from study progress

    cursor.execute("""
        SELECT
            subject,
            SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)

    progress_rows = cursor.fetchall()


    # Store completed hours by subject

    progress_data = {}

    for subject, completed in progress_rows:

        progress_data[subject] = completed


    # Create subject list

    subjects = []


    for subject, planned in plan_rows:

        completed = progress_data.get(subject, 0)


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
    # STUDY GOALS
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
    # HIGHEST PRIORITY SUBJECT
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


    # --------------------------------------------------
    # CLOSE DATABASE
    # --------------------------------------------------

    conn.close()


    # --------------------------------------------------
    # RETURN DASHBOARD DATA
    # --------------------------------------------------

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


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/")
def home():

    data = get_dashboard_data()

    return render_template(
        "index.html",
        data=data
    )


# --------------------------------------------------
# ADD STUDY PLAN
# --------------------------------------------------

@app.route("/add-plan", methods=["POST"])
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


# --------------------------------------------------
# STUDY PLANS PAGE
# --------------------------------------------------

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


# --------------------------------------------------
# DELETE STUDY PLAN
# --------------------------------------------------

@app.route("/delete-plan/<int:plan_id>")
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


# --------------------------------------------------
# UPDATE STUDY PLAN
# --------------------------------------------------

@app.route(
    "/update-plan/<int:plan_id>",
    methods=["GET", "POST"]
)
def update_plan(plan_id):

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()


    # UPDATE DATA

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


    # GET EXISTING PLAN

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


# --------------------------------------------------
# PROGRAM START
# --------------------------------------------------

if __name__ == "__main__":

    app.run(debug=True)
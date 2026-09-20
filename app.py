from flask import Flask, render_template
import sqlite3

app = Flask(__name__)

DATABASE = "study_buddy.db"


def get_dashboard_data():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Total subjects
    cursor.execute("""
        SELECT COUNT(DISTINCT subject)
        FROM study_plans
    """)
    total_subjects = cursor.fetchone()[0]

    # Planned study hours
    cursor.execute("""
        SELECT SUM(days * daily_hours)
        FROM study_plans
    """)
    planned_hours = cursor.fetchone()[0] or 0

    # Completed study hours
    cursor.execute("""
        SELECT SUM(completed_hours)
        FROM study_progress
    """)
    completed_hours = cursor.fetchone()[0] or 0

    # Overall progress
    if planned_hours > 0:
        overall_progress = (completed_hours / planned_hours) * 100
    else:
        overall_progress = 0

    if overall_progress > 100:
        overall_progress = 100

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

    # Subject progress
    cursor.execute("""
        SELECT
            subject,
            SUM(planned_hours),
            SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)

    subject_rows = cursor.fetchall()

    subjects = []

    for subject, planned, completed in subject_rows:

        if planned > 0:
            progress = (completed / planned) * 100
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

    # Study goals
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
            progress = (completed / target) * 100
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

    # Highest priority subject
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
        "recommendation_subject": recommendation_subject,
        "recommendation_priority": recommendation_priority
    }


@app.route("/")
def home():

    data = get_dashboard_data()

    return render_template(
        "index.html",
        data=data
    )


if __name__ == "__main__":
    app.run(debug=True)
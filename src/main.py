import sqlite3


# ============================================================
# DATABASE
# ============================================================

def create_database():
    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    # Study Plans Table
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

    # Study Progress Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            planned_hours REAL,
            completed_hours REAL
        )
    """)

    # Study Goals Table
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

    conn.commit()
    conn.close()


# ============================================================
# SAVE STUDY PLAN TO DATABASE
# ============================================================

def save_to_database(name, subjects, priorities, days, hours):
    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    for subject, priority in zip(subjects, priorities):
        cursor.execute("""
            INSERT INTO study_plans
            (name, subject, priority, days, daily_hours)
            VALUES (?, ?, ?, ?, ?)
        """, (name, subject, priority, days, hours))

    conn.commit()
    conn.close()

    print("\n✅ Study plan saved to database successfully!")


# ============================================================
# GET SUBJECTS
# ============================================================

def get_subjects():
    while True:
        try:
            count = int(input("\nEnter number of subjects: "))

            if count <= 0:
                print("❌ Enter a positive number.")
                continue

            subjects = []

            for i in range(count):
                while True:
                    subject = input(f"Enter subject {i + 1}: ").strip()

                    if subject == "":
                        print("❌ Subject cannot be empty.")
                    elif subject in subjects:
                        print("❌ Subject already entered.")
                    else:
                        subjects.append(subject)
                        break

            return subjects

        except ValueError:
            print("❌ Please enter a valid number.")


# ============================================================
# GET PRIORITIES
# ============================================================

def get_priorities(subjects):
    priorities = []

    print("\nPriority Scale:")
    print("1 - Very Low")
    print("2 - Low")
    print("3 - Medium")
    print("4 - High")
    print("5 - Very High")

    for subject in subjects:
        while True:
            try:
                priority = int(
                    input(f"Enter priority for {subject} (1-5): ")
                )

                if 1 <= priority <= 5:
                    priorities.append(priority)
                    break
                else:
                    print("❌ Priority must be between 1 and 5.")

            except ValueError:
                print("❌ Please enter a valid number.")

    return priorities


# ============================================================
# CREATE STUDY PLAN
# ============================================================

def create_study_plan(subjects, priorities, days, daily_hours):
    total_priority = sum(priorities)

    plan = []

    for subject, priority in zip(subjects, priorities):

        subject_hours = (
            daily_hours * priority / total_priority
        )

        plan.append((subject, priority, subject_hours))

    return plan


# ============================================================
# CREATE SESSIONS
# ============================================================

def create_sessions(plan):
    sessions = []

    for subject, priority, hours in plan:

        first_session = hours / 2
        second_session = hours / 2

        sessions.append(
            (
                subject,
                priority,
                first_session,
                second_session
            )
        )

    return sessions


# ============================================================
# SAVE STUDY PLAN TO TEXT FILE
# ============================================================

def save_study_plan(name, plan, sessions, days, daily_hours):

    with open("study_plan.txt", "w") as file:

        file.write("SMART STUDY BUDDY\n")
        file.write("=================\n\n")

        file.write(f"Student: {name}\n")
        file.write(f"Study Days: {days}\n")
        file.write(f"Daily Study Hours: {daily_hours}\n\n")

        file.write("STUDY PLAN\n")
        file.write("----------\n")

        for subject, priority, hours in plan:

            file.write(
                f"{subject} | "
                f"Priority: {priority} | "
                f"Hours: {hours:.2f}\n"
            )

        file.write("\nSTUDY SESSIONS\n")
        file.write("--------------\n")

        for subject, priority, session1, session2 in sessions:

            file.write(
                f"{subject} | "
                f"Session 1: {session1:.2f} hrs | "
                f"Session 2: {session2:.2f} hrs\n"
            )

    print("\n✅ Study plan saved to study_plan.txt")


# ============================================================
# VIEW PREVIOUS TEXT PLAN
# ============================================================

def view_previous_plan():

    try:

        with open("study_plan.txt", "r") as file:
            content = file.read()

        print("\n" + "=" * 55)
        print(content)
        print("=" * 55)

    except FileNotFoundError:
        print("\n❌ No previous study plan found.")


# ============================================================
# VIEW DATABASE PLANS
# ============================================================

def view_database_plans():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, subject, priority, days, daily_hours
        FROM study_plans
        ORDER BY id
    """)

    plans = cursor.fetchall()

    print("\n" + "=" * 65)
    print("DATABASE STUDY PLANS")
    print("=" * 65)

    if not plans:
        print("No study plans found.")
    else:

        for plan in plans:

            plan_id, name, subject, priority, days, hours = plan

            print(
                f"\nID: {plan_id}"
                f"\nStudent: {name}"
                f"\nSubject: {subject}"
                f"\nPriority: {priority}"
                f"\nDays: {days}"
                f"\nDaily Hours: {hours}"
            )

    conn.close()


# ============================================================
# UPDATE STUDY PLAN
# ============================================================

def update_study_plan():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    try:

        plan_id = int(
            input("\nEnter Study Plan ID to update: ")
        )

        cursor.execute(
            "SELECT * FROM study_plans WHERE id = ?",
            (plan_id,)
        )

        plan = cursor.fetchone()

        if not plan:
            print("❌ Study plan not found.")
            conn.close()
            return

        print("\nCurrent Plan:")
        print(f"Subject: {plan[2]}")
        print(f"Current Priority: {plan[3]}")

        new_priority = int(
            input("Enter new priority (1-5): ")
        )

        if not 1 <= new_priority <= 5:
            print("❌ Priority must be between 1 and 5.")
            conn.close()
            return

        cursor.execute("""
            UPDATE study_plans
            SET priority = ?
            WHERE id = ?
        """, (new_priority, plan_id))

        conn.commit()

        print("\n✅ Study plan updated successfully!")

    except ValueError:
        print("❌ Please enter valid numbers.")

    conn.close()


# ============================================================
# RECORD STUDY PROGRESS
# ============================================================

def record_progress():

    subject = input("\nEnter subject: ").strip()

    if subject == "":
        print("❌ Subject cannot be empty.")
        return

    try:

        planned_hours = float(
            input("Enter planned hours: ")
        )

        completed_hours = float(
            input("Enter completed hours: ")
        )

        if planned_hours < 0 or completed_hours < 0:
            print("❌ Hours cannot be negative.")
            return

        conn = sqlite3.connect("study_buddy.db")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO study_progress
            (subject, planned_hours, completed_hours)
            VALUES (?, ?, ?)
        """, (
            subject,
            planned_hours,
            completed_hours
        ))

        conn.commit()
        conn.close()

        print("\n✅ Study progress recorded!")

    except ValueError:
        print("❌ Please enter valid numbers.")


# ============================================================
# VIEW STUDY PROGRESS
# ============================================================

def view_progress():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, subject, planned_hours, completed_hours
        FROM study_progress
        ORDER BY id
    """)

    progress = cursor.fetchall()

    print("\n" + "=" * 60)
    print("STUDY PROGRESS")
    print("=" * 60)

    if not progress:
        print("No progress recorded yet.")

    else:

        for item in progress:

            progress_id, subject, planned, completed = item

            if planned > 0:
                percentage = (
                    completed / planned
                ) * 100
            else:
                percentage = 0

            print(
                f"\nID: {progress_id}"
                f"\nSubject: {subject}"
                f"\nPlanned Hours: {planned:.2f}"
                f"\nCompleted Hours: {completed:.2f}"
                f"\nProgress: {percentage:.2f}%"
            )

    conn.close()


# ============================================================
# PROGRESS SUMMARY
# ============================================================

def view_progress_summary():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            SUM(planned_hours),
            SUM(completed_hours)
        FROM study_progress
    """)

    result = cursor.fetchone()

    planned = result[0] or 0
    completed = result[1] or 0

    if planned > 0:
        percentage = (
            completed / planned
        ) * 100
    else:
        percentage = 0

    if percentage > 100:
        percentage = 100

    print("\n" + "=" * 50)
    print("PROGRESS SUMMARY")
    print("=" * 50)

    print(f"Total Planned Hours   : {planned:.2f}")
    print(f"Total Completed Hours : {completed:.2f}")
    print(f"Overall Progress      : {percentage:.2f}%")

    if percentage < 50:
        print("Status                : Needs More Practice")
    elif percentage < 75:
        print("Status                : Improving")
    elif percentage < 90:
        print("Status                : Good Progress")
    else:
        print("Status                : Excellent Progress")

    conn.close()


# ============================================================
# SMART RECOMMENDATIONS
# ============================================================

def smart_recommendations():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            subject,
            SUM(planned_hours),
            SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)

    subjects = cursor.fetchall()

    print("\n" + "=" * 55)
    print("SMART STUDY RECOMMENDATIONS")
    print("=" * 55)

    if not subjects:
        print("No study progress available.")
        conn.close()
        return

    for subject, planned, completed in subjects:

        if planned > 0:
            percentage = (
                completed / planned
            ) * 100
        else:
            percentage = 0

        print(f"\n📚 {subject}")

        if percentage < 50:
            print("➡️ Recommendation: Increase study time.")

        elif percentage < 75:
            print("➡️ Recommendation: Improve consistency.")

        elif percentage < 90:
            print("➡️ Recommendation: Good progress. Keep going.")

        else:
            print("➡️ Recommendation: Excellent! Maintain this level.")

    conn.close()


# ============================================================
# PERSONALIZED STUDY SUGGESTIONS
# ============================================================

def personalized_suggestions():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT subject, priority
        FROM study_plans
    """)

    plans = cursor.fetchall()

    cursor.execute("""
        SELECT subject, completed_hours, planned_hours
        FROM study_progress
    """)

    progress_data = cursor.fetchall()

    progress_dict = {}

    for subject, completed, planned in progress_data:

        if planned > 0:
            percentage = (
                completed / planned
            ) * 100
        else:
            percentage = 0

        progress_dict[subject] = percentage

    print("\n" + "=" * 60)
    print("PERSONALIZED STUDY SUGGESTIONS")
    print("=" * 60)

    if not plans:
        print("Create a study plan first.")
        conn.close()
        return

    for subject, priority in plans:

        progress = progress_dict.get(subject, 0)

        print(f"\n📚 {subject}")
        print(f"Priority : {priority}")
        print(f"Progress : {progress:.2f}%")

        if priority >= 4 and progress < 50:
            print(
                "💡 High priority + low progress."
                "\n   Increase study time."
            )

        elif priority >= 4 and progress < 75:
            print(
                "💡 High priority subject."
                "\n   Continue improving."
            )

        elif priority >= 4 and progress >= 75:
            print(
                "💡 High priority subject."
                "\n   Maintain your progress."
            )

        elif priority <= 2 and progress < 50:
            print(
                "💡 Lower priority subject."
                "\n   Focus on higher priority subjects first."
            )

        elif progress < 50:
            print(
                "💡 Progress is low."
                "\n   Increase practice."
            )

        elif progress >= 75:
            print(
                "💡 Good progress."
                "\n   Continue consistently."
            )

        else:
            print(
                "💡 Keep practicing consistently."
            )

    conn.close()


# ============================================================
# CREATE STUDY GOAL
# ============================================================

def create_study_goal():

    print("\n" + "=" * 50)
    print("CREATE STUDY GOAL")
    print("=" * 50)

    goal = input("\nEnter your goal: ").strip()

    if goal == "":
        print("❌ Goal cannot be empty.")
        return

    try:

        target_hours = float(
            input("Enter target study hours: ")
        )

        if target_hours <= 0:
            print("❌ Target hours must be positive.")
            return

    except ValueError:
        print("❌ Please enter a valid number.")
        return

    deadline = input(
        "Enter deadline (DD-MM-YYYY): "
    ).strip()

    if deadline == "":
        print("❌ Deadline cannot be empty.")
        return

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO study_goals
        (goal, target_hours, completed_hours, deadline, status)
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

    print("\n✅ Study goal created successfully!")


# ============================================================
# VIEW STUDY GOALS
# ============================================================

def view_study_goals():

    conn = sqlite3.connect("study_buddy.db")
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
        ORDER BY id
    """)

    goals = cursor.fetchall()

    print("\n" + "=" * 65)
    print("STUDY GOALS")
    print("=" * 65)

    if not goals:
        print("No study goals created yet.")

    else:

        for goal in goals:

            goal_id, name, target, completed, deadline, status = goal

            print(f"\nID       : {goal_id}")
            print(f"Goal     : {name}")
            print(f"Target   : {target:.2f} hours")
            print(f"Completed: {completed:.2f} hours")
            print(f"Deadline : {deadline}")
            print(f"Status   : {status}")

            if target > 0:
                percentage = (
                    completed / target
                ) * 100
            else:
                percentage = 0

            if percentage > 100:
                percentage = 100

            print(f"Progress : {percentage:.2f}%")

    conn.close()


# ============================================================
# UPDATE GOAL PROGRESS
# ============================================================

def update_goal_progress():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    try:

        goal_id = int(
            input("\nEnter Goal ID: ")
        )

        cursor.execute("""
            SELECT
                goal,
                target_hours,
                completed_hours
            FROM study_goals
            WHERE id = ?
        """, (goal_id,))

        goal = cursor.fetchone()

        if not goal:
            print("❌ Goal not found.")
            conn.close()
            return

        goal_name, target, current = goal

        print(f"\nGoal: {goal_name}")
        print(f"Target Hours: {target}")
        print(f"Current Completed Hours: {current}")

        completed = float(
            input("Enter total completed hours: ")
        )

        if completed < 0:
            print("❌ Hours cannot be negative.")
            conn.close()
            return

        if completed >= target:
            status = "Completed"
        elif completed > 0:
            status = "In Progress"
        else:
            status = "Pending"

        cursor.execute("""
            UPDATE study_goals
            SET completed_hours = ?,
                status = ?
            WHERE id = ?
        """, (
            completed,
            status,
            goal_id
        ))

        conn.commit()

        print("\n✅ Goal progress updated!")
        print(f"Status: {status}")

    except ValueError:
        print("❌ Please enter valid numbers.")

    conn.close()


# ============================================================
# STUDENT DASHBOARD - STEP 52
# ============================================================

def student_dashboard():

    conn = sqlite3.connect("study_buddy.db")
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("              SMART STUDY BUDDY")
    print("                 DASHBOARD")
    print("=" * 60)

    # --------------------------------------------------------
    # SUBJECT SUMMARY
    # --------------------------------------------------------

    cursor.execute("""
        SELECT COUNT(DISTINCT subject)
        FROM study_plans
    """)

    total_subjects = cursor.fetchone()[0]

    # --------------------------------------------------------
    # PLANNED HOURS
    # --------------------------------------------------------

    cursor.execute("""
        SELECT SUM(days * daily_hours)
        FROM study_plans
    """)

    planned_hours = cursor.fetchone()[0] or 0

    # --------------------------------------------------------
    # COMPLETED HOURS
    # --------------------------------------------------------

    cursor.execute("""
        SELECT SUM(completed_hours)
        FROM study_progress
    """)

    completed_hours = cursor.fetchone()[0] or 0

    # --------------------------------------------------------
    # OVERALL PROGRESS
    # --------------------------------------------------------

    if planned_hours > 0:
        overall_progress = (
            completed_hours / planned_hours
        ) * 100
    else:
        overall_progress = 0

    if overall_progress > 100:
        overall_progress = 100

    # --------------------------------------------------------
    # GOAL SUMMARY
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MAIN DASHBOARD
    # --------------------------------------------------------

    print(f"\n📚 Total Subjects        : {total_subjects}")
    print(f"⏱ Planned Study Hours   : {planned_hours:.2f}")
    print(f"✅ Completed Study Hours : {completed_hours:.2f}")
    print(f"📊 Overall Progress      : {overall_progress:.2f}%")

    print(f"\n🎯 Active Goals          : {active_goals}")
    print(f"🏆 Completed Goals       : {completed_goals}")

    # --------------------------------------------------------
    # STUDY GOALS
    # --------------------------------------------------------

    print("\n" + "-" * 60)
    print("🎯 STUDY GOALS")
    print("-" * 60)

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

    goals = cursor.fetchall()

    if goals:

        for goal, target, completed, deadline, status in goals:

            if target > 0:
                progress = (
                    completed / target
                ) * 100
            else:
                progress = 0

            if progress > 100:
                progress = 100

            print(f"\nGoal      : {goal}")
            print(
                f"Progress  : "
                f"{completed:.2f}/{target:.2f} hours"
            )
            print(f"Progress %: {progress:.2f}%")
            print(f"Deadline  : {deadline}")
            print(f"Status    : {status}")

    else:
        print("No study goals created yet.")

    # --------------------------------------------------------
    # SUBJECT PROGRESS
    # --------------------------------------------------------

    print("\n" + "-" * 60)
    print("📚 SUBJECT PROGRESS")
    print("-" * 60)

    cursor.execute("""
        SELECT
            subject,
            SUM(planned_hours),
            SUM(completed_hours)
        FROM study_progress
        GROUP BY subject
    """)

    subjects = cursor.fetchall()

    if subjects:

        for subject, planned, completed in subjects:

            if planned > 0:
                progress = (
                    completed / planned
                ) * 100
            else:
                progress = 0

            if progress > 100:
                progress = 100

            print(
                f"{subject:<20}"
                f"{completed:.2f}/{planned:.2f} hrs "
                f"({progress:.1f}%)"
            )

    else:
        print("No study progress recorded yet.")

    # --------------------------------------------------------
    # RECOMMENDATION
    # --------------------------------------------------------

    print("\n" + "-" * 60)
    print("💡 RECOMMENDATION")
    print("-" * 60)

    cursor.execute("""
        SELECT subject, priority
        FROM study_plans
        ORDER BY priority DESC
        LIMIT 1
    """)

    recommendation = cursor.fetchone()

    if recommendation:

        subject, priority = recommendation

        print(
            f"Focus more on {subject} because "
            f"it has priority {priority}."
        )

    else:

        print(
            "Create a study plan to receive "
            "personalized recommendations."
        )

    print("\n" + "=" * 60)
    print("              END OF DASHBOARD")
    print("=" * 60)

    conn.close()


# ============================================================
# CREATE COMPLETE PLAN
# ============================================================

def create_plan():

    print("\n" + "=" * 55)
    print("CREATE STUDY PLAN")
    print("=" * 55)

    name = input("\nEnter your name: ").strip()

    if name == "":
        print("❌ Name cannot be empty.")
        return

    subjects = get_subjects()

    priorities = get_priorities(subjects)

    while True:

        try:

            days = int(
                input("\nEnter number of study days: ")
            )

            if days <= 0:
                print("❌ Days must be positive.")
                continue

            break

        except ValueError:
            print("❌ Please enter a valid number.")

    while True:

        try:

            daily_hours = float(
                input("Enter daily study hours: ")
            )

            if daily_hours <= 0:
                print("❌ Hours must be positive.")
                continue

            break

        except ValueError:
            print("❌ Please enter a valid number.")

    plan = create_study_plan(
        subjects,
        priorities,
        days,
        daily_hours
    )

    sessions = create_sessions(plan)

    print("\n" + "=" * 55)
    print("YOUR STUDY PLAN")
    print("=" * 55)

    for subject, priority, hours in plan:

        print(
            f"\n📚 {subject}"
            f"\nPriority: {priority}"
            f"\nStudy Hours: {hours:.2f}"
        )

    print("\n" + "-" * 55)
    print("STUDY SESSIONS")
    print("-" * 55)

    for subject, priority, session1, session2 in sessions:

        print(
            f"\n{subject}"
            f"\nSession 1: {session1:.2f} hours"
            f"\nSession 2: {session2:.2f} hours"
        )

    save_study_plan(
        name,
        plan,
        sessions,
        days,
        daily_hours
    )

    save_to_database(
        name,
        subjects,
        priorities,
        days,
        daily_hours
    )


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    create_database()

    while True:

        print("\n")
        print("=" * 60)
        print("             SMART STUDY BUDDY")
        print("=" * 60)

        print("\n1. Create Study Plan")
        print("2. View Previous Study Plan")
        print("3. View Database Plans")
        print("4. Update Study Plan")
        print("5. Record Study Progress")
        print("6. View Study Progress")
        print("7. View Progress Summary")
        print("8. Smart Recommendations")
        print("9. Personalized Study Suggestions")
        print("10. Create Study Goal")
        print("11. View Study Goals")
        print("12. Update Goal Progress")
        print("13. Exit")
        print("14. Student Dashboard")

        choice = input(
            "\nEnter your choice: "
        ).strip()

        if choice == "1":

            create_plan()

        elif choice == "2":

            view_previous_plan()

        elif choice == "3":

            view_database_plans()

        elif choice == "4":

            update_study_plan()

        elif choice == "5":

            record_progress()

        elif choice == "6":

            view_progress()

        elif choice == "7":

            view_progress_summary()

        elif choice == "8":

            smart_recommendations()

        elif choice == "9":

            personalized_suggestions()

        elif choice == "10":

            create_study_goal()

        elif choice == "11":

            view_study_goals()

        elif choice == "12":

            update_goal_progress()

        elif choice == "13":

            print("\n👋 Thank you for using Smart Study Buddy!")
            break

        elif choice == "14":

            student_dashboard()

        else:

            print(
                "\n❌ Invalid choice. "
                "Please enter a number from 1 to 14."
            )


# ============================================================
# PROGRAM START
# ============================================================

if __name__ == "__main__":
    main()
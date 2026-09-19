import sqlite3


# Create database
def create_database():

    connection = sqlite3.connect("study_buddy.db")

    cursor = connection.cursor()

    # Study plans table
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

    # Study progress table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            planned_hours REAL,
            completed_hours REAL
        )
    """)

    connection.commit()

    connection.close()


print("Welcome to study buddy!")

name = input("What is your name? ")

create_database()

print(
    "Hello, " + name +
    "! Let's get started with your study session."
)


# Save study plan to database
def save_to_database(
    name,
    subjects,
    priorities,
    days,
    hours
):

    connection = sqlite3.connect("study_buddy.db")

    cursor = connection.cursor()

    for i in range(len(subjects)):

        cursor.execute(
            """
            INSERT INTO study_plans
            (name, subject, priority, days, daily_hours)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                subjects[i],
                priorities[i],
                days,
                hours
            )
        )

    connection.commit()

    connection.close()

    print()
    print("Study plan saved to database!")


# Get subjects
def get_subjects():

    subjects = []

    while True:

        try:

            number_of_subjects = int(
                input("How many subjects do you have? ")
            )

            if number_of_subjects > 0:

                break

            else:

                print(
                    "Please enter at least one subject."
                )

        except ValueError:

            print(
                "Please enter a valid number."
            )

    for i in range(number_of_subjects):

        subject = input("Enter subject: ")

        subjects.append(subject)

    return subjects


# Get priorities
def get_priorities(subjects):

    priorities = []

    for subject in subjects:

        while True:

            try:

                priority = int(
                    input(
                        "Rate " +
                        subject +
                        " priority (1-5): "
                    )
                )

                if 1 <= priority <= 5:

                    priorities.append(priority)

                    break

                else:

                    print(
                        "Please enter a priority between 1 and 5."
                    )

            except ValueError:

                print(
                    "Please enter a valid number."
                )

    return priorities


# Create priority-based study plan
def create_study_plan(
    subjects,
    priorities,
    hours
):

    total_priority = sum(priorities)

    print()
    print("Priority-based study plan:")

    for i in range(len(subjects)):

        subject_hours = (
            priorities[i] /
            total_priority
        ) * hours

        print(
            subjects[i],
            "->",
            round(subject_hours, 2),
            "hours"
        )


# Create two study sessions
def create_sessions(
    subjects,
    priorities,
    hours
):

    sessions = 2

    total_priority = sum(priorities)

    print()
    print("Today's study sessions:")

    for i in range(len(subjects)):

        subject_hours = (
            priorities[i] /
            total_priority
        ) * hours

        session_hours = (
            subject_hours /
            sessions
        )

        print(
            subjects[i] + ":"
        )

        print(
            "  Session 1:",
            round(session_hours, 2),
            "hours"
        )

        print(
            "  Session 2:",
            round(session_hours, 2),
            "hours"
        )


# Save study plan to text file
def save_study_plan(
    name,
    subjects,
    priorities,
    days,
    hours
):

    total_priority = sum(priorities)

    with open(
        "study_plan.txt",
        "w"
    ) as file:

        file.write(
            "SMART STUDY BUDDY\n"
        )

        file.write(
            "=================\n"
        )

        file.write(
            "Name: " +
            name +
            "\n"
        )

        file.write(
            "Days remaining: " +
            str(days) +
            "\n"
        )

        file.write(
            "Daily study hours: " +
            str(hours) +
            "\n\n"
        )

        file.write(
            "STUDY PLAN\n"
        )

        file.write(
            "----------\n"
        )

        for i in range(len(subjects)):

            subject_hours = (
                priorities[i] /
                total_priority
            ) * hours

            session_hours = (
                subject_hours / 2
            )

            file.write(
                subjects[i] +
                "\n"
            )

            file.write(
                "Priority: " +
                str(priorities[i]) +
                "\n"
            )

            file.write(
                "Total time: " +
                str(round(subject_hours, 2)) +
                " hours\n"
            )

            file.write(
                "Session 1: " +
                str(round(session_hours, 2)) +
                " hours\n"
            )

            file.write(
                "Session 2: " +
                str(round(session_hours, 2)) +
                " hours\n\n"
            )


# View previous study plan
def view_previous_plan():

    try:

        with open(
            "study_plan.txt",
            "r"
        ) as file:

            plan = file.read()

        print()
        print(
            "===== PREVIOUS STUDY PLAN ====="
        )

        print(plan)

    except FileNotFoundError:

        print()
        print(
            "No study plan found."
        )

        print(
            "Please create a study plan first."
        )


# View study plans from database
def view_database_plans():

    connection = sqlite3.connect(
        "study_buddy.db"
    )

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            subject,
            priority,
            days,
            daily_hours
        FROM study_plans
    """)

    plans = cursor.fetchall()

    connection.close()

    print()
    print(
        "===== STUDY PLANS FROM DATABASE ====="
    )

    if len(plans) == 0:

        print(
            "No study plans found."
        )

    else:

        for plan in plans:

            print()

            print(
                "ID:",
                plan[0]
            )

            print(
                "Name:",
                plan[1]
            )

            print(
                "Subject:",
                plan[2]
            )

            print(
                "Priority:",
                plan[3]
            )

            print(
                "Days remaining:",
                plan[4]
            )

            print(
                "Daily study hours:",
                plan[5]
            )


# Update study plan
def update_study_plan():

    connection = sqlite3.connect(
        "study_buddy.db"
    )

    cursor = connection.cursor()

    # Show available subjects
    cursor.execute("""
        SELECT id, subject, priority
        FROM study_plans
    """)

    plans = cursor.fetchall()

    print()
    print(
        "===== UPDATE STUDY PLAN ====="
    )

    if len(plans) == 0:

        print(
            "No study plans found."
        )

        connection.close()

        return

    print(
        "Available subjects:"
    )

    for plan in plans:

        print(
            "ID:",
            plan[0],
            "| Subject:",
            plan[1],
            "| Priority:",
            plan[2]
        )

    # Get ID
    while True:

        try:

            plan_id = int(
                input(
                    "Enter the ID you want to update: "
                )
            )

            cursor.execute(
                """
                SELECT subject
                FROM study_plans
                WHERE id = ?
                """,
                (plan_id,)
            )

            result = cursor.fetchone()

            if result is not None:

                break

            else:

                print(
                    "ID not found. Please enter a valid ID."
                )

        except ValueError:

            print(
                "Please enter a valid number."
            )

    # Get new priority
    while True:

        try:

            new_priority = int(
                input(
                    "Enter the new priority (1-5): "
                )
            )

            if 1 <= new_priority <= 5:

                break

            else:

                print(
                    "Priority must be between 1 and 5."
                )

        except ValueError:

            print(
                "Please enter a valid number."
            )

    # UPDATE query
    cursor.execute(
        """
        UPDATE study_plans
        SET priority = ?
        WHERE id = ?
        """,
        (
            new_priority,
            plan_id
        )
    )

    connection.commit()

    print()
    print(
        "Study plan updated successfully!"
    )

    print(
        "Subject:",
        result[0]
    )

    print(
        "New priority:",
        new_priority
    )

    connection.close()


# Create complete study plan
def create_plan():

    # Get subjects
    subjects = get_subjects()

    print()
    print(
        "Your subjects are:"
    )

    print(subjects)

    print()
    print(
        "All subjects:"
    )

    for subject in subjects:

        print(subject)

    print(
        "Number of subjects:",
        len(subjects)
    )


    # Get priorities
    priorities = get_priorities(
        subjects
    )

    print()

    print(
        "Total priority:",
        sum(priorities)
    )

    print(
        "Subject priorities:"
    )

    print(priorities)


    # Get exam days
    while True:

        try:

            days = int(
                input(
                    "How many days do you have left for exam? "
                )
            )

            if days > 0:

                break

            else:

                print(
                    "Please enter a positive number of days."
                )

        except ValueError:

            print(
                "Please enter a valid number of days."
            )


    print(
        "You have",
        days,
        "days left to study"
    )


    # Get daily study hours
    while True:

        try:

            hours = float(
                input(
                    "How many hours can you dedicate "
                    "to studying each day? "
                )
            )

            if hours > 0:

                break

            else:

                print(
                    "Please enter a positive number of hours."
                )

        except ValueError:

            print(
                "Please enter a valid number of hours."
            )


    print(
        "You can dedicate",
        hours,
        "hours each day to studying."
    )


    # Create priority-based study plan
    create_study_plan(
        subjects,
        priorities,
        hours
    )


    # Total available study time
    total_hours = days * hours

    print()

    print(
        "In total, you have",
        total_hours,
        "hours to study for " +
        ", ".join(subjects) +
        "."
    )


    # Exam message
    if days <= 3:

        print(
            "Your exam is very close. "
            "Let's study seriously!"
        )

    else:

        print(
            "You still have some time. "
            "Let's make a study plan."
        )


    # Study session message
    if hours >= 3:

        print(
            "You can divide your study time into 2 sessions."
        )

    else:

        print(
            "Let's focus on one short study session."
        )


    # Create study sessions
    create_sessions(
        subjects,
        priorities,
        hours
    )


    # Save study plan to text file
    save_study_plan(
        name,
        subjects,
        priorities,
        days,
        hours
    )


    # Save study plan to database
    save_to_database(
        name,
        subjects,
        priorities,
        days,
        hours
    )

    print()
    print(
        "Study plan saved successfully!"
    )


# Main menu
while True:

    print()
    print(
        "===== SMART STUDY BUDDY ====="
    )

    print(
        "1. Create Study Plan"
    )

    print(
        "2. View Previous Study Plan"
    )

    print(
        "3. View Database Plans"
    )

    print(
        "4. Update Study Plan"
    )

    print(
        "5. Exit"
    )

    choice = input(
        "Enter your choice: "
    )


    if choice == "1":

        create_plan()


    elif choice == "2":

        view_previous_plan()


    elif choice == "3":

        view_database_plans()


    elif choice == "4":

        update_study_plan()


    elif choice == "5":

        print(
            "Thank you for using Smart Study Buddy!"
        )

        break


    else:

        print(
            "Please enter 1, 2, 3, 4, or 5."
        )
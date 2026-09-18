print("Welcome to study buddy!")

name = input("What is your name? ")

print("Hello, " + name + "! Let's get started with your study session.")


# Get subjects
def get_subjects():
    subjects = []

    number_of_subjects = int(input("How many subjects do you have? "))

    for i in range(number_of_subjects):
        subject = input("Enter subject: ")
        subjects.append(subject)

    return subjects


subjects = get_subjects()

print("Your subjects are:")
print(subjects)

print("All subjects:")
for subject in subjects:
    print(subject)

number_of_subjects = len(subjects)

print("Number of subjects:", number_of_subjects)


# Get priorities
def get_priorities(subjects):
    priorities = []

    for subject in subjects:
        priority = int(input("Rate " + subject + " priority (1-5): "))
        priorities.append(priority)

    return priorities


priorities = get_priorities(subjects)

total_priority = sum(priorities)

print("Total priority:", total_priority)

print("Subject priorities:")
print(priorities)


# Exam information
days = int(input("How many days do you have left for exam? "))

print("You have", days, "days left to study")

hours = float(
    input("How many hours can you dedicate to studying each day? ")
)

print("You can dedicate", hours, "hours each day to studying.")


# Create priority-based study plan
def create_study_plan(subjects, priorities, hours):
    total_priority = sum(priorities)

    for i in range(len(subjects)):
        subject_hours = (priorities[i] / total_priority) * hours
        print(subjects[i], "->", round(subject_hours, 2), "hours")


print("Priority-based study plan:")

create_study_plan(subjects, priorities, hours)


# Total available study time
total_hours = days * hours

print(
    "In total, you have",
    total_hours,
    "hours to study for " + ", ".join(subjects) + "."
)


# Exam message
if days <= 3:
    print("Your exam is very close. Let's study seriously!")
else:
    print("You still have some time. Let's make a study plan.")


# Study session message
if hours >= 3:
    print("You can divide your study time into 2 sessions.")
else:
    print("Let's focus on one short study session.")


# Create two study sessions
def create_sessions(subjects, priorities, hours):
    sessions = 2
    total_priority = sum(priorities)

    print("Today's study sessions:")

    for i in range(len(subjects)):
        subject_hours = (priorities[i] / total_priority) * hours
        session_hours = subject_hours / sessions

        print(subjects[i], ":")
        print("  Session 1:", round(session_hours, 2), "hours")
        print("  Session 2:", round(session_hours, 2), "hours")


create_sessions(subjects, priorities, hours)


# Save study plan
def save_study_plan(name, subjects, priorities, days, hours):
    total_priority = sum(priorities)

    with open("study_plan.txt", "w") as file:
        file.write("SMART STUDY BUDDY\n")
        file.write("=================\n")
        file.write("Name: " + name + "\n")
        file.write("Days remaining: " + str(days) + "\n")
        file.write("Daily study hours: " + str(hours) + "\n\n")

        file.write("STUDY PLAN\n")
        file.write("----------\n")

        for i in range(len(subjects)):
            subject_hours = (priorities[i] / total_priority) * hours
            session_hours = subject_hours / 2

            file.write(subjects[i] + "\n")
            file.write("Priority: " + str(priorities[i]) + "\n")
            file.write(
                "Total time: "
                + str(round(subject_hours, 2))
                + " hours\n"
            )
            file.write(
                "Session 1: "
                + str(round(session_hours, 2))
                + " hours\n"
            )
            file.write(
                "Session 2: "
                + str(round(session_hours, 2))
                + " hours\n\n"
            )


save_study_plan(name, subjects, priorities, days, hours)

print("Study plan saved successfully!")
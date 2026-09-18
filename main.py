print("Welcome to study buddy!")
name = input("What is your name? ") 
print("Hello, " + name + "! Let's get started with your study session.")
subjects = []

number_of_subjects = int(input("How many subjects do you have? "))

for i in range(number_of_subjects):
    subject = input("Enter subject: ")
    subjects.append(subject)

print("Your subjects are:")
print(subjects)


print("All subjects:")
for subject in subjects:
    print(subject)
number_of_subjects = len(subjects)

print("Number of subjects:", number_of_subjects)  
priorities = []

for subject in subjects:
    priority = int(input("Rate " + subject + " priority (1-5): "))
    priorities.append(priority)
    total_priority = sum(priorities)


print("Total priority:", total_priority)

print("Subject priorities:")
print(priorities)  
days = int(input("How many days do you have left for exam? "))
print("You have ", days, " days left to study ")
hours = float(input("How many hours can you dedicate to studying each day? "))
print("You can dedicate ", hours, " hours each day to studying.")


print("Priority-based study plan:")

for i in range(number_of_subjects):
    subject_hours = (priorities[i] / total_priority) * hours
    print(subjects[i], "->", round(subject_hours, 2), "hours")
total_hours = days * hours
print("In total, you have ", total_hours, " hours to study for " + ", ".join(subjects) + ".")
if days <= 3:
    print("Your exam is very close. Let's study seriously!")
else:
    print("You still have some time. Let's make a study plan.")
if hours >= 3:
    print("You can divide your study time into 2 sessions.")
else:
    print("Let's focus on one short study session.")   
sessions = 2

print("Today's study sessions:")

for i in range(number_of_subjects):
    subject_hours = (priorities[i] / total_priority) * hours
    session_hours = subject_hours / sessions

    print(subjects[i], ":")
    print("  Session 1:", round(session_hours, 2), "hours")
    print("  Session 2:", round(session_hours, 2), "hours")


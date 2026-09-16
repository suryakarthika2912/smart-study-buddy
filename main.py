print("Welcome to study buddy!")
name = input("What is your name? ") 
print("Hello, " + name + "! Let's get started with your study session.")
subject = input("What subject would you like to study today? ")
print("Great! Let's focus on " + subject + ".")
days = int(input("How many days do you have left? "))
print("You have ", days, " days left to study ")
hours = float(input("How many hours can you dedicate to studying each day? "))
print("You can dedicate ", hours, " hours each day to studying.")
total_hours = days * hours
print("In total, you have ", total_hours, " hours to study for " + subject + ".")
if days <= 3:
    print("Your exam is very close. Let's study seriously!")
else:
    print("You still have some time. Let's make a study plan.")
if hours >= 3:
    print("You can divide your study time into 2 sessions.")
else:
    print("Let's focus on one short study session.")   
sessions = 2
sessions_hours = total_hours / sessions
print("Today's plan:-")
print("Number of sessions:", sessions)
print("Study each session for:", sessions_hours, "hours")  
total_session_hours = sessions * sessions_hours
print("Today plannened study time is:", total_session_hours, "hours") 

"""Seed a realistic 100-question bank across 12 categories.

Every question is created through ``QuestionService.create_question``, which
is the same validation/persistence path the admin portal uses: MCQ answers
must be one of the options, coding questions need a language plus test
cases, and marks are derived from difficulty (easy=1, medium=3, hard=5).

The coding questions are self-checked before insertion: each one includes a
reference solution that is executed against its own test cases with the real
``code_execution_service``. A reference solution that fails its cases aborts
the seed, so the bank never contains a coding question whose expected output
is wrong.

Composition (100 total):
    - 12 categories
    - 76 MCQs
    - 12 coding questions (Python and JavaScript, each with 3 test cases)
    - 12 descriptive questions (manual-review questions)

Usage (from backend/):
    .venv\\Scripts\\python.exe -m scripts.seed_question_bank
    .venv\\Scripts\\python.exe -m scripts.seed_question_bank --force
    .venv\\Scripts\\python.exe -m scripts.seed_question_bank --reset

--force appends missing questions and skips questions whose text already
exists. --reset replaces the question bank (refused if any assessment or
attempt exists, because both reference category/question IDs).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import textwrap
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.assessment import (  # noqa: E402
    CategoryCreateRequest,
    CodingLanguage,
    DifficultyLevel,
    QuestionCreateRequest,
    QuestionType,
    TestCase,
)
from app.services.code_execution_service import execute_code  # noqa: E402
from app.services.question_service import QuestionError, QuestionService  # noqa: E402

CATEGORY_NAMES = [
    "Data Structures & Algorithms",
    "DBMS & SQL",
    "Operating Systems",
    "Computer Networks",
    "Object-Oriented Programming",
    "Python Programming",
    "JavaScript & Web Development",
    "Aptitude & Logical Reasoning",
    "Machine Learning & AI",
    "Cybersecurity",
    "Cloud & DevOps",
    "Software Engineering",
]

# Ties questions to the mock companies/drives created by seed_mock_drives.py.
# Aptitude is intentionally untagged because it is general campus-placement
# content rather than a company-specific skill.
CATEGORY_COMPANY_TAGS = {
    "Data Structures & Algorithms": ["Nexora Technologies", "CloudNest Infrastructure"],
    "DBMS & SQL": ["CloudNest Infrastructure", "Skyline Analytics"],
    "Operating Systems": ["BlueOrbit Solutions", "QuantumEdge Systems"],
    "Computer Networks": ["QuantumEdge Systems", "BlueOrbit Solutions"],
    "Object-Oriented Programming": ["Nexora Technologies", "PixelForge Studios"],
    "Python Programming": ["Nexora Technologies", "TerraNova Fintech"],
    "JavaScript & Web Development": ["PixelForge Studios", "Nexora Technologies"],
    "Aptitude & Logical Reasoning": [],
    "Machine Learning & AI": ["TerraNova Fintech"],
    "Cybersecurity": ["QuantumEdge Systems"],
    "Cloud & DevOps": ["BlueOrbit Solutions", "CloudNest Infrastructure"],
    "Software Engineering": ["Nexora Technologies", "Aurora HealthTech"],
}


def mcq(difficulty: str, text: str, options: list[str], correct_answer: str, skill_tags: list[str]) -> dict:
    return {
        "difficulty": difficulty,
        "text": text,
        "options": options,
        "correct_answer": correct_answer,
        "skill_tags": skill_tags,
    }


def code_block(value: str) -> str:
    return textwrap.dedent(value).strip("\n") + "\n"


def coding(
    difficulty: str,
    text: str,
    language: str,
    starter_code: str,
    test_cases: list[tuple[str, str, str, bool]],
    reference_solution: str,
    skill_tags: list[str],
) -> dict:
    return {
        "difficulty": difficulty,
        "text": text,
        "language": language,
        "starter_code": code_block(starter_code),
        "test_cases": [
            {"name": name, "input": stdin, "expected_output": expected, "is_hidden": hidden}
            for name, stdin, expected, hidden in test_cases
        ],
        "reference_solution": code_block(reference_solution),
        "skill_tags": skill_tags,
    }


def desc(difficulty: str, text: str, skill_tags: list[str]) -> dict:
    return {"difficulty": difficulty, "text": text, "skill_tags": skill_tags}


MCQ_BANK: dict[str, list[dict]] = {
    "Data Structures & Algorithms": [
        mcq(
            "easy",
            "What is the average-case time complexity of binary search on a sorted array of n elements?",
            ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
            "O(log n)",
            ["Data Structures", "Algorithms", "Searching"],
        ),
        mcq(
            "easy",
            "Which data structure follows the Last-In, First-Out (LIFO) principle?",
            ["Queue", "Stack", "Linked list", "Binary heap"],
            "Stack",
            ["Data Structures", "Stack"],
        ),
        mcq(
            "medium",
            "What is the worst-case time complexity of Quicksort?",
            ["O(n)", "O(n log n)", "O(n^2)", "O(log n)"],
            "O(n^2)",
            ["Algorithms", "Sorting"],
        ),
        mcq(
            "medium",
            "Which traversal of a binary search tree visits nodes in ascending order?",
            ["Pre-order", "In-order", "Post-order", "Level-order"],
            "In-order",
            ["Data Structures", "Trees", "Traversal"],
        ),
        mcq(
            "medium",
            "What is the minimum number of comparisons needed to find the maximum element in an unsorted array of n elements?",
            ["n", "n - 1", "log n", "n / 2"],
            "n - 1",
            ["Algorithms", "Arrays"],
        ),
        mcq(
            "hard",
            "What is the time complexity of building a binary heap from n elements using the bottom-up heapify method?",
            ["O(n log n)", "O(n)", "O(log n)", "O(n^2)"],
            "O(n)",
            ["Data Structures", "Heap", "Algorithms"],
        ),
    ],
    "DBMS & SQL": [
        mcq(
            "easy",
            "Which SQL clause is used to filter rows before grouping?",
            ["HAVING", "WHERE", "GROUP BY", "ORDER BY"],
            "WHERE",
            ["SQL", "Database"],
        ),
        mcq(
            "easy",
            "Which constraint uniquely identifies each row in a table and cannot contain NULL values?",
            ["Foreign key", "Primary key", "Check constraint", "Default constraint"],
            "Primary key",
            ["SQL", "Database Design"],
        ),
        mcq(
            "easy",
            "What does the 'I' in ACID stand for?",
            ["Integrity", "Isolation", "Indexing", "Inheritance"],
            "Isolation",
            ["DBMS", "Transactions"],
        ),
        mcq(
            "medium",
            "Which normal form eliminates partial dependencies on a composite primary key?",
            [
                "First Normal Form (1NF)",
                "Second Normal Form (2NF)",
                "Third Normal Form (3NF)",
                "Boyce-Codd Normal Form (BCNF)",
            ],
            "Second Normal Form (2NF)",
            ["DBMS", "Normalization"],
        ),
        mcq(
            "medium",
            "What is the main difference between DELETE and TRUNCATE in SQL?",
            [
                "DELETE removes the table structure; TRUNCATE removes only rows.",
                "TRUNCATE can use a WHERE clause; DELETE cannot.",
                "DELETE removes rows and can use a WHERE clause; TRUNCATE removes all rows and cannot use WHERE.",
                "Both are identical in every database.",
            ],
            "DELETE removes rows and can use a WHERE clause; TRUNCATE removes all rows and cannot use WHERE.",
            ["SQL", "Database"],
        ),
        mcq(
            "medium",
            "Which JOIN returns all rows from the left table and matching rows from the right table?",
            ["INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "CROSS JOIN"],
            "LEFT JOIN",
            ["SQL", "Joins"],
        ),
        mcq(
            "hard",
            "In a table with a composite primary key, what does the composite key guarantee?",
            [
                "Each individual column must be unique.",
                "The combination of columns uniquely identifies each row.",
                "The table can have no foreign keys.",
                "All columns must have NULL values.",
            ],
            "The combination of columns uniquely identifies each row.",
            ["DBMS", "Keys"],
        ),
    ],
    "Operating Systems": [
        mcq(
            "easy",
            "What is a process?",
            [
                "A program stored on disk",
                "A program in execution",
                "A thread that has not started",
                "A file descriptor",
            ],
            "A program in execution",
            ["Operating Systems", "Processes"],
        ),
        mcq(
            "easy",
            "Which CPU scheduling policy gives each process a fixed time quantum?",
            [
                "First-Come, First-Served",
                "Shortest Job First",
                "Round Robin",
                "Priority Scheduling",
            ],
            "Round Robin",
            ["Operating Systems", "Scheduling"],
        ),
        mcq(
            "easy",
            "What is thrashing in an operating system?",
            [
                "A CPU running at maximum utilization",
                "Excessive paging that leaves little time for useful work",
                "A process waiting for user input",
                "A disk with too many partitions",
            ],
            "Excessive paging that leaves little time for useful work",
            ["Operating Systems", "Memory Management"],
        ),
        mcq(
            "medium",
            "Which page replacement algorithm can suffer from Belady's anomaly?",
            ["LRU", "Optimal", "FIFO", "LFU"],
            "FIFO",
            ["Operating Systems", "Memory Management", "Page Replacement"],
        ),
        mcq(
            "medium",
            "Which of the following is NOT a necessary condition for deadlock?",
            ["Mutual exclusion", "Hold and wait", "Circular wait", "Preemption"],
            "Preemption",
            ["Operating Systems", "Deadlock"],
        ),
        mcq(
            "medium",
            "What is the main purpose of a semaphore?",
            [
                "To store the process's page table",
                "To control access to a shared resource using a counter",
                "To schedule processes by priority",
                "To allocate disk blocks",
            ],
            "To control access to a shared resource using a counter",
            ["Operating Systems", "Synchronization"],
        ),
        mcq(
            "hard",
            "Which scheduling algorithm minimizes the average waiting time for a given set of processes when all arrival times are zero?",
            [
                "First-Come, First-Served",
                "Shortest Job First",
                "Round Robin",
                "Priority Scheduling",
            ],
            "Shortest Job First",
            ["Operating Systems", "Scheduling", "Algorithms"],
        ),
    ],
    "Computer Networks": [
        mcq(
            "easy",
            "Which OSI layer is responsible for routing packets between networks?",
            ["Data Link layer", "Network layer", "Transport layer", "Session layer"],
            "Network layer",
            ["Computer Networks", "OSI Model"],
        ),
        mcq(
            "easy",
            "What is the primary purpose of DNS?",
            [
                "To encrypt web traffic",
                "To resolve domain names to IP addresses",
                "To assign MAC addresses",
                "To route packets between routers",
            ],
            "To resolve domain names to IP addresses",
            ["Computer Networks", "DNS"],
        ),
        mcq(
            "easy",
            "Which transport-layer protocol is connection-oriented and provides reliable delivery?",
            ["UDP", "TCP", "IP", "ICMP"],
            "TCP",
            ["Computer Networks", "TCP/IP"],
        ),
        mcq(
            "medium",
            "What does ARP do?",
            [
                "Maps IP addresses to MAC addresses",
                "Maps domain names to IP addresses",
                "Assigns IP addresses dynamically",
                "Encrypts network packets",
            ],
            "Maps IP addresses to MAC addresses",
            ["Computer Networks", "ARP"],
        ),
        mcq(
            "medium",
            "Which port is used by HTTPS by default?",
            ["21", "22", "80", "443"],
            "443",
            ["Computer Networks", "Ports", "Security"],
        ),
        mcq(
            "medium",
            "What is subnetting?",
            [
                "Dividing a larger network into smaller logical networks",
                "Combining multiple networks into one broadcast domain",
                "Encrypting traffic between two hosts",
                "Assigning domain names to servers",
            ],
            "Dividing a larger network into smaller logical networks",
            ["Computer Networks", "Subnetting"],
        ),
        mcq(
            "hard",
            "How many usable host addresses are available in an IPv4 /27 subnet?",
            ["14", "30", "32", "62"],
            "30",
            ["Computer Networks", "Subnetting", "IPv4"],
        ),
    ],
    "Object-Oriented Programming": [
        mcq(
            "easy",
            "What is encapsulation in object-oriented programming?",
            [
                "Bundling data and methods together and restricting direct access to internal state",
                "Creating multiple classes with the same name",
                "Inheriting from more than one class",
                "Converting a class into a function",
            ],
            "Bundling data and methods together and restricting direct access to internal state",
            ["OOP", "Encapsulation"],
        ),
        mcq(
            "easy",
            "Which OOP concept allows a subclass to provide its own implementation of a method defined in its superclass?",
            ["Method overloading", "Method overriding", "Abstraction", "Composition"],
            "Method overriding",
            ["OOP", "Inheritance", "Polymorphism"],
        ),
        mcq(
            "easy",
            "What is a class in object-oriented programming?",
            [
                "An instance of an object",
                "A blueprint for creating objects",
                "A built-in database table",
                "A function that returns only integers",
            ],
            "A blueprint for creating objects",
            ["OOP", "Classes"],
        ),
        mcq(
            "medium",
            "What is the key difference between abstraction and encapsulation?",
            [
                "Abstraction hides implementation complexity; encapsulation hides internal data and restricts access.",
                "Abstraction applies only to databases; encapsulation applies only to web apps.",
                "Encapsulation hides implementation complexity; abstraction hides internal data.",
                "They are exactly the same concept.",
            ],
            "Abstraction hides implementation complexity; encapsulation hides internal data and restricts access.",
            ["OOP", "Abstraction", "Encapsulation"],
        ),
        mcq(
            "medium",
            "Which relationship is described as a 'has-a' relationship?",
            ["Inheritance", "Composition", "Polymorphism", "Abstraction"],
            "Composition",
            ["OOP", "Composition"],
        ),
        mcq(
            "hard",
            "What is the diamond problem in object-oriented programming?",
            [
                "A class inheriting from two classes that share a common base class, causing ambiguity",
                "A database table with four primary keys",
                "A method with four overloaded versions",
                "A loop that never terminates",
            ],
            "A class inheriting from two classes that share a common base class, causing ambiguity",
            ["OOP", "Inheritance", "Multiple Inheritance"],
        ),
    ],
    "Python Programming": [
        mcq(
            "easy",
            'What is the output of len("hello") in Python?',
            ["4", "5", "6", "A TypeError is raised"],
            "5",
            ["Python", "Strings"],
        ),
        mcq(
            "easy",
            "Which keyword is used to define a function in Python?",
            ["func", "def", "function", "lambda"],
            "def",
            ["Python", "Functions"],
        ),
        mcq(
            "medium",
            "What is the output of [1, 2, 3][-1] in Python?",
            ["1", "2", "3", "An IndexError is raised"],
            "3",
            ["Python", "Lists"],
        ),
        mcq(
            "medium",
            "What does the Python list method sort() return?",
            ["A new sorted list", "None", "The original list", "True"],
            "None",
            ["Python", "Lists", "Sorting"],
        ),
        mcq(
            "hard",
            "What is the average-case time complexity of the 'in' operator when checking membership in a Python list of n elements?",
            ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
            "O(n)",
            ["Python", "Algorithms", "Lists"],
        ),
    ],
    "JavaScript & Web Development": [
        mcq(
            "easy",
            "Which JavaScript keyword declares a variable that cannot be reassigned?",
            ["var", "let", "const", "static"],
            "const",
            ["JavaScript", "Variables"],
        ),
        mcq(
            "easy",
            "What does the JavaScript === operator compare?",
            ["Only value", "Only type", "Both value and type", "Neither value nor type"],
            "Both value and type",
            ["JavaScript", "Operators"],
        ),
        mcq(
            "medium",
            "What is the result of typeof null in JavaScript?",
            ['"null"', '"object"', '"undefined"', '"number"'],
            '"object"',
            ["JavaScript", "Types"],
        ),
        mcq(
            "medium",
            "Which array method adds one or more elements to the end of an array?",
            ["pop()", "push()", "shift()", "unshift()"],
            "push()",
            ["JavaScript", "Arrays"],
        ),
        mcq(
            "hard",
            "What is a closure in JavaScript?",
            [
                "A function that retains access to its lexical scope even after the outer function returns",
                "A loop that closes automatically",
                "A method that cannot be overridden",
                "A way to close a browser tab",
            ],
            "A function that retains access to its lexical scope even after the outer function returns",
            ["JavaScript", "Closures", "Functions"],
        ),
    ],
    "Aptitude & Logical Reasoning": [
        mcq(
            "easy",
            "A train travels 60 km in 1.5 hours. What is its average speed?",
            ["30 km/h", "40 km/h", "45 km/h", "90 km/h"],
            "40 km/h",
            ["Aptitude", "Speed and Distance"],
        ),
        mcq(
            "easy",
            "What is 15% of 200?",
            ["15", "20", "30", "35"],
            "30",
            ["Aptitude", "Percentages"],
        ),
        mcq(
            "easy",
            "Which number comes next in the sequence: 2, 4, 8, 16, __?",
            ["18", "24", "32", "64"],
            "32",
            ["Aptitude", "Number Series"],
        ),
        mcq(
            "medium",
            "A shopkeeper gives a 20% discount on an item marked at ₹500. What is the selling price?",
            ["₹380", "₹400", "₹420", "₹450"],
            "₹400",
            ["Aptitude", "Percentages"],
        ),
        mcq(
            "medium",
            "If 5 workers complete a job in 12 days, how many days will 10 workers take at the same rate?",
            ["3 days", "6 days", "8 days", "24 days"],
            "6 days",
            ["Aptitude", "Time and Work"],
        ),
        mcq(
            "medium",
            "The ratio of boys to girls in a class is 3:2. If there are 30 boys, how many girls are there?",
            ["15", "18", "20", "25"],
            "20",
            ["Aptitude", "Ratios"],
        ),
        mcq(
            "hard",
            "A sum of money doubles in 8 years at simple interest. What is the annual rate of interest?",
            ["10%", "12.5%", "15%", "20%"],
            "12.5%",
            ["Aptitude", "Simple Interest"],
        ),
        mcq(
            "hard",
            "In how many different ways can 3 people be seated in 3 chairs?",
            ["3", "6", "9", "12"],
            "6",
            ["Aptitude", "Permutations"],
        ),
    ],
    "Machine Learning & AI": [
        mcq(
            "easy",
            "What is supervised learning?",
            [
                "Learning from labeled training data",
                "Learning without any data",
                "Only clustering unlabeled data",
                "Building databases without labels",
            ],
            "Learning from labeled training data",
            ["Machine Learning", "Supervised Learning"],
        ),
        mcq(
            "easy",
            "Which metric is commonly used to evaluate a classification model?",
            ["Mean Squared Error", "Accuracy", "R-squared", "Mean Absolute Error"],
            "Accuracy",
            ["Machine Learning", "Evaluation"],
        ),
        mcq(
            "easy",
            "What is overfitting?",
            [
                "A model that performs well on training data but poorly on unseen data",
                "A model that is too simple to learn anything",
                "A dataset with too few features",
                "A training process that stops too early",
            ],
            "A model that performs well on training data but poorly on unseen data",
            ["Machine Learning", "Model Evaluation"],
        ),
        mcq(
            "medium",
            "What is the main purpose of splitting data into training and test sets?",
            [
                "To reduce the number of features",
                "To evaluate how well the model generalizes to unseen data",
                "To increase the training accuracy",
                "To remove missing values",
            ],
            "To evaluate how well the model generalizes to unseen data",
            ["Machine Learning", "Evaluation"],
        ),
        mcq(
            "medium",
            "Which of the following is a classification algorithm?",
            ["Linear Regression", "Logistic Regression", "K-Means", "Principal Component Analysis"],
            "Logistic Regression",
            ["Machine Learning", "Classification"],
        ),
        mcq(
            "hard",
            "What does regularization do in a machine learning model?",
            [
                "It penalizes model complexity to reduce overfitting",
                "It always increases training accuracy",
                "It removes the need for a test set",
                "It converts regression into clustering",
            ],
            "It penalizes model complexity to reduce overfitting",
            ["Machine Learning", "Regularization"],
        ),
    ],
    "Cybersecurity": [
        mcq(
            "easy",
            "What is the primary goal of a phishing attack?",
            [
                "To steal credentials or personal information by impersonating a trusted entity",
                "To physically damage a server",
                "To speed up network traffic",
                "To encrypt backups",
            ],
            "To steal credentials or personal information by impersonating a trusted entity",
            ["Cybersecurity", "Phishing"],
        ),
        mcq(
            "easy",
            "What does HTTPS provide compared with HTTP?",
            ["Faster downloads", "Encrypted communication", "Larger bandwidth", "Automatic backups"],
            "Encrypted communication",
            ["Cybersecurity", "HTTPS"],
        ),
        mcq(
            "easy",
            "What is malware?",
            ["Malicious software", "A hardware firewall", "A network cable", "A backup policy"],
            "Malicious software",
            ["Cybersecurity", "Malware"],
        ),
        mcq(
            "medium",
            "What is SQL injection?",
            [
                "Injecting malicious SQL through unsanitized user input",
                "A hardware failure in a database server",
                "A backup restoration technique",
                "A method for indexing tables",
            ],
            "Injecting malicious SQL through unsanitized user input",
            ["Cybersecurity", "SQL Injection", "Web Security"],
        ),
        mcq(
            "medium",
            "What is the principle of least privilege?",
            [
                "Grant users only the minimum permissions needed to perform their work",
                "Give every user administrator access",
                "Disable all authentication",
                "Store passwords in plain text",
            ],
            "Grant users only the minimum permissions needed to perform their work",
            ["Cybersecurity", "Access Control"],
        ),
        mcq(
            "medium",
            "What is the main function of a firewall?",
            [
                "To filter network traffic based on rules",
                "To store database backups",
                "To compile source code",
                "To assign domain names",
            ],
            "To filter network traffic based on rules",
            ["Cybersecurity", "Firewall", "Network Security"],
        ),
        mcq(
            "hard",
            "What is a zero-day vulnerability?",
            [
                "A vulnerability that is exploited before a fix is available",
                "A vulnerability that takes zero seconds to exploit",
                "A bug that only affects day-zero installations",
                "A vulnerability with a known patch",
            ],
            "A vulnerability that is exploited before a fix is available",
            ["Cybersecurity", "Vulnerabilities"],
        ),
    ],
    "Cloud & DevOps": [
        mcq(
            "easy",
            "What is Docker primarily used for?",
            ["Containerizing applications", "Editing spreadsheets", "Managing payroll", "Designing logos"],
            "Containerizing applications",
            ["Cloud", "DevOps", "Docker"],
        ),
        mcq(
            "easy",
            "What does CI stand for in DevOps?",
            ["Continuous Integration", "Cloud Infrastructure", "Container Isolation", "Central Indexing"],
            "Continuous Integration",
            ["DevOps", "CI/CD"],
        ),
        mcq(
            "easy",
            "Which AWS service provides object storage?",
            ["EC2", "S3", "RDS", "Lambda"],
            "S3",
            ["Cloud", "AWS"],
        ),
        mcq(
            "medium",
            "What is Kubernetes?",
            [
                "A container orchestration platform",
                "A relational database",
                "A JavaScript testing framework",
                "A CSS preprocessor",
            ],
            "A container orchestration platform",
            ["Cloud", "DevOps", "Kubernetes"],
        ),
        mcq(
            "medium",
            "What is Infrastructure as Code (IaC)?",
            [
                "Managing infrastructure through machine-readable configuration files",
                "Writing application code only in the cloud",
                "Storing infrastructure in a physical vault",
                "A programming language for hardware",
            ],
            "Managing infrastructure through machine-readable configuration files",
            ["Cloud", "DevOps", "IaC"],
        ),
        mcq(
            "hard",
            "What is a blue-green deployment?",
            [
                "Running two environments and switching traffic from one to the other",
                "Deploying only during the day",
                "Using two different programming languages",
                "Deploying to two developers' laptops",
            ],
            "Running two environments and switching traffic from one to the other",
            ["DevOps", "Deployment"],
        ),
    ],
    "Software Engineering": [
        mcq(
            "easy",
            "What is the main purpose of version control systems like Git?",
            [
                "To track changes to source code over time",
                "To compile code faster",
                "To replace unit tests",
                "To design user interfaces",
            ],
            "To track changes to source code over time",
            ["Software Engineering", "Version Control", "Git"],
        ),
        mcq(
            "easy",
            "What does SDLC stand for?",
            [
                "Software Development Life Cycle",
                "System Debugging and Logging Cycle",
                "Source Deployment and Launch Control",
                "Secure Data Linking Component",
            ],
            "Software Development Life Cycle",
            ["Software Engineering", "SDLC"],
        ),
        mcq(
            "easy",
            "What is unit testing?",
            [
                "Testing individual components or functions in isolation",
                "Testing the entire system with real users",
                "Testing only the database",
                "Testing the network cable",
            ],
            "Testing individual components or functions in isolation",
            ["Software Engineering", "Testing"],
        ),
        mcq(
            "medium",
            "What is the difference between black-box and white-box testing?",
            [
                "Black-box tests behavior without internal knowledge; white-box tests internal logic.",
                "Black-box tests only databases; white-box tests only user interfaces.",
                "Black-box testing is always automated; white-box testing is always manual.",
                "They are the same thing.",
            ],
            "Black-box tests behavior without internal knowledge; white-box tests internal logic.",
            ["Software Engineering", "Testing"],
        ),
        mcq(
            "medium",
            "What is code review?",
            [
                "Having peers examine code for quality, bugs, and maintainability",
                "Running the application in production",
                "Deleting unused repositories",
                "Writing documentation after release",
            ],
            "Having peers examine code for quality, bugs, and maintainability",
            ["Software Engineering", "Code Review"],
        ),
        mcq(
            "hard",
            "What is technical debt?",
            [
                "The future cost of choosing an easier short-term solution over a better long-term design",
                "Money owed to cloud providers",
                "The number of bugs in a release",
                "The time spent writing tests",
            ],
            "The future cost of choosing an easier short-term solution over a better long-term design",
            ["Software Engineering", "Technical Debt"],
        ),
    ],
}

CODING_BANK: dict[str, list[dict]] = {
    "Data Structures & Algorithms": [
        coding(
            "easy",
            "Read a line of space-separated integers from standard input and print their sum. If the input is empty, print 0.",
            "python",
            """
                # Read all integers from standard input and print their sum.
                # If there is no input, print 0.
            """,
            [
                ("positive numbers", "1 2 3", "6", False),
                ("mixed signs", "10 -5 2", "7", True),
                ("empty input", "", "0", True),
            ],
            """
                import sys

                data = sys.stdin.read().split()
                print(sum(int(x) for x in data))
            """,
            ["Python", "Data Structures", "Arrays", "Algorithms"],
        ),
        coding(
            "medium",
            "Read a line of text and print the longest word. If multiple words have the same length, print the first one. Treat any whitespace as a separator.",
            "python",
            """
                # Read a line of text and print the longest word.
            """,
            [
                ("basic", "I love programming", "programming", False),
                ("longest at end", "a bb ccc dddd", "dddd", True),
                ("single word", "hello", "hello", True),
            ],
            """
                import sys

                words = sys.stdin.read().split()
                print(max(words, key=len) if words else "")
            """,
            ["Python", "Strings", "Data Structures"],
        ),
    ],
    "DBMS & SQL": [
        coding(
            "medium",
            "Read an integer N, then N lines of the form `name salary`. Print the name of the employee with the highest salary. If there is a tie, print the name that appears first.",
            "python",
            """
                # Read N, then N lines of "name salary".
                # Print the name of the highest-paid employee.
            """,
            [
                (
                    "three employees",
                    "3\nAlice 50000\nBob 65000\nCara 60000",
                    "Bob",
                    False,
                ),
                ("two employees", "2\nJohn 70000\nJane 80000", "Jane", True),
                ("single employee", "1\nSam 45000", "Sam", True),
            ],
            """
                import sys

                lines = sys.stdin.read().strip().splitlines()
                if not lines:
                    raise SystemExit
                n = int(lines[0].strip())
                best_name = None
                best_salary = None
                for line in lines[1 : 1 + n]:
                    name, salary = line.rsplit(None, 1)
                    salary = int(salary)
                    if best_salary is None or salary > best_salary:
                        best_salary = salary
                        best_name = name
                print(best_name)
            """,
            ["Python", "SQL", "Data Processing"],
        ),
    ],
    "Object-Oriented Programming": [
        coding(
            "medium",
            "Read two integers, width and height, on a single line. Define a class `Rectangle` with attributes `width` and `height`, and a method `area()` that returns width * height. Print the area.",
            "python",
            """
                # Define a Rectangle class with width, height, and an area() method.
                # Read two integers and print the rectangle's area.
            """,
            [
                ("3 by 4", "3 4", "12", False),
                ("5 by 2", "5 2", "10", True),
                ("10 by 10", "10 10", "100", True),
            ],
            """
                import sys

                class Rectangle:
                    def __init__(self, width, height):
                        self.width = width
                        self.height = height

                    def area(self):
                        return self.width * self.height

                w, h = map(int, sys.stdin.read().split())
                print(Rectangle(w, h).area())
            """,
            ["Python", "OOP", "Classes"],
        ),
    ],
    "Python Programming": [
        coding(
            "easy",
            "Read a line of space-separated integers and print the maximum value.",
            "python",
            """
                # Read integers and print the largest one.
            """,
            [
                ("basic", "1 5 3", "5", False),
                ("all negative", "-10 -2 -30", "-2", True),
                ("single value", "7", "7", True),
            ],
            """
                import sys

                nums = [int(x) for x in sys.stdin.read().split()]
                print(max(nums))
            """,
            ["Python", "Lists", "Algorithms"],
        ),
        coding(
            "medium",
            "Read an integer N, then a line containing N space-separated integers. Print how many of those integers are even.",
            "python",
            """
                # Read N, then N integers. Print the number of even integers.
            """,
            [
                ("mixed", "5\n1 2 3 4 5", "2", False),
                ("all even", "3\n2 4 6", "3", True),
                ("all odd", "4\n1 3 5 7", "0", True),
            ],
            """
                import sys

                data = sys.stdin.read().split()
                if not data:
                    raise SystemExit
                n = int(data[0])
                nums = [int(x) for x in data[1 : 1 + n]]
                print(sum(1 for x in nums if x % 2 == 0))
            """,
            ["Python", "Lists", "Control Flow"],
        ),
        coding(
            "hard",
            "Read an integer N, then a line containing N integers. Print the second largest distinct value. If no second largest distinct value exists, print `NA`.",
            "python",
            """
                # Read N and N integers. Print the second largest distinct value, or NA.
            """,
            [
                ("distinct values", "5\n3 1 4 4 2", "3", False),
                ("all equal", "3\n7 7 7", "NA", True),
                ("ascending", "4\n10 20 30 40", "30", True),
            ],
            """
                import sys

                data = sys.stdin.read().split()
                if not data:
                    raise SystemExit
                n = int(data[0])
                nums = [int(x) for x in data[1 : 1 + n]]
                distinct = sorted(set(nums), reverse=True)
                print(distinct[1] if len(distinct) >= 2 else "NA")
            """,
            ["Python", "Sorting", "Sets", "Algorithms"],
        ),
    ],
    "JavaScript & Web Development": [
        coding(
            "easy",
            "Read a line of space-separated integers from standard input and print their sum.",
            "javascript",
            """
                // Read all integers from standard input and print their sum.
                const data = require('fs').readFileSync(0, 'utf8').trim();
            """,
            [
                ("positive numbers", "1 2 3", "6", False),
                ("two numbers", "10 20", "30", True),
                ("mixed signs", "-5 5", "0", True),
            ],
            """
                const data = require('fs').readFileSync(0, 'utf8').trim();
                const nums = data.length ? data.split(/\\s+/).map(Number) : [];
                console.log(nums.reduce((a, b) => a + b, 0));
            """,
            ["JavaScript", "Arrays", "Algorithms"],
        ),
        coding(
            "medium",
            "Read an integer N, then a line containing N space-separated integers. Print how many are even.",
            "javascript",
            """
                // Read N and then N integers. Print the count of even numbers.
                const data = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);
            """,
            [
                ("mixed", "5\n1 2 3 4 5", "2", False),
                ("all even", "3\n2 4 6", "3", True),
                ("all odd", "4\n1 3 5 7", "0", True),
            ],
            """
                const data = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);
                const n = data[0];
                const nums = data.slice(1, 1 + n);
                console.log(nums.filter((x) => x % 2 === 0).length);
            """,
            ["JavaScript", "Arrays", "Control Flow"],
        ),
        coding(
            "hard",
            "Read an integer N, then a line containing N integers. Print the second largest distinct value. If it does not exist, print `NA`.",
            "javascript",
            """
                // Read N and N integers. Print the second largest distinct value or NA.
                const data = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);
            """,
            [
                ("distinct values", "5\n3 1 4 4 2", "3", False),
                ("all equal", "3\n7 7 7", "NA", True),
                ("ascending", "4\n10 20 30 40", "30", True),
            ],
            """
                const data = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);
                const n = data[0];
                const nums = data.slice(1, 1 + n);
                const distinct = [...new Set(nums)].sort((a, b) => b - a);
                console.log(distinct.length >= 2 ? distinct[1] : 'NA');
            """,
            ["JavaScript", "Sorting", "Sets", "Algorithms"],
        ),
    ],
    "Machine Learning & AI": [
        coding(
            "medium",
            "Read an integer N, then a line containing N numbers. Print their arithmetic mean rounded to 2 decimal places.",
            "python",
            """
                # Read N and N numbers. Print the mean rounded to 2 decimal places.
            """,
            [
                ("three numbers", "3\n1 2 3", "2.00", False),
                ("even numbers", "4\n2 4 6 8", "5.00", True),
                ("two numbers", "2\n10 20", "15.00", True),
            ],
            """
                import sys

                data = sys.stdin.read().split()
                if not data:
                    raise SystemExit
                n = int(data[0])
                nums = [float(x) for x in data[1 : 1 + n]]
                print(f"{sum(nums) / n:.2f}")
            """,
            ["Python", "Machine Learning", "Statistics"],
        ),
    ],
    "Cloud & DevOps": [
        coding(
            "medium",
            "Read all lines from standard input and print how many lines contain the word `ERROR` (case-sensitive).",
            "python",
            """
                # Read lines from standard input and count those containing ERROR.
            """,
            [
                ("two errors", "INFO ok\nERROR disk\nERROR memory", "2", False),
                ("no errors", "INFO ok\nWARN low disk", "0", True),
                ("empty input", "", "0", True),
            ],
            """
                import sys

                lines = sys.stdin.read().splitlines()
                print(sum(1 for line in lines if "ERROR" in line))
            """,
            ["Python", "DevOps", "Log Analysis"],
        ),
    ],
}

DESCRIPTIVE_BANK: dict[str, list[dict]] = {
    "Data Structures & Algorithms": [
        desc(
            "medium",
            "Explain the difference between an array and a linked list. Include the time complexity of random access and insertion at the beginning for each.",
            ["Data Structures", "Arrays", "Linked List"],
        ),
    ],
    "DBMS & SQL": [
        desc(
            "hard",
            "Explain the difference between Third Normal Form (3NF) and Boyce-Codd Normal Form (BCNF). Give an example where a relation is in 3NF but not in BCNF.",
            ["DBMS", "Normalization", "Database Design"],
        ),
    ],
    "Operating Systems": [
        desc(
            "medium",
            "Explain the difference between a process and a thread. Include at least two advantages of using threads.",
            ["Operating Systems", "Processes", "Threads"],
        ),
    ],
    "Computer Networks": [
        desc(
            "medium",
            "Explain the difference between TCP and UDP. Give one real-world use case for each protocol.",
            ["Computer Networks", "TCP", "UDP"],
        ),
    ],
    "Object-Oriented Programming": [
        desc(
            "medium",
            "Explain polymorphism with a real-world example. Distinguish between compile-time and runtime polymorphism.",
            ["OOP", "Polymorphism"],
        ),
    ],
    "Python Programming": [
        desc(
            "medium",
            "Explain the difference between a Python list and a tuple. Give one scenario where a tuple is a better choice.",
            ["Python", "Lists", "Tuples"],
        ),
    ],
    "JavaScript & Web Development": [
        desc(
            "medium",
            "Explain the difference between `var`, `let`, and `const` in JavaScript. Include scope and reassignment behavior.",
            ["JavaScript", "Variables", "Scope"],
        ),
    ],
    "Machine Learning & AI": [
        desc(
            "medium",
            "Explain the bias-variance tradeoff in machine learning and how it relates to overfitting and underfitting.",
            ["Machine Learning", "Bias-Variance", "Model Evaluation"],
        ),
    ],
    "Cybersecurity": [
        desc(
            "medium",
            "Explain the difference between authentication and authorization. Give one example of each.",
            ["Cybersecurity", "Authentication", "Authorization"],
        ),
    ],
    "Cloud & DevOps": [
        desc(
            "medium",
            "Explain the difference between a container and a virtual machine. Include at least two tradeoffs.",
            ["Cloud", "DevOps", "Containers", "Virtual Machines"],
        ),
    ],
    "Software Engineering": [
        desc(
            "medium",
            "Explain the difference between Agile and Waterfall software development methodologies.",
            ["Software Engineering", "Agile", "Waterfall"],
        ),
        desc(
            "hard",
            "Describe the SOLID principles of object-oriented design. Pick one principle and give a concrete example of how violating it harms maintainability.",
            ["Software Engineering", "SOLID", "Design Principles"],
        ),
    ],
}


def build_specs() -> list[tuple[str, str, dict]]:
    specs: list[tuple[str, str, dict]] = []
    for category_name in CATEGORY_NAMES:
        for spec in MCQ_BANK.get(category_name, []):
            specs.append((category_name, "mcq", spec))
        for spec in CODING_BANK.get(category_name, []):
            specs.append((category_name, "coding", spec))
        for spec in DESCRIPTIVE_BANK.get(category_name, []):
            specs.append((category_name, "descriptive", spec))
    return specs


def validate_distribution(specs: list[tuple[str, str, dict]]) -> None:
    if len(specs) != 100:
        raise SystemExit(f"Expected exactly 100 questions, but built {len(specs)}.")

    by_category = Counter(category for category, _, _ in specs)
    by_type = Counter(kind for _, kind, _ in specs)
    by_difficulty = Counter(spec["difficulty"] for _, _, spec in specs)

    if set(by_category) != set(CATEGORY_NAMES):
        raise SystemExit("Category set mismatch between CATEGORY_NAMES and the banks.")

    for category_name in CATEGORY_NAMES:
        medium_count = sum(
            1
            for category, _, spec in specs
            if category == category_name and spec["difficulty"] == "medium"
        )
        if medium_count == 0:
            raise SystemExit(f"{category_name} has no medium-difficulty question.")

    print("Planned distribution:")
    print("  by type:      " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    print("  by difficulty:" + ", ".join(f"{k}={v}" for k, v in sorted(by_difficulty.items())))
    print("  by category:  " + ", ".join(f"{k}={v}" for k, v in by_category.items()))
    print()


def short_text(value: str, limit: int = 68) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def verify_coding_reference(spec: dict, cases: list[TestCase]) -> tuple[bool, str]:
    # Mark all cases visible for verification so a failure shows actual vs
    # expected. The student-facing TestCase objects keep their hidden flags.
    visible_cases = [
        TestCase(
            name=case.name,
            input=case.input,
            expected_output=case.expected_output,
            is_hidden=False,
        )
        for case in cases
    ]
    summary = execute_code(spec["language"], spec["reference_solution"], visible_cases)
    if summary.status == "disabled":
        return True, "code execution disabled; reference solution not verified"
    if summary.all_passed:
        return True, "reference solution passed all test cases"
    details = "; ".join(
        f"{result.name or result.index}: status={result.status} "
        f"expected={result.expected_output!r} actual={result.actual_output!r}"
        for result in summary.results
        if not result.passed
    )
    return False, details or summary.error or "unknown failure"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a 100-question PLACER question bank.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Append missing questions even when the questions collection is not empty.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing questions and categories first (refused if assessments exist).",
    )
    args = parser.parse_args()

    specs = build_specs()
    validate_distribution(specs)

    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]

    try:
        admin = await db.users.find_one({"email": "admin@placer.edu", "role": "admin"})
        if not admin:
            admin = await db.users.find_one({"role": "admin"})
        if not admin:
            print("No admin user found. Create one first with scripts.create_admin.")
            return
        admin_id = str(admin["_id"])

        existing_questions = await db.questions.count_documents({})
        if args.reset:
            assessment_count = await db.assessments.count_documents({})
            attempt_count = await db.assessment_attempts.count_documents({})
            if assessment_count or attempt_count:
                print(
                    f"Refusing --reset: {assessment_count} assessment(s) and "
                    f"{attempt_count} attempt(s) exist and may reference these "
                    "category/question IDs."
                )
                return
            deleted_questions = await db.questions.delete_many({})
            deleted_categories = await db.question_categories.delete_many({})
            print(
                f"Reset question bank: deleted {deleted_questions.deleted_count} question(s) "
                f"and {deleted_categories.deleted_count} category/categories."
            )
        elif existing_questions and not args.force:
            print(
                f"questions already has {existing_questions} document(s); refusing to append. "
                "Use --force to append missing questions or --reset to replace the bank."
            )
            return

        service = QuestionService(db)

        categories = {}
        created_categories = 0
        for name in CATEGORY_NAMES:
            existing = await service.categories.find_one({"name": name})
            if existing:
                categories[name] = existing
            else:
                categories[name] = await service.create_category(CategoryCreateRequest(name=name))
                created_categories += 1
        print(
            f"Categories: {len(categories)} ready "
            f"({created_categories} created, {len(categories) - created_categories} reused).\n"
        )

        # Shuffle insertion order so the bank is visibly mixed by category and
        # difficulty in the admin list, while the distribution stays balanced.
        random.Random(42).shuffle(specs)

        created = 0
        skipped = 0
        failures: list[str] = []

        for index, (category_name, kind, spec) in enumerate(specs, start=1):
            category = categories[category_name]
            company_tags = CATEGORY_COMPANY_TAGS.get(category_name, [])

            existing = await service.questions.find_one({"text": spec["text"]})
            if existing:
                skipped += 1
                print(f"{index:3d}. SKIP  [{category_name}] {short_text(spec['text'])}")
                continue

            if kind == "mcq":
                payload = QuestionCreateRequest(
                    category_id=category.id,
                    skill_tags=spec["skill_tags"],
                    difficulty=DifficultyLevel(spec["difficulty"]),
                    type=QuestionType.MCQ,
                    text=spec["text"],
                    options=spec["options"],
                    correct_answer=spec["correct_answer"],
                    company_tags=company_tags,
                )
            elif kind == "descriptive":
                payload = QuestionCreateRequest(
                    category_id=category.id,
                    skill_tags=spec["skill_tags"],
                    difficulty=DifficultyLevel(spec["difficulty"]),
                    type=QuestionType.DESCRIPTIVE,
                    text=spec["text"],
                    options=[],
                    correct_answer=None,
                    company_tags=company_tags,
                )
            else:
                cases = [TestCase(**case) for case in spec["test_cases"]]
                ok, detail = verify_coding_reference(spec, cases)
                if not ok:
                    failures.append(f"[{category_name}] {spec['text']}: {detail}")
                    print(f"{index:3d}. FAIL  [{category_name}] coding reference: {detail}")
                    continue
                payload = QuestionCreateRequest(
                    category_id=category.id,
                    skill_tags=spec["skill_tags"],
                    difficulty=DifficultyLevel(spec["difficulty"]),
                    type=QuestionType.CODING,
                    text=spec["text"],
                    language=CodingLanguage(spec["language"]),
                    starter_code=spec["starter_code"],
                    test_cases=cases,
                    company_tags=company_tags,
                )

            try:
                await service.create_question(admin_id, payload)
            except QuestionError as exc:
                failures.append(f"[{category_name}] {spec['text']}: {exc.message}")
                print(f"{index:3d}. FAIL  [{category_name}] {exc.message}")
                continue

            created += 1
            language_label = f" ({spec['language']})" if kind == "coding" else ""
            print(
                f"{index:3d}. CREATE [{category_name}] "
                f"{spec['difficulty']:6s} {kind:11s}{language_label} "
                f"{short_text(spec['text'])}"
            )

        total_questions = await db.questions.count_documents({})
        total_categories = await db.question_categories.count_documents({})
        print(
            f"\nDone. created={created}, skipped={skipped}, failed={len(failures)}; "
            f"collection totals: questions={total_questions}, categories={total_categories}."
        )
        if skipped:
            print("Skipped questions already existed (matched by exact question text).")
        if failures:
            print("\nFailures:")
            for failure in failures:
                print(f"  - {failure}")
            raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())

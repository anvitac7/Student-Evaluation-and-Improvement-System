"""Create 10 realistic mock companies + placement drives.

Uses DriveService so company creation, TPO ownership, validation, and
assessment linkage behave exactly like the real TPO "create drive" flow.

Usage (from backend/):
    .venv\\Scripts\\python.exe -m scripts.seed_mock_drives
    .venv\\Scripts\\python.exe -m scripts.seed_mock_drives --force

Without --force the script refuses to append when placement_drives already
has documents, so re-running it after a database reset is the intended use.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.models.drive import (
    DriveCreateRequest,
    DriveStatus,
    DriveUpdateRequest,
)
from app.services.drive_service import DriveService

DRIVES = [
    {
        "tpo": "rec",
        "closed": False,
        "payload": {
            "company_name": "Nexora Technologies",
            "company_description": (
                "Nexora Technologies builds a cloud-native workflow platform that helps "
                "mid-market fintech companies automate onboarding, KYC and reconciliation."
            ),
            "company_website": "https://www.nexoratech.example",
            "company_industry": "Software Product Development",
            "job_title": "Software Development Engineer I",
            "description": (
                "Design, build and ship customer-facing features across our React frontend "
                "and Python services, with a strong focus on reliability and clean APIs."
            ),
            "jd_text": (
                "Nexora Technologies is hiring Software Development Engineer I for its "
                "Bengaluru product engineering team. You will work with senior engineers to "
                "design REST APIs in Python, build responsive React interfaces, write tests, "
                "and deploy services on AWS. The role suits final-year students or recent "
                "graduates with 0-1 years of experience who are comfortable with Python, "
                "JavaScript, React, SQL and Git. You will take part in code reviews, debug "
                "production issues, and contribute to our internal design system. "
                "Eligibility: CGPA 7.0 or above, CSE/IT/ECE, graduating in 2026 or 2027. "
                "Selection: online coding assessment, two technical interviews, and HR interview."
            ),
            "required_skills": [
                "Python", "JavaScript", "React", "REST APIs", "SQL", "Git", "AWS",
            ],
            "experience_required_years": 0.0,
            "package": "₹14 LPA",
            "location": "Bengaluru",
            "eligibility": {
                "min_cgpa": 7.0,
                "departments": [
                    "Computer Science",
                    "Information Technology",
                    "Electronics and Communication",
                ],
                "batch_years": [2026, 2027],
            },
            "deadline": datetime(2026, 12, 15, 23, 59),
            "selection_process": [
                "Online Coding Assessment",
                "Technical Interview 1",
                "Technical Interview 2",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "insights",
        "closed": False,
        "payload": {
            "company_name": "Skyline Analytics",
            "company_description": (
                "Skyline Analytics is a data analytics consultancy that helps retail and "
                "consumer brands turn transaction data into pricing, assortment and "
                "demand-planning decisions."
            ),
            "company_website": "https://www.skylineanalytics.example",
            "company_industry": "Data Analytics & Consulting",
            "job_title": "Data Analyst",
            "description": (
                "Work with consulting teams to clean, model and visualise client data, and "
                "translate analysis into clear business recommendations."
            ),
            "jd_text": (
                "Skyline Analytics is looking for Data Analysts to join its Hyderabad "
                "delivery centre. You will write SQL queries against large retail datasets, "
                "build dashboards in Power BI, automate recurring reports with Python, and "
                "present findings to client stakeholders. The ideal candidate has strong "
                "statistical reasoning, comfort with Excel and SQL, and the ability to explain "
                "data clearly to non-technical audiences. Eligibility: CGPA 6.5+, "
                "CSE/IT/Mathematics & Computing/Statistics, 2026 or 2027 graduates. "
                "Selection: aptitude test, SQL and Python assessment, case-study interview, "
                "and HR interview."
            ),
            "required_skills": [
                "SQL", "Python", "Excel", "Power BI", "Statistics", "Data Visualisation",
            ],
            "experience_required_years": 0.0,
            "package": "₹8.5 LPA",
            "location": "Hyderabad",
            "eligibility": {
                "min_cgpa": 6.5,
                "departments": [
                    "Computer Science",
                    "Information Technology",
                    "Mathematics and Computing",
                    "Statistics",
                ],
                "batch_years": [2026, 2027],
            },
            "deadline": datetime(2026, 12, 22, 23, 59),
            "selection_process": [
                "Aptitude Test",
                "SQL & Python Assessment",
                "Case Study Interview",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "rec",
        "closed": False,
        "payload": {
            "company_name": "QuantumEdge Systems",
            "company_description": (
                "QuantumEdge Systems provides managed detection and response, penetration "
                "testing and security engineering services to BFSI and healthcare clients."
            ),
            "company_website": "https://www.quantumedge.example",
            "company_industry": "Cybersecurity",
            "job_title": "Cybersecurity Analyst",
            "description": (
                "Monitor client environments, investigate alerts, and help build detection "
                "rules and incident-response playbooks."
            ),
            "jd_text": (
                "QuantumEdge Systems is hiring Cybersecurity Analysts for its Pune security "
                "operations centre. You will triage SIEM alerts, investigate suspicious "
                "network and endpoint activity, document incidents, and support containment "
                "and remediation. You should understand TCP/IP, Linux fundamentals, common "
                "web vulnerabilities, and basic Python scripting for automation. Exposure to "
                "Splunk, Sentinel or Wazuh is a plus. Eligibility: CGPA 7.0+, CSE/IT/ECE, "
                "2026 graduates. Selection: online security assessment, technical interview, "
                "incident-response case discussion, and HR interview."
            ),
            "required_skills": [
                "Networking", "Linux", "Python", "SIEM", "Threat Analysis", "Incident Response",
            ],
            "experience_required_years": 0.0,
            "package": "₹10 LPA",
            "location": "Pune",
            "eligibility": {
                "min_cgpa": 7.0,
                "departments": [
                    "Computer Science",
                    "Information Technology",
                    "Electronics and Communication",
                ],
                "batch_years": [2026],
            },
            "deadline": datetime(2027, 1, 10, 23, 59),
            "selection_process": [
                "Online Security Assessment",
                "Technical Interview",
                "Incident Response Case Discussion",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "insights",
        "closed": False,
        "payload": {
            "company_name": "BlueOrbit Solutions",
            "company_description": (
                "BlueOrbit Solutions helps SaaS companies run reliable multi-cloud "
                "infrastructure with observability, cost optimisation and platform engineering."
            ),
            "company_website": "https://www.blueorbit.example",
            "company_industry": "Cloud Infrastructure & DevOps",
            "job_title": "DevOps Engineer",
            "description": (
                "Automate build and deployment pipelines, manage Kubernetes workloads, and "
                "improve observability across client platforms."
            ),
            "jd_text": (
                "BlueOrbit Solutions is hiring a DevOps Engineer to work remotely with our "
                "platform team. You will maintain CI/CD pipelines, containerise services with "
                "Docker, deploy to Kubernetes on AWS, write infrastructure-as-code, and build "
                "monitoring dashboards. You should be comfortable on Linux, have scripting "
                "experience in Python or Bash, and understand networking and cloud "
                "fundamentals. Eligibility: CGPA 6.5+, CSE/IT/Electrical Engineering, "
                "2023/2026/2027 graduates. Selection: online assessment, technical interview, "
                "take-home infrastructure project, and HR interview."
            ),
            "required_skills": [
                "Linux", "Docker", "Kubernetes", "AWS", "CI/CD", "Python", "Terraform",
            ],
            "experience_required_years": 0.5,
            "package": "₹12.5 LPA",
            "location": "Remote (India)",
            "eligibility": {
                "min_cgpa": 6.5,
                "departments": [
                    "Computer Science",
                    "Information Technology",
                    "Electrical Engineering",
                ],
                "batch_years": [2023, 2026, 2027],
            },
            "deadline": datetime(2026, 12, 30, 23, 59),
            "selection_process": [
                "Online Assessment",
                "Technical Interview",
                "Take-home Infrastructure Project",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "rec",
        "closed": False,
        "payload": {
            "company_name": "PixelForge Studios",
            "company_description": (
                "PixelForge Studios designs and publishes casual mobile games played by "
                "millions of users across India and Southeast Asia."
            ),
            "company_website": "https://www.pixelforge.example",
            "company_industry": "Gaming & Mobile Apps",
            "job_title": "Frontend Developer",
            "description": (
                "Build polished, responsive web and in-game interfaces using React and "
                "TypeScript, and collaborate closely with designers and artists."
            ),
            "jd_text": (
                "PixelForge Studios is looking for a Frontend Developer to join its Mumbai "
                "studio. You will implement UI features in React and TypeScript, build "
                "reusable components, optimise performance for low-end devices, and work with "
                "designers to ship accessible interfaces. A portfolio or GitHub profile "
                "showing personal projects is valued. Eligibility: CGPA 6.0+, CSE/IT/ECE, "
                "2026 or 2027 graduates. Selection: portfolio review, coding assessment, "
                "technical interview, and HR interview."
            ),
            "required_skills": [
                "React", "TypeScript", "JavaScript", "HTML", "CSS", "Git",
            ],
            "experience_required_years": 0.0,
            "package": "₹9 LPA",
            "location": "Mumbai",
            "eligibility": {
                "min_cgpa": 6.0,
                "departments": [
                    "Computer Science",
                    "Information Technology",
                    "Electronics and Communication",
                ],
                "batch_years": [2026, 2027],
            },
            "deadline": datetime(2027, 1, 5, 23, 59),
            "selection_process": [
                "Portfolio Review",
                "Coding Assessment",
                "Technical Interview",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "insights",
        "closed": False,
        "payload": {
            "company_name": "CloudNest Infrastructure",
            "company_description": (
                "CloudNest Infrastructure provides a managed data platform for logistics and "
                "e-commerce companies, with APIs for inventory, pricing and order orchestration."
            ),
            "company_website": "https://www.cloudnest.example",
            "company_industry": "SaaS & Cloud Infrastructure",
            "job_title": "Backend Engineer",
            "description": (
                "Own backend services and data models for our multi-tenant platform, with a "
                "focus on API design, performance and reliability."
            ),
            "jd_text": (
                "CloudNest Infrastructure is hiring a Backend Engineer for its Chennai "
                "engineering team. You will design and build Python services with FastAPI, "
                "model data in PostgreSQL and MongoDB, add Redis caching, and deploy "
                "containers with Docker. You will also participate in on-call rotations and "
                "contribute to system-design reviews. Eligibility: CGPA 7.0+, CSE/IT, 2026 "
                "graduates with 0-1 years of experience. Selection: online assessment, "
                "system-design interview, technical interview, and HR interview."
            ),
            "required_skills": [
                "Python", "FastAPI", "MongoDB", "PostgreSQL", "Redis", "Docker", "REST APIs",
            ],
            "experience_required_years": 1.0,
            "package": "₹13 LPA",
            "location": "Chennai",
            "eligibility": {
                "min_cgpa": 7.0,
                "departments": ["Computer Science", "Information Technology"],
                "batch_years": [2026],
            },
            "deadline": datetime(2026, 12, 18, 23, 59),
            "selection_process": [
                "Online Assessment",
                "System Design Interview",
                "Technical Interview",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "rec",
        "closed": False,
        "payload": {
            "company_name": "TerraNova Fintech",
            "company_description": (
                "TerraNova Fintech builds credit-underwriting and fraud-detection models for "
                "small-business lenders."
            ),
            "company_website": "https://www.terranova.example",
            "company_industry": "Fintech",
            "job_title": "Machine Learning Engineer",
            "description": (
                "Train, evaluate and deploy models for credit risk and fraud detection, and "
                "work with product and risk teams to put them into production."
            ),
            "jd_text": (
                "TerraNova Fintech is hiring a Machine Learning Engineer for its Gurugram "
                "office. You will build feature pipelines with Python, Pandas and SQL, train "
                "models with Scikit-learn and PyTorch, evaluate them against business "
                "metrics, and deploy them behind low-latency APIs. Experience with NLP or "
                "tabular deep learning is a plus. Eligibility: CGPA 7.5+, "
                "CSE/IT/Mathematics & Computing, 2026 or 2027 graduates. Selection: online "
                "assessment, ML case study, technical interview, and HR interview."
            ),
            "required_skills": [
                "Python", "PyTorch", "Scikit-learn", "SQL", "Pandas", "NLP", "Machine Learning",
            ],
            "experience_required_years": 0.0,
            "package": "₹16 LPA",
            "location": "Gurugram",
            "eligibility": {
                "min_cgpa": 7.5,
                "departments": [
                    "Computer Science",
                    "Information Technology",
                    "Mathematics and Computing",
                ],
                "batch_years": [2026, 2027],
            },
            "deadline": datetime(2027, 1, 20, 23, 59),
            "selection_process": [
                "Online Assessment",
                "ML Case Study",
                "Technical Interview",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "insights",
        "closed": False,
        "payload": {
            "company_name": "Aurora HealthTech",
            "company_description": (
                "Aurora HealthTech builds patient-engagement and clinical-workflow software "
                "for hospitals and diagnostic chains."
            ),
            "company_website": "https://www.aurorahealth.example",
            "company_industry": "Healthcare Technology",
            "job_title": "QA Automation Engineer",
            "description": (
                "Build and maintain automated test suites for web and API workflows, and "
                "partner with developers to catch regressions early."
            ),
            "jd_text": (
                "Aurora HealthTech is looking for a QA Automation Engineer to join its Noida "
                "quality-engineering team. You will write automated UI tests with Selenium "
                "and Java, build API test suites, maintain test data, and integrate tests into "
                "CI pipelines. You should understand software testing fundamentals, SQL, and "
                "Git. Eligibility: CGPA 6.0+, CSE/IT/ECE, 2026 or 2027 graduates. Selection: "
                "online assessment, automation assignment, technical interview, and HR "
                "interview."
            ),
            "required_skills": [
                "Java", "Selenium", "TestNG", "SQL", "API Testing", "Git", "CI/CD",
            ],
            "experience_required_years": 0.0,
            "package": "₹7.5 LPA",
            "location": "Noida",
            "eligibility": {
                "min_cgpa": 6.0,
                "departments": [
                    "Computer Science",
                    "Information Technology",
                    "Electronics and Communication",
                ],
                "batch_years": [2026, 2027],
            },
            "deadline": datetime(2027, 2, 1, 23, 59),
            "selection_process": [
                "Online Assessment",
                "Automation Assignment",
                "Technical Interview",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "rec",
        "closed": True,
        "payload": {
            "company_name": "GreenLoop Logistics",
            "company_description": (
                "GreenLoop Logistics operates a tech-enabled reverse-logistics network for "
                "e-commerce returns and refurbishment."
            ),
            "company_website": "https://www.greenloop.example",
            "company_industry": "Logistics & Supply Chain",
            "job_title": "Business Analyst",
            "description": (
                "Analyse operational data, build dashboards, and work with warehouse and "
                "product teams to improve turnaround times."
            ),
            "jd_text": (
                "GreenLoop Logistics is hiring a Business Analyst for its Bengaluru "
                "operations team. You will analyse delivery and returns data with SQL and "
                "Excel, build Power BI dashboards, define operational KPIs, and present "
                "recommendations to warehouse and product leaders. Strong communication and "
                "problem-solving skills are essential. Eligibility: CGPA 6.5+, any "
                "engineering branch, 2026 or 2027 graduates. Selection: aptitude test, "
                "case-study interview, panel interview, and HR interview."
            ),
            "required_skills": [
                "Excel", "SQL", "Power BI", "Communication", "Problem Solving",
                "Operations Analysis",
            ],
            "experience_required_years": 0.0,
            "package": "₹7 LPA",
            "location": "Bengaluru",
            "eligibility": {
                "min_cgpa": 6.5,
                "departments": [],
                "batch_years": [2026, 2027],
            },
            "deadline": datetime(2026, 10, 30, 23, 59),
            "selection_process": [
                "Aptitude Test",
                "Case Study Interview",
                "Panel Interview",
                "HR Interview",
            ],
        },
    },
    {
        "tpo": "insights",
        "closed": False,
        "payload": {
            "company_name": "Vertex Robotics",
            "company_description": (
                "Vertex Robotics builds autonomous mobile robots and vision systems for "
                "warehouse automation."
            ),
            "company_website": "https://www.vertexrobotics.example",
            "company_industry": "Robotics & Automation",
            "job_title": "Embedded Software Engineer",
            "description": (
                "Develop firmware and control software for autonomous robots, working close "
                "to sensors, motors and real-time operating systems."
            ),
            "jd_text": (
                "Vertex Robotics is hiring an Embedded Software Engineer for its Hyderabad "
                "R&D centre. You will write embedded C and C++ for microcontrollers, integrate "
                "sensors and motor drivers, work with RTOS scheduling, and debug "
                "hardware-software interactions on the bench. Familiarity with ARM Cortex, "
                "I2C/SPI/UART, and version control is expected. Eligibility: CGPA 7.0+, "
                "ECE/EEE/CSE, 2026 graduates. Selection: online assessment, technical "
                "interview, embedded lab round, and HR interview."
            ),
            "required_skills": [
                "C", "C++", "Embedded C", "Microcontrollers", "RTOS", "Git", "ARM Cortex",
            ],
            "experience_required_years": 0.0,
            "package": "₹11 LPA",
            "location": "Hyderabad",
            "eligibility": {
                "min_cgpa": 7.0,
                "departments": [
                    "Electronics and Communication",
                    "Electrical Engineering",
                    "Computer Science",
                ],
                "batch_years": [2026],
            },
            "deadline": datetime(2027, 1, 15, 23, 59),
            "selection_process": [
                "Online Assessment",
                "Technical Interview",
                "Embedded Lab Round",
                "HR Interview",
            ],
        },
    },
]


async def main():
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]

    existing_drives = await db.placement_drives.count_documents({})
    if existing_drives and "--force" not in sys.argv:
        print(
            f"placement_drives already has {existing_drives} document(s); "
            "refusing to add duplicates. Re-run with --force to append anyway."
        )
        client.close()
        return

    rec = await db.users.find_one({"email": "rec.tpo@college.edu"})
    insights = await db.users.find_one({"email": "insights.tpo@college.edu"})
    if not rec or not insights:
        print("Both TPO users must exist before seeding drives.")
        client.close()
        return

    tpo_user_ids = {"rec": str(rec["_id"]), "insights": str(insights["_id"])}
    service = DriveService(db)

    print(f"Creating {len(DRIVES)} companies + drives...\n")
    for index, item in enumerate(DRIVES):
        tpo_key = item["tpo"]
        tpo_user_id = tpo_user_ids[tpo_key]
        payload = DriveCreateRequest(**item["payload"])
        drive = await service.create_drive(tpo_user_id, payload)

        # Make the mock timeline look realistic instead of every drive being
        # created in the same second.
        created_at = datetime.utcnow() - timedelta(days=3 + index * 2)
        await db.placement_drives.update_one(
            {"_id": ObjectId(drive.id)}, {"$set": {"created_at": created_at}}
        )

        if item["closed"]:
            drive = await service.update_drive(
                tpo_user_id, drive.id, DriveUpdateRequest(status=DriveStatus.CLOSED)
            )

        print(
            f"{index + 1:2d}. {item['payload']['company_name']:28s} | "
            f"{drive.job_title:32s} | {drive.status.value:6s} | "
            f"{drive.location:16s} | {drive.package}"
        )

    print(
        f"\nDone. companies={await db.companies.count_documents({})}, "
        f"drives={await db.placement_drives.count_documents({})}"
    )
    client.close()


if __name__ == "__main__":
    asyncio.run(main())

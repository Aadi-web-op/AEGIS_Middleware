"""Kestrel Freight & Logistics Pvt. Ltd. -- the dry-run company knowledge base.

A fictional mid-size Indian logistics company (about 1,400 employees,
22 branches, HQ in Pune). Its internal assistant, "Kestrel Assist", answers
HR, Finance, IT and customer-support questions from these documents. AEGIS
sits between that assistant and the person asking.

Every document is generated as a PDF by build_pdfs.py. `preload=True`
documents are ingested when the dry run starts; the rest are uploaded by the
evaluator during the walkthrough.

The set deliberately contains the mess real companies have:
  * a policy replaced by a newer version of the same source (leave policy,
    rate card) -> SUPERSEDES in the graph;
  * an amendment circular that changes numbers in another document
    (finance circular vs travel policy) -> CONFLICTS_WITH across sources;
  * a handbook nobody updated, still quoting the old leave figure;
  * common questions no document answers (referral bonus, gratuity,
    night-shift allowance) -> knowledge gaps.
"""

from __future__ import annotations

COMPANY = "Kestrel Freight & Logistics Pvt. Ltd."

DOCS = [
    # ------------------------------------------------------------------ HR
    {
        "key": "leave_2024",
        "file": "HR_Leave_Policy_2024.pdf",
        "source": "leave_policy.pdf",
        "version": "2024",
        "date": "2024-03-01",
        "dept": "People & Culture (HR)",
        "title": "Leave Policy",
        "doc_no": "HR/2024/11",
        "preload": True,
        "sections": [
            ("1. Scope", [
                "This policy applies to all permanent employees of Kestrel Freight & Logistics "
                "Pvt. Ltd. at the corporate office, branches and warehouses. Contract staff are "
                "governed by their agency agreements.",
            ]),
            ("2. Leave entitlements", [
                "Employees are entitled to 18 days of casual leave per calendar year.",
                "Unused casual leave may be carried forward for up to 6 months into the next year.",
                "Employees earn 15 days of earned leave per year, credited monthly.",
                "Employees are entitled to 8 days of sick leave per year. Sick leave of more than "
                "2 consecutive days requires a medical certificate.",
            ]),
            ("3. Parental leave", [
                "Female employees are entitled to 26 weeks of paid maternity leave as per the "
                "Maternity Benefit Act.",
                "Male employees are entitled to 5 days of paternity leave, to be taken within "
                "3 months of the birth or adoption of a child.",
            ]),
            ("4. Applying for leave", [
                "Leave must be applied for on the PeopleDesk HRMS at least 3 working days in "
                "advance, except for sick leave and emergencies.",
                "Probation lasts three months from the date of joining.",
            ]),
        ],
    },
    {
        "key": "leave_2026",
        "file": "HR_Leave_Policy_2026_NEW.pdf",
        "source": "leave_policy.pdf",
        "version": "2026",
        "date": "2026-11-02",
        "dept": "People & Culture (HR)",
        "title": "Leave Policy (Revised)",
        "doc_no": "HR/2026/09",
        "supersedes": "HR/2024/11",
        "preload": False,  # the evaluator uploads this one live
        "sections": [
            ("1. Scope and effective date", [
                "This revised policy is effective from 2 November 2026 and supersedes circular "
                "HR/2024/11. It applies to all permanent employees.",
            ]),
            ("2. Leave entitlements", [
                "Employees are entitled to 12 days of casual leave per calendar year.",
                "Carry-forward of casual leave is no longer permitted. Unused casual leave lapses "
                "on 31 December.",
                "Employees earn 18 days of earned leave per year, credited monthly.",
                "Employees are entitled to 10 days of sick leave per year. Sick leave of more than "
                "2 consecutive days requires a medical certificate.",
            ]),
            ("3. Parental leave", [
                "Female employees are entitled to 26 weeks of paid maternity leave as per the "
                "Maternity Benefit Act.",
                "Male employees are entitled to 10 days of paternity leave, to be taken within "
                "6 months of the birth or adoption of a child.",
            ]),
            ("4. Applying for leave", [
                "Leave must be applied for on the PeopleDesk HRMS at least 5 working days in "
                "advance, except for sick leave and emergencies.",
            ]),
        ],
    },
    {
        "key": "handbook",
        "file": "HR_Employee_Handbook_2025.pdf",
        "source": "employee_handbook.pdf",
        "version": "2025.1",
        "date": "2025-06-01",
        "dept": "People & Culture (HR)",
        "title": "Employee Handbook",
        "doc_no": "HR/HB/2025",
        "preload": True,
        "sections": [
            ("1. Working hours", [
                "Standard office hours are 9:30 AM to 6:30 PM, Monday to Friday. Warehouse and "
                "operations staff follow the shift roster published by their branch manager.",
            ]),
            ("2. Probation and notice period", [
                "New employees serve a probation period of 6 months from the date of joining.",
                "The notice period is 60 days for confirmed employees and 30 days during probation.",
            ]),
            ("3. Leave at a glance", [
                "Employees get 18 days of casual leave every year, in addition to earned leave and "
                "sick leave. See the Leave Policy for details.",
            ]),
            ("4. Dress code", [
                "Business casual is expected from Monday to Thursday. Fridays are casual dress days. "
                "Safety shoes and high-visibility vests are mandatory on warehouse floors.",
            ]),
            ("5. Grievances and POSH", [
                "Workplace harassment complaints can be raised with the Internal Committee at "
                "ic@kestrel.example. Complaints are acknowledged within 2 working days.",
            ]),
        ],
    },
    {
        "key": "wfh",
        "file": "HR_Work_From_Home_Policy.pdf",
        "source": "wfh_policy.pdf",
        "version": "1.2",
        "date": "2025-01-15",
        "dept": "People & Culture (HR)",
        "title": "Hybrid Work and Work From Home Policy",
        "doc_no": "HR/2025/02",
        "preload": True,
        "sections": [
            ("1. Eligibility", [
                "Corporate office employees may work from home for up to 2 days per week with "
                "approval from their reporting manager.",
                "Work from home is not available to warehouse, fleet and branch operations roles, "
                "or to employees in their first 3 months of service.",
            ]),
            ("2. Expectations", [
                "Employees working from home must be reachable on Microsoft Teams between 10:00 AM "
                "and 5:00 PM and must use the company VPN for all work systems.",
            ]),
            ("3. Reimbursement", [
                "Eligible employees receive an internet reimbursement of Rs 1,000 per month, "
                "claimed through ExpenseHub.",
            ]),
        ],
    },
    {
        "key": "benefits",
        "file": "HR_Benefits_and_Insurance_2026.pdf",
        "source": "benefits_insurance.pdf",
        "version": "2026",
        "date": "2026-04-01",
        "dept": "People & Culture (HR)",
        "title": "Employee Benefits and Group Health Insurance 2026-27",
        "doc_no": "HR/BEN/2026",
        "preload": True,
        "sections": [
            ("1. Group medical cover", [
                "All permanent employees are covered under a group medical policy with a family "
                "floater sum insured of Rs 5 lakh per year.",
                "The policy covers the employee, spouse and up to 2 children. Parents can be added "
                "through an optional top-up, with the premium deducted from salary.",
                "Maternity expenses are covered up to Rs 75,000 per delivery.",
            ]),
            ("2. Claims", [
                "Cashless hospitalisation is available at network hospitals through CareLink TPA. "
                "Reimbursement claims must be filed within 30 days of discharge.",
            ]),
            ("3. Wellness", [
                "Employees aged 35 and above are eligible for one free annual health check-up.",
            ]),
        ],
    },
    # ------------------------------------------------------------- Finance
    {
        "key": "travel",
        "file": "FIN_Travel_and_Expense_Policy_v3.pdf",
        "source": "travel_expense_policy.pdf",
        "version": "3.0",
        "date": "2025-07-01",
        "dept": "Finance",
        "title": "Travel and Expense Policy",
        "doc_no": "FIN/POL/03",
        "preload": True,
        "sections": [
            ("1. Mode of travel", [
                "Economy class air travel is allowed for journeys over 500 km. Shorter journeys "
                "must use AC 2-tier rail or a company-approved cab.",
            ]),
            ("2. Hotel and daily allowance", [
                "The hotel limit is Rs 6,000 per night in metro cities and Rs 4,000 per night in "
                "other cities.",
                "The daily allowance is Rs 1,200 per day in metro cities and Rs 800 per day "
                "elsewhere.",
            ]),
            ("3. Claims", [
                "Expense claims must be submitted on ExpenseHub within 30 days of the end of the trip.",
                "Original receipts are required for every expense above Rs 500.",
                "A travel advance of up to Rs 20,000 can be requested with manager approval.",
            ]),
        ],
    },
    {
        "key": "fin_circular",
        "file": "FIN_Circular_2026_07_Travel_Amendment.pdf",
        "source": "finance_circular_fin_2026_07.pdf",
        "version": "FIN/2026/07",
        "date": "2026-10-15",
        "dept": "Finance",
        "title": "Circular: Amendment to Travel and Expense Limits",
        "doc_no": "FIN/2026/07",
        "preload": True,
        "sections": [
            ("Amendment", [
                "With effect from 15 October 2026, the hotel limit in metro cities is revised to "
                "Rs 7,500 per night. The limit for other cities is unchanged.",
                "Expense claims must now be submitted within 15 days of the end of the trip. Claims "
                "submitted later require CFO approval.",
                "All other provisions of the Travel and Expense Policy remain unchanged.",
            ]),
        ],
    },
    # ------------------------------------------------------------------ IT
    {
        "key": "it_security",
        "file": "IT_Information_Security_Policy.pdf",
        "source": "it_security_policy.pdf",
        "version": "4.1",
        "date": "2025-10-01",
        "dept": "Information Technology",
        "title": "Information Security and Acceptable Use Policy",
        "doc_no": "IT/SEC/04",
        "preload": True,
        "sections": [
            ("1. Passwords and authentication", [
                "Passwords must be at least 12 characters long and must be changed every 90 days.",
                "Multi-factor authentication is mandatory for email, VPN and the ERP system.",
            ]),
            ("2. Devices and data", [
                "USB storage devices are blocked on all company laptops. Exceptions need written "
                "approval from the IT Security team.",
                "Personal phones may access company email only after enrolling in DeviceGuard "
                "mobile device management.",
                "All company laptops are encrypted with BitLocker.",
            ]),
            ("3. Incident reporting", [
                "Suspected phishing emails must be reported to security@kestrel.example within "
                "1 hour, using the Report Phish button in Outlook.",
            ]),
        ],
    },
    {
        "key": "it_catalog",
        "file": "IT_Service_Catalogue_2026.pdf",
        "source": "it_service_catalogue.pdf",
        "version": "2026.2",
        "date": "2026-08-10",
        "dept": "Information Technology",
        "title": "IT Service Catalogue and Support SLAs",
        "doc_no": "IT/SVC/2026",
        "preload": True,
        "sections": [
            ("1. Requests", [
                "New laptops, software and access requests are raised on the ServiceDesk portal "
                "and need reporting manager approval.",
                "Company laptops are refreshed every 4 years.",
                "Forgotten passwords can be reset on the self-service portal at reset.kestrel.example.",
            ]),
            ("2. Support SLAs", [
                "Priority 1 incidents, such as a site-wide outage, get a response within 30 minutes "
                "and a resolution target of 4 hours.",
                "Priority 2 incidents get a response within 4 hours and a resolution target of "
                "1 business day.",
            ]),
        ],
    },
    # ------------------------------------------------- Customer operations
    {
        "key": "sla",
        "file": "OPS_Customer_Service_Level_Agreement_2026.pdf",
        "source": "customer_sla.pdf",
        "version": "2026",
        "date": "2026-01-01",
        "dept": "Customer Operations",
        "title": "Standard Customer Service Level Agreement",
        "doc_no": "OPS/SLA/2026",
        "preload": True,
        "sections": [
            ("1. Delivery performance", [
                "Kestrel targets on-time delivery for 95% of consignments each month.",
            ]),
            ("2. Damage and loss claims", [
                "Damage claims must be raised within 7 days of delivery, with photographs of the "
                "package and the proof of delivery.",
                "Approved claims are settled by credit note or refund within 14 business days of "
                "approval.",
                "Kestrel's liability is capped at Rs 50,000 per consignment unless the customer has "
                "bought transit insurance.",
                "Transit insurance costs 0.3% of the declared value of the goods.",
            ]),
        ],
    },
    {
        "key": "rates_q3",
        "file": "OPS_Rate_Card_Q3_2026.pdf",
        "source": "rate_card.pdf",
        "version": "Q3-2026",
        "date": "2026-07-01",
        "dept": "Customer Operations",
        "title": "Rate Card and Surcharges - Q3 2026",
        "doc_no": "OPS/RATE/Q3-26",
        "preload": True,
        "sections": [
            ("Surcharges", [
                "The fuel surcharge is 9% of the freight charge.",
                "Express delivery is charged at 35% above the standard freight rate.",
                "The cash-on-delivery fee is Rs 40 or 1.5% of the collected amount, whichever is higher.",
                "Deliveries to out-of-delivery-area pin codes carry a surcharge of Rs 750 per consignment.",
            ]),
        ],
    },
    {
        "key": "rates_q4",
        "file": "OPS_Rate_Card_Q4_2026.pdf",
        "source": "rate_card.pdf",
        "version": "Q4-2026",
        "date": "2026-10-01",
        "dept": "Customer Operations",
        "title": "Rate Card and Surcharges - Q4 2026",
        "doc_no": "OPS/RATE/Q4-26",
        "preload": True,
        "sections": [
            ("Surcharges", [
                "The fuel surcharge is 12% of the freight charge.",
                "Express delivery is charged at 40% above the standard freight rate.",
                "The cash-on-delivery fee is Rs 45 or 2% of the collected amount, whichever is higher.",
                "Deliveries to out-of-delivery-area pin codes carry a surcharge of Rs 850 per consignment.",
            ]),
        ],
    },
    {
        "key": "privacy",
        "file": "LEGAL_Data_Privacy_Policy.pdf",
        "source": "data_privacy_policy.pdf",
        "version": "2.0",
        "date": "2025-11-01",
        "dept": "Legal & Compliance",
        "title": "Data Privacy and Retention Policy",
        "doc_no": "LEG/PRIV/02",
        "preload": True,
        "sections": [
            ("1. Retention", [
                "Shipment and billing records are retained for 8 years.",
                "Warehouse CCTV footage is retained for 90 days and then deleted.",
            ]),
            ("2. Customer rights", [
                "Customer requests to access or delete personal data are answered within 30 days, "
                "in line with the Digital Personal Data Protection Act, 2023.",
                "Customer phone numbers may be shared only with the delivery partner handling that "
                "consignment.",
            ]),
        ],
    },
]

BY_KEY = {d["key"]: d for d in DOCS}


def doc_text_lines(doc: dict) -> list[str]:
    """Every sentence-level paragraph of a document, for passage checks."""
    return [p for _, paras in doc["sections"] for p in paras]

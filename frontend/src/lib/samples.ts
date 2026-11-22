/**
 * Fictional Kestrel Freight & Logistics policies (scenarios/kestrel). Served from
 * public/samples so anyone can try ingest, evaluation and change detection without
 * their own documents. source/version/date match scenarios/kestrel/corpus.py.
 */
export interface SampleDocument {
  file: string;
  title: string;
  department: string;
  source: string;
  version: string;
  date: string;
  note?: string;
}

export const SAMPLE_DOCUMENTS: SampleDocument[] = [
  {
    file: "HR_Leave_Policy_2024.pdf",
    title: "Leave Policy",
    department: "HR",
    source: "leave_policy.pdf",
    version: "2024",
    date: "2024-03-01",
    note: "Step 1 of the change demo",
  },
  {
    file: "HR_Leave_Policy_2026_NEW.pdf",
    title: "Leave Policy, revised",
    department: "HR",
    source: "leave_policy.pdf",
    version: "2026",
    date: "2026-11-02",
    note: "Step 3: supersedes 2024",
  },
  {
    file: "HR_Employee_Handbook_2025.pdf",
    title: "Employee Handbook",
    department: "HR",
    source: "employee_handbook.pdf",
    version: "2025.1",
    date: "2025-06-01",
    note: "Outdated leave figure",
  },
  {
    file: "HR_Work_From_Home_Policy.pdf",
    title: "Hybrid Work / WFH Policy",
    department: "HR",
    source: "wfh_policy.pdf",
    version: "1.2",
    date: "2025-01-15",
  },
  {
    file: "HR_Benefits_and_Insurance_2026.pdf",
    title: "Benefits & Group Health Insurance",
    department: "HR",
    source: "benefits_insurance.pdf",
    version: "2026",
    date: "2026-04-01",
  },
  {
    file: "FIN_Travel_and_Expense_Policy_v3.pdf",
    title: "Travel & Expense Policy",
    department: "Finance",
    source: "travel_expense_policy.pdf",
    version: "3.0",
    date: "2025-07-01",
  },
  {
    file: "FIN_Circular_2026_07_Travel_Amendment.pdf",
    title: "Circular FIN/2026/07",
    department: "Finance",
    source: "finance_circular_fin_2026_07.pdf",
    version: "FIN/2026/07",
    date: "2026-10-15",
    note: "Conflicts with travel policy",
  },
  {
    file: "IT_Information_Security_Policy.pdf",
    title: "Information Security Policy",
    department: "IT",
    source: "it_security_policy.pdf",
    version: "4.1",
    date: "2025-10-01",
  },
  {
    file: "IT_Service_Catalogue_2026.pdf",
    title: "IT Service Catalogue & SLAs",
    department: "IT",
    source: "it_service_catalogue.pdf",
    version: "2026.2",
    date: "2026-08-10",
  },
  {
    file: "OPS_Customer_Service_Level_Agreement_2026.pdf",
    title: "Customer SLA",
    department: "Customer Ops",
    source: "customer_sla.pdf",
    version: "2026",
    date: "2026-01-01",
  },
  {
    file: "OPS_Rate_Card_Q3_2026.pdf",
    title: "Rate Card Q3 2026",
    department: "Customer Ops",
    source: "rate_card.pdf",
    version: "Q3-2026",
    date: "2026-07-01",
  },
  {
    file: "OPS_Rate_Card_Q4_2026.pdf",
    title: "Rate Card Q4 2026",
    department: "Customer Ops",
    source: "rate_card.pdf",
    version: "Q4-2026",
    date: "2026-10-01",
    note: "Replaces Q3",
  },
  {
    file: "LEGAL_Data_Privacy_Policy.pdf",
    title: "Data Privacy & Retention Policy",
    department: "Legal",
    source: "data_privacy_policy.pdf",
    version: "2.0",
    date: "2025-11-01",
  },
];

export const sampleUrl = (doc: SampleDocument) => `/samples/${doc.file}`;

/** The sample whose file name matches an uploaded file, so its metadata can be pre-filled. */
export function findSample(fileName: string): SampleDocument | undefined {
  const name = fileName.toLowerCase();
  return SAMPLE_DOCUMENTS.find((doc) => doc.file.toLowerCase() === name);
}

import { useMutation } from "@tanstack/react-query";
import { Check, Download, FlaskConical, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useService } from "./service";
import { BlastRadius } from "./blast-radius";
import { uploadPdf, type IngestResult } from "./ingest";

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

async function ingestSample(base: string, doc: SampleDocument): Promise<IngestResult> {
  const response = await fetch(sampleUrl(doc));
  if (!response.ok) throw new Error(`Could not load the sample file (${response.status}).`);
  return uploadPdf(base, await response.blob(), doc.source, doc.version, doc.date);
}

function SampleRow({ doc }: { doc: SampleDocument }) {
  const { base, connected, user } = useService();
  const mutation = useMutation({ mutationFn: () => ingestSample(base, doc) });
  const change = mutation.data?.change_detection;
  const canIngest = !user?.auth_enabled || user.role === "admin";
  return (
    <>
      <tr>
        <td>{doc.department}</td>
        <td>
          {doc.title}
          {doc.note && <div className="minor-label">{doc.note}</div>}
        </td>
        <td className="font-mono">{doc.version}</td>
        <td className="font-mono">{doc.date}</td>
        <td>
          <div className="flex gap-1 justify-end">
            <Button asChild size="sm" variant="ghost" title={`Download ${doc.file}`}>
              <a href={sampleUrl(doc)} download={doc.file}>
                <Download />
                <span className="sr-only">Download {doc.title}</span>
              </a>
            </Button>
            <Button
              size="sm"
              variant={mutation.isSuccess ? "secondary" : "outline"}
              disabled={!connected || !canIngest || mutation.isPending}
              title={canIngest ? "Ingest into AEGIS" : "Ingesting documents needs an admin account"}
              onClick={() => mutation.mutate()}
            >
              {mutation.isSuccess ? <Check /> : <Upload />}
              {mutation.isPending ? "Ingesting…" : mutation.isSuccess ? "Ingested" : "Ingest"}
            </Button>
          </div>
        </td>
      </tr>
      {(mutation.error || (change?.status === "ok" && change.changed)) && (
        <tr>
          <td colSpan={5} className="whitespace-normal">
            {mutation.error && (
              <p className="text-escalate text-xs" role="alert">
                {mutation.error.message}
              </p>
            )}
            {change?.status === "ok" && change.changed && (
              <BlastRadius
                title={`New version supersedes ${change.previous_version ? `v${change.previous_version}` : "the previous version"}`}
                newDocument={mutation.data?.document?.id ?? "new version"}
                oldDocument={change.previous_document_id ?? "previous version"}
                decisions={change.affected_decisions ?? []}
              />
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function SampleDocuments() {
  return (
    <details className="ingest-section" open>
      <summary>
        <FlaskConical size={13} className="inline mr-1" />
        Sample documents · try AEGIS without your own files
      </summary>
      <p className="section-description mt-3">
        13 policies from <strong>Kestrel Freight &amp; Logistics</strong>, a fictional company. They
        contain the problems real knowledge bases have: an outdated handbook, a circular that
        conflicts with a policy, and a rate card replaced mid-year. For the change-detection demo:
        ingest <em>Leave Policy 2024</em>, ask a leave question on Live Evaluation, then ingest{" "}
        <em>Leave Policy, revised</em> and see which past answers are affected.
      </p>
      <div className="table-scroll mt-3">
        <table>
          <thead>
            <tr>
              <th>Department</th>
              <th>Document</th>
              <th>Version</th>
              <th>Effective</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_DOCUMENTS.map((doc) => (
              <SampleRow key={doc.file} doc={doc} />
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

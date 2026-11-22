import { useMutation } from "@tanstack/react-query";
import { Check, Download, FlaskConical, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useService } from "./service";
import { BlastRadius } from "./blast-radius";
import { IngestStatus, uploadPdf, type IngestResult } from "./ingest";
import { SAMPLE_DOCUMENTS, sampleUrl, type SampleDocument } from "@/lib/samples";

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
      {(mutation.data || mutation.error) && (
        <tr>
          <td colSpan={5} className="whitespace-normal">
            {mutation.data && <IngestStatus result={mutation.data} />}
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

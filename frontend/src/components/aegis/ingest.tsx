import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus, Radar, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest, type AffectedDecision } from "@/lib/aegis-api";
import { useService } from "./service";
import { BlastRadius } from "./blast-radius";

interface ChangeDetection {
  status: string;
  changed?: boolean;
  previous_document_id?: string | null;
  previous_version?: string | null;
  affected_request_ids?: string[];
  affected_decisions?: AffectedDecision[];
}
interface IngestResult {
  chunks_added: number;
  document?: { id: string; source: string; version: string | null };
  change_detection?: ChangeDetection;
}
interface ImpactResult {
  source: string;
  version: string | null;
  doc_id: string | null;
  total_affected_decisions: number;
  decisions: AffectedDecision[];
}

async function uploadPdf(
  base: string,
  file: File,
  source: string,
  version: string,
  date: string,
): Promise<IngestResult> {
  const params = new URLSearchParams({ source });
  if (version) params.set("version", version);
  if (date) params.set("date", date);
  const response = await fetch(`${base}/v1/rag/ingest/upload?${params}`, {
    method: "POST",
    headers: { "Content-Type": "application/pdf" },
    body: file,
    signal: AbortSignal.timeout(120000),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : `AEGIS returned ${response.status}.`,
    );
  return data as IngestResult;
}

export function IngestDocument() {
  const { base, connected } = useService();
  const [mode, setMode] = useState<"upload" | "path">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [path, setPath] = useState("");
  const [source, setSource] = useState("");
  const [date, setDate] = useState("");
  const [version, setVersion] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      mode === "upload" && file
        ? uploadPdf(base, file, source.trim() || file.name, version.trim(), date)
        : apiRequest<IngestResult>(base, "/v1/rag/ingest", {
            pdf_path: path,
            source: source.trim() || null,
            date: date || null,
            version: version || null,
          }),
  });
  const change = mutation.data?.change_detection;
  const ready = mode === "upload" ? Boolean(file) : Boolean(path.trim());
  return (
    <details className="ingest-section" open>
      <summary>Ingest a document version · change detection</summary>
      <div className="flex gap-2 mt-3">
        <Button
          size="sm"
          variant={mode === "upload" ? "secondary" : "ghost"}
          onClick={() => setMode("upload")}
        >
          Upload PDF
        </Button>
        <Button
          size="sm"
          variant={mode === "path" ? "secondary" : "ghost"}
          onClick={() => setMode("path")}
        >
          Server path
        </Button>
      </div>
      <div className="ingest-fields">
        {mode === "upload" ? (
          <label>
            PDF file
            <Input
              type="file"
              accept="application/pdf,.pdf"
              onChange={(e) => {
                const picked = e.target.files?.[0] ?? null;
                setFile(picked);
                if (picked && !source) setSource(picked.name);
              }}
            />
          </label>
        ) : (
          <label>
            PDF path on the AEGIS server
            <Input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="data/policies/document.pdf"
            />
          </label>
        )}
        <label>
          Document name (source)
          <Input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="leave_policy.pdf"
          />
        </label>
        <label>
          Version
          <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="2025" />
        </label>
        <label>
          Effective date
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <Button
          size="sm"
          disabled={!connected || !ready || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mode === "upload" ? <Upload /> : <Plus />}
          {mutation.isPending ? "Ingesting…" : "Ingest & detect changes"}
        </Button>
      </div>
      {mutation.data && (
        <p className="text-answer text-xs mt-3" role="status">
          Document ingested: {mutation.data.chunks_added} chunks added
          {mutation.data.document?.version ? ` (version ${mutation.data.document.version})` : ""}.
        </p>
      )}
      {change && change.status !== "ok" && (
        <p className="minor-label mt-2">
          Change detection needs the Neo4j graph; it is not connected, so no blast radius was
          computed.
        </p>
      )}
      {change?.status === "ok" && !change.changed && (
        <p className="minor-label mt-2">
          No earlier version with different content was found, so no past decision is at risk.
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
      {mutation.error && (
        <p className="text-escalate text-xs mt-3" role="alert">
          {mutation.error.message}
        </p>
      )}
    </details>
  );
}

/** "If this document is wrong, which past decisions relied on it?" */
export function ImpactLookup() {
  const { base, connected } = useService();
  const [source, setSource] = useState("");
  const [version, setVersion] = useState("");
  const mutation = useMutation({
    mutationFn: () => {
      const params = new URLSearchParams({ source: source.trim() });
      if (version.trim()) params.set("version", version.trim());
      return apiRequest<ImpactResult>(base, `/v1/insights/impact?${params}`);
    },
  });
  return (
    <details className="ingest-section">
      <summary>Blast radius: which decisions rely on a document?</summary>
      <div className="ingest-fields">
        <label>
          Document name (source)
          <Input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="leave_policy.pdf"
          />
        </label>
        <label>
          Version (optional)
          <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="2024" />
        </label>
        <Button
          size="sm"
          disabled={!connected || !source.trim() || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          <Radar />
          {mutation.isPending ? "Tracing…" : "Show blast radius"}
        </Button>
      </div>
      {mutation.data &&
        (mutation.data.total_affected_decisions ? (
          <BlastRadius
            title={`${mutation.data.total_affected_decisions} decision(s) relied on ${mutation.data.source}`}
            oldDocument={mutation.data.doc_id ?? mutation.data.source}
            decisions={mutation.data.decisions}
          />
        ) : (
          <p className="minor-label mt-3">
            No recorded decision relied on this document (or the Neo4j graph is not connected).
          </p>
        ))}
      {mutation.error && (
        <p className="text-escalate text-xs mt-3" role="alert">
          {mutation.error.message}
        </p>
      )}
    </details>
  );
}

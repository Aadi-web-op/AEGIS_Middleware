import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/aegis-api";
import { useService } from "./service";
export function IngestDocument() {
  const { base, connected } = useService();
  const [path, setPath] = useState("");
  const [date, setDate] = useState("");
  const [version, setVersion] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      apiRequest<{ chunks_added: number }>(base, "/v1/rag/ingest", {
        pdf_path: path,
        date: date || null,
        version: version || null,
      }),
  });
  return (
    <details className="ingest-section">
      <summary>Ingest a knowledge base document</summary>
      <div className="ingest-fields">
        <label>
          PDF path on the AEGIS server
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="data/policies/document.pdf"
          />
        </label>
        <label>
          Effective date
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Version
          <Input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="Version"
          />
        </label>
        <Button
          size="sm"
          disabled={!connected || !path.trim() || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          <Plus />
          {mutation.isPending ? "Ingesting…" : "Ingest PDF"}
        </Button>
      </div>
      {mutation.data && (
        <p className="text-answer text-xs mt-3" role="status">
          Document ingested: {mutation.data.chunks_added} chunks added.
        </p>
      )}
      {mutation.error && (
        <p className="text-escalate text-xs mt-3" role="alert">
          {mutation.error.message}
        </p>
      )}
    </details>
  );
}

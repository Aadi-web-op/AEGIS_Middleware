import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  apiRequest,
  type EvaluationResult,
  type GraphStatus,
  type RecordData,
} from "@/lib/aegis-api";
interface ServiceState {
  base: string;
  setBase: (url: string) => void;
  health: RecordData | undefined;
  error: string;
  connected: boolean;
  checking: boolean;
  graph: GraphStatus | undefined;
  result: EvaluationResult | null;
  setResult: (result: EvaluationResult) => void;
}
const ServiceContext = createContext<ServiceState | null>(null);
export function ServiceProvider({ children }: { children: ReactNode }) {
  // VITE_AEGIS_API wins; in local dev fall back to the FastAPI default port.
  const [base, setBase] = useState<string>(
    import.meta.env["VITE_AEGIS_API"] ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : ""),
  );
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const query = useQuery({
    queryKey: ["aegis", base, "health"],
    queryFn: () => apiRequest<RecordData>(base, "/v1/health"),
    enabled: Boolean(base),
    retry: false,
    refetchInterval: 15000,
  });
  const graphQuery = useQuery({
    queryKey: ["aegis", base, "graph-status"],
    queryFn: () => apiRequest<GraphStatus>(base, "/v1/graph/status"),
    enabled: Boolean(base && query.data),
    retry: false,
    refetchInterval: 15000,
  });
  return (
    <ServiceContext.Provider
      value={{
        base,
        setBase,
        health: query.data,
        connected: Boolean(query.data && !query.error),
        checking: query.isFetching,
        error: query.error?.message ?? "",
        graph: graphQuery.error ? undefined : graphQuery.data,
        result,
        setResult,
      }}
    >
      {children}
    </ServiceContext.Provider>
  );
}
export function useService() {
  const context = useContext(ServiceContext);
  if (!context) throw new Error("AEGIS service context missing.");
  return context;
}
export function useRecords(path: string | null) {
  const { base } = useService();
  return useQuery({
    queryKey: ["aegis", base, path],
    queryFn: () => apiRequest<RecordData[]>(base, path ?? ""),
    enabled: Boolean(base && path),
    retry: false,
  });
}

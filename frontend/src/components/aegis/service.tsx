import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LoginScreen } from "./login";
import {
  AuthError,
  apiRequest,
  type AuthUser,
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
  user: AuthUser | undefined;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}
const ServiceContext = createContext<ServiceState | null>(null);
/**
 * Production builds call the API through this site's own /api proxy (see src/server.ts) so the
 * session cookie stays first-party. Local dev talks to VITE_AEGIS_API directly. Set
 * VITE_AEGIS_PROXY=0 to call the API directly in production too.
 */
export function defaultApiBase(): string {
  const configured = (import.meta.env["VITE_AEGIS_API"] ?? "").trim().replace(/\/+$/, "");
  if (import.meta.env.PROD && configured && import.meta.env["VITE_AEGIS_PROXY"] !== "0")
    return "/api";
  return configured || (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");
}
export function ServiceProvider({ children }: { children: ReactNode }) {
  const [base, setBase] = useState<string>(defaultApiBase);
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
  const queryClient = useQueryClient();
  const authQuery = useQuery({
    queryKey: ["aegis", base, "auth-me"],
    queryFn: () => apiRequest<AuthUser>(base, "/v1/auth/me"),
    enabled: Boolean(base && query.data),
    retry: false,
    refetchInterval: 60000,
  });
  const login = async (email: string, password: string) => {
    await apiRequest(base, "/v1/auth/login", { email, password });
    await queryClient.invalidateQueries({ queryKey: ["aegis"] });
  };
  const logout = async () => {
    await apiRequest(base, "/v1/auth/logout", {});
    // Drop cached data, then re-check the session: /v1/auth/me now answers 401,
    // which switches the console back to the sign-in screen.
    queryClient.removeQueries({
      queryKey: ["aegis"],
      predicate: (q) => !["health", "auth-me"].includes(String(q.queryKey[2])),
    });
    await queryClient.refetchQueries({ queryKey: ["aegis", base, "auth-me"] });
  };
  const connected = Boolean(query.data && !query.error);
  const signedOut = connected && authQuery.error instanceof AuthError;
  const checkingSession = connected && authQuery.isPending;
  return (
    <ServiceContext.Provider
      value={{
        base,
        setBase,
        health: query.data,
        connected,
        checking: query.isFetching,
        error: query.error?.message ?? "",
        graph: graphQuery.error ? undefined : graphQuery.data,
        result,
        setResult,
        user: authQuery.data,
        login,
        logout,
      }}
    >
      {signedOut ? (
        <LoginScreen />
      ) : checkingSession ? (
        <main className="login-shell">
          <p className="text-sm text-muted-foreground">Checking your session…</p>
        </main>
      ) : (
        children
      )}
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

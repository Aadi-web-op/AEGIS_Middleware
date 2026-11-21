import { useState, type FormEvent } from "react";
import { LockKeyhole, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useService } from "./service";

/** Sign-in gate. The session lives in an HttpOnly cookie set by the API. */
export function LoginScreen() {
  const { login, base } = useService();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email.trim(), password);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed.");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <form className="login-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="login-brand">
          <ShieldCheck size={22} aria-hidden />
          <div>
            <div className="brand-name">AEGIS</div>
            <div className="brand-caption">Trust Console</div>
          </div>
        </div>
        <h1 id="login-title" className="login-title">
          Sign in
        </h1>
        <label className="login-label" htmlFor="login-email">
          Email
        </label>
        <Input
          id="login-email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label className="login-label" htmlFor="login-password">
          Password
        </label>
        <Input
          id="login-password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy || !email || !password} className="w-full">
          <LockKeyhole />
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="login-foot">Connected to {base}</p>
      </form>
    </main>
  );
}

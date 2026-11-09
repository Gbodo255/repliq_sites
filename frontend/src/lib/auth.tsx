import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AuthConfig, User } from "@/types";

type Status = "loading" | "authed" | "anon";

interface AuthState {
  status: Status;
  user: User | null;
  config: AuthConfig | null;
  refresh: () => Promise<void>;
  devLogin: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
      setStatus("authed");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setUser(null);
        setStatus("anon");
      } else {
        // Network/other error: treat as anonymous so the landing still shows.
        setUser(null);
        setStatus("anon");
      }
    }
  }, []);

  useEffect(() => {
    api.authConfig().then(setConfig).catch(() => setConfig({ google: false, dev: false }));
    refresh();
  }, [refresh]);

  const devLogin = useCallback(async () => {
    const me = await api.devLogin();
    setUser(me);
    setStatus("authed");
  }, []);

  const logout = useCallback(async () => {
    await api.logout().catch(() => {});
    setUser(null);
    setStatus("anon");
  }, []);

  return (
    <AuthContext.Provider value={{ status, user, config, refresh, devLogin, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

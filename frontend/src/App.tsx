import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "@/components/Layout";
import Landing from "@/pages/Landing";
import Dashboard from "@/pages/Dashboard";
import NewReplication from "@/pages/NewReplication";
import ProjectDetail from "@/pages/ProjectDetail";
import { useAuth } from "@/lib/auth";
import Logo from "@/components/Logo";

function Splash() {
  return (
    <div className="grid min-h-screen place-items-center bg-white">
      <div className="flex flex-col items-center gap-3">
        <Logo withWord={false} className="animate-pulse" />
        <span className="eyebrow">Chargement…</span>
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "loading") return <Splash />;
  if (status === "anon") return <Navigate to="/" replace />;
  return <Layout>{children}</Layout>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/app" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/app/new" element={<RequireAuth><NewReplication /></RequireAuth>} />
      <Route path="/app/projects/:id" element={<RequireAuth><ProjectDetail /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

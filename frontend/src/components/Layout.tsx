import { NavLink, useNavigate } from "react-router-dom";
import { Plus, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";
import Logo from "@/components/Logo";
import { useAuth } from "@/lib/auth";

const NAV = [
  { to: "/app", label: "Dashboard", end: true },
  { to: "/app/new", label: "Nouvelle réplication", end: false },
];

function Avatar({ name, picture }: { name: string; picture: string }) {
  if (picture) {
    return <img src={picture} alt="" className="h-8 w-8 rounded-full border border-border" referrerPolicy="no-referrer" />;
  }
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return (
    <span className="grid h-8 w-8 place-items-center rounded-full bg-ink text-[13px] font-semibold text-white">
      {initial}
    </span>
  );
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const onLogout = async () => {
    await logout();
    navigate("/");
  };

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-40 border-b border-border bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-content items-center justify-between gap-4 px-4 md:px-8">
          <div className="flex items-center gap-6">
            <button onClick={() => navigate("/app")} aria-label="Accueil app"><Logo /></button>
            <nav className="hidden items-center gap-1 md:flex">
              {NAV.map(({ to, label, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cn(
                      "rounded-lg px-3 py-2 text-[14.5px] font-medium transition-colors",
                      isActive ? "bg-panel text-ink" : "text-muted hover:text-ink"
                    )
                  }
                >
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-2.5">
            <Button size="sm" onClick={() => navigate("/app/new")} className="hidden sm:inline-flex">
              <Plus className="h-4 w-4" /> Nouvelle
            </Button>
            {user && (
              <div className="flex items-center gap-2.5">
                <Avatar name={user.name} picture={user.picture} />
                <span className="hidden text-sm font-medium text-ink lg:block">{user.name}</span>
                <button
                  onClick={onLogout}
                  title="Se déconnecter"
                  className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-panel hover:text-ink"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        </div>
        {/* Mobile nav */}
        <div className="flex items-center gap-1 border-t border-border px-4 py-2 md:hidden">
          {NAV.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn("rounded-lg px-3 py-1.5 text-sm font-medium", isActive ? "bg-panel text-ink" : "text-muted")
              }
            >
              {label}
            </NavLink>
          ))}
        </div>
      </header>

      <main>
        <div className="mx-auto max-w-content px-4 py-8 md:px-8 md:py-10 animate-fade-in">{children}</div>
      </main>
    </div>
  );
}

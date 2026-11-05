import { NavLink, useNavigate } from "react-router-dom";
import { LayoutDashboard, Plus, Globe, Moon, Sun, Github } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/new", label: "New replication", icon: Plus, end: false },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const navigate = useNavigate();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="hidden md:flex w-64 flex-col border-r bg-card/50 backdrop-blur">
        <div className="flex items-center gap-2.5 px-5 h-16 border-b">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Globe className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <div className="font-bold">Replicator</div>
            <div className="text-xs text-muted-foreground">Website engine</div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t space-y-1">
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={() => setDark((d) => !d)}>
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {dark ? "Light mode" : "Dark mode"}
          </Button>
          <a
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary"
          >
            <Github className="h-4 w-4" />
            API docs
          </a>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="md:hidden flex items-center justify-between h-14 px-4 border-b">
          <button className="flex items-center gap-2 font-bold" onClick={() => navigate("/")}>
            <Globe className="h-5 w-5 text-primary" /> Replicator
          </button>
          <Button size="sm" onClick={() => navigate("/new")}>
            <Plus className="h-4 w-4" /> New
          </Button>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-4 md:px-8 py-6 md:py-8 animate-fade-in">{children}</div>
        </main>
      </div>
    </div>
  );
}

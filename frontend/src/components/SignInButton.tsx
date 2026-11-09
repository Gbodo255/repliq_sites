import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** Minimal four-colour Google "G" mark for the sign-in control. */
function GoogleMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" width="18" height="18">
      <path fill="#4285F4" d="M23.52 12.27c0-.82-.07-1.6-.2-2.36H12v4.47h6.47a5.53 5.53 0 0 1-2.4 3.63v3h3.88c2.27-2.09 3.57-5.17 3.57-8.74z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.96-1.08 7.95-2.9l-3.88-3c-1.08.72-2.46 1.15-4.07 1.15-3.13 0-5.78-2.11-6.73-4.96H1.26v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.27 14.29A7.2 7.2 0 0 1 4.89 12c0-.8.14-1.57.38-2.29v-3.1H1.26A12 12 0 0 0 0 12c0 1.94.46 3.77 1.26 5.39l4.01-3.1z" />
      <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.43-3.43C17.95 1.19 15.23 0 12 0A12 12 0 0 0 1.26 6.61l4.01 3.1C6.22 6.86 8.87 4.75 12 4.75z" />
    </svg>
  );
}

export default function SignInButton({
  className,
  label = "Se connecter avec Google",
  size = "md",
}: {
  className?: string;
  label?: string;
  size?: "sm" | "md" | "lg";
}) {
  const { config, devLogin } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  const sizeCls =
    size === "lg" ? "h-12 px-6 text-base" : size === "sm" ? "h-9 px-3.5 text-[13px]" : "h-11 px-5 text-[15px]";

  const google = config?.google;
  const dev = config?.dev;

  const onClick = async () => {
    if (google) {
      window.location.href = api.googleLoginUrl();
      return;
    }
    if (dev) {
      setBusy(true);
      try {
        await devLogin();
        navigate("/app");
      } finally {
        setBusy(false);
      }
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || (!google && !dev)}
      className={cn("btn btn-outline bg-white", sizeCls, className)}
      title={!google && !dev ? "Connexion non configurée" : undefined}
    >
      <GoogleMark className="shrink-0" />
      {busy ? "Connexion…" : google ? label : dev ? "Connexion (dev)" : "Connexion indisponible"}
    </button>
  );
}

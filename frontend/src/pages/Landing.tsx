import { useEffect } from "react";
import { Link } from "react-router-dom";
import {
  MonitorSmartphone,
  Layers,
  ShieldCheck,
  Boxes,
  Sparkles,
  Link2Off,
  ArrowRight,
  Gauge,
  Search,
  Download,
  CheckCircle2,
} from "lucide-react";
import Logo from "@/components/Logo";
import Reveal from "@/components/Reveal";
import HeroArt from "@/components/landing/HeroArt";
import SignInButton from "@/components/SignInButton";
import { useAuth } from "@/lib/auth";

const FRAMEWORKS = ["React", "Vue", "Next.js", "Angular", "WordPress", "Webflow", "Framer"];

const FEATURES = [
  { icon: MonitorSmartphone, title: "Le rendu réel", body: "Capturé après le JavaScript, pas le HTML brut. On copie ce que l'on voit." },
  { icon: Layers, title: "Multipage & responsive", body: "Toutes les pages, tous les écrans. Rien ne casse à la bascule mobile." },
  { icon: ShieldCheck, title: "Fidélité vérifiée", body: "La copie est comparée à l'original, puis corrigée. Un score par page." },
  { icon: Sparkles, title: "Animations rejouées", body: "Carrousels, menus, apparitions : recréés nativement, sans dépendance." },
  { icon: Boxes, title: "5 formats", body: "HTML, React, Next.js, WordPress. Une capture, cinq sorties." },
  { icon: Link2Off, title: "Zéro lien externe", body: "100 % local. Aucun tracker, aucune dépendance distante." },
];

const STEPS = [
  { icon: Search, k: "01", title: "Analyser", body: "Rendu Chromium, pages découvertes, styles et framework détectés." },
  { icon: Download, k: "02", title: "Reconstruire", body: "Ressources localisées, HTML autonome qui tourne hors-ligne." },
  { icon: CheckCircle2, k: "03", title: "Vérifier", body: "Comparaison visuelle à l'original, corrections en boucle." },
  { icon: Download, k: "04", title: "Exporter", body: "Le format voulu, prêt à ouvrir ou à déployer." },
];

const FORMATS = [
  ["HTML / CSS / JS", "Ouvrir index.html"],
  ["React (Vite)", "npm run dev"],
  ["Next.js (App Router)", "pré-rendu SSG"],
  ["Thème WordPress", "Apparence → Téléverser"],
  ["WordPress headless", "WP + front Next.js"],
];

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-white/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-content items-center justify-between px-4 md:px-8">
        <Link to="/"><Logo /></Link>
        <nav className="hidden items-center gap-8 text-[15px] text-muted md:flex">
          <a href="#features" className="hover:text-ink">Fonctionnalités</a>
          <a href="#how" className="hover:text-ink">Comment ça marche</a>
          <a href="#formats" className="hover:text-ink">Formats</a>
        </nav>
        <SignInButton size="sm" label="Se connecter" />
      </div>
    </header>
  );
}

export default function Landing() {
  const { status } = useAuth();

  // If a signed-in user lands here, nudge them toward the app.
  useEffect(() => {
    if (status === "authed") {
      // keep them on the landing but the nav/app link is available
    }
  }, [status]);

  return (
    <div className="min-h-screen bg-white">
      <Nav />

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 dot-grid opacity-60" style={{ maskImage: "radial-gradient(70% 60% at 50% 30%, #000, transparent)" }} />
        <div className="relative mx-auto grid max-w-content items-center gap-10 px-4 py-16 md:grid-cols-2 md:px-8 md:py-24">
          <div>
            <Reveal>
              <h1 className="font-display mt-5 text-[40px] leading-[1.04] tracking-tight text-ink md:text-[60px]">
                Répliquez n'importe quel site, <span className="text-faint">au pixel près.</span>
              </h1>
            </Reveal>
            <Reveal delay={120}>
              <p className="mt-5 max-w-xl text-[18px] leading-relaxed text-muted">
                Collez une URL. Repartez avec une copie <strong className="font-semibold text-ink">locale, fidèle
                et autonome</strong> — prête à ouvrir, hors-ligne. Vérifiée au pixel près.
              </p>
            </Reveal>
            <Reveal delay={180}>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <SignInButton size="lg" />
                <a href="#how" className="btn btn-primary h-12 px-6 text-base">
                  Comment ça marche <ArrowRight className="h-4 w-4" />
                </a>
              </div>
            </Reveal>
            <Reveal delay={240}>
              <p className="eyebrow mt-8 flex flex-wrap items-center gap-x-4 gap-y-1">
                {FRAMEWORKS.map((f) => (
                  <span key={f}>{f}</span>
                ))}
              </p>
            </Reveal>
          </div>
          <Reveal delay={120} className="mx-auto w-full max-w-[460px]">
            <HeroArt className="w-full" />
          </Reveal>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-t border-border bg-panel-2/40">
        <div className="mx-auto max-w-content px-4 py-20 md:px-8 md:py-28">
          <Reveal>
            <h2 className="font-display max-w-2xl text-[32px] leading-tight tracking-tight text-ink md:text-[44px]">
              Une copie fidèle. <span className="text-faint">Pas un à-peu-près.</span>
            </h2>
          </Reveal>
          <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={i * 50}>
                <div className="h-full rounded-2xl border border-border bg-white p-6 transition-shadow hover:shadow-[0_1px_0_0_var(--border-strong)]">
                  <div className="grid h-11 w-11 place-items-center rounded-xl bg-panel text-ink">
                    <f.icon className="h-5 w-5" />
                  </div>
                  <h3 className="mt-5 text-[17px] font-semibold tracking-tight text-ink">{f.title}</h3>
                  <p className="mt-2 text-[14.5px] leading-relaxed text-muted">{f.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="border-t border-border">
        <div className="mx-auto max-w-content px-4 py-20 md:px-8 md:py-28">
          <div className="grid gap-12 md:grid-cols-[0.9fr_1.1fr] md:items-start">
            <div>
              <Reveal>
                <h2 className="font-display text-[32px] leading-tight tracking-tight text-ink md:text-[44px]">
                  De l'URL à la copie <span className="text-faint">vérifiée.</span>
                </h2>
              </Reveal>
              <Reveal delay={120}>
                <p className="mt-5 max-w-md text-[16px] leading-relaxed text-muted">
                  De l'URL au ZIP, sans intervention. Tout se passe dans un vrai navigateur.
                </p>
              </Reveal>
            </div>
            <div className="space-y-3">
              {STEPS.map((s, i) => (
                <Reveal key={s.k} delay={i * 60}>
                  <div className="flex items-start gap-4 rounded-2xl border border-border bg-white p-5">
                    <span className="mono mt-0.5 text-[13px] font-semibold text-accent">{s.k}</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <s.icon className="h-4 w-4 text-ink" />
                        <h3 className="text-[16px] font-semibold text-ink">{s.title}</h3>
                      </div>
                      <p className="mt-1 text-[14.5px] leading-relaxed text-muted">{s.body}</p>
                    </div>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Formats */}
      <section id="formats" className="border-t border-border bg-ink text-white">
        <div className="mx-auto max-w-content px-4 py-20 md:px-8 md:py-28">
          <Reveal>
            <h2 className="font-display max-w-2xl text-[32px] leading-tight tracking-tight text-white md:text-[44px]">
Une capture. <span className="text-white/45">Cinq sorties.</span>
            </h2>
          </Reveal>
          <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10 sm:grid-cols-2 lg:grid-cols-5">
            {FORMATS.map(([name, hint], i) => (
              <Reveal key={name} delay={i * 50} className="bg-ink">
                <div className="h-full p-6">
                  <div className="mono text-[12px] text-white/40">{String(i + 1).padStart(2, "0")}</div>
                  <div className="mt-3 text-[16px] font-semibold text-white">{name}</div>
                  <div className="mono mt-2 text-[12px] text-accent">{hint}</div>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal delay={120}>
            <p className="mt-6 max-w-2xl text-[15px] leading-relaxed text-white/60">
              Toutes générées depuis la même copie vérifiée. Rendu identique au pixel près.
            </p>
          </Reveal>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border">
        <div className="mx-auto max-w-content px-4 py-20 md:px-8 md:py-28">
          <Reveal>
            <div className="relative overflow-hidden rounded-3xl border border-border bg-panel px-6 py-14 text-center md:px-16 md:py-20">
              <div className="pointer-events-none absolute inset-0 dot-grid opacity-60" style={{ maskImage: "radial-gradient(60% 80% at 50% 0%, #000, transparent)" }} />
              <div className="relative">
                <Gauge className="mx-auto h-7 w-7 text-accent" />
                <h2 className="font-display mx-auto mt-5 max-w-2xl text-[30px] leading-tight tracking-tight text-ink md:text-[42px]">
                  Prêt à répliquer votre premier site ?
                </h2>
                <p className="mx-auto mt-4 max-w-md text-[16px] text-muted">
                  Connectez-vous avec Google et lancez une réplication en quelques secondes.
                </p>
                <div className="mt-8 flex justify-center">
                  <SignInButton size="lg" />
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-content flex-col items-center justify-between gap-4 px-4 py-10 md:flex-row md:px-8">
          <Logo />
          <p className="text-[13px] text-faint">
            Pour répliquer des sites que vous possédez ou pour lesquels vous avez l'autorisation.
          </p>
        </div>
      </footer>
    </div>
  );
}

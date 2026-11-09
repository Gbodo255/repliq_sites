---
title: Replicator Tools
emoji: 🧬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Universal Website Replication Engine

Un moteur professionnel de **réplication de sites web**. Vous collez une URL,
l'application analyse le site réel dans un vrai navigateur, télécharge toutes
les ressources, reconstruit une copie **locale, autonome et multipage**, puis
**vérifie elle-même** le résultat par comparaison visuelle.

> Il ne s'agit pas d'un simple scraper HTML : chaque page est capturée depuis le
> **DOM rendu** (après exécution du JavaScript), ce qui permet de répliquer
> aussi les sites React / Vue / Next / Angular / WordPress / Webflow / Framer à
> partir de ce qu'ils affichent réellement.

---

## Sommaire

- [Aperçu](#aperçu)
- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Installation (Windows, une commande)](#installation-windows-une-commande)
- [Démarrage](#démarrage)
- [Utilisation](#utilisation)
  - [Interface web](#interface-web)
  - [Ligne de commande](#ligne-de-commande)
  - [API REST / WebSocket](#api-rest--websocket)
- [Configuration (`.env`)](#configuration-env)
- [Comment la fidélité est obtenue](#comment-la-fidélité-est-obtenue)
- [Structure d'un projet généré](#structure-dun-projet-généré)
- [Tests](#tests)
- [Sécurité](#sécurité)
- [Limitations (en toute transparence)](#limitations-en-toute-transparence)

---

## Aperçu

Chaîne de traitement entièrement automatique :

```
ANALYSER → EXPLORER → TÉLÉCHARGER → COMPRENDRE → RECONSTRUIRE → TESTER → COMPARER → CORRIGER → EXPORTER
```

- **Analyse intelligente** : DOM rendu, styles calculés, palette, polices,
  composants, détection du framework.
- **Exploration multipage** : liens internes + `sitemap.xml` + `robots.txt`,
  profondeur et périmètre configurables (même domaine uniquement).
- **Capture visuelle** : chargement complet, lazy-loading déclenché par
  défilement, captures d'écran desktop → petit mobile.
- **Téléchargement des ressources** : images (JPG/PNG/WebP/AVIF/SVG/GIF),
  `srcset`, images de fond CSS, polices (WOFF/WOFF2/TTF/OTF), CSS, vidéos,
  icônes — avec déduplication par hash et inventaire JSON.
- **Reconstruction** : HTML5 autonome, CSS d'origine conservé (fidélité
  maximale), chemins locaux relatifs, pages fonctionnant hors ligne.
- **Animations fidèles** : les apparitions au défilement sont capturées *par
  l'effet* (état initial → état révélé + transition réelle), indépendamment de
  la bibliothèque d'origine (AOS, WOW, GSAP/ScrollTrigger, Framer, observateur
  maison…) et rejouées nativement sur la copie ; les animations/keyframes CSS et
  les transitions `:hover` sont conservées et se rejouent telles quelles.
- **Comportement au défilement** : header collant/rétractable, nav « scrolled »,
  bouton retour-haut — les classes que le JavaScript ajoute au scroll sont
  capturées et rejouées (c'est le CSS d'origine qui style l'état).
- **Expérience utilisateur** : menus mobiles, accordéons, onglets, modales,
  **carrousels/sliders** (Swiper, Slick, Splide, Glide, Bootstrap, génériques —
  flèches, puces, boucle et défilement automatique), défilement fluide et
  formulaires, réimplémentés sans dépendance (`interactions.js`).
- **Responsive** : les media queries du site sont conservées telles quelles, et
  les classes posées par le JavaScript à chaque largeur d'écran sont rejouées.
  `prefers-reduced-motion` est respecté (animations désactivées).
- **Contrôle qualité automatique** : comparaison **SSIM** + différence pixel,
  images de diff, boucle *générer → comparer → corriger*.
- **Interface web** moderne (React + TypeScript + Tailwind) avec progression en
  temps réel, comparaison côte à côte / différence, et export ZIP.
- **Choix du rendu** : site répliqué en **HTML/CSS/JS**, **React (Vite)**,
  **Next.js**, **WordPress headless** (WordPress + Next.js), ou **thème
  WordPress** installable qui importe le contenu à l'activation.
- **Zéro lien externe** : chaque image, police, feuille de style et script est
  local ; les liens vers d'autres sites, iframes, trackers, polices distantes,
  balises canonical/preconnect, etc. sont neutralisés, puis un **audit**
  confirme qu'il ne reste aucune référence externe.

## Formats de sortie

| Format | Contenu de l'archive | Lancer |
|--------|----------------------|--------|
| HTML / CSS / JS | `index.html`, `pages/`, `assets/` | ouvrir `index.html` |
| React (Vite) | projet Vite, une page = un composant JSX, layout partagé | `npm install && npm run dev` |
| Next.js | App Router, pages pré-rendues (SSG), layout partagé | `npm install && npm run dev` |
| Thème WordPress | `<theme>.zip` à téléverser + `docker-compose.yml` de test | *Apparence → Thèmes → Téléverser* |
| WordPress headless | extension WordPress (`.zip`) + front-end Next.js + `docker-compose.yml` | `docker compose up -d` puis `npm run dev` |

- Tous les formats sont générés à partir de la copie statique **vérifiée** :
  même HTML, mêmes styles dans le même ordre, mêmes attributs `<html>`/`<body>`.
  Le rendu React / Next.js / WordPress est identique au pixel près à la copie
  HTML.
- **Thème WordPress** : à l'activation, il crée les pages répliquées (bloc *HTML
  personnalisé*, donc modifiables), importe les **articles, catégories, tags et
  images à la une** de la base WordPress source (quand le site d'origine est un
  WordPress), définit la page d'accueil et les permaliens. *Apparence →
  Replicator* permet de réimporter le contenu.
- **WordPress headless** : l'extension crée le même contenu et expose le HTML
  exact dans l'API REST (`rx_html`) ; le front-end Next.js l'affiche (ISR 60 s)
  et retombe sur le contenu embarqué si WordPress n'est pas joignable.
- Un format peut être ajouté après coup depuis la page du projet (bouton **+**)
  sans refaire la réplication.

## Architecture

```
Replicator/
├─ backend/                         FastAPI + Playwright (le moteur)
│  ├─ app/
│  │  ├─ config.py                  Configuration centrale (.env)
│  │  ├─ main.py                    Application FastAPI (API + sert le frontend)
│  │  ├─ api/                       Routes REST + WebSocket de progression
│  │  ├─ core/                      logging, sécurité (SSRF), utilitaires, bus d'événements
│  │  ├─ db/                        Index SQLite des projets
│  │  ├─ models/                    Schémas (pydantic) + objets du domaine
│  │  ├─ services/                  Orchestrateur de réplication + stockage projet
│  │  └─ modules/                   Le moteur, un module par responsabilité :
│  │     ├─ browser/                Rendu Playwright (DOM rendu, screenshots)
│  │     ├─ crawler/                Découverte des pages (liens, sitemap, robots)
│  │     ├─ analyzer/               Analyse DOM/CSS, palette, composants
│  │     ├─ asset_downloader/       Téléchargement + localisation des ressources
│  │     ├─ css_analyzer/           Extraction / réécriture des url() CSS
│  │     ├─ dom_parser/             Réécriture du HTML en version locale
│  │     ├─ page_builder/           Assemblage du site généré
│  │     ├─ interaction_analyzer/   interactions.js (menus, onglets, etc.)
│  │     ├─ responsive_analyzer/    Support responsive
│  │     ├─ visual_comparator/      SSIM + diff pixel
│  │     ├─ auto_fixer/             Correction automatique (re-liage d'assets)
│  │     └─ exporter/               Export ZIP
│  ├─ run.py                        Démarrage du serveur
│  └─ replicate_cli.py              Réplication en ligne de commande
├─ frontend/                        React + TypeScript + Tailwind (l'interface)
├─ projects/                        Projets générés + base SQLite (runtime)
├─ tests/                           Tests unitaires + intégration
├─ install.bat / start.bat / dev.bat
└─ README.md
```

## Déploiement en ligne (Docker / Hugging Face Spaces)

Le `Dockerfile` à la racine produit une image prête à l'emploi (interface +
API + Chromium) qui écoute sur le port `7860`.

```bash
docker build -t replicator .
docker run -p 7860:7860 -e APP_PASSWORD=motdepasse replicator
```

Sur **Hugging Face Spaces** (gratuit, 16 Go de RAM) : créer un Space de type
*Docker*, y pousser ce dépôt, et définir le secret `APP_PASSWORD` dans les
paramètres du Space. Sans `APP_PASSWORD`, l'instance est ouverte à tous.
Le stockage d'un Space gratuit est éphémère : téléchargez vos exports.

## Authentification Google (mise en ligne)

L'application est **protégée par une connexion Google** : la page d'accueil est
publique, mais il faut se connecter (ou créer son compte) avec Google pour
utiliser l'outil. Chaque utilisateur ne voit que **ses** réplications.

### 1. Créer un identifiant OAuth Google

1. Ouvrez [Google Cloud Console](https://console.cloud.google.com/) → créez (ou
   choisissez) un projet.
2. **APIs & Services → OAuth consent screen** : type « External », renseignez le
   nom de l'app et votre e-mail. Ajoutez les scopes `openid`, `email`, `profile`.
   Ajoutez votre adresse dans « Test users » tant que l'app est en test.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** :
   type **Web application**.
   - *Authorized JavaScript origins* : l'origine publique de l'app
     (ex. `https://votre-domaine`, et `http://localhost:5173` en dev).
   - *Authorized redirect URIs* : **exactement**
     `https://votre-domaine/api/auth/google/callback`
     (et `http://localhost:5173/api/auth/google/callback` en dev).
4. Copiez le **Client ID** et le **Client secret**.

### 2. Variables d'environnement

Dans `backend/.env` (ou les variables de l'hébergeur) :

| Variable | Rôle |
|----------|------|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Identifiants de l'OAuth client |
| `OAUTH_REDIRECT_URI` | Doit correspondre **au caractère près** à l'URI de redirection déclarée |
| `PUBLIC_BASE_URL` | Origine publique (sert à déduire l'URI de redirection si vide) |
| `SESSION_SECRET` | Secret de signature du cookie de session (valeur aléatoire longue en prod) |
| `COOKIE_SECURE` | `true` en production (cookie envoyé uniquement en HTTPS) |
| `SESSION_DAYS` | Durée de la session (jours, défaut 30) |
| `DEV_AUTH` | `true` en local pour tester **sans** Google (bouton « Connexion dev ») |

Générer un secret : `python -c "import secrets;print(secrets.token_urlsafe(48))"`.

### 3. Tester en local sans Google

```bat
cd backend
set DEV_AUTH=true
.venv\Scripts\python.exe run.py
```

La page d'accueil affiche un bouton **Connexion (dev)** qui ouvre l'application
avec un compte de test. Ne jamais activer `DEV_AUTH` en production.

## Prérequis

- **Windows 10/11**
- **Python 3.12 ou 3.14** (détecté automatiquement)
- **Node.js 18+** et **npm**

Playwright télécharge Chromium automatiquement lors de l'installation.

## Installation (Windows, une commande)

```bat
install.bat
```

Le script crée l'environnement virtuel Python, installe les dépendances
backend, installe Chromium, puis installe et compile le frontend.

## Démarrage

```bat
start.bat
```

Le serveur démarre sur `http://127.0.0.1:8000` et votre navigateur s'ouvre
automatiquement. (Au premier lancement, `start.bat` exécute `install.bat` si
nécessaire.)

Pour le **mode développement** (rechargement à chaud du frontend) :

```bat
dev.bat
```

API sur `:8000`, interface Vite sur `http://localhost:5173`.

## Utilisation

### Interface web

1. Ouvrez `http://127.0.0.1:8000`.
2. **New replication** → collez l'URL.
3. Choisissez le rendu : **Replicated site** (puis la stack : HTML/CSS/JS,
   React, Next.js ou WordPress headless) ou **WordPress template**.
4. Choisissez un mode : **Auto** (recommandé), **Full** (exploration profonde,
   tous les breakpoints, boucle qualité renforcée) ou **Single page**.
5. **Launch replication** et suivez la progression en direct.
6. Consultez le score de fidélité par page, la comparaison visuelle et
   l'aperçu, puis téléchargez chaque format. **Re-run** refait la réplication
   (rapide grâce au cache des ressources).

### Ligne de commande

Sans serveur, pour l'automatisation :

```bat
cd backend
.venv\Scripts\python.exe replicate_cli.py https://exemple.com --mode auto
```

Options : `--mode {auto,full,single_page}`, `--pages N`, `--depth N`,
`--fix-cycles N`, `--keep-js`, `--no-quality`, `--keep-external-links`,
`--output {static,react,nextjs,wordpress_theme,wordpress_headless}`
(répétable, ex. `--output nextjs --output wordpress_theme`).

### API REST / WebSocket

Documentation interactive : `http://127.0.0.1:8000/docs`.

| Méthode | Route | Rôle |
|--------|-------|------|
| `POST` | `/api/replicate` | Lance une réplication, renvoie un `project_id` |
| `GET`  | `/api/dashboard` | Statistiques globales |
| `GET`  | `/api/projects` | Liste des projets |
| `GET`  | `/api/projects/{id}` | Détail d'un projet |
| `POST` | `/api/projects/{id}/cancel` | Annule un job en cours |
| `DELETE` | `/api/projects/{id}` | Supprime un projet |
| `GET`  | `/api/projects/{id}/download?target=…` | Télécharge un format (`static`, `react`, `nextjs`, `wordpress_theme`, `wordpress_headless`) |
| `POST` | `/api/projects/{id}/outputs` | Génère des formats supplémentaires (`{"targets": [...]}`) |
| `POST` | `/api/projects/{id}/rerun` | Refait la réplication avec les mêmes options |
| `GET`  | `/api/targets` | Liste des formats disponibles |
| `GET`  | `/api/projects/{id}/site/...` | Sert la copie générée |
| `WS`   | `/ws/jobs/{id}` | Progression en temps réel |

## Configuration (`.env`)

Copiez `backend/.env.example` vers `backend/.env`. Toutes les valeurs ont des
valeurs par défaut sûres. Principales options :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `PORT` | `8000` | Port du serveur |
| `MAX_PAGES` | `40` | Nombre maximal de pages explorées |
| `MAX_DEPTH` | `2` | Profondeur d'exploration |
| `PAGE_CONCURRENCY` | `3` | Pages rendues en parallèle |
| `ASSET_CONCURRENCY` | `8` | Ressources téléchargées en parallèle |
| `MAX_ASSET_MB` | `25` | Taille maximale d'une ressource |
| `MAX_TOTAL_MB` | `600` | Budget total de téléchargement par projet |
| `NAV_TIMEOUT_MS` | `45000` | Timeout de navigation |
| `HEADFUL` | `false` | Afficher la fenêtre Chromium |
| `BLOCK_PRIVATE_HOSTS` | `true` | Protection SSRF (IP privées/metadata) |
| `BLOCK_TRACKERS` | `true` | Bloque analytics, pubs, bannières cookies et chats pendant la capture |
| `ASSET_CACHE_TTL_HOURS` | `168` | Durée du cache des ressources partagé entre projets (0 = désactivé) |

## Comment la fidélité est obtenue

- La page est **rendue dans Chromium** puis le DOM (`outerHTML`) est sérialisé
  **après exécution du JavaScript**. Les frameworks modernes sont donc
  reproduits à partir de ce qu'ils affichent, et non de leur code source.
- Le **CSS d'origine est conservé** et localisé (c'est plus fidèle que de
  régénérer le CSS à partir des styles calculés). Les styles injetés au runtime
  (styled-components, CSS-in-JS) sont capturés car présents dans le DOM rendu.
- Les ressources effectivement chargées sont découvertes via l'**API
  Performance** du navigateur (couvre lazy-loading, `srcset`, images de fond),
  complétées par une analyse statique du HTML et des fichiers CSS.
- Le JavaScript du framework est **retiré par défaut** (pour un instantané
  statique stable), et les interactions **et animations** courantes sont
  réimplémentées par `js/interactions.js`. Utilisez `--keep-js` pour conserver
  le JS d'origine.
- Les **animations au défilement** sont capturées par *effet*, et non par
  bibliothèque : avant tout défilement, l'état au repos (opacité / transform /
  visibilité) de chaque élément est mesuré ; après défilement complet (qui
  déclenche la logique de révélation d'origine), on relève ceux qui sont
  apparus. Chacun est marqué (`data-rx-reveal-i`) avec son état initial et sa
  transition réelle, puis rejoué par `interactions.js` via `IntersectionObserver`
  — quelle que soit la lib (AOS, WOW, GSAP, Framer, observateur maison…).
- Les **carrousels/sliders** sont redonnés vivants par un moteur sans dépendance
  (flèches, puces, boucle, défilement automatique, pause au survol).
- Les écrans de contrôle qualité **figent** les deux côtés de façon déterministe
  (`ReplicatorInteractions.freeze()` résout animations et carrousels), donc la
  comparaison SSIM n'est pas faussée par les animations ajoutées.
- Avant la sérialisation : règles CSS-in-JS injectées via `insertRule`,
  `adoptedStyleSheets` et Shadow DOM ouverts sont matérialisés ; l'état des
  formulaires et l'image réellement affichée par les `<img>` lazy sont figés ;
  les polices sont attendues (`document.fonts.ready`).
- Les **iframes et canvas** (cartes, vidéos, graphiques, widgets tiers) sont
  reproduits par une capture pixel-exacte de l'élément.
- Les **classes posées par le JavaScript selon la largeur d'écran** (menu
  mobile, header compact...) sont capturées à chaque breakpoint et rejouées.
- Le résultat est **vérifié** : la copie est rouverte dans Chromium aux mêmes
  dimensions (animations figées des deux côtés), comparée aux captures
  originales (SSIM + diff pixel). Le **correcteur de mise en page** compare
  l'état calculé (display, visibility, opacity, transform) de chaque élément
  entre l'original et la copie et restaure l'état d'origine par breakpoint ; la
  boucle *comparer → corriger* recommence jusqu'à stabilité.
- **Limitation de débit** : en cas de HTTP 429/503 (page ou ressources), la
  page est recapturée avec temporisation, puis une seconde chance est donnée
  après refroidissement ; une page d'erreur n'est jamais répliquée comme si
  c'était du contenu.

## Structure d'un projet généré

```
replicated-site/
├─ index.html
├─ pages/                 autres pages capturées (about.html, ...)
├─ assets/
│  ├─ images/  fonts/  icons/  videos/  css/  js/  other/
├─ css/responsive.css     (fallbacks non destructifs)
├─ js/interactions.js     (menus, onglets, accordéons, scroll...)
├─ data/
│  ├─ assets-manifest.json  (URL d'origine, chemin local, type, taille, hash...)
│  ├─ pages-manifest.json
│  ├─ analysis.json         (palette, polices, framework, composants...)
│  └─ quality-report.json   (score de fidélité par page, audit des liens externes)
└─ README.md
```

Ouvrez `index.html` dans n'importe quel navigateur : tout est local et relatif.

## Tests

```bat
cd backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

REM depuis la racine du dépôt :
backend\.venv\Scripts\python.exe -m pytest tests/unit

REM test d'intégration de bout en bout (nécessite Internet) :
set RUN_NETWORK_TESTS=1
backend\.venv\Scripts\python.exe -m pytest tests/integration
```

Couverture : sécurité/SSRF, utilitaires, CSS (extraction/réécriture), réécriture
HTML, crawler, comparateur SSIM, téléchargeur (avec recursion CSS + dédup),
export ZIP, nettoyage des références externes, correcteur de mise en page,
conversion HTML → JSX, génération des 5 formats (dont `php -l` du thème et de
l'extension WordPress), et pipeline complet.

## Sécurité

- **Protection SSRF** : les adresses privées, loopback, link-local et
  l'endpoint de métadonnées cloud (`169.254.169.254`) sont bloqués, à chaque
  requête et à chaque redirection (validées une par une).
- **Limites** : taille par fichier, budget total, nombre de pages, concurrence,
  timeouts, nettoyage des noms de fichiers, protection contre la traversée de
  chemins.
- Les **scripts téléchargés ne sont jamais exécutés** par le moteur, et aucune
  protection anti-automatisation, CAPTCHA, paywall ou authentification n'est
  contournée. Les éléments inaccessibles sont signalés, pas forcés.
- Cet outil est destiné à répliquer des sites que **vous possédez** ou pour
  lesquels vous disposez d'une autorisation.

## Limitations (en toute transparence)

- Les fonctionnalités nécessitant un **backend distant** (recherche, connexion,
  envoi réel de formulaires, personnalisation côté serveur) ne peuvent pas
  fonctionner hors ligne ; les formulaires conservent leur apparence et leur
  validation côté client mais l'envoi est désactivé.
- Le correcteur restaure l'état d'affichage calculé des éléments (contenu
  masqué/affiché par le JavaScript retiré) ; un écart d'une autre nature reste
  **signalé** par le score de fidélité de la page plutôt que masqué.
- Un site qui limite fortement le débit peut refuser certaines pages même après
  les nouvelles tentatives : elles sont listées comme ignorées, jamais
  remplacées par une page d'erreur.
- Les contenus derrière authentification, CAPTCHA ou paywall ne sont pas
  récupérés (aucun contournement).
- La fidélité est excellente sur les sites vitrines, institutionnels, landing
  pages, blogs et la plupart des sites applicatifs ; les applications très
  dynamiques dépendant fortement d'API restent, par nature, partiellement
  statiques une fois répliquées.

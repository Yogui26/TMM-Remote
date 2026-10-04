# TMM Remote

Télécommande web tactile (mobile / tablette) pour l'API HTTP de tinyMediaManager.
Une seule page HTML sans dépendance, installable comme une appli (PWA).

## Ce que fait l'appli

L'API HTTP de tinyMediaManager sert à **déclencher des actions** (scanner, scraper,
sous-titres, renommer…) sur des portées (nouveaux, tout, non scrapés, une source, un
dossier). Elle ne permet pas de lister ni d'éditer la bibliothèque : l'appli est donc une
télécommande, pas un navigateur de médiathèque.

- **Scénarios** : gros boutons (pipeline « nouveautés », sous-titres FR, images, notes, Kodi…)
  avec confirmation avant envoi.
- **Construire** : choisir action, portée et options, empiler plusieurs étapes dans une
  séquence envoyée en un seul appel (nécessaire pour que « Nouveaux » fonctionne).
- **Journal** : historique des envois, réponse brute de l'API, bouton « Rejouer ».
- **Réglages** : URL, clé API, langue des sous-titres, test de connexion.

## Déploiement (Docker, recommandé)

1. Dans tinyMediaManager, activez l'API HTTP et notez le port (7878 par défaut) et la clé.
2. Éditez `docker-compose.yml` : `TMM_HOST` (nom du conteneur : port), `TMM_API_KEY`, et le
   nom du réseau Docker partagé avec votre conteneur tinyMediaManager.
3. `docker compose up -d`, puis ouvrez `http://serveur:8080`.

Le proxy nginx ajoute la clé API côté serveur (elle n'arrive jamais dans le navigateur) et
évite les problèmes de CORS et de contenu mixte HTTP/HTTPS. Dans l'appli, laissez l'URL à `/api`.

## Sécurité

Quiconque atteint le port 8080 peut piloter tinyMediaManager. Ne l'exposez pas tel quel sur
Internet : gardez-le sur le réseau local, derrière un VPN (Tailscale, WireGuard), ou activez
`auth_basic` (lignes commentées dans `nginx/default.conf.template`) ou un reverse proxy avec
authentification.

## Sans proxy

Servez le dossier `app/` avec n'importe quel serveur statique, puis dans Réglages : URL
`http://serveur:7878/api` et clé API. Le navigateur doit être autorisé par CORS à appeler
l'API ; si ça échoue, utilisez le proxy.

## Installer sur l'écran d'accueil

iPhone / iPad : Partager → « Sur l'écran d'accueil ». Android : menu ⋮ → « Installer l'application ».

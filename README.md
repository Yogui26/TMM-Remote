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

L'image est publiée sur GitHub Container Registry (`linux/amd64`, `arm64`, `arm/v7`) :
`ghcr.io/yogui26/tmm-remote` (tags `latest`, `main`, et `1.2.3` / `1.2` / `1` pour les releases).

1. Dans tinyMediaManager, activez l'API HTTP et notez le port (7878 par défaut) et la clé.
2. Récupérez `docker-compose.yml` et `.env.example` de ce dépôt, copiez `.env.example` en
   `.env`, puis renseignez `TMM_API_KEY` (et `TMM_HOST` / `TMM_NETWORK` si besoin :
   nom du conteneur tinyMediaManager et réseau Docker qu'il utilise).
3. `docker compose up -d`, puis ouvrez `http://serveur:8080`.

Aucun volume n'est nécessaire : l'appli est dans l'image. Pour mettre à jour :
`docker compose pull && docker compose up -d`.

Le proxy nginx ajoute la clé API côté serveur (elle n'arrive jamais dans le navigateur) et
évite les problèmes de CORS et de contenu mixte HTTP/HTTPS. Dans l'appli, laissez l'URL à `/api`.

## Installation sous Unraid

Prérequis : le conteneur tinyMediaManager tourne déjà, son **API HTTP est activée** et son port
(7878 par défaut) est **publié** sur le serveur, avec une clé API définie.

1. Ouvrez le terminal d'Unraid (ou SSH) et installez le modèle :
   ```
   wget -O /boot/config/plugins/dockerMan/templates-user/my-TMM-Remote.xml \
     https://raw.githubusercontent.com/Yogui26/TMM-Remote/main/unraid/tmm-remote.xml
   ```
2. Onglet **Docker** → **Add Container** → liste **Template** → section *User templates* →
   **TMM-Remote**.
3. Renseignez :
   - **TMM_HOST** : `IP-DE-VOTRE-UNRAID:7878` (l'IP du serveur et le port publié de l'API, pas
     le port 4000 de l'interface VNC) ;
   - **TMM_API_KEY** : la clé API de tinyMediaManager ;
   - **Port de l'interface** : 8765 par défaut, à changer s'il est déjà pris.
4. **Apply**. Cliquez ensuite sur l'icône du conteneur → **WebUI**, ou ouvrez
   `http://IP-DE-VOTRE-UNRAID:8765`.

Aucun chemin ni volume à configurer. Mise à jour : onglet Docker → *Check for updates*, puis
*apply update* sur TMM-Remote.

Conseil : utilisez l'IP du serveur dans `TMM_HOST` plutôt qu'un nom de conteneur. Sur le réseau
`bridge` par défaut d'Unraid, les conteneurs ne se retrouvent pas par leur nom, et une IP évite
aussi tout souci d'ordre de démarrage au lancement de la baie.

## Publier une nouvelle version

Chaque push sur `main` met à jour `latest`. Pour une version figée, créez une release GitHub
avec un tag `vX.Y.Z` (ex. `v1.0.0`) : le workflow `.github/workflows/docker.yml` construit et
publie l'image `1.0.0`, `1.0`, `1` et `latest`.

Si le paquet est privé après la première publication (Profil GitHub → Packages → tmm-remote →
Package settings → Change visibility), passez-le en public pour que `docker pull` fonctionne
sans identifiants.

## Dépannage

Au démarrage, le conteneur affiche l'adresse d'API qu'il utilise (`docker logs tmm-remote`) :
`tmm-remote: API tinyMediaManager -> http://hôte:port/api/`. Les valeurs de `TMM_HOST` et
`TMM_API_KEY` sont nettoyées automatiquement (espaces, guillemets, retours chariot d'un `.env`
créé sous Windows, `http://` ou `/api` en trop) ; si une correction a eu lieu, les octets
reçus sont affichés dans le log.

- `host not found in upstream` : le nom du conteneur n'est pas résolu. Vérifiez `TMM_NETWORK`
  (`docker network ls`) ou utilisez l'adresse IP du serveur dans `TMM_HOST`.
- Erreur 401 / 403 dans le Journal de l'appli : clé API incorrecte.

## Sécurité

Quiconque atteint le port 8080 peut piloter tinyMediaManager. Ne l'exposez pas tel quel sur
Internet : gardez-le sur le réseau local, derrière un VPN (Tailscale, WireGuard), ou placez-le
derrière un reverse proxy avec authentification.

## Construire l'image soi-même

```
docker build -t tmm-remote .
docker run -d -p 8080:80 -e TMM_HOST=tinymediamanager:7878 -e TMM_API_KEY=xxxx tmm-remote
```

## Sans proxy

Servez le dossier `app/` avec n'importe quel serveur statique, puis dans Réglages : URL
`http://serveur:7878/api` et clé API. Le navigateur doit être autorisé par CORS à appeler
l'API ; si ça échoue, utilisez le proxy.

## Installer sur l'écran d'accueil

iPhone / iPad : Partager → « Sur l'écran d'accueil ». Android : menu ⋮ → « Installer l'application ».

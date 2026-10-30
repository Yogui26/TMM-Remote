# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

## [1.2.0] - 2026-10-30

Fonctions de l'API de tinyMediaManager **5.3.5** (l'appli reste compatible avec les versions précédentes :
ces fonctions n'apparaissent que si `GET /api/system` répond).

### Ajouté
- **État de tinyMediaManager en direct** (`GET /api/system`) : pastille « inactif / travaille · N en attente »
  en haut de l'écran, tâches en cours dans le Journal, badge « terminé » sur les commandes envoyées et
  notification à la fin du traitement.
- Le suivi automatique du log dure désormais tant que tinyMediaManager travaille (au lieu de 2 minutes fixes).
- **Ciblage par identifiant** (`tmdbId`, `imdbId`, `tvdbId`) pour les actions sur une fiche : plus besoin que
  `TMM_MEDIA_PATH` corresponde au chemin vu par tinyMediaManager. Repli automatique sur le chemin du dossier
  pour les fiches sans identifiant.
- **Marquer comme vu / non vu** (`setWatched`) dans les fiches et dans le constructeur.
- Le test de connexion indique la version de tinyMediaManager et les fonctions disponibles.

## [1.1.0] - 2026-10-23

### Ajouté
- Journal : vue **lisible** du log de tinyMediaManager. Les étapes sont regroupées en séquences (mise à jour
  des sources, scrape, images, renommage, NFO, nettoyage…), avec le résultat film par film (ancien → nouveau
  nom, score de scrape insuffisant, annulation), la durée de chaque étape et les alertes répétées regroupées.
  Le **log brut** reste accessible par une bascule 📖 / 🧾, avec ses filtres et le suivi en direct.
- Nouveau point d'accès du service de lecture : `/lib/api/logview` (analyse jusqu'aux 16 derniers Mo du log).
- Reconstruction automatique de l'image chaque lundi pour reprendre les correctifs de sécurité.

### Modifié
- Interface plus sobre : les emojis sont remplacés par des icônes SVG d'une seule couleur (teinte propre à
  chaque icône, adaptée aux thèmes sombre et clair).
- Image de base `nginx:1.27-alpine` → `nginx:1.30-alpine` (branche stable maintenue ; la 1.27 ne reçoit plus
  de correctifs de sécurité).
- Les NFO sont lus au format **Emby** (balises `imdbid` / `tmdbid` / `tvdbid` / `uniqueid`, noms d'images
  Emby), tout en restant compatibles avec Kodi.

### Supprimé
- La mise à jour de la bibliothèque Kodi (scénarios et actions).

## [1.0.0] - 2026-10-04

### Ajouté
- Télécommande web tactile (PWA) pour l'API HTTP de tinyMediaManager : scénarios en un geste, constructeur
  de séquences, journal des envois avec « Rejouer », réglages et test de connexion.
- Image Docker publiée sur ghcr.io (`amd64`, `arm64`, `arm/v7`), `docker-compose.yml` et modèle Unraid.
- Proxy nginx qui ajoute la clé API côté serveur ; nettoyage automatique de `TMM_HOST` / `TMM_API_KEY`.
- Onglet Biblio en lecture seule (films et séries lus depuis les NFO, affiches, filtres, fiche détaillée,
  actions ciblées sur un seul film ou une seule série) et lecture du log de tinyMediaManager.

FROM nginx:1.27-alpine

LABEL org.opencontainers.image.title="TMM Remote" \
      org.opencontainers.image.description="Télécommande web tactile pour l'API HTTP de tinyMediaManager" \
      org.opencontainers.image.source="https://github.com/Yogui26/TMM-Remote"

# Le modèle est transformé au démarrage par l'entrypoint de l'image nginx
# (les variables ${TMM_HOST} et ${TMM_API_KEY} sont substituées).
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY app/ /usr/share/nginx/html/

# Conteneur tinyMediaManager (nom ou IP : port de l'API HTTP) et clé API
ENV TMM_HOST=tinymediamanager:7878 \
    TMM_API_KEY=

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -q --spider http://127.0.0.1/ || exit 1

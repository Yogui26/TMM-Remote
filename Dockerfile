FROM nginx:1.27-alpine

LABEL org.opencontainers.image.title="TMM Remote" \
      org.opencontainers.image.description="Télécommande web tactile pour l'API HTTP de tinyMediaManager" \
      org.opencontainers.image.source="https://github.com/Yogui26/TMM-Remote"

# Le modèle est transformé au démarrage par l'entrypoint de l'image nginx
# (les variables ${TMM_HOST} et ${TMM_API_KEY} sont substituées).
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
# Nettoie TMM_HOST / TMM_API_KEY avant la substitution (doit être exécutable)
COPY docker/18-tmm-env.envsh /docker-entrypoint.d/18-tmm-env.envsh
COPY app/ /usr/share/nginx/html/

RUN sed -i 's/\r$//' /docker-entrypoint.d/18-tmm-env.envsh /etc/nginx/templates/default.conf.template \
 && chmod 755 /docker-entrypoint.d/18-tmm-env.envsh

# Conteneur tinyMediaManager (nom ou IP : port de l'API HTTP) et clé API
ENV TMM_HOST=tinymediamanager:7878 \
    TMM_API_KEY=

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -q --spider http://127.0.0.1/ || exit 1

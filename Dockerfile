FROM nginx:1.27-alpine

LABEL org.opencontainers.image.title="TMM Remote" \
      org.opencontainers.image.description="Télécommande web tactile pour l'API HTTP de tinyMediaManager" \
      org.opencontainers.image.source="https://github.com/Yogui26/TMM-Remote"

# Python (bibliothèque standard seulement) pour l'indexeur de bibliothèque en lecture seule
RUN apk add --no-cache python3

# Le modèle est transformé au démarrage par l'entrypoint de l'image nginx
# (les variables ${TMM_HOST} et ${TMM_API_KEY} sont substituées).
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
# Nettoie TMM_HOST / TMM_API_KEY avant la substitution (doit être exécutable)
COPY docker/18-tmm-env.envsh /docker-entrypoint.d/18-tmm-env.envsh
# Lance l'indexeur en arrière-plan avant nginx
COPY docker/40-start-indexer.sh /docker-entrypoint.d/40-start-indexer.sh
COPY indexer/indexer.py /opt/indexer/indexer.py
COPY app/ /usr/share/nginx/html/

RUN sed -i 's/\r$//' /docker-entrypoint.d/18-tmm-env.envsh /docker-entrypoint.d/40-start-indexer.sh \
        /etc/nginx/templates/default.conf.template /opt/indexer/indexer.py \
 && chmod 755 /docker-entrypoint.d/18-tmm-env.envsh /docker-entrypoint.d/40-start-indexer.sh

# Conteneur tinyMediaManager (nom ou IP : port de l'API HTTP) et clé API
ENV TMM_HOST=tinymediamanager:7878 \
    TMM_API_KEY= \
    TMM_MEDIA_PATH=/media \
    MEDIA_DIR=/media \
    DATA_DIR=/data

# Facultatif, à monter en lecture seule : /media = vos médias, /data = données de tinyMediaManager
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -q --spider http://127.0.0.1/ || exit 1

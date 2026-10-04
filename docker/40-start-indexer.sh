#!/bin/sh
# Lance l'indexeur de bibliothèque (lecture seule) en arrière-plan ; il est relancé s'il s'arrête.
# Il n'écoute que sur 127.0.0.1 : nginx l'expose sous /lib/.
(
  while true; do
    python3 -u /opt/indexer/indexer.py
    echo "tmm-remote: indexeur arrêté, relance dans 3 s"
    sleep 3
  done
) < /dev/null &

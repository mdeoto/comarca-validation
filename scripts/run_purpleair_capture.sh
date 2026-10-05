#!/bin/bash

set -uo pipefail

# ============================================================
# PurpleAir operational capture
#
# Wrapper para ejecución automática mediante cron.
#
# Funciones:
#   - localiza automáticamente la raíz del repositorio
#   - evita ejecuciones simultáneas mediante flock
#   - ejecuta capture_purpleair.py en el entorno dedicado
#   - limita la duración máxima mediante timeout
#   - mantiene un log operativo
# ============================================================


# ------------------------------------------------------------
# Configuración
# ------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASEDIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENV_NAME="purpleair-capture"

SCRIPT="${BASEDIR}/scripts/capture_purpleair.py"

LOGDIR="${BASEDIR}/logs"
LOGFILE="${LOGDIR}/purpleair_capture.log"

LOCKFILE="${BASEDIR}/.purpleair_capture.lock"


# ------------------------------------------------------------
# Preparación
# ------------------------------------------------------------

mkdir -p "${LOGDIR}"

cd "${BASEDIR}" || exit 1


# ------------------------------------------------------------
# Lock
# ------------------------------------------------------------

exec 9>"${LOCKFILE}"

if ! flock -n 9; then
    echo "$(date --iso-8601=seconds) SKIP: otra corrida sigue activa" \
        >> "${LOGFILE}"
    exit 0
fi


# ------------------------------------------------------------
# Conda
# ------------------------------------------------------------

CONDA_BIN="$(command -v conda || true)"

if [ -z "${CONDA_BIN}" ]; then
    echo "$(date --iso-8601=seconds) ERROR: conda no encontrado" \
        >> "${LOGFILE}"
    exit 1
fi


# ------------------------------------------------------------
# Ejecución
# ------------------------------------------------------------

echo "============================================================" >> "${LOGFILE}"
echo "$(date --iso-8601=seconds) START" >> "${LOGFILE}"

timeout --signal=TERM --kill-after=30s 8m \
    "${CONDA_BIN}" run --no-capture-output -n "${ENV_NAME}" \
    python "${SCRIPT}" >> "${LOGFILE}" 2>&1

STATUS=$?


# ------------------------------------------------------------
# Estado final
# ------------------------------------------------------------

if [ "${STATUS}" -eq 0 ]; then

    echo "$(date --iso-8601=seconds) END OK" \
        >> "${LOGFILE}"

elif [ "${STATUS}" -eq 124 ]; then

    echo "$(date --iso-8601=seconds) END TIMEOUT" \
        >> "${LOGFILE}"

else

    echo "$(date --iso-8601=seconds) END ERROR exit=${STATUS}" \
        >> "${LOGFILE}"

fi

exit "${STATUS}"

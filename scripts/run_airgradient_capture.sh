#!/bin/bash

set -uo pipefail

# ============================================================
# AirGradient operational acquisition
#
# Funciones:
#   - localiza automáticamente la raíz del repositorio
#   - carga las credenciales locales
#   - evita ejecuciones simultáneas mediante flock
#   - ejecuta fetch_airgradient.py en el entorno dedicado
#   - limita la duración máxima mediante timeout
#   - mantiene un log operativo
# ============================================================


# ------------------------------------------------------------
# Configuración
# ------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASEDIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENV_NAME="airgradient-capture"

SCRIPT="${BASEDIR}/scripts/fetch_airgradient.py"

SECRETS_FILE="${BASEDIR}/.secrets/airgradient.env"

LOGDIR="${BASEDIR}/logs"
LOGFILE="${LOGDIR}/airgradient_capture.log"

LOCKFILE="${BASEDIR}/.airgradient_capture.lock"


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
# Credenciales
# ------------------------------------------------------------

if [ ! -f "${SECRETS_FILE}" ]; then
    echo "$(date --iso-8601=seconds) ERROR: no existe ${SECRETS_FILE}" \
        >> "${LOGFILE}"
    exit 1
fi

set -a
source "${SECRETS_FILE}"
set +a

if [ -z "${AIRGRADIENT_API_TOKEN:-}" ]; then
    echo "$(date --iso-8601=seconds) ERROR: AIRGRADIENT_API_TOKEN no definido" \
        >> "${LOGFILE}"
    exit 1
fi


# ------------------------------------------------------------
# Python / entorno Conda
# ------------------------------------------------------------

PYTHON_BIN="/home/mdeoto/miniconda3/envs/${ENV_NAME}/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "$(date --iso-8601=seconds) ERROR: no existe ${PYTHON_BIN}" \
        >> "${LOGFILE}"
    exit 1
fi

# ------------------------------------------------------------
# Ejecución
# ------------------------------------------------------------

echo "============================================================" >> "${LOGFILE}"
echo "$(date --iso-8601=seconds) START" >> "${LOGFILE}"

timeout --signal=TERM --kill-after=30s 2m \
    "${PYTHON_BIN}" "${SCRIPT}" >> "${LOGFILE}" 2>&1

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

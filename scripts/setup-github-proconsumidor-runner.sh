#!/usr/bin/env bash
# Instala e registra um GitHub Actions self-hosted runner para o workflow
# "Proconsumidor local processing" (IP no Brasil, sem HTTP 403 no portal MJ).
#
# Pré-requisitos:
#   - Linux x64 ou macOS (Apple Silicon use arch arm64 no RUNNER_ARCH)
#   - curl, tar
#   - Token de registro (expira em 1h):
#     GitHub → Repo → Settings → Actions → Runners → New self-hosted runner
#
# Uso:
#   export RUNNER_REGISTRATION_TOKEN="AAAA..."
#   bash scripts/setup-github-proconsumidor-runner.sh
#
# Opcional:
#   RUNNER_NAME="escritorio-sp-procon" INSTALL_DIR="$HOME/actions-runner-procon"

set -euo pipefail

GITHUB_OWNER="${GITHUB_OWNER:-ivoalexandrino-png}"
GITHUB_REPO="${GITHUB_REPO:-ClassificacaoProcons}"
RUNNER_NAME="${RUNNER_NAME:-procon-br-$(hostname -s 2>/dev/null || echo host)}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/actions-runner-proconsumidor}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,procon-br}"
RUNNER_GROUP="${RUNNER_GROUP:-default}"

if [ -z "${RUNNER_REGISTRATION_TOKEN:-}" ]; then
  echo "ERRO: defina RUNNER_REGISTRATION_TOKEN (Settings → Actions → Runners → New)." >&2
  exit 1
fi

HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" "https://proconsumidor.mj.gov.br/" || true)"
if [ "${HTTP_STATUS}" = "403" ]; then
  echo "AVISO: este host recebe HTTP 403 do portal Proconsumidor." >&2
  echo "Use um Mac/PC no escritório ou rede residencial no Brasil antes de confiar neste runner." >&2
  if [ "${ALLOW_403:-}" != "1" ]; then
    echo "Para continuar mesmo assim: ALLOW_403=1 bash $0" >&2
    exit 1
  fi
fi

OS="$(uname -s)"
ARCH="$(uname -m)"
case "${OS}" in
  Linux) RUNNER_OS="linux" ;;
  Darwin) RUNNER_OS="osx" ;;
  *)
    echo "ERRO: SO não suportado: ${OS}" >&2
    exit 1
    ;;
esac
case "${ARCH}" in
  x86_64) RUNNER_ARCH="x64" ;;
  arm64|aarch64) RUNNER_ARCH="arm64" ;;
  *)
    echo "ERRO: arquitetura não suportada: ${ARCH}" >&2
    exit 1
    ;;
esac

RUNNER_VERSION="${RUNNER_VERSION:-2.327.1}"
TARBALL="actions-runner-${RUNNER_OS}-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"

mkdir -p "${INSTALL_DIR}"
cd "${INSTALL_DIR}"

if [ ! -f ./config.sh ]; then
  echo "Baixando runner ${RUNNER_VERSION} (${RUNNER_OS}/${RUNNER_ARCH})..."
  curl -fsSL -o "${TARBALL}" "${DOWNLOAD_URL}"
  tar xzf "${TARBALL}"
  rm -f "${TARBALL}"
fi

if [ -f ./run.sh ] && [ -f .runner ]; then
  echo "Runner já configurado em ${INSTALL_DIR}. Para reconfigurar, remova .runner e rode de novo."
else
  ./config.sh \
    --url "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}" \
    --token "${RUNNER_REGISTRATION_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --runnergroup "${RUNNER_GROUP}" \
    --unattended \
    --replace
fi

echo ""
echo "Runner registrado: ${RUNNER_NAME} (labels: ${RUNNER_LABELS})"
echo ""
if [ "${RUNNER_OS}" = "linux" ] && command -v sudo >/dev/null 2>&1; then
  echo "Instalando serviço systemd (sudo)..."
  sudo ./svc.sh install
  sudo ./svc.sh start
  sudo ./svc.sh status || true
  echo ""
  echo "Serviço ativo. Jobs 'Proconsumidor local processing' devem sair da fila em até 1 minuto."
else
  echo "Inicie o runner em foreground (deixe o terminal aberto ou use launchd/nohup):"
  echo "  cd ${INSTALL_DIR} && ./run.sh"
fi
echo ""
echo "Teste no GitHub:"
echo "  gh workflow run \"Proconsumidor local processing\" -f max_results=5"
echo "  gh run list --workflow=\"Proconsumidor local processing\" --limit 3"

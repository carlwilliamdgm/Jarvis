const { spawn } = require('node:child_process');

const API_SCHEME = process.env.GREATOS_API_SCHEME === 'https' ? 'https' : 'http';
const BACKEND_URL = `${API_SCHEME}://localhost:8000/jarvis/status`;
const TASK_NAME = 'JarvisAgent';
const DEFAULT_TIMEOUT_MS = 90_000;
const DEFAULT_POLL_INTERVAL_MS = 500;

async function isBackendReady(fetchImpl = globalThis.fetch) {
  try {
    const response = await fetchImpl(BACKEND_URL, {
      cache: 'no-store',
      signal: AbortSignal.timeout(1_500),
    });
    return response.ok;
  } catch {
    return false;
  }
}

function startScheduledBackend({ spawnImpl = spawn, platform = process.platform } = {}) {
  if (platform !== 'win32') {
    return Promise.reject(new Error('Le démarrage automatique est disponible uniquement sous Windows.'));
  }

  return new Promise((resolve, reject) => {
    const child = spawnImpl(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        `Start-ScheduledTask -TaskName '${TASK_NAME}' -ErrorAction Stop`,
      ],
      { windowsHide: true, stdio: 'ignore' },
    );

    child.once('error', reject);
    child.once('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`La tâche Windows ${TASK_NAME} n’a pas pu être démarrée (code ${code}).`));
    });
  });
}

async function ensureBackendAvailable({
  platform = process.platform,
  isReady = isBackendReady,
  startBackend = () => startScheduledBackend({ platform }),
  timeoutMs = DEFAULT_TIMEOUT_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  now = Date.now,
  sleep = (duration) => new Promise((resolve) => setTimeout(resolve, duration)),
} = {}) {
  if (await isReady()) return { started: false };
  if (platform !== 'win32') {
    throw new Error('Le serveur GreatOS est indisponible. Le démarrage automatique est configuré pour Windows.');
  }

  try {
    await startBackend();
  } catch (error) {
    throw new Error(
      `Impossible de démarrer la tâche Windows ${TASK_NAME}. Installe d’abord le service GreatOS avec le script install.ps1.`,
      { cause: error },
    );
  }

  const deadline = now() + timeoutMs;
  while (now() < deadline) {
    await sleep(Math.min(pollIntervalMs, deadline - now()));
    if (await isReady()) return { started: true };
  }

  const timeoutSeconds = Math.ceil(timeoutMs / 1_000);
  throw new Error(
    `Le serveur GreatOS ne répond pas après ${timeoutSeconds} seconde${timeoutSeconds > 1 ? 's' : ''}. Vérifie la tâche ${TASK_NAME} et ses journaux, puis réessaie.`,
  );
}

module.exports = {
  BACKEND_URL,
  DEFAULT_POLL_INTERVAL_MS,
  DEFAULT_TIMEOUT_MS,
  TASK_NAME,
  ensureBackendAvailable,
  isBackendReady,
  startScheduledBackend,
};

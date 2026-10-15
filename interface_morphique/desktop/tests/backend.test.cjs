const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { execFileSync } = require('node:child_process');
const {
  BACKEND_URL,
  ensureBackendAvailable,
  isBackendReady,
  startScheduledBackend,
} = require('../electron/backend.cjs');
const { resolveApiScheme } = require('../electron/api-config.cjs');

test('packaged desktop always uses operator TLS despite stale inherited environment', () => {
  assert.equal(resolveApiScheme({ packaged: true, configuredScheme: 'http' }), 'https');
  assert.equal(resolveApiScheme({ packaged: true, configuredScheme: undefined }), 'https');
});

test('development desktop keeps local HTTP unless TLS is explicitly configured', () => {
  assert.equal(resolveApiScheme({ packaged: false, configuredScheme: undefined }), 'http');
  assert.equal(resolveApiScheme({ packaged: false, configuredScheme: 'https' }), 'https');
});

test('backend health check targets the loopback GreatOS status endpoint', async () => {
  let requestedUrl;
  const ready = await isBackendReady(async (url) => {
    requestedUrl = url;
    return { ok: true };
  });

  assert.equal(ready, true);
  assert.equal(requestedUrl, BACKEND_URL);
});

test('operator-provisioned API scheme selects HTTPS for the desktop health check', () => {
  const backendPath = require.resolve('../electron/backend.cjs');
  const url = execFileSync(process.execPath, [
    '-e',
    `process.env.GREATOS_API_SCHEME = 'https'; console.log(require(${JSON.stringify(backendPath)}).BACKEND_URL)`,
  ], { encoding: 'utf8' }).trim();

  assert.equal(url, 'https://localhost:8000/jarvis/status');
});

test('does not start the scheduled task when GreatOS is already ready', async () => {
  let startCount = 0;
  const result = await ensureBackendAvailable({
    platform: 'win32',
    isReady: async () => true,
    startBackend: async () => { startCount += 1; },
  });

  assert.deepEqual(result, { started: false });
  assert.equal(startCount, 0);
});

test('starts the existing Windows task once and waits for the API', async () => {
  let readyChecks = 0;
  let startCount = 0;
  let clock = 0;
  const result = await ensureBackendAvailable({
    platform: 'win32',
    timeoutMs: 1_000,
    pollIntervalMs: 100,
    isReady: async () => ++readyChecks >= 3,
    startBackend: async () => { startCount += 1; },
    now: () => clock,
    sleep: async (duration) => { clock += duration; },
  });

  assert.deepEqual(result, { started: true });
  assert.equal(startCount, 1);
  assert.equal(readyChecks, 3);
});

test('does not try to start a Windows task on other platforms', async () => {
  let startCount = 0;
  await assert.rejects(
    ensureBackendAvailable({
      platform: 'linux',
      isReady: async () => false,
      startBackend: async () => { startCount += 1; },
    }),
    /configuré pour Windows/,
  );
  assert.equal(startCount, 0);
});

test('reports a missing scheduled task with installation guidance', async () => {
  await assert.rejects(
    ensureBackendAvailable({
      platform: 'win32',
      isReady: async () => false,
      startBackend: async () => { throw new Error('task not registered'); },
    }),
    /Installe d’abord le service GreatOS avec le script install\.ps1/,
  );
});

test('fails clearly when the scheduled task starts but the API never responds', async () => {
  let clock = 0;
  await assert.rejects(
    ensureBackendAvailable({
      platform: 'win32',
      timeoutMs: 300,
      pollIntervalMs: 100,
      isReady: async () => false,
      startBackend: async () => {},
      now: () => clock,
      sleep: async (duration) => { clock += duration; },
    }),
    /ne répond pas après 1 seconde\./,
  );
});

test('starts the named scheduled task through hidden PowerShell', async () => {
  const child = new EventEmitter();
  let launch;
  const started = startScheduledBackend({
    platform: 'win32',
    spawnImpl: (...args) => { launch = args; return child; },
  });
  child.emit('close', 0);
  await started;

  assert.equal(launch[0], 'powershell.exe');
  assert.ok(launch[1].includes('-NonInteractive'));
  assert.ok(launch[1].at(-1).includes("Start-ScheduledTask -TaskName 'JarvisAgent'"));
  assert.deepEqual(launch[2], { windowsHide: true, stdio: 'ignore' });
});


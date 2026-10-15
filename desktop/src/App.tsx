import { FormEvent, KeyboardEvent as ReactKeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Chart from 'chart.js/auto';

type Layout = 'chat' | 'focus' | 'dashboard' | 'vocal_hud' | 'task_runner' | 'web_nav' | 'idle' | 'defcon_alert';
type FeedItem = { id: string; kind: 'user' | 'assistant' | 'event' | 'error'; text: string; time?: string };
type Status = {
  cpu?: number; ram?: number; active?: boolean;
  voice?: { audio_input_ready?: boolean; reason?: string; audio?: { default_input?: { name?: string } } };
  vision?: { interpretation_ready?: boolean; interpretation_provider?: string | null; remote_analysis_enabled?: boolean };
  security?: { memory_backend?: string; encryption?: { enabled?: boolean; algorithm?: string } };
};
type Confirmation = { action_id: string; description: string };
type OnboardingData = {
  activity: string; repetitive_task: string; priority: string; workflow_id: string; language: 'fr' | 'en';
};
type OnboardingWorkflow = { id: string; name: string; description: string };
type ProgressGoal = { id: string; title: string; progress: number; status: string; due_date?: string | null };
type ProgressDashboard = {
  summary: { total: number; termines: number; actifs: number; taux_completion: number; progression_moyenne: number };
  goals: ProgressGoal[];
};
type TotpStatus = { enabled: boolean; enrollment_pending: boolean };
type UnlockStatus = { locked: boolean; windows_session_locked?: boolean; hello_available: boolean; manual_recovery_available: boolean; dpapi_recovery_available?: boolean };
const layouts: { id: Layout; label: string; icon: string }[] = [
  { id: 'chat', label: 'Chat', icon: '◈' }, { id: 'focus', label: 'Focus', icon: '◉' },
  { id: 'dashboard', label: 'Dashboard', icon: '▦' }, { id: 'vocal_hud', label: 'Vocal HUD', icon: '◖' },
  { id: 'task_runner', label: 'Task Runner', icon: '⌘' }, { id: 'web_nav', label: 'Web Nav', icon: '◎' },
  { id: 'idle', label: 'Veille', icon: '◌' }, { id: 'defcon_alert', label: 'DEFCON', icon: '⚠' },
];
const localInstance = {
  id: 'local',
  nom: 'Local',
  url: import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin,
};
const sessionId = sessionStorage.getItem('jarvis-session-id') || crypto.randomUUID();
sessionStorage.setItem('jarvis-session-id', sessionId);

function apiError(response: Response) {
  if (response.status === 401 || response.status === 403) return new Error('auth');
  return new Error(`http-${response.status}`);
}

async function apiFailure(response: Response, fallback: string): Promise<Error> {
  let detail = '';
  try {
    const body = await response.clone().json() as { detail?: unknown };
    if (typeof body.detail === 'string') detail = body.detail.slice(0, 240);
  } catch { /* preserve the status even when the response is not JSON */ }
  return new Error(`${fallback} (HTTP ${response.status}${detail ? ` : ${detail}` : ''})`);
}

const HELLO_CREATION_PENDING_KEY = 'greatos.hello.creation-pending';
const HELLO_CREDENTIAL_REVIEWED_KEY = 'greatos.hello.credential-reviewed';
function readHelloCreationPending(): boolean {
  try { return window.localStorage.getItem(HELLO_CREATION_PENDING_KEY) === '1'; }
  catch { return false; }
}
function readHelloCredentialReviewed(): boolean {
  try { return window.localStorage.getItem(HELLO_CREDENTIAL_REVIEWED_KEY) === '1'; }
  catch { return false; }
}
function setHelloCreationPending(pending: boolean): boolean {
  try {
    if (pending) window.localStorage.setItem(HELLO_CREATION_PENDING_KEY, '1');
    else window.localStorage.removeItem(HELLO_CREATION_PENDING_KEY);
    return true;
  } catch { /* The caller must stop enrollment if this durable guard cannot be saved. */ }
  return false;
}
function setHelloCredentialReviewed(reviewed: boolean): boolean {
  try {
    if (reviewed) window.localStorage.setItem(HELLO_CREDENTIAL_REVIEWED_KEY, '1');
    else window.localStorage.removeItem(HELLO_CREDENTIAL_REVIEWED_KEY);
    return true;
  } catch { /* The caller must stop enrollment if this durable guard cannot be saved. */ }
  return false;
}

function decodeBase64Url(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return bytes.buffer;
}

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function prfSaltOptions(raw: Record<string, any>, salt?: string): Record<string, any> {
  const options = { ...raw };
  const extensions = { ...(options.extensions || {}) };
  const prf = { ...(extensions.prf || {}) };
  const evalInput = { ...(prf.eval || {}) };
  const encodedSalt = salt || evalInput.first;
  if (typeof encodedSalt !== 'string') throw new Error('Le serveur n’a pas fourni le sel PRF requis.');
  evalInput.first = decodeBase64Url(encodedSalt);
  prf.eval = evalInput;
  extensions.prf = prf;
  options.extensions = extensions;
  return options;
}

function prfOutputBase64Url(credential: PublicKeyCredential): string {
  const result = credential.getClientExtensionResults().prf?.results?.first;
  if (!(result instanceof ArrayBuffer) || result.byteLength !== 32) {
    throw new Error('Windows Hello n’a pas retourné un résultat PRF valide de 32 octets.');
  }
  const bytes = new Uint8Array(result);
  try { return encodeBase64Url(result); }
  finally { bytes.fill(0); }
}

function webAuthnCredentialJson(credential: PublicKeyCredential, includePrf = true): Record<string, unknown> {
  const response = credential.response;
  const extensionResults = credential.getClientExtensionResults();
  const clientExtensionResults = includePrf ? extensionResults : Object.fromEntries(
    Object.entries(extensionResults).filter(([name]) => name !== 'prf'),
  );
  const common = { id: credential.id, rawId: encodeBase64Url(credential.rawId), type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults };
  if (response instanceof AuthenticatorAttestationResponse) {
    return { ...common, response: { clientDataJSON: encodeBase64Url(response.clientDataJSON),
      attestationObject: encodeBase64Url(response.attestationObject), transports: response.getTransports?.() || [] } };
  }
  if (response instanceof AuthenticatorAssertionResponse) {
    return { ...common, response: { clientDataJSON: encodeBase64Url(response.clientDataJSON),
      authenticatorData: encodeBase64Url(response.authenticatorData), signature: encodeBase64Url(response.signature),
      userHandle: response.userHandle ? encodeBase64Url(response.userHandle) : null } };
  }
  throw new Error('Réponse Windows Hello invalide.');
}

function publicKeyOptions(raw: Record<string, any>, requirePrf = false): PublicKeyCredentialRequestOptions {
  const options = requirePrf || raw.extensions?.prf ? prfSaltOptions(raw) : { ...raw };
  options.challenge = decodeBase64Url(options.challenge);
  if (Array.isArray(options.allowCredentials)) options.allowCredentials = options.allowCredentials.map((item: any) => ({ ...item, id: decodeBase64Url(item.id) }));
  return options as PublicKeyCredentialRequestOptions;
}

function creationOptions(raw: Record<string, any>, prfSalt?: string): PublicKeyCredentialCreationOptions {
  const options = prfSalt ? prfSaltOptions(raw, prfSalt) : { ...raw };
  options.challenge = decodeBase64Url(options.challenge);
  if (options.user?.id) options.user = { ...options.user, id: decodeBase64Url(options.user.id) };
  if (Array.isArray(options.excludeCredentials)) options.excludeCredentials = options.excludeCredentials.map((item: any) => ({ ...item, id: decodeBase64Url(item.id) }));
  return options as PublicKeyCredentialCreationOptions;
}

export default function App() {
  const [apiBase, setApiBase] = useState(localInstance.url);
  const [items, setItems] = useState<FeedItem[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status>({});
  const [layout, setLayout] = useState<Layout>('chat');
  const [appContext, setAppContext] = useState('');
  const [view, setView] = useState<'chat' | 'dashboard'>('chat');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [browserSessions, setBrowserSessions] = useState<Record<string, unknown>[]>([]);
  const [progressDashboard, setProgressDashboard] = useState<ProgressDashboard | null>(null);
  const [progressError, setProgressError] = useState('');
  const [progressLoading, setProgressLoading] = useState(false);
  const [remoteSession, setRemoteSession] = useState<{ apiBase: string; token: string } | null>(null);
  const [remoteAuthOpen, setRemoteAuthOpen] = useState(false);
  const [remoteAuthError, setRemoteAuthError] = useState('');
  const [totpStatus, setTotpStatus] = useState<TotpStatus | null>(null);
  const [totpManagedHere, setTotpManagedHere] = useState(false);
  const [totpSetupSecret, setTotpSetupSecret] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [totpError, setTotpError] = useState('');
  const [totpBusy, setTotpBusy] = useState(false);
  const [unlockStatus, setUnlockStatus] = useState<UnlockStatus | null>(null);
  const [service, setService] = useState<'checking' | 'online' | 'offline' | 'auth'>('checking');
  const [onboardingReady, setOnboardingReady] = useState(false);
  const [onboardingCompleted, setOnboardingCompleted] = useState(false);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);
  const [onboardingError, setOnboardingError] = useState('');
  const [onboardingRetry, setOnboardingRetry] = useState(0);
  const [onboardingSaving, setOnboardingSaving] = useState(false);
  const [onboardingData, setOnboardingData] = useState<OnboardingData>({ activity: '', repetitive_task: '', priority: '', workflow_id: '', language: 'fr' });
  const [onboardingWorkflows, setOnboardingWorkflows] = useState<OnboardingWorkflow[]>([]);
  const [instances, setInstances] = useState<{ id: string; nom: string; url: string }[]>(() => {
    try { return [localInstance, ...JSON.parse(localStorage.getItem('jarvis-instances') || '[]')]; }
    catch { return [localInstance]; }
  });
  const [instanceDraft, setInstanceDraft] = useState({ nom: '', url: '' });
  const [showInstances, setShowInstances] = useState(false);
  const [discoveryResults, setDiscoveryResults] = useState<{ id: string; nom: string; ip: string; url: string }[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const authContextRef = useRef({ apiBase, remoteSession });
  authContextRef.current = { apiBase, remoteSession };
  const abortRef = useRef<AbortController | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const progressChartRef = useRef<HTMLCanvasElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activeInstance = useMemo(() => instances.find((instance) => instance.url === apiBase), [instances, apiBase]);
  const apiFetch = useCallback(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    const activeToken = remoteSession?.apiBase === apiBase ? remoteSession.token : null;
    const requestApiBase = apiBase;
    if (activeToken) headers.set('Authorization', `Bearer ${activeToken}`);
    const response = await fetch(input, { ...init, headers });
    if (response.status === 401) {
      const current = authContextRef.current;
      if (current.apiBase !== requestApiBase
        || (activeToken && current.remoteSession?.token !== activeToken)
        || (!activeToken && current.remoteSession?.apiBase === requestApiBase)) return response;
      if (activeToken) setRemoteSession(null);
      setRemoteAuthOpen(true);
    }
    return response;
  }, [apiBase, remoteSession]);

  useEffect(() => {
    setRemoteSession(null); setRemoteAuthOpen(false); setRemoteAuthError('');
    setTotpStatus(null); setTotpManagedHere(false); setTotpSetupSecret(''); setTotpError('');
  }, [apiBase]);

  useEffect(() => {
    let live = true;
    setOnboardingReady(false); setOnboardingError('');
    apiFetch(`${apiBase}/jarvis/onboarding`, { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw apiError(response);
        return response.json();
      })
      .then((data: { completed?: boolean; onboarding?: Partial<OnboardingData>; workflows?: OnboardingWorkflow[] }) => {
        if (!live) return;
        setOnboardingCompleted(Boolean(data.completed));
        setOnboardingDismissed(Boolean(data.completed));
        if (data.onboarding) setOnboardingData((current) => ({ ...current, ...data.onboarding }));
        setOnboardingWorkflows(Array.isArray(data.workflows) ? data.workflows : []);
      })
      .catch((error: Error) => { if (live) setOnboardingError(error.message === 'auth' ? 'L’accès au serveur demande une authentification.' : 'GreatOS doit être joignable pour charger le profil chiffré.'); })
      .finally(() => { if (live) setOnboardingReady(true); });
    return () => { live = false; };
  }, [apiBase, apiFetch, onboardingRetry]);

  const addItem = useCallback((item: Omit<FeedItem, 'id'>) => {
    setItems((current) => [...current, { ...item, id: crypto.randomUUID() }]);
  }, []);

  useEffect(() => {
    let active = true;
    const refreshUnlockStatus = () => fetch(`${apiBase}/jarvis/security/unlock/status`, { cache: 'no-store' })
      .then(async (response) => response.ok ? await response.json() as UnlockStatus : null)
      .then((value) => { if (active) setUnlockStatus(value); })
      .catch(() => { if (active) setUnlockStatus(null); });
    void refreshUnlockStatus();
    const timer = window.setInterval(() => void refreshUnlockStatus(), 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [apiBase]);

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => { document.documentElement.dataset.layout = layout; }, [layout]);
  useEffect(() => { feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' }); }, [items]);

  const refreshStatus = useCallback(async () => {
    try {
      const response = await apiFetch(`${apiBase}/jarvis/status`, { cache: 'no-store' });
      if (!response.ok) throw apiError(response);
      setStatus(await response.json()); setService('online');
    } catch (error) { setService((error as Error).message === 'auth' ? 'auth' : 'offline'); }
  }, [apiBase, apiFetch]);

  const refreshSessions = useCallback(async () => {
    try {
      const response = await apiFetch(`${apiBase}/jarvis/browser-sessions`, { cache: 'no-store' });
      if (response.ok) setBrowserSessions((await response.json()).sessions || []);
    } catch { /* dashboard shows an empty state when backend is unavailable */ }
  }, [apiBase, apiFetch]);

  const refreshProgress = useCallback(async () => {
    setProgressLoading(true); setProgressError('');
    try {
      const response = await apiFetch(`${apiBase}/jarvis/progress/dashboard`, { cache: 'no-store' });
      if (!response.ok) throw apiError(response);
      setProgressDashboard(await response.json());
    } catch (error) {
      setProgressError((error as Error).message === 'auth' ? 'Authentification requise pour lire les objectifs.' : 'Les données Progress Tracker sont indisponibles.');
    } finally { setProgressLoading(false); }
  }, [apiBase, apiFetch]);

  const refreshTotpStatus = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/jarvis/auth/totp`, { cache: 'no-store' });
      if (response.status === 403) { setTotpManagedHere(false); return; }
      if (!response.ok) throw apiError(response);
      setTotpStatus(await response.json()); setTotpManagedHere(true); setTotpError('');
    } catch { setTotpManagedHere(true); setTotpError('État de la configuration TOTP indisponible.'); }
  }, [apiBase]);

  useEffect(() => {
    void refreshStatus(); void refreshSessions();
    const timer = window.setInterval(() => { void refreshStatus(); void refreshSessions(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshStatus, refreshSessions]);

  useEffect(() => {
    if (view === 'dashboard') { void refreshProgress(); void refreshTotpStatus(); }
  }, [view, refreshProgress, refreshTotpStatus]);

  useEffect(() => {
    const canvas = progressChartRef.current;
    if (!canvas || !progressDashboard || view !== 'dashboard') return;
    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: progressDashboard.goals.map((goal) => goal.title),
        datasets: [{
          label: 'Progression (%)',
          data: progressDashboard.goals.map((goal) => goal.progress),
          backgroundColor: theme === 'dark' ? 'rgba(73, 189, 165, 0.72)' : 'rgba(8, 123, 104, 0.72)',
          borderColor: theme === 'dark' ? '#78d4c0' : '#087b68',
          borderWidth: 1,
          borderRadius: 5,
          maxBarThickness: 26,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 180 },
        plugins: { legend: { display: false } },
        scales: {
          x: { min: 0, max: 100, ticks: { color: theme === 'dark' ? '#afbdc8' : '#435957', callback: (value) => `${value}%` }, grid: { color: theme === 'dark' ? 'rgba(145, 162, 175, 0.18)' : 'rgba(67, 89, 87, 0.16)' } },
          y: { ticks: { color: theme === 'dark' ? '#edf3f6' : '#1a2928' }, grid: { display: false } },
        },
      },
    });
    return () => chart.destroy();
  }, [progressDashboard, theme, view]);

  useEffect(() => {
    let live = true;
    const refreshLayout = async () => {
      try {
        const response = await apiFetch(`${apiBase}/jarvis/layout`, { cache: 'no-store' });
        if (!response.ok) return;
        const data = await response.json();
        if (!live) return;
        if (layouts.some((candidate) => candidate.id === data.layout)) setLayout(data.layout);
        setAppContext(data.os_context?.application || '');
      } catch { /* transient: keep the last known layout */ }
    };
    void refreshLayout();
    const timer = window.setInterval(() => void refreshLayout(), 1500);
    return () => { live = false; window.clearInterval(timer); };
  }, [apiBase, apiFetch]);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    async function listenForEvents() {
      while (!stopped) {
        try {
          const response = await apiFetch(`${apiBase}/jarvis/events`, { headers: { Accept: 'text/event-stream' }, signal: controller.signal });
          if (!response.ok) throw apiError(response);
          if (!response.body) throw new Error('Flux d’événements indisponible');
          const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
          while (!stopped) {
            const { done, value } = await reader.read(); if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split(/\r?\n\r?\n/); buffer = frames.pop() || '';
            for (const frame of frames) {
              const payload = frame.split(/\r?\n/).find((line) => line.startsWith('data:'))?.slice(5).trim();
              if (!payload) continue;
              try { handleEvent(JSON.parse(payload)); } catch { /* skip malformed event */ }
            }
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          if ((error as Error).message === 'auth') setService('auth');
          await new Promise((resolve) => window.setTimeout(resolve, 2500));
        }
      }
    }
    void listenForEvents();
    return () => { stopped = true; controller.abort(); };
  }, [apiBase, apiFetch]);

  function handleEvent(event: { type: string; data?: Record<string, unknown> }) {
    const data = event.data || {};
    if (event.type === 'response') addItem({ kind: 'assistant', text: String(data.text || ''), time: String(data.timestamp || '') });
    else if (event.type === 'thinking') addItem({ kind: 'event', text: String(data.message || 'J.A.R.V.I.S réfléchit…') });
    else if (event.type === 'provider') addItem({ kind: 'event', text: `Modèle ${data.provider || 'actif'} · ${data.model || ''}` });
    else if (event.type === 'tool_started') addItem({ kind: 'event', text: `Exécution · ${data.outil || 'capacité'}` });
    else if (event.type === 'tool_completed') addItem({ kind: 'event', text: `Terminé · ${data.outil || 'capacité'} · ${String(data.resultat || '').slice(0, 120)}` });
    else if (event.type === 'tool_failed') addItem({ kind: 'error', text: `Échec · ${data.outil || 'capacité'} · ${String(data.resultat || '').slice(0, 120)}` });
    else if (event.type === 'step_rollback_started') addItem({ kind: 'event', text: `Retour arrière · ${data.step_id || 'étape'}…` });
    else if (event.type === 'step_rollback_completed') addItem({ kind: 'event', text: `Retour arrière terminé · ${data.step_id || 'étape'}` });
    else if (event.type === 'step_rollback_failed') addItem({ kind: 'error', text: `Retour arrière incomplet · ${data.step_id || 'étape'} · ${String(data.resultat || '')}` });
    else if (event.type === 'plan_interrupted') {
      const rollback = data.rollback as Record<string, unknown> | undefined;
      const remaining = Array.isArray(rollback?.effects_not_reverted) ? rollback.effects_not_reverted.length : 0;
      const withoutUndo = Array.isArray(rollback?.steps_without_compensator) ? rollback.steps_without_compensator.length : 0;
      const details = [`Plan interrompu${rollback?.status === 'completed' ? ' · retour arrière terminé' : rollback?.status === 'partial' ? ' · retour arrière partiel' : ''}`];
      if (remaining) details.push(`${remaining} effet(s) non annulé(s)`);
      if (withoutUndo) details.push(`${withoutUndo} étape(s) sans compensation déclarée`);
      addItem({ kind: rollback?.status === 'partial' ? 'error' : 'event', text: details.join(' · ') });
    }
    else if (event.type === 'confirmation_required') setConfirmation({ action_id: String(data.action_id || ''), description: String(data.description || 'Cette action') });
    else if (event.type === 'morphic_layout_changed') {
      const selected = String(data.nouveau_layout || 'chat') as Layout;
      if (layouts.some((candidate) => candidate.id === selected)) setLayout(selected);
      setAppContext(String((data.os_context as Record<string, unknown>)?.application || ''));
    } else if (event.type === 'error') addItem({ kind: 'error', text: String(data.message || 'Erreur inconnue') });
  }

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault();
    const text = message.trim();
    if (!text || busy) return;
    setMessage(''); addItem({ kind: 'user', text }); setBusy(true);
    const controller = new AbortController(); abortRef.current = controller;
    try {
      const url = `${apiBase}/jarvis/stream?message=${encodeURIComponent(text)}&session_id=${encodeURIComponent(sessionId)}`;
      const response = await apiFetch(url, { signal: controller.signal, headers: { Accept: 'text/event-stream' } });
      if (!response.ok) throw apiError(response);
      if (!response.body) throw new Error('Flux SSE indisponible');
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split(/\r?\n\r?\n/); buffer = frames.pop() || '';
        for (const frame of frames) {
          const payload = frame.split(/\r?\n/).find((line) => line.startsWith('data:'))?.slice(5).trim();
          if (!payload) continue;
          try { handleEvent(JSON.parse(payload)); } catch { /* ignore malformed SSE frame */ }
        }
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError') addItem({ kind: 'error', text: (error as Error).message === 'auth' ? 'Authentification requise par le serveur.' : `Service indisponible : ${(error as Error).message}` });
    } finally { setBusy(false); abortRef.current = null; inputRef.current?.focus(); }
  }

  async function resolveConfirmation(confirmed: boolean) {
    if (!confirmation) return;
    try {
      const response = await apiFetch(`${apiBase}/jarvis/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, action_id: confirmation.action_id, confirmed }) });
      if (!response.ok) throw apiError(response);
      addItem({ kind: 'event', text: confirmed ? 'Action autorisée.' : 'Action refusée.' });
    } catch { addItem({ kind: 'error', text: 'La confirmation n’a pas pu être transmise.' }); }
    setConfirmation(null);
  }

  async function saveOnboarding(): Promise<boolean> {
    setOnboardingSaving(true); setOnboardingError('');
    try {
      const response = await apiFetch(`${apiBase}/jarvis/onboarding`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(onboardingData),
      });
      if (!response.ok) throw apiError(response);
      setOnboardingCompleted(true);
      return true;
    } catch (error) {
      setOnboardingError((error as Error).message === 'auth' ? 'L’accès au serveur demande une authentification.' : 'Impossible d’enregistrer le profil chiffré. Vérifiez la connexion puis réessayez.');
      return false;
    } finally { setOnboardingSaving(false); }
  }

  async function beginTotpSetup() {
    setTotpBusy(true); setTotpError('');
    try {
      const response = await fetch(`${apiBase}/jarvis/auth/totp/enrollment`, { method: 'POST' });
      if (!response.ok) throw apiError(response);
      const enrollment = await response.json() as { secret: string };
      setTotpSetupSecret(enrollment.secret); setTotpStatus({ enabled: false, enrollment_pending: true });
    } catch (error) {
      setTotpError((error as Error).message === 'auth' ? 'L’enrôlement doit être lancé depuis un appareil de confiance.' : 'Impossible de créer l’enrôlement TOTP chiffré.');
    } finally { setTotpBusy(false); }
  }

  async function confirmTotpSetup() {
    setTotpBusy(true); setTotpError('');
    try {
      const response = await fetch(`${apiBase}/jarvis/auth/totp/enrollment/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: totpCode }) });
      if (!response.ok) throw apiError(response);
      setTotpCode(''); setTotpSetupSecret(''); await refreshTotpStatus();
    } catch (error) {
      setTotpError((error as Error).message === 'auth' ? 'L’activation TOTP doit être confirmée depuis un appareil de confiance.' : 'Code invalide ou activation TOTP impossible.');
    } finally { setTotpBusy(false); }
  }

  async function resetTotp() {
    if (!window.confirm('Réinitialiser le TOTP distant ? Les sessions distantes actives seront révoquées.')) return;
    setTotpBusy(true); setTotpError('');
    try {
      const response = await fetch(`${apiBase}/jarvis/auth/totp`, { method: 'DELETE' });
      if (!response.ok) throw apiError(response);
      setTotpCode(''); setTotpSetupSecret(''); await refreshTotpStatus();
    } catch { setTotpError('Réinitialisation refusée ou chiffrement de profil indisponible.'); }
    finally { setTotpBusy(false); }
  }

  function onRemoteAuthenticated(token: string) {
    const session = { apiBase, token };
    authContextRef.current = { apiBase, remoteSession: session };
    setRemoteSession(session); setRemoteAuthError(''); setRemoteAuthOpen(false);
    setOnboardingRetry((value) => value + 1);
  }

  function selectApiBase(nextApiBase: string) {
    authContextRef.current = { apiBase: nextApiBase, remoteSession: null };
    setRemoteSession(null); setApiBase(nextApiBase);
  }

  function onInputKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendMessage(); }
  }

  function saveInstance() {
    const url = instanceDraft.url.trim().replace(/\/$/, ''); const name = instanceDraft.nom.trim();
    try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol) || !name) return; }
    catch { return; }
    const next = [...instances.filter((item) => item.id !== 'local' && item.url !== url), { id: crypto.randomUUID(), nom: name, url }];
    setInstances([localInstance, ...next]); localStorage.setItem('jarvis-instances', JSON.stringify(next));
    setInstanceDraft({ nom: '', url: '' });
  }

  async function discoverInstances() {
    setDiscovering(true); setDiscoveryResults([]);
    try {
      const response = await apiFetch(`${apiBase}/jarvis/discover`, { cache: 'no-store' });
      if (!response.ok) throw apiError(response);
      const data = await response.json();
      setDiscoveryResults((data.devices || []).map((device: { nom: string; ip: string }) => ({ ...device, id: crypto.randomUUID(), url: `http://${device.ip}:8000` })));
    } catch (error) {
      addItem({ kind: 'error', text: (error as Error).message === 'auth' ? 'La découverte demande une authentification.' : `Découverte réseau impossible : ${(error as Error).message}` });
    } finally { setDiscovering(false); }
  }

  function addDiscoveredInstance(instance: { nom: string; url: string }) {
    const next = [...instances.filter((item) => item.id !== 'local' && item.url !== instance.url), { id: crypto.randomUUID(), ...instance }];
    setInstances([localInstance, ...next]); localStorage.setItem('jarvis-instances', JSON.stringify(next));
    selectApiBase(instance.url); setShowInstances(false); setDiscoveryResults([]);
  }

  const activeLayout = layouts.find((item) => item.id === layout) || layouts[0];
  const memoryEncrypted = status.security?.memory_backend === 'encrypted' && status.security.encryption?.enabled;
  const markDataShieldUnlocked = () => {
    setUnlockStatus((current) => current ? { ...current, locked: false } : current);
    setOnboardingRetry((value) => value + 1);
    void refreshStatus();
  };

  if (!onboardingReady || !onboardingCompleted || !onboardingDismissed) {
    return <><OnboardingWizard
      loading={!onboardingReady} error={onboardingError} workflows={onboardingWorkflows}
      data={onboardingData} onChange={setOnboardingData} memoryEncrypted={!!memoryEncrypted}
      securityReady={status.security?.memory_backend !== undefined && status.security.encryption?.enabled !== undefined}
      serviceOnline={service === 'online'} saving={onboardingSaving}
      retry={() => setOnboardingRetry((value) => value + 1)} onSave={saveOnboarding}
      onDone={() => setOnboardingDismissed(true)}
    />{unlockStatus?.locked && <UnlockDialog apiBase={apiBase} helloAvailable={unlockStatus.hello_available} dpapiRecoveryAvailable={Boolean(unlockStatus.dpapi_recovery_available)} onUnlocked={markDataShieldUnlocked} />}{remoteAuthOpen && <RemoteAuthDialog apiBase={apiBase} error={remoteAuthError} onError={setRemoteAuthError} onAuthenticated={onRemoteAuthenticated} />}</>;
  }

  return <div className="app-shell">
    <nav className="sidebar" aria-label="Navigation principale">
      <div className="brand"><div className="brand-mark" aria-hidden="true">G</div><div><strong>GREATOS</strong><span>J.A.R.V.I.S</span></div></div>
      <div className="nav-label">ESPACE</div>
      <button className={`nav-item ${view === 'chat' ? 'selected' : ''}`} aria-pressed={view === 'chat'} onClick={() => setView('chat')}><span aria-hidden="true">◈</span> Conversation</button>
      <button className={`nav-item ${view === 'dashboard' ? 'selected' : ''}`} aria-pressed={view === 'dashboard'} onClick={() => { setView('dashboard'); void refreshStatus(); void refreshSessions(); }}><span aria-hidden="true">▦</span> Vue d’ensemble</button>
      <button className="nav-item" onClick={() => window.open(`${apiBase}/hud`, '_blank')}><span aria-hidden="true">◖</span> HUD Réacteur Arc</button>
      <div className="nav-label layouts-label">INTERFACE MORPHIQUE</div>
      <div className="layout-list" role="group" aria-label="Layout contextuel actif"><div className="layout-item selected" aria-current="true"><span aria-hidden="true">{activeLayout.icon}</span>{activeLayout.label}<i aria-hidden="true" /></div><div className="layout-context">{appContext || 'Adaptation au contexte Windows'}</div></div>
      <div className="sidebar-bottom"><div className="instance-switch"><span>INSTANCE</span><select aria-label="Instance Jarvis" value={apiBase} onChange={(event) => selectApiBase(event.target.value)}>{instances.map((item) => <option value={item.url} key={item.id}>{item.nom}</option>)}</select><button type="button" aria-label="Gérer les instances" onClick={() => setShowInstances((value) => !value)}>＋</button></div>{showInstances && <div className="instance-form"><input aria-label="Nom de l’instance" placeholder="Nom" value={instanceDraft.nom} onChange={(event) => setInstanceDraft({ ...instanceDraft, nom: event.target.value })} /><input aria-label="Adresse de l’instance" placeholder="URL https://…" value={instanceDraft.url} onChange={(event) => setInstanceDraft({ ...instanceDraft, url: event.target.value })} /><button onClick={saveInstance}>Ajouter une instance</button><button className="discover-button" onClick={() => void discoverInstances()}>{discovering ? 'Recherche…' : 'Découverte Tailscale'}</button>{discoveryResults.map((instance) => <div className="discovery-row" key={instance.id}><span><b>{instance.nom}</b><small>{instance.ip}</small></span><button onClick={() => addDiscoveredInstance(instance)}>Ajouter</button></div>)}</div>}<div className="connection"><i className={`connection-dot ${service}`} aria-hidden="true" /><span>{service === 'online' ? 'Système opérationnel' : service === 'auth' ? 'Authentification requise' : service === 'checking' ? 'Connexion…' : 'Système hors ligne'}</span><button type="button" aria-label="Actualiser l’état de GreatOS" onClick={() => void refreshStatus()}>↻</button></div></div>
    </nav>

    <main className="main-column">
      <header className="topbar"><div><div className="eyebrow">{view === 'dashboard' ? 'PROGRESS TRACKER · SYSTÈME' : 'ASSISTANT PERSONNEL'}</div><h1>{view === 'dashboard' ? 'Vue d’ensemble' : 'Conversation'}</h1></div><div className="topbar-right"><div className="context-badge"><span aria-hidden="true">{activeLayout.icon}</span><b>{activeLayout.label}</b>{appContext && <em>· {appContext}</em>}</div><button className="icon-button" onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')} aria-label="Changer de thème">{theme === 'dark' ? '☼' : '☾'}</button><div className="avatar" aria-hidden="true">G</div></div></header>
      {view === 'chat' ? <>
        <div className="feed" ref={feedRef} role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation J.A.R.V.I.S">
          {items.length === 0 && <div className="welcome"><div className="orbital"><div className="orbital-core">G</div></div><div className="eyebrow">VOTRE ASSISTANT PERSONNEL</div><h2>À votre service.</h2><p>Je suis prêt à vous aider.</p><div className="suggestions"><button onClick={() => setMessage('Résume mon activité récente')}>⌁ <span>Résume mon activité récente</span></button><button onClick={() => setMessage('Aide-moi à organiser mes tâches')}>◷ <span>Organise mes tâches</span></button><button onClick={() => setMessage('Que se passe-t-il sur mon écran ?')}>▧ <span>Analyse mon écran</span></button></div></div>}
          {items.map((item) => <article className={`feed-item ${item.kind}`} key={item.id}><div className="message-avatar" aria-hidden="true">{item.kind === 'user' ? 'C' : item.kind === 'assistant' ? 'G' : item.kind === 'error' ? '!' : '·'}</div><div className="message-content">{item.kind !== 'event' && <div className="message-author">{item.kind === 'user' ? 'VOUS' : item.kind === 'error' ? 'SYSTÈME' : 'J.A.R.V.I.S'}{item.time && <time>{item.time}</time>}</div>}<p>{item.text}</p></div></article>)}
          {busy && <div className="thinking"><span /><span /><span /> J.A.R.V.I.S réfléchit</div>}
        </div>
        <form className="composer" onSubmit={sendMessage}><div className="composer-box"><textarea ref={inputRef} rows={1} value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={onInputKeyDown} placeholder="Écrivez à J.A.R.V.I.S…" aria-label="Message à J.A.R.V.I.S" /><div className="composer-actions"><span>Entrée pour envoyer · Maj + Entrée pour une nouvelle ligne</span><div>{busy && <button type="button" className="cancel-button" onClick={() => abortRef.current?.abort()}>Arrêter</button>}<button type="submit" className="send-button" disabled={!message.trim() || busy} aria-label="Envoyer">↑</button></div></div></div></form>
      </> : <div className="dashboard-view"><section className="progress-section"><div className="section-title"><div><div className="eyebrow">SUIVI DES OBJECTIFS</div><h2>Progress Tracker</h2></div><button className="text-button" onClick={() => void refreshProgress()} disabled={progressLoading}>{progressLoading ? 'Actualisation…' : 'Actualiser'}</button></div>{progressError ? <div className="empty-state" role="status">{progressError}</div> : progressDashboard && <><div className="metric-grid progress-metrics"><Metric label="Objectifs suivis" value={String(progressDashboard.summary.total)} detail={`${progressDashboard.summary.actifs} actifs`} /><Metric label="Progression moyenne" value={`${progressDashboard.summary.progression_moyenne}%`} detail="Sur l’ensemble des objectifs" /><Metric label="Objectifs terminés" value={`${progressDashboard.summary.taux_completion}%`} detail={`${progressDashboard.summary.termines} terminés`} good /></div>{progressDashboard.goals.length ? <section className="panel goals-panel"><div className="panel-heading"><div><div className="eyebrow">PROGRESSION PAR OBJECTIF</div><h3>Avancement</h3></div><span className="chart-unit">0–100 %</span></div><div className="goal-chart" style={{ height: `${Math.max(170, progressDashboard.goals.length * 36)}px` }} role="img" aria-label={`Progression de ${progressDashboard.goals.length} objectifs` }><canvas ref={progressChartRef} /></div><ul className="goal-progress-list" aria-label="Détail de progression des objectifs">{progressDashboard.goals.map((goal) => <li key={goal.id}><div className="goal-row-label"><span>{goal.title}</span><strong>{goal.progress}%</strong></div><div className="goal-track" role="progressbar" aria-label={`Progression : ${goal.title}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={goal.progress}><span style={{ width: `${goal.progress}%` }} /></div></li>)}</ul></section> : <div className="empty-state progress-empty">Aucun objectif suivi pour le moment.</div>}</>}{!progressError && !progressDashboard && <div className="empty-state" aria-live="polite">{progressLoading ? 'Chargement des objectifs…' : 'Aucune donnée disponible.'}</div>}</section>{totpManagedHere && <><section className="panel totp-panel"><div className="panel-heading"><div><div className="eyebrow">DATASHIELD · ACCÈS DISTANT</div><h2>Authentification TOTP</h2></div><span className={totpStatus?.enabled ? 'good' : 'warn'}>{totpStatus?.enabled ? 'Activée' : 'Non activée'}</span></div>{totpError && <p className="totp-error" role="status">{totpError}</p>}{totpStatus?.enabled ? <><p className="totp-description">Les connexions depuis un réseau non approuvé demandent la clé Bearer et un code temporaire. Les sessions durent 30 minutes.</p><button className="secondary-button" disabled={totpBusy} onClick={() => void resetTotp()}>Réinitialiser l’authentification distante</button></> : !totpSetupSecret ? <><p className="totp-description">Le secret sera conservé dans le profil chiffré. L’enrôlement et la réinitialisation restent réservés à un appareil local ou Tailscale.</p><button className="primary-button" disabled={totpBusy || !totpStatus} onClick={() => void beginTotpSetup()}>{totpBusy ? 'Préparation…' : totpStatus?.enrollment_pending ? 'Recommencer l’enrôlement' : 'Configurer le TOTP distant'}</button></> : <><p className="totp-description">Ajoute cette clé à une application d’authentification, puis saisis le code généré pour confirmer l’enrôlement.</p><code className="totp-secret">{totpSetupSecret}</code><label className="totp-code-label">Code de vérification<input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, '').slice(0, 6))} /></label><button className="primary-button" disabled={totpBusy || totpCode.length !== 6} onClick={() => void confirmTotpSetup()}>{totpBusy ? 'Vérification…' : 'Confirmer l’enrôlement'}</button></>}</section><HelloEnrollmentPanel apiBase={apiBase} /></>}<div className="dashboard-panels"><section className="panel"><div className="panel-heading"><div><div className="eyebrow">ACTIVITÉ</div><h2>Sessions navigateur</h2></div><button className="text-button" onClick={() => void refreshSessions()}>Actualiser</button></div>{browserSessions.length ? browserSessions.slice(0, 6).map((session, index) => <div className="browser-session" key={String(session.session_id || index)}><div className="session-icon" aria-hidden="true">◎</div><div><strong>{String(session.current_title || session.session_id || 'Session navigateur')}</strong><span>{String(session.current_url || 'Page non renseignée')}</span></div><small>{String(session.state || 'active')}</small></div>) : <div className="empty-state">Aucune session navigateur active.</div>}</section><section className="panel"><div className="eyebrow">ÉTAT DE GREATOS</div><h2>Capacités système</h2><div className="capability-row"><span>API Jarvis</span><b className={service === 'online' ? 'good' : 'warn'}>{service === 'online' ? 'Connectée' : 'Indisponible'}</b></div><div className="capability-row"><span>Instance active</span><b>{activeInstance?.nom || 'Personnalisée'}</b></div><div className="capability-row"><span>Chiffrement mémoire</span><b className={memoryEncrypted ? 'good' : 'warn'}>{memoryEncrypted ? 'AES-256-GCM' : 'À vérifier'}</b></div><div className="capability-row"><span>Entrée Vocale</span><b className={status.voice?.audio_input_ready ? 'good' : 'warn'}>{status.voice?.audio_input_ready ? 'Active (Synaptics / Vosk)' : 'Prête'}</b></div><div className="capability-row"><span>Filtre Anti-Hallucinations</span><b className="good">Actif (38+ signatures)</b></div><div className="capability-row"><span>Mises à jour automatiques</span><b className="good">Cycle 12h glissantes</b></div><button className="primary-button full" onClick={() => setView('chat')}>Ouvrir la conversation</button></section></div></div>}
      <footer className="footer"><span>GREATOS PERSONAL OS</span><span>Données conservées localement · Cloud préféré pour le calcul</span><span>WINDOWS</span></footer>
    </main>

    {confirmation && <ConfirmationDialog confirmation={confirmation} onResolve={resolveConfirmation} />}
    {unlockStatus?.locked && <UnlockDialog apiBase={apiBase} helloAvailable={unlockStatus.hello_available} dpapiRecoveryAvailable={Boolean(unlockStatus.dpapi_recovery_available)} onUnlocked={markDataShieldUnlocked} />}
    {remoteAuthOpen && <RemoteAuthDialog apiBase={apiBase} error={remoteAuthError} onError={setRemoteAuthError} onAuthenticated={onRemoteAuthenticated} />}
  </div>;
}

function useModalFocus(dialogRef: { current: HTMLElement | null }) {
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const getFocusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ));
    dialog.focus();
    const containTab = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const focusable = getFocusable();
      if (!focusable.length) { event.preventDefault(); dialog.focus(); return; }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog || !dialog.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener('keydown', containTab);
    return () => {
      document.removeEventListener('keydown', containTab);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);
}

function ConfirmationDialog({ confirmation, onResolve }: { confirmation: Confirmation; onResolve: (approved: boolean) => Promise<void> }) {
  const dialogRef = useRef<HTMLElement>(null);
  useModalFocus(dialogRef);
  return <div className="modal-backdrop" role="presentation"><section ref={dialogRef} tabIndex={-1} className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description"><div className="warning-mark" aria-hidden="true">!</div><div className="eyebrow">AUTORISATION REQUISE</div><h2 id="confirm-title">Confirmer cette action</h2><p id="confirm-description">J.A.R.V.I.S souhaite : <strong>{confirmation.description}</strong></p><div className="modal-actions"><button className="secondary-button" onClick={() => void onResolve(false)}>Refuser</button><button className="primary-button" onClick={() => void onResolve(true)}>Autoriser</button></div></section></div>;
}

function HelloEnrollmentPanel({ apiBase }: { apiBase: string }) {
  const [enrolled, setEnrolled] = useState(false);
  const [prfProtected, setPrfProtected] = useState(false);
  const [enrollmentAllowed, setEnrollmentAllowed] = useState(false);
  const [keyWrappingAllowed, setKeyWrappingAllowed] = useState(false);
  const [creationNeedsReview, setCreationNeedsReview] = useState(readHelloCreationPending);
  const [credentialReviewed, setCredentialReviewed] = useState(readHelloCredentialReviewed);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    let active = true;
    fetch(`${apiBase}/jarvis/security/hello`, { cache: 'no-store' })
      .then(async (response) => response.ok ? await response.json() as { enrolled: boolean; key_wrapped?: boolean; enrollment_allowed?: boolean; key_wrapping_allowed?: boolean } : null)
      .then((result) => { if (active && result) { setEnrolled(result.enrolled); setPrfProtected(result.key_wrapped === true); setEnrollmentAllowed(result.enrollment_allowed === true); setKeyWrappingAllowed(result.key_wrapping_allowed === true); if (result.enrolled) { setHelloCreationPending(false); setCreationNeedsReview(false); setHelloCredentialReviewed(true); setCredentialReviewed(true); } } })
      .catch(() => undefined);
    return () => { active = false; };
  }, [apiBase]);

  const wrapDataShieldKey = async () => {
    const keyOptionsResponse = await fetch(`${apiBase}/jarvis/security/hello/enrollment/key-options`, { method: 'POST', cache: 'no-store' });
    if (!keyOptionsResponse.ok) throw await apiFailure(keyOptionsResponse, 'La préparation du verrou DataShield a échoué. La clé de secours reste disponible.');
    const keyCeremony = await keyOptionsResponse.json() as { ceremony_id: string; publicKey: Record<string, any> };
      const keyCredential = await navigator.credentials.get({ publicKey: publicKeyOptions(keyCeremony.publicKey, true) });
    if (!(keyCredential instanceof PublicKeyCredential)) throw new Error('La confirmation Windows Hello a été annulée. Le credential reste enregistré.');
    const prfOutput = prfOutputBase64Url(keyCredential);
    const keyFinish = await fetch(`${apiBase}/jarvis/security/hello/enrollment/key-confirm`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ceremony_id: keyCeremony.ceremony_id, credential: webAuthnCredentialJson(keyCredential, false), prf_output: prfOutput }),
    });
    if (!keyFinish.ok) throw await apiFailure(keyFinish, 'Windows Hello est enregistré, mais le verrou DataShield n’a pas pu être activé. La clé de secours reste disponible.');
  };

  const activateExistingCredential = async () => {
    if (!keyWrappingAllowed) { setMessage(`Windows Hello est enrôlé comme second facteur distant. Le déverrouillage DataShield suit la session Windows (${window.location.origin}).`); return; }
    if (!navigator.credentials || !window.isSecureContext) { setMessage('Windows Hello nécessite une origine sécurisée.'); return; }
    setBusy(true); setMessage('');
    try { await wrapDataShieldKey(); setPrfProtected(true); setMessage('Windows Hello protège maintenant le déverrouillage local.'); }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Activation du verrou Windows Hello impossible.'); }
    finally { setBusy(false); }
  };

  const acknowledgeCredentialReview = () => {
    if (!setHelloCreationPending(false) || !setHelloCredentialReviewed(true)) { setMessage('Le navigateur ne peut pas enregistrer la vérification de sécurité. Autorise le stockage local avant de continuer.'); return; }
    setCreationNeedsReview(false);
    setCredentialReviewed(true);
    setMessage('Contrôle enregistré. Tu peux maintenant relancer une création si aucun passkey GreatOS résiduel n’est conservé dans Windows.');
  };

  const enroll = async () => {
    if (creationNeedsReview && !enrolled) { setMessage('Une tentative précédente a peut-être créé un passkey Windows non enregistré par GreatOS. Vérifie-le dans Windows avant de relancer une création.'); return; }
    if (!enrollmentAllowed) { setMessage(`Configure Windows Hello depuis l’application GreatOS installée, à ${window.location.origin}.`); return; }
    if (enrolled) { if (keyWrappingAllowed) await activateExistingCredential(); else setMessage('Le second facteur Windows Hello distant est déjà configuré.'); return; }
    if (!credentialReviewed) { setMessage('Vérifie dans Windows qu’aucun passkey GreatOS orphelin ne subsiste avant d’en créer un.'); return; }
    if (!navigator.credentials || !window.isSecureContext) { setMessage('Windows Hello nécessite une origine sécurisée.'); return; }
    setBusy(true); setMessage('');
    try {
      const begin = await fetch(`${apiBase}/jarvis/security/hello/enrollment`, { method: 'POST', cache: 'no-store' });
      if (!begin.ok) throw await apiFailure(begin, 'Impossible de démarrer l’enrôlement Windows Hello.');
      const ceremony = await begin.json() as { ceremony_id: string; publicKey: Record<string, any>; prf_salt?: string };
      if (!setHelloCredentialReviewed(false) || !setHelloCreationPending(true)) throw new Error('Le navigateur ne peut pas enregistrer le garde anti-doublon. Autorise le stockage local avant de créer un passkey.');
      setCreationNeedsReview(true); setCredentialReviewed(false);
      const credential = await navigator.credentials.create({ publicKey: creationOptions(ceremony.publicKey, ceremony.prf_salt) });
      if (!(credential instanceof PublicKeyCredential)) throw new Error('L’enrôlement Windows Hello a été annulé.');
      const finish = await fetch(`${apiBase}/jarvis/security/hello/enrollment/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ceremony_id: ceremony.ceremony_id, credential: webAuthnCredentialJson(credential) }) });
      if (!finish.ok) throw await apiFailure(finish, 'Windows Hello n’a pas pu être enregistré.');
      setHelloCreationPending(false); setCreationNeedsReview(false);
      setEnrolled(true);
      if (keyWrappingAllowed) {
        await wrapDataShieldKey();
        setEnrolled(true); setPrfProtected(true); setMessage('Windows Hello protège maintenant le déverrouillage local.');
      } else {
        setMessage('Windows Hello est configuré comme second facteur distant. DataShield local reste protégé par son mécanisme actuel.');
      }
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Enrôlement Windows Hello impossible.'); }
    finally { setBusy(false); }
  };

  const panelTitle = 'Windows Hello · second facteur distant';
  const panelDescription = 'Windows Hello peut servir de second facteur aux connexions distantes HTTPS, après la clé Bearer. DataShield local suit la session du compte Windows via DPAPI CurrentUser; toute ancienne enveloppe Hello est conservée comme voie de migration et ne remplace pas DPAPI. Configure le second facteur depuis un appareil local ou Tailscale de confiance.';
  const securityStatus = prfProtected ? 'Migration DPAPI requise' : enrolled ? 'Second facteur actif' : 'Optionnel';
  return <section className="panel totp-panel"><div className="panel-heading"><div><div className="eyebrow">DATASHIELD · SÉCURITÉ</div><h2>{panelTitle}</h2></div><span className={prfProtected || enrolled ? 'good' : 'warn'}>{securityStatus}</span></div><p className="totp-description">{panelDescription}</p>{prfProtected && <p className="totp-description">Déverrouille une fois DataShield avec Windows Hello ou la clé de secours afin de créer et valider le coffre DPAPI de ce compte Windows.</p>}{creationNeedsReview && !enrolled && <p className="totp-error" role="status">Une tentative antérieure a peut-être laissé un passkey dans Windows. Vérifie ou supprime ce passkey avant toute nouvelle création.</p>}{!credentialReviewed && !enrolled && enrollmentAllowed && <button className="secondary-button" type="button" disabled={busy} onClick={acknowledgeCredentialReview}>{creationNeedsReview ? 'J’ai vérifié/supprimé le passkey précédent dans Windows' : 'J’ai vérifié qu’aucun passkey GreatOS ne subsiste dans Windows'}</button>}{message && <p className="totp-error" role="status">{message}</p>}<button className="primary-button" disabled={busy || prfProtected || (enrolled && !keyWrappingAllowed) || (!enrollmentAllowed && !enrolled) || (!credentialReviewed && !enrolled) || (creationNeedsReview && !enrolled)} onClick={() => void enroll()}>{busy ? 'Enrôlement…' : prfProtected ? 'Migration DPAPI requise' : enrolled && !keyWrappingAllowed ? 'Second facteur distant actif' : enrolled ? 'Configurer Windows Hello' : creationNeedsReview ? 'Vérification Windows requise' : !credentialReviewed ? 'Vérification Windows requise' : enrollmentAllowed ? 'Configurer Windows Hello' : 'Disponible dans l’application installée'}</button></section>;
}

function UnlockDialog({ apiBase, helloAvailable, dpapiRecoveryAvailable, onUnlocked }: { apiBase: string; helloAvailable: boolean; dpapiRecoveryAvailable: boolean; onUnlocked: () => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useModalFocus(dialogRef);

  const submitManual = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const response = await fetch(`${apiBase}/jarvis/security/unlock/manual`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) });
      if (!response.ok) throw new Error('La clé DataShield est incorrecte ou le trousseau est indisponible.');
      setKey(''); onUnlocked();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Déverrouillage impossible.'); }
    finally { setBusy(false); }
  };

  const unlockWithDpapi = async () => {
    setBusy(true); setError('');
    try {
      const response = await fetch(`${apiBase}/jarvis/security/unlock/dpapi`, { method: 'POST', cache: 'no-store' });
      if (!response.ok) throw await apiFailure(response, 'La récupération locale DataShield a échoué.');
      onUnlocked();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'La récupération locale DataShield a échoué.'); }
    finally { setBusy(false); }
  };

  const unlockWithHello = async () => {
    if (!navigator.credentials || !window.isSecureContext) { setError('Windows Hello nécessite une origine sécurisée.'); return; }
    setBusy(true); setError('');
    try {
      const begin = await fetch(`${apiBase}/jarvis/security/unlock/hello/options`, { method: 'POST', cache: 'no-store' });
      if (!begin.ok) throw new Error('Windows Hello n’est pas enrôlé ou n’est pas disponible.');
      const ceremony = await begin.json() as { ceremony_id: string; publicKey: Record<string, any> };
      const credential = await navigator.credentials.get({ publicKey: publicKeyOptions(ceremony.publicKey, true) });
      if (!(credential instanceof PublicKeyCredential)) throw new Error('La vérification Windows Hello a été annulée.');
      const prfOutput = prfOutputBase64Url(credential);
      const finish = await fetch(`${apiBase}/jarvis/security/unlock/hello/verify`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ceremony_id: ceremony.ceremony_id, credential: webAuthnCredentialJson(credential, false), prf_output: prfOutput }) });
      if (!finish.ok) throw new Error('Windows Hello n’a pas pu déverrouiller DataShield.');
      onUnlocked();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Windows Hello est indisponible.'); }
    finally { setBusy(false); }
  };

  return <div className="modal-backdrop security-lock-backdrop" role="presentation"><section ref={dialogRef} tabIndex={-1} className="confirm-modal remote-auth-modal" role="dialog" aria-modal="true" aria-labelledby="unlock-title" aria-describedby="unlock-description"><div className="eyebrow">DATASHIELD · PROFIL WINDOWS</div><h2 id="unlock-title">Déverrouiller GreatOS</h2><p id="unlock-description">Le profil chiffré est verrouillé. Utilise Windows Hello, la récupération locale liée à ton compte Windows ou la clé DataShield de secours.</p>{error && <p className="totp-error" role="alert">{error}</p>}{helloAvailable && <button className="primary-button full" type="button" disabled={busy} onClick={() => void unlockWithHello()}>{busy ? 'Vérification…' : 'Déverrouiller avec Windows Hello'}</button>}{dpapiRecoveryAvailable && <><button className="secondary-button full" type="button" disabled={busy} onClick={() => void unlockWithDpapi()}>{busy ? 'Récupération…' : 'Récupérer via le compte Windows'}</button><p className="totp-description">Utilise le coffre DPAPI de cette session Windows. La clé n’est ni affichée ni transmise au navigateur.</p></>}<form onSubmit={submitManual}><label className="totp-code-label">Clé DataShield de secours<input type="password" autoComplete="off" value={key} onChange={(event) => setKey(event.target.value)} required /></label><button className="secondary-button full" type="submit" disabled={busy || !key}>{busy ? 'Déverrouillage…' : 'Utiliser la clé de secours'}</button></form></section></div>;
}

function RemoteAuthDialog({ apiBase, error, onError, onAuthenticated }: { apiBase: string; error: string; onError: (message: string) => void; onAuthenticated: (token: string) => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  const [apiKey, setApiKey] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  useModalFocus(dialogRef);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!apiKey || code.length !== 6 || busy) return;
    setBusy(true); onError('');
    try {
      const response = await fetch(`${apiBase}/jarvis/auth/session`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      const data = await response.json().catch(() => ({})) as { access_token?: string; detail?: string };
      if (!response.ok || !data.access_token) throw new Error(data.detail || 'Authentification distante refusée.');
      setApiKey(''); setCode(''); onAuthenticated(data.access_token);
    } catch (authError) {
      setApiKey(''); setCode('');
      onError((authError as Error).message || 'Impossible de joindre l’instance distante.');
    } finally { setBusy(false); }
  }

    async function submitHello() {
      if (!apiKey || busy) return;
      if (!navigator.credentials || !window.isSecureContext) { onError('Windows Hello nécessite une origine sécurisée.'); return; }
      setBusy(true); onError('');
      try {
        const headers = { Authorization: `Bearer ${apiKey}` };
        const begin = await fetch(`${apiBase}/jarvis/auth/session/hello/options`, { method: 'POST', headers, cache: 'no-store' });
        const optionsBody = await begin.json().catch(() => ({})) as { ceremony_id?: string; publicKey?: Record<string, any>; detail?: string };
        if (!begin.ok || !optionsBody.ceremony_id || !optionsBody.publicKey) throw new Error(optionsBody.detail || 'Windows Hello distant indisponible.');
        const credential = await navigator.credentials.get({ publicKey: publicKeyOptions(optionsBody.publicKey) });
        if (!(credential instanceof PublicKeyCredential)) throw new Error('La vérification Windows Hello a été annulée.');
        const response = await fetch(`${apiBase}/jarvis/auth/session/hello`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ ceremony_id: optionsBody.ceremony_id, credential: webAuthnCredentialJson(credential) }) });
        const data = await response.json().catch(() => ({})) as { access_token?: string; detail?: string };
        if (!response.ok || !data.access_token) throw new Error(data.detail || 'Authentification Windows Hello refusée.');
        setApiKey(''); setCode(''); onAuthenticated(data.access_token);
      } catch (authError) { onError((authError as Error).message || 'Windows Hello distant indisponible.'); }
      finally { setBusy(false); }
    }

    return <div className="modal-backdrop" role="presentation"><section ref={dialogRef} tabIndex={-1} className="confirm-modal remote-auth-modal" role="dialog" aria-modal="true" aria-labelledby="remote-auth-title" aria-describedby="remote-auth-description"><div className="eyebrow">DATASHIELD · INSTANCE DISTANTE</div><h2 id="remote-auth-title">Authentification requise</h2><p id="remote-auth-description">Saisis la clé Bearer puis choisis Windows Hello ou un code TOTP. La session sera gardée en mémoire pendant 30 minutes.</p><label className="totp-code-label">Clé d’accès<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} required /></label>{error && <p className="totp-error" role="alert">{error}</p>}<button className="primary-button full" type="button" disabled={busy || !apiKey} onClick={() => void submitHello()}>{busy ? 'Vérification…' : 'Continuer avec Windows Hello'}</button><form onSubmit={submit}><label className="totp-code-label">Code TOTP de secours<input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} /></label><button className="secondary-button full" type="submit" disabled={busy || !apiKey || code.length !== 6}>{busy ? 'Vérification…' : 'Utiliser le TOTP'}</button></form></section></div>;
}

function Metric({ label, value, detail, good }: { label: string; value: string; detail: string; good?: boolean }) {
  return <section className="metric-card"><div className="metric-label">{label}</div><div className={`metric-value ${good === undefined ? '' : good ? 'good' : 'warn'}`}>{value}</div><div className="metric-detail">{detail}</div></section>;
}

function OnboardingWizard({
  loading, error, workflows, data, onChange, memoryEncrypted, securityReady, serviceOnline, saving, retry, onSave, onDone,
}: {
  loading: boolean; error: string; workflows: OnboardingWorkflow[]; data: OnboardingData;
  onChange: (value: OnboardingData) => void; memoryEncrypted: boolean; securityReady: boolean;
  serviceOnline: boolean; saving: boolean; retry: () => void; onSave: () => Promise<boolean>; onDone: () => void;
}) {
  const [step, setStep] = useState(0);
  const stepHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { stepHeadingRef.current?.focus(); }, [error, loading, step]);
  const stepNames = ['Bienvenue', 'Découverte', 'Workflow', 'Configuration', 'Terminé'];
  const workflowByActivity: Record<string, string> = {
    development: 'session_dev', maintenance: 'nettoyage_systeme',
    data_protection: 'sauvegarde_securisee', project_tracking: 'synthese_projet', other: 'synthese_projet',
  };
  const recommendedId = workflowByActivity[data.activity] || '';
  const recommended = workflows.find((workflow) => workflow.id === recommendedId);
  const update = (patch: Partial<OnboardingData>) => onChange({ ...data, ...patch });

  if (loading || error) return <main className="onboarding-shell"><section className="onboarding-card onboarding-gate" aria-live="polite">
    <div className="brand-mark">G</div><div className="eyebrow">GREATOS · PREMIÈRE UTILISATION</div>
    <h1>{loading ? 'Chargement de votre profil' : 'Connexion nécessaire'}</h1>
    <p>{loading ? 'Lecture sécurisée de votre profil local…' : error}</p>
    {!loading && <button className="primary-button" onClick={retry}>Réessayer</button>}
  </section></main>;

  const next = async () => {
    if (step === 1 && !data.activity) return;
    if (step === 2 && !data.workflow_id) return;
    if (step === 3) {
      if (!serviceOnline || !securityReady || !memoryEncrypted) return;
      if (await onSave()) { setSaved(true); setStep(4); }
      return;
    }
    setStep((current) => Math.min(current + 1, 4));
  };

  return <main className="onboarding-shell">
    <section className="onboarding-card" aria-labelledby="onboarding-title">
      <header className="onboarding-head"><div className="brand"><div className="brand-mark" aria-hidden="true">G</div><div><strong>GREATOS</strong><span>J.A.R.V.I.S</span></div></div><span className="onboarding-duration">5 étapes · 5 min</span></header>
      <div className="onboarding-progress" role="progressbar" aria-label="Progression de l’onboarding" aria-valuemin={1} aria-valuemax={5} aria-valuenow={step + 1}><div style={{ width: `${((step + 1) / 5) * 100}%` }} /></div>
      <ol className="onboarding-steps" aria-label="Étapes de configuration">{stepNames.map((name, index) => <li key={name} className={index === step ? 'current' : index < step ? 'done' : ''} aria-current={index === step ? 'step' : undefined}><span>{index < step ? '✓' : index + 1}</span>{name}</li>)}</ol>
      <div className="onboarding-content">
        {step === 0 && <div className="onboarding-welcome"><div className="orbital" aria-hidden="true"><div className="orbital-core">G</div></div><div className="eyebrow">VOTRE ASSISTANT PERSONNEL</div><h1 ref={stepHeadingRef} tabIndex={-1} id="onboarding-title">Bienvenue dans GreatOS.</h1><p>Configurons votre espace en quelques étapes. Vos réponses seront enregistrées dans votre profil local chiffré.</p></div>}
        {step === 1 && <><div className="eyebrow">02 · QUESTIONS DE DÉCOUVERTE</div><h1 ref={stepHeadingRef} tabIndex={-1} id="onboarding-title">Comment puis-je vous aider&nbsp;?</h1><label className="onboarding-field">Votre activité principale
          <select value={data.activity} onChange={(event) => update({ activity: event.target.value, workflow_id: workflowByActivity[event.target.value] || '' })}>
            <option value="">Choisir une activité</option><option value="development">Développement et ingénierie</option><option value="maintenance">Maintenance de mon système</option><option value="data_protection">Protéger et sauvegarder mes données</option><option value="project_tracking">Suivre mes projets et apprentissages</option><option value="other">Autre activité</option>
          </select>
        </label><label className="onboarding-field">Quelle tâche répétitive aimeriez-vous simplifier&nbsp;? <span>Facultatif</span><textarea rows={2} maxLength={1000} value={data.repetitive_task} onChange={(event) => update({ repetitive_task: event.target.value })} /></label><label className="onboarding-field">Quelle est votre priorité avec GreatOS&nbsp;? <span>Facultatif</span><textarea rows={2} maxLength={1000} value={data.priority} onChange={(event) => update({ priority: event.target.value })} /></label></>}
        {step === 2 && <><div className="eyebrow">03 · PREMIER WORKFLOW SUGGÉRÉ</div><h1 ref={stepHeadingRef} tabIndex={-1} id="onboarding-title">Un premier workflow pour démarrer.</h1><p className="onboarding-intro">Suggestion basée sur votre activité. La sélectionner ne lance aucune action.</p><div className="workflow-options">{workflows.map((workflow) => <button key={workflow.id} className={`workflow-option ${data.workflow_id === workflow.id ? 'selected' : ''}`} onClick={() => update({ workflow_id: workflow.id })} aria-pressed={data.workflow_id === workflow.id}><span className="workflow-option-top">{workflow.name}{workflow.id === recommendedId && <small>RECOMMANDÉ</small>}</span><span>{workflow.description}</span></button>)}</div>{!recommended && <p className="onboarding-note">Choisissez un workflow parmi ceux disponibles.</p>}</>}
        {step === 3 && <><div className="eyebrow">04 · CONFIGURATION ESSENTIELLE</div><h1 ref={stepHeadingRef} tabIndex={-1} id="onboarding-title">Vos préférences de base.</h1><label className="onboarding-field">Langue de J.A.R.V.I.S<select value={data.language} onChange={(event) => update({ language: event.target.value as 'fr' | 'en' })}><option value="fr">Français</option><option value="en">English</option></select></label><div className="onboarding-setting"><div><strong>Fournisseur IA</strong><span>Cloud privilégié, modèle local en repli</span></div><b className="good">Activé</b></div><div className="onboarding-setting"><div><strong>Données et mémoire</strong><span>Stockage local protégé par DataShield</span></div><b className={memoryEncrypted ? 'good' : 'warn'}>{!securityReady ? 'Vérification…' : memoryEncrypted ? 'Chiffré · AES-256-GCM' : 'Chiffrement indisponible'}</b></div>{(!serviceOnline || !securityReady || !memoryEncrypted) && <p className="onboarding-error">{!serviceOnline ? 'Connexion au serveur nécessaire pour vérifier la sécurité.' : !securityReady ? 'État du chiffrement en cours de vérification.' : 'Le profil ne sera pas enregistré tant que le chiffrement n’est pas disponible.'}</p>}</>}
        {step === 4 && <div className="onboarding-welcome"><div className="completion-mark" aria-hidden="true">✓</div><div className="eyebrow">05 · TERMINÉ</div><h1 ref={stepHeadingRef} tabIndex={-1} id="onboarding-title">Votre espace est prêt.</h1><p>{saved ? 'Vos préférences ont été enregistrées dans votre profil local chiffré.' : 'Votre profil GreatOS est configuré.'} Vous pouvez maintenant commencer une conversation avec J.A.R.V.I.S.</p></div>}
        {error && <p className="onboarding-error" role="alert">{error}</p>}
      </div>
      <footer className="onboarding-actions">{step > 0 && step < 4 ? <button className="secondary-button" onClick={() => setStep((current) => current - 1)}>Retour</button> : <span />}{step < 4 ? <button className="primary-button" onClick={() => void next()} disabled={saving || (step === 1 && !data.activity) || (step === 2 && (!data.workflow_id || workflows.length === 0)) || (step === 3 && (!serviceOnline || !securityReady || !memoryEncrypted))}>{saving ? 'Enregistrement sécurisé…' : step === 3 ? 'Enregistrer et terminer' : 'Continuer'}</button> : <button className="primary-button" onClick={onDone}>Accéder à GreatOS</button>}</footer>
    </section>
  </main>;
}

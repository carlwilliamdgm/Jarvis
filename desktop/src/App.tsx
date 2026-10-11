import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

type Layout = 'chat' | 'focus' | 'dashboard' | 'vocal_hud' | 'task_runner' | 'web_nav' | 'idle' | 'defcon_alert';
type FeedItem = { id: string; kind: 'user' | 'assistant' | 'event' | 'error'; text: string; time?: string };
type Status = {
  cpu?: number; ram?: number; active?: boolean;
  voice?: { audio_input_ready?: boolean; reason?: string; audio?: { default_input?: { name?: string } } };
  vision?: { interpretation_ready?: boolean; interpretation_provider?: string | null; remote_analysis_enabled?: boolean };
  security?: { memory_backend?: string; encryption?: { enabled?: boolean; algorithm?: string } };
};
type Confirmation = { action_id: string; description: string };
const layouts: { id: Layout; label: string; icon: string }[] = [
  { id: 'chat', label: 'Chat', icon: '◈' }, { id: 'focus', label: 'Focus', icon: '◉' },
  { id: 'dashboard', label: 'Dashboard', icon: '▦' }, { id: 'vocal_hud', label: 'Vocal HUD', icon: '◖' },
  { id: 'task_runner', label: 'Task Runner', icon: '⌘' }, { id: 'web_nav', label: 'Web Nav', icon: '◎' },
  { id: 'idle', label: 'Veille', icon: '◌' }, { id: 'defcon_alert', label: 'DEFCON', icon: '⚠' },
];
const localInstance = {
  id: 'local',
  nom: 'Local',
  url: import.meta.env.DEV ? 'http://127.0.0.1:8000' : window.location.origin,
};
const sessionId = sessionStorage.getItem('jarvis-session-id') || crypto.randomUUID();
sessionStorage.setItem('jarvis-session-id', sessionId);

function apiError(response: Response) {
  if (response.status === 401 || response.status === 403) return new Error('auth');
  return new Error(`http-${response.status}`);
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
  const [service, setService] = useState<'checking' | 'online' | 'offline' | 'auth'>('checking');
  const [instances, setInstances] = useState<{ id: string; nom: string; url: string }[]>(() => {
    try { return [localInstance, ...JSON.parse(localStorage.getItem('jarvis-instances') || '[]')]; }
    catch { return [localInstance]; }
  });
  const [instanceDraft, setInstanceDraft] = useState({ nom: '', url: '' });
  const [showInstances, setShowInstances] = useState(false);
  const [discoveryResults, setDiscoveryResults] = useState<{ id: string; nom: string; ip: string; url: string }[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activeInstance = useMemo(() => instances.find((instance) => instance.url === apiBase), [instances, apiBase]);

  const addItem = useCallback((item: Omit<FeedItem, 'id'>) => {
    setItems((current) => [...current, { ...item, id: crypto.randomUUID() }]);
  }, []);

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => { document.documentElement.dataset.layout = layout; }, [layout]);
  useEffect(() => { feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' }); }, [items]);

  const refreshStatus = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/jarvis/status`, { cache: 'no-store' });
      if (!response.ok) throw apiError(response);
      setStatus(await response.json()); setService('online');
    } catch (error) { setService((error as Error).message === 'auth' ? 'auth' : 'offline'); }
  }, [apiBase]);

  const refreshSessions = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/jarvis/browser-sessions`, { cache: 'no-store' });
      if (response.ok) setBrowserSessions((await response.json()).sessions || []);
    } catch { /* dashboard shows an empty state when backend is unavailable */ }
  }, [apiBase]);

  useEffect(() => {
    void refreshStatus(); void refreshSessions();
    const timer = window.setInterval(() => { void refreshStatus(); void refreshSessions(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshStatus, refreshSessions]);

  useEffect(() => {
    let live = true;
    const refreshLayout = async () => {
      try {
        const response = await fetch(`${apiBase}/jarvis/layout`, { cache: 'no-store' });
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
  }, [apiBase]);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    async function listenForEvents() {
      while (!stopped) {
        try {
          const response = await fetch(`${apiBase}/jarvis/events`, { headers: { Accept: 'text/event-stream' }, signal: controller.signal });
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
  }, [apiBase]);

  function handleEvent(event: { type: string; data?: Record<string, unknown> }) {
    const data = event.data || {};
    if (event.type === 'response') addItem({ kind: 'assistant', text: String(data.text || ''), time: String(data.timestamp || '') });
    else if (event.type === 'thinking') addItem({ kind: 'event', text: String(data.message || 'J.A.R.V.I.S réfléchit…') });
    else if (event.type === 'provider') addItem({ kind: 'event', text: `Modèle ${data.provider || 'actif'} · ${data.model || ''}` });
    else if (event.type === 'tool_started') addItem({ kind: 'event', text: `Exécution · ${data.outil || 'capacité'}` });
    else if (event.type === 'tool_completed') addItem({ kind: 'event', text: `Terminé · ${data.outil || 'capacité'} · ${String(data.resultat || '').slice(0, 120)}` });
    else if (event.type === 'tool_failed') addItem({ kind: 'error', text: `Échec · ${data.outil || 'capacité'} · ${String(data.resultat || '').slice(0, 120)}` });
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
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'text/event-stream' } });
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
      const response = await fetch(`${apiBase}/jarvis/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, action_id: confirmation.action_id, confirmed }) });
      if (!response.ok) throw apiError(response);
      addItem({ kind: 'event', text: confirmed ? 'Action autorisée.' : 'Action refusée.' });
    } catch { addItem({ kind: 'error', text: 'La confirmation n’a pas pu être transmise.' }); }
    setConfirmation(null);
  }

  function onInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
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
      const response = await fetch(`${apiBase}/jarvis/discover`, { cache: 'no-store' });
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
    setApiBase(instance.url); setShowInstances(false); setDiscoveryResults([]);
  }

  const activeLayout = layouts.find((item) => item.id === layout) || layouts[0];
  const memoryEncrypted = status.security?.memory_backend === 'encrypted' && status.security.encryption?.enabled;

  return <main className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">G</div><div><strong>GREATOS</strong><span>J.A.R.V.I.S</span></div></div>
      <div className="nav-label">ESPACE</div>
      <button className={`nav-item ${view === 'chat' ? 'selected' : ''}`} onClick={() => setView('chat')}><span>◈</span> Conversation</button>
      <button className={`nav-item ${view === 'dashboard' ? 'selected' : ''}`} onClick={() => { setView('dashboard'); void refreshStatus(); void refreshSessions(); }}><span>▦</span> Vue d’ensemble</button>
      <div className="nav-label layouts-label">INTERFACE MORPHIQUE</div>
      <div className="layout-list" aria-label="Layout contextuel actif"><div className="layout-item selected" aria-current="true"><span>{activeLayout.icon}</span>{activeLayout.label}<i /></div><div className="layout-context">{appContext || 'Adaptation au contexte Windows'}</div></div>
      <div className="sidebar-bottom"><div className="instance-switch"><span>INSTANCE</span><select aria-label="Instance Jarvis" value={apiBase} onChange={(event) => setApiBase(event.target.value)}>{instances.map((item) => <option value={item.url} key={item.id}>{item.nom}</option>)}</select><button title="Gérer les instances" onClick={() => setShowInstances((value) => !value)}>＋</button></div>{showInstances && <div className="instance-form"><input placeholder="Nom" value={instanceDraft.nom} onChange={(event) => setInstanceDraft({ ...instanceDraft, nom: event.target.value })} /><input placeholder="URL https://…" value={instanceDraft.url} onChange={(event) => setInstanceDraft({ ...instanceDraft, url: event.target.value })} /><button onClick={saveInstance}>Ajouter une instance</button><button className="discover-button" onClick={() => void discoverInstances()}>{discovering ? 'Recherche…' : 'Découverte Tailscale'}</button>{discoveryResults.map((instance) => <div className="discovery-row" key={instance.id}><span><b>{instance.nom}</b><small>{instance.ip}</small></span><button onClick={() => addDiscoveredInstance(instance)}>Ajouter</button></div>)}</div>}<div className="connection"><i className={`connection-dot ${service}`} /><span>{service === 'online' ? 'Système opérationnel' : service === 'auth' ? 'Authentification requise' : service === 'checking' ? 'Connexion…' : 'Système hors ligne'}</span><button onClick={() => void refreshStatus()} title="Actualiser l’état">↻</button></div></div>
    </aside>

    <section className="main-column">
      <header className="topbar"><div><div className="eyebrow">{view === 'dashboard' ? 'SYSTÈME' : 'ASSISTANT PERSONNEL'}</div><h1>{view === 'dashboard' ? 'Vue d’ensemble' : 'Conversation'}</h1></div><div className="topbar-right"><div className="context-badge"><span>{activeLayout.icon}</span><b>{activeLayout.label}</b>{appContext && <em>· {appContext}</em>}</div><button className="icon-button" onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')} aria-label="Changer de thème">{theme === 'dark' ? '☼' : '☾'}</button><div className="avatar">C</div></div></header>
      {view === 'chat' ? <>
        <div className="feed" ref={feedRef} aria-live="polite" aria-label="Conversation J.A.R.V.I.S">
          {items.length === 0 && <div className="welcome"><div className="orbital"><div className="orbital-core">G</div></div><div className="eyebrow">VOTRE ASSISTANT PERSONNEL</div><h2>À votre service.</h2><p>Je suis prêt à vous aider.</p><div className="suggestions"><button onClick={() => setMessage('Résume mon activité récente')}>⌁ <span>Résume mon activité récente</span></button><button onClick={() => setMessage('Aide-moi à organiser mes tâches')}>◷ <span>Organise mes tâches</span></button><button onClick={() => setMessage('Que se passe-t-il sur mon écran ?')}>▧ <span>Analyse mon écran</span></button></div></div>}
          {items.map((item) => <article className={`feed-item ${item.kind}`} key={item.id}><div className="message-avatar">{item.kind === 'user' ? 'C' : item.kind === 'assistant' ? 'G' : item.kind === 'error' ? '!' : '·'}</div><div className="message-content">{item.kind !== 'event' && <div className="message-author">{item.kind === 'user' ? 'VOUS' : item.kind === 'error' ? 'SYSTÈME' : 'J.A.R.V.I.S'}{item.time && <time>{item.time}</time>}</div>}<p>{item.text}</p></div></article>)}
          {busy && <div className="thinking"><span /><span /><span /> J.A.R.V.I.S réfléchit</div>}
        </div>
        <form className="composer" onSubmit={sendMessage}><div className="composer-box"><textarea ref={inputRef} rows={1} value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={onInputKeyDown} placeholder="Écrivez à J.A.R.V.I.S…" aria-label="Message à J.A.R.V.I.S" /><div className="composer-actions"><span>Entrée pour envoyer · Maj + Entrée pour une nouvelle ligne</span><div>{busy && <button type="button" className="cancel-button" onClick={() => abortRef.current?.abort()}>Arrêter</button>}<button type="submit" className="send-button" disabled={!message.trim() || busy} aria-label="Envoyer">↑</button></div></div></div></form>
      </> : <div className="dashboard-view"><div className="metric-grid"><Metric label="Processeur" value={status.cpu == null ? '—' : `${Math.round(status.cpu)}%`} detail="Utilisation système" /><Metric label="Mémoire vive" value={status.ram == null ? '—' : `${Math.round(status.ram)}%`} detail="Utilisation système" /><Metric label="Entrée vocale" value={status.voice?.audio_input_ready ? 'Prête' : 'Indisponible'} detail={status.voice?.audio?.default_input?.name || status.voice?.reason || 'Micro Windows'} good={!!status.voice?.audio_input_ready} /><Metric label="Vision" value={status.vision?.interpretation_ready ? 'Configurée' : 'Capture seule'} detail={status.vision?.interpretation_provider === 'groq' ? 'Groq prioritaire · Ollama en repli' : 'Interprétation à configurer'} good={!!status.vision?.interpretation_ready} /><Metric label="Mémoire chiffrée" value={memoryEncrypted ? 'Active' : 'Indisponible'} detail={status.security?.encryption?.algorithm || 'AES-256-GCM'} good={!!memoryEncrypted} /><Metric label="Layout actif" value={activeLayout.label} detail={appContext || 'Contexte Windows'} /></div><div className="dashboard-panels"><section className="panel"><div className="panel-heading"><div><div className="eyebrow">ACTIVITÉ</div><h2>Sessions navigateur</h2></div><button className="text-button" onClick={() => void refreshSessions()}>Actualiser</button></div>{browserSessions.length ? browserSessions.slice(0, 6).map((session, index) => <div className="browser-session" key={String(session.session_id || index)}><div className="session-icon">◎</div><div><strong>{String(session.current_title || session.session_id || 'Session navigateur')}</strong><span>{String(session.current_url || 'Page non renseignée')}</span></div><small>{String(session.state || 'active')}</small></div>) : <div className="empty-state">Aucune session navigateur active.</div>}</section><section className="panel"><div className="eyebrow">ÉTAT DE GREATOS</div><h2>Capacités système</h2><div className="capability-row"><span>API Jarvis</span><b className={service === 'online' ? 'good' : 'warn'}>{service === 'online' ? 'Connectée' : 'Indisponible'}</b></div><div className="capability-row"><span>Instance active</span><b>{activeInstance?.nom || 'Personnalisée'}</b></div><div className="capability-row"><span>Chiffrement mémoire</span><b className={memoryEncrypted ? 'good' : 'warn'}>{memoryEncrypted ? 'AES-256-GCM' : 'À vérifier'}</b></div><button className="primary-button full" onClick={() => setView('chat')}>Ouvrir la conversation</button></section></div></div>}
      <footer className="footer"><span>GREATOS PERSONAL OS</span><span>Données conservées localement · Cloud préféré pour le calcul</span><span>WINDOWS</span></footer>
    </section>

    {confirmation && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><div className="warning-mark">!</div><div className="eyebrow">AUTORISATION REQUISE</div><h2 id="confirm-title">Confirmer cette action</h2><p>J.A.R.V.I.S souhaite : <strong>{confirmation.description}</strong></p><div className="modal-actions"><button className="secondary-button" onClick={() => void resolveConfirmation(false)}>Refuser</button><button className="primary-button" onClick={() => void resolveConfirmation(true)}>Autoriser</button></div></section></div>}
  </main>;
}

function Metric({ label, value, detail, good }: { label: string; value: string; detail: string; good?: boolean }) {
  return <section className="metric-card"><div className="metric-label">{label}</div><div className={`metric-value ${good === undefined ? '' : good ? 'good' : 'warn'}`}>{value}</div><div className="metric-detail">{detail}</div></section>;
}

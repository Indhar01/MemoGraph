import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  Database,
  HardDrive,
  Cloud,
  FileText,
  Plus,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  ArrowRight,
  PlayCircle,
} from 'lucide-react';
import axios from 'axios';
import {
  sourcesAPI,
  getErrorMessage,
  isNotFoundError,
  type Source,
  type SourceKind,
} from '../lib/api';
import { ErrorAlert } from '../components/ErrorDisplay';

const KIND_LABEL: Record<SourceKind, string> = {
  local: 'Local folder',
  s3: 'Amazon S3 / S3-compatible',
  gdrive: 'Google Drive',
  onedrive: 'OneDrive / SharePoint',
  notion: 'Notion',
};

const KIND_ICON: Record<SourceKind, typeof Database> = {
  local: HardDrive,
  s3: Database,
  gdrive: Cloud,
  onedrive: Cloud,
  notion: FileText,
};

const KIND_HINT: Record<SourceKind, string> = {
  local: 'A folder of markdown files on this machine.',
  s3: 'Any S3 bucket — AWS, MinIO, Backblaze B2, Cloudflare R2.',
  gdrive: 'Sign in with Google via Nango. One click — no fields. Read-only.',
  onedrive: 'Sign in with Microsoft (personal or work) via Nango. One click. Read-only.',
  notion: 'Sign in with Notion via Nango. One click — no manual token needed.',
};

export default function SourcesPage() {
  const [params, setParams] = useSearchParams();
  const [wizardOpen, setWizardOpen] = useState(false);

  const connected = params.get('connected');
  const oauthError = params.get('oauth_error');

  useEffect(() => {
    if (connected || oauthError) {
      const t = setTimeout(() => {
        const next = new URLSearchParams(params);
        next.delete('connected');
        next.delete('oauth_error');
        setParams(next, { replace: true });
      }, 8000);
      return () => clearTimeout(t);
    }
  }, [connected, oauthError, params, setParams]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['sources'],
    queryFn: () => sourcesAPI.list(),
  });

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-bold font-display">Sources</h1>
          <p className="text-muted-fg mt-1">
            Where MemoGraph reads your memories from. Connect a folder or a cloud
            account; switch between them without losing data.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setWizardOpen(true)}
          className="btn btn-primary"
        >
          <Plus className="w-4 h-4" />
          Add source
        </button>
      </header>

      {connected && (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          Connected <span className="font-mono">{connected}</span>.
        </div>
      )}
      {oauthError && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm flex items-center gap-2">
          <XCircle className="w-4 h-4 text-red-500" />
          OAuth flow failed: {oauthError}
        </div>
      )}

      {/*
        A 404 here means the source subsystem isn't mounted on this
        backend — show the friendly EmptyState instead of a red error
        alert. The Layout-level banner handles the admin-facing notice.
        Other failures (500, network) still surface as a hard error
        because they're not "no sources yet" — they're broken.
      */}
      {error && !isNotFoundError(error) && (
        <ErrorAlert
          message={getErrorMessage(error)}
          onRetry={() => {
            void refetch();
          }}
        />
      )}

      {isLoading ? (
        <p className="text-muted-fg">Loading sources…</p>
      ) : isNotFoundError(error) || (data && data.sources.length === 0) ? (
        <EmptyState onAdd={() => setWizardOpen(true)} />
      ) : (
        <div className="space-y-3">
          {data?.sources.map((s) => (
            <SourceCard
              key={s.source_id}
              source={s}
              activeId={data.active_source_id}
            />
          ))}
        </div>
      )}

      {wizardOpen && (
        <AddSourceWizard
          onClose={() => setWizardOpen(false)}
          onCreated={() => {
            setWizardOpen(false);
          }}
        />
      )}
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="rounded-lg border border-border bg-surface/40 p-8 text-center space-y-3">
      <Database className="w-10 h-10 mx-auto text-muted-fg" />
      <h2 className="text-lg font-semibold">No sources yet</h2>
      <p className="text-sm text-muted-fg max-w-md mx-auto">
        Connect a local folder or a cloud account to start collecting memories.
        You can switch between sources at any time.
      </p>
      <button type="button" onClick={onAdd} className="btn btn-primary mx-auto">
        <Plus className="w-4 h-4" />
        Add your first source
      </button>
    </div>
  );
}

function SourceCard({ source, activeId }: { source: Source; activeId: string | null }) {
  const Icon = KIND_ICON[source.kind];
  const isActive = source.source_id === activeId;
  const qc = useQueryClient();

  const { data: health, isFetching: healthFetching, refetch: refetchHealth } = useQuery({
    queryKey: ['source-health', source.source_id],
    queryFn: () => sourcesAPI.health(source.source_id),
    staleTime: 30_000,
  });

  // Activating a source re-points the kernel at it and triggers a
  // reindex; syncing materializes new files and re-indexes if active.
  // Both can change what shows up on the Memories / Graph / Analytics
  // pages, so invalidate those query keys too — the user shouldn't
  // have to reload to see their new memories.
  const invalidateMemoryViews = () => {
    qc.invalidateQueries({ queryKey: ['sources'] });
    qc.invalidateQueries({ queryKey: ['memories'] });
    qc.invalidateQueries({ queryKey: ['graph'] });
    qc.invalidateQueries({ queryKey: ['analytics'] });
  };

  const activate = useMutation({
    mutationFn: () => sourcesAPI.activate(source.source_id),
    onSuccess: invalidateMemoryViews,
  });

  const syncNow = useMutation({
    mutationFn: () => sourcesAPI.sync(source.source_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['source-health', source.source_id] });
      invalidateMemoryViews();
    },
  });

  const remove = useMutation({
    mutationFn: () => sourcesAPI.delete(source.source_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  });

  return (
    <div
      className={`rounded-lg border ${
        isActive ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-border bg-surface/40'
      } p-4`}
    >
      <div className="flex items-start gap-4">
        <div className="shrink-0 p-2 rounded-md bg-surface border border-border">
          <Icon className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold truncate">{source.display_name}</h3>
            <span className="text-xs px-2 py-0.5 rounded-full bg-surface border border-border text-muted-fg">
              {KIND_LABEL[source.kind]}
            </span>
            {isActive && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
                Active
              </span>
            )}
            <HealthPill health={health?.status} loading={healthFetching} />
          </div>
          <p className="text-xs text-muted-fg font-mono mt-1 truncate">
            {source.source_id}
          </p>
          {health?.last_error && (
            <p className="text-xs text-red-500 mt-1 truncate">
              {health.last_error}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => refetchHealth()}
            disabled={healthFetching}
            className="btn btn-ghost p-2"
            aria-label="Re-check health"
            title="Re-check health"
          >
            <RefreshCw className={`w-4 h-4 ${healthFetching ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={() => syncNow.mutate()}
            disabled={syncNow.isPending}
            className="btn btn-ghost p-2"
            aria-label="Sync now"
            title="Sync now — pulls fresh content from the source immediately"
          >
            <PlayCircle className={`w-4 h-4 ${syncNow.isPending ? 'animate-pulse' : ''}`} />
          </button>
          {!isActive && (
            <button
              type="button"
              onClick={() => activate.mutate()}
              disabled={activate.isPending}
              className="btn btn-secondary"
            >
              <ArrowRight className="w-4 h-4" />
              {activate.isPending ? 'Switching…' : 'Activate'}
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`Remove source "${source.display_name}"?`)) {
                remove.mutate();
              }
            }}
            disabled={remove.isPending}
            className="btn btn-ghost p-2 text-red-500"
            aria-label="Delete source"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
      {activate.isError && (
        <p className="text-xs text-red-500 mt-2">
          {getErrorMessage(activate.error)}
        </p>
      )}
      {remove.isError && (
        <p className="text-xs text-red-500 mt-2">
          {getErrorMessage(remove.error)}
        </p>
      )}
      {syncNow.isError && (
        <p className="text-xs text-red-500 mt-2">
          {getErrorMessage(syncNow.error)}
        </p>
      )}
      {syncNow.isSuccess && syncNow.data?.last_error && (
        <p className="text-xs text-amber-500 mt-2">
          Sync completed with error: {syncNow.data.last_error}
        </p>
      )}
      {syncNow.isSuccess && !syncNow.data?.last_error && (
        <p className="text-xs text-emerald-500 mt-2">
          Synced{syncNow.data?.last_success_at
            ? ` at ${new Date(syncNow.data.last_success_at).toLocaleTimeString()}`
            : ''}.
        </p>
      )}
    </div>
  );
}

function HealthPill({
  health,
  loading,
}: {
  health: 'ok' | 'degraded' | 'failed' | undefined;
  loading: boolean;
}) {
  if (loading && !health) {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-surface border border-border text-muted-fg">
        Probing…
      </span>
    );
  }
  if (health === 'ok') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
        <CheckCircle2 className="w-3 h-3" /> Healthy
      </span>
    );
  }
  if (health === 'degraded') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30">
        <AlertTriangle className="w-3 h-3" /> Degraded
      </span>
    );
  }
  if (health === 'failed') {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/15 text-red-600 dark:text-red-400 border border-red-500/30">
        <XCircle className="w-3 h-3" /> Failed
      </span>
    );
  }
  return null;
}

// --- Wizard -----------------------------------------------------------------

const KIND_ORDER: SourceKind[] = ['local', 's3', 'gdrive', 'onedrive', 'notion'];

type NangoKind = 'gdrive' | 'onedrive' | 'notion';

function isNangoKind(k: SourceKind): k is NangoKind {
  return k === 'gdrive' || k === 'onedrive' || k === 'notion';
}

function AddSourceWizard({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState<SourceKind | null>(null);
  const routedThroughNango = kind !== null && isNangoKind(kind);

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-bg border border-border rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <header className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <h2 className="font-bold text-lg">
              {kind ? `Connect ${KIND_LABEL[kind]}` : 'Add a source'}
            </h2>
            <p className="text-xs text-muted-fg mt-0.5">
              {!kind
                ? 'Pick the kind of source you want to connect.'
                : routedThroughNango
                  ? "You'll sign in with the provider through Nango. Tokens stay encrypted in your Nango instance."
                  : 'Fill in the connection details.'}
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost p-2">
            <XCircle className="w-5 h-5" />
          </button>
        </header>
        <div className="p-4">
          {!kind ? (
            <KindPicker onPick={setKind} />
          ) : routedThroughNango ? (
            <NangoConnect
              kind={kind}
              onBack={() => setKind(null)}
              onConnected={onCreated}
            />
          ) : (
            <KindForm
              kind={kind as 'local' | 's3'}
              onBack={() => setKind(null)}
              onCreated={onCreated}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function nangoErrorHint(err: unknown): string {
  // 404: the /sources/connect-session route isn't mounted on this
  // backend — sources subsystem is disabled or running stale code.
  // 503: route mounted but Nango isn't configured / not reachable.
  // Anything else: fall through to the generic axios message.
  if (isNotFoundError(err)) {
    return "This MemoGraph instance hasn't enabled source connections. Contact your administrator.";
  }
  if (axios.isAxiosError(err) && err.response?.status === 503) {
    const detail = err.response.data?.error;
    return (
      detail ||
      "Nango isn't reachable from this MemoGraph backend. Ask your administrator to bring up the Nango stack (docs/SOURCES.md)."
    );
  }
  return getErrorMessage(err);
}

function NangoConnect({
  kind,
  onBack,
  onConnected,
}: {
  kind: NangoKind;
  onBack: () => void;
  onConnected: () => void;
}) {
  const qc = useQueryClient();
  const providerLabel = {
    gdrive: 'Google Drive',
    onedrive: 'OneDrive / SharePoint',
    notion: 'Notion',
  }[kind];

  // Probe Nango readiness so the operator knows up front whether
  // the integration is wired. A red banner here saves the user
  // from clicking through to a 503.
  const { data: nangoHealth, isLoading: nangoChecking } = useQuery({
    queryKey: ['nango-health'],
    queryFn: () => sourcesAPI.getNangoHealth(),
    staleTime: 60_000,
  });

  const connect = useMutation({
    mutationFn: async () => {
      const session = await sourcesAPI.createConnectSession({ kind });
      // Lazy-load Nango's frontend SDK to keep the main bundle slim.
      // Falls back to opening the connect_link in a new tab if the
      // SDK isn't installed yet — useful while the operator is still
      // wiring up the integration.
      try {
        // The dep is declared in package.json but kept optional at
        // build time so checkouts without `npm install` still
        // typecheck AND don't crash the dev server. /* @vite-ignore */
        // tells Vite not to pre-bundle or statically resolve the
        // specifier, so a missing module surfaces as a runtime
        // exception (caught below) instead of a Vite parse error.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const nangoModule: any = await import(/* @vite-ignore */ '@nangohq/frontend');
        const Nango =
          (nangoModule.default as unknown as new (opts: {
            host: string;
          }) => {
            openConnectUI: (opts: {
              sessionToken: string;
              onEvent?: (e: { type: string; payload?: unknown }) => void;
            }) => unknown;
          }) ?? null;
        // Use public_url for the SDK — the browser, not the backend,
        // talks to Nango here, so the URL needs to be reachable from
        // the user's machine. Falls back to base_url for installs
        // where only the legacy single-URL env var is set.
        const nangoHost = nangoHealth?.public_url || nangoHealth?.base_url;
        if (Nango && nangoHost) {
          const nango = new Nango({ host: nangoHost });
          await new Promise<void>((resolve, reject) => {
            nango.openConnectUI({
              sessionToken: session.session_token,
              onEvent: (event: { type: string }) => {
                if (event.type === 'close') {
                  resolve();
                } else if (event.type === 'connect') {
                  resolve();
                }
              },
            });
            // Safety timeout: 5 minutes is well under Nango's 30-min
            // session lifetime; if the modal never reports close we
            // still let the user retry.
            setTimeout(() => reject(new Error('Connect timed out')), 5 * 60_000);
          });
        } else if (session.connect_link) {
          window.open(session.connect_link, '_blank', 'noopener,noreferrer');
        } else {
          throw new Error(
            'Nango SDK is not installed and no connect_link was returned. ' +
              "Run 'npm install @nangohq/frontend' in the frontend " +
              'project to enable the embedded modal.'
          );
        }
      } catch (err) {
        // Module not found → fall back to the connect_link.
        if (session.connect_link) {
          window.open(session.connect_link, '_blank', 'noopener,noreferrer');
        } else {
          throw err;
        }
      }
      return session;
    },
    onSuccess: () => {
      // The webhook lands asynchronously — re-fetch the sources list
      // immediately, but expect the user may need to wait a beat. If
      // this is the first source, the webhook also auto-activates +
      // triggers a kernel ingest, so refresh the memory views too.
      qc.invalidateQueries({ queryKey: ['sources'] });
      qc.invalidateQueries({ queryKey: ['memories'] });
      qc.invalidateQueries({ queryKey: ['graph'] });
      qc.invalidateQueries({ queryKey: ['analytics'] });
      onConnected();
    },
  });

  const nangoBroken =
    nangoHealth && !nangoHealth.configured;
  // MemoGraph kind → Nango provider-config-key (must match the values
  // in memograph/sources/nango_client.py KIND_TO_PROVIDER_KEY).
  const kindToProviderKey: Record<NangoKind, string> = {
    gdrive: 'google-drive',
    onedrive: 'one-drive',
    notion: 'notion',
  };
  const providerKey = kindToProviderKey[kind];
  // Once the health probe reports back, we know whether the operator
  // has actually configured this provider in the Nango admin UI. If
  // not, clicking Continue would mint a session that fails inside the
  // Connect modal with "no integration found" — far too late.
  const integrationMissing =
    nangoHealth?.configured === true &&
    Array.isArray(nangoHealth.available_integrations) &&
    !nangoHealth.available_integrations.includes(providerKey);

  return (
    <div className="space-y-4">
      {nangoChecking && (
        <p className="text-xs text-muted-fg">Checking Nango status…</p>
      )}
      {nangoBroken && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs">
          <strong>Nango is not configured.</strong> Set{' '}
          <code>MEMOGRAPH_NANGO_BASE_URL</code> and{' '}
          <code>MEMOGRAPH_NANGO_SECRET_KEY</code> in your server
          environment, then restart. See{' '}
          <code>docs/SOURCES.md</code> for the full walkthrough.
        </div>
      )}
      {integrationMissing && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs">
          <strong>{providerLabel} isn&rsquo;t configured in Nango yet.</strong>{' '}
          Open the Nango admin UI at{' '}
          <code>{nangoHealth?.public_url || nangoHealth?.base_url}</code>{' '}
          and create an integration with the provider key{' '}
          <code>{providerKey}</code> before continuing here.
        </div>
      )}
      <div className="rounded-md border border-border bg-surface/40 p-4 text-sm space-y-2">
        <p>
          You&rsquo;ll be sent to <strong>{providerLabel}</strong> to sign in
          and approve access. Once you finish, MemoGraph will register the
          source automatically — no fields to fill in here.
        </p>
        <p className="text-muted-fg text-xs">
          Authentication is brokered by Nango (your self-hosted instance).
          MemoGraph never sees your provider tokens.
        </p>
      </div>
      {connect.isError && (
        <p className="text-xs text-red-500">{nangoErrorHint(connect.error)}</p>
      )}
      <div className="flex items-center justify-between pt-2">
        <button type="button" onClick={onBack} className="btn btn-ghost">
          ← Back
        </button>
        <button
          type="button"
          onClick={() => connect.mutate()}
          disabled={connect.isPending || nangoBroken || integrationMissing}
          className="btn btn-primary"
        >
          {connect.isPending ? 'Opening Nango…' : `Continue with ${providerLabel} →`}
        </button>
      </div>
    </div>
  );
}

function KindPicker({ onPick }: { onPick: (k: SourceKind) => void }) {
  return (
    <div className="grid sm:grid-cols-2 gap-3">
      {KIND_ORDER.map((k) => {
        const Icon = KIND_ICON[k];
        return (
          <button
            key={k}
            type="button"
            onClick={() => onPick(k)}
            className="text-left p-4 rounded-lg border border-border bg-surface/40 hover:bg-surface/80 transition-colors"
          >
            <div className="flex items-center gap-2 mb-2">
              <Icon className="w-5 h-5" />
              <span className="font-semibold">{KIND_LABEL[k]}</span>
            </div>
            <p className="text-xs text-muted-fg">{KIND_HINT[k]}</p>
          </button>
        );
      })}
    </div>
  );
}

function KindForm({
  kind,
  onBack,
  onCreated,
}: {
  kind: 'local' | 's3';
  onBack: () => void;
  onCreated: () => void;
}) {
  const qc = useQueryClient();
  const [sourceId, setSourceId] = useState('');
  const [displayName, setDisplayName] = useState('');
  // local
  const [localPath, setLocalPath] = useState('');
  // s3
  const [bucket, setBucket] = useState('');
  const [region, setRegion] = useState('');
  const [prefix, setPrefix] = useState('');
  const [endpointUrl, setEndpointUrl] = useState('');

  const create = useMutation({
    mutationFn: async () => {
      if (kind === 'local') {
        return sourcesAPI.create({
          source_id: sourceId,
          kind,
          display_name: displayName || sourceId,
          params: { path: localPath },
        });
      }
      // s3
      const params: Record<string, unknown> = { bucket };
      if (region) params.region = region;
      if (prefix) params.prefix = prefix;
      if (endpointUrl) params.endpoint_url = endpointUrl;
      return sourcesAPI.create({
        source_id: sourceId,
        kind,
        display_name: displayName || sourceId,
        params,
      });
    },
    onSuccess: (result) => {
      if (result) {
        // First-source auto-activate happens server-side, so a new
        // Local/S3 source can immediately produce memories on the
        // Memories page. Invalidate those queries too.
        qc.invalidateQueries({ queryKey: ['sources'] });
        qc.invalidateQueries({ queryKey: ['memories'] });
        qc.invalidateQueries({ queryKey: ['graph'] });
        qc.invalidateQueries({ queryKey: ['analytics'] });
        onCreated();
      }
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
      className="space-y-4"
    >
      <Field
        label="Source ID"
        hint="Lowercase letters, digits, dashes or underscores. Used in URLs and audit log."
      >
        <input
          type="text"
          value={sourceId}
          onChange={(e) => setSourceId(e.target.value)}
          required
          pattern="^[a-z0-9_-]{1,64}$"
          placeholder={`${kind}-primary`}
          className="input w-full"
        />
      </Field>
      <Field label="Display name">
        <input
          type="text"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Notes from work"
          className="input w-full"
        />
      </Field>

      {kind === 'local' && (
        <Field
          label="Absolute path to your markdown folder"
          hint={
            'The folder must exist on this server and contain your .md files. ' +
            'Forward slashes work on every OS — on Windows, prefer C:/Users/me/notes ' +
            'over backslashes. The path is checked when you click Create.'
          }
        >
          <input
            type="text"
            value={localPath}
            onChange={(e) => setLocalPath(e.target.value)}
            required
            placeholder="C:/Users/me/notes"
            className="input w-full font-mono"
          />
        </Field>
      )}

      {kind === 's3' && (
        <>
          <Field label="Bucket">
            <input
              type="text"
              value={bucket}
              onChange={(e) => setBucket(e.target.value)}
              required
              placeholder="my-vault-bucket"
              className="input w-full font-mono"
            />
          </Field>
          <Field label="Region (optional)">
            <input
              type="text"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder="us-east-1"
              className="input w-full font-mono"
            />
          </Field>
          <Field label="Prefix (optional)" hint="Limits the source to a sub-path inside the bucket.">
            <input
              type="text"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              placeholder="memos/"
              className="input w-full font-mono"
            />
          </Field>
          <Field
            label="Endpoint URL (optional)"
            hint="Set for MinIO, Backblaze B2, Cloudflare R2, etc."
          >
            <input
              type="text"
              value={endpointUrl}
              onChange={(e) => setEndpointUrl(e.target.value)}
              placeholder="https://s3.example.com"
              className="input w-full font-mono"
            />
          </Field>
        </>
      )}

      {create.isError && (
        <p className="text-xs text-red-500">{getErrorMessage(create.error)}</p>
      )}

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={onBack}
          className="btn btn-ghost"
        >
          ← Back
        </button>
        <button
          type="submit"
          disabled={create.isPending}
          className="btn btn-primary"
        >
          {create.isPending ? 'Creating…' : 'Create source'}
        </button>
      </div>
    </form>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium block mb-1">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-fg block mt-1">{hint}</span>}
    </label>
  );
}

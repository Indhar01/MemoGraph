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
} from 'lucide-react';
import { sourcesAPI, getErrorMessage, type Source, type SourceKind } from '../lib/api';
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
  gdrive: 'OAuth into a Google Drive folder. Read-only.',
  onedrive: 'OAuth into personal OneDrive or a SharePoint document library. Read-only.',
  notion: 'A Notion workspace via internal integration token.',
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

      {error && (
        <ErrorAlert
          message={getErrorMessage(error)}
          onRetry={() => {
            void refetch();
          }}
        />
      )}

      {isLoading ? (
        <p className="text-muted-fg">Loading sources…</p>
      ) : data && data.sources.length === 0 ? (
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

  const activate = useMutation({
    mutationFn: () => sourcesAPI.activate(source.source_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
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

function AddSourceWizard({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState<SourceKind | null>(null);

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-bg border border-border rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <header className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <h2 className="font-bold text-lg">
              {kind ? `Connect ${KIND_LABEL[kind]}` : 'Add a source'}
            </h2>
            <p className="text-xs text-muted-fg mt-0.5">
              {kind
                ? 'Configure the connection. Tokens are encrypted on disk.'
                : 'Pick the kind of source you want to connect.'}
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost p-2">
            <XCircle className="w-5 h-5" />
          </button>
        </header>
        <div className="p-4">
          {!kind ? (
            <KindPicker onPick={setKind} />
          ) : (
            <KindForm
              kind={kind}
              onBack={() => setKind(null)}
              onCreated={onCreated}
            />
          )}
        </div>
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
  kind: SourceKind;
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
  // notion
  const [notionToken, setNotionToken] = useState('');
  const [notionDatabaseId, setNotionDatabaseId] = useState('');
  // gdrive / onedrive
  const [folderId, setFolderId] = useState('');
  const [driveId, setDriveId] = useState('');

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
      if (kind === 's3') {
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
      }
      if (kind === 'notion') {
        const params: Record<string, unknown> = {};
        if (notionToken) params.auth_token = notionToken;
        if (notionDatabaseId) params.database_id = notionDatabaseId;
        return sourcesAPI.create({
          source_id: sourceId,
          kind,
          display_name: displayName || sourceId,
          params,
        });
      }
      // OAuth-driven kinds: kick off the flow rather than POST first.
      // The callback auto-registers the source.
      if (kind === 'gdrive') {
        const flow = await sourcesAPI.startGoogleOAuth({
          source_id: sourceId,
          display_name: displayName || sourceId,
          folder_id: folderId || undefined,
        });
        window.location.href = flow.authorization_url;
        return undefined;
      }
      if (kind === 'onedrive') {
        const flow = await sourcesAPI.startMicrosoftOAuth({
          source_id: sourceId,
          display_name: displayName || sourceId,
          drive_id: driveId || undefined,
          folder_id: folderId || undefined,
        });
        window.location.href = flow.authorization_url;
        return undefined;
      }
    },
    onSuccess: (result) => {
      if (result) {
        qc.invalidateQueries({ queryKey: ['sources'] });
        onCreated();
      }
      // OAuth kinds: the page has already been redirected.
    },
  });

  const isOAuth = kind === 'gdrive' || kind === 'onedrive';

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
          label="Absolute path"
          hint="Must be an absolute path to a directory of markdown files."
        >
          <input
            type="text"
            value={localPath}
            onChange={(e) => setLocalPath(e.target.value)}
            required
            placeholder="/Users/me/notes  or  C:\\Users\\me\\notes"
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

      {kind === 'notion' && (
        <>
          <Field
            label="Internal integration token"
            hint="Create one at notion.so/my-integrations. Stored encrypted."
          >
            <input
              type="password"
              value={notionToken}
              onChange={(e) => setNotionToken(e.target.value)}
              placeholder="secret_..."
              className="input w-full font-mono"
            />
          </Field>
          <Field label="Database ID (optional)">
            <input
              type="text"
              value={notionDatabaseId}
              onChange={(e) => setNotionDatabaseId(e.target.value)}
              className="input w-full font-mono"
            />
          </Field>
        </>
      )}

      {kind === 'gdrive' && (
        <Field
          label="Drive folder ID (optional)"
          hint="Leave blank to scan all reachable files. Find the ID in the folder's URL."
        >
          <input
            type="text"
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            className="input w-full font-mono"
          />
        </Field>
      )}

      {kind === 'onedrive' && (
        <>
          <Field
            label="Drive ID (optional)"
            hint="For SharePoint libraries. Leave blank to use your personal OneDrive."
          >
            <input
              type="text"
              value={driveId}
              onChange={(e) => setDriveId(e.target.value)}
              className="input w-full font-mono"
            />
          </Field>
          <Field label="Folder ID (optional)">
            <input
              type="text"
              value={folderId}
              onChange={(e) => setFolderId(e.target.value)}
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
          {create.isPending
            ? 'Connecting…'
            : isOAuth
              ? 'Continue to provider →'
              : 'Create source'}
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

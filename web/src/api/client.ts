const BASE = '';

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(`${BASE}${path}`, opts);
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(resp.ok ? 'Invalid JSON response' : `HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }
  if (!resp.ok) {
    const msg = data.detail || data.error || `HTTP ${resp.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data as T;
}

export const api = {
  createConnection: (conn: unknown) => request<unknown>('POST', '/api/connections', conn),
  listConnections: () => request<unknown[]>('GET', '/api/connections'),
  updateConnection: (id: string, conn: unknown) => request<unknown>('PUT', `/api/connections/${id}`, conn),
  deleteConnection: (id: string) => request<void>('DELETE', `/api/connections/${id}`),
  testConnection: (id: string) => request<{ ok: boolean; error?: string }>('POST', `/api/connections/${id}/test`),
  getVersions: () => request<{ source_versions: string[]; target_versions: string[] }>('GET', '/api/versions'),

  listResourceTypes: (connId: string) => request<unknown[]>('GET', `/api/connections/${connId}/resources`),
  listResources: (connId: string, type: string) => request<unknown[]>('GET', `/api/connections/${connId}/resources/${type}`),

  runCleanup: (connId: string) => request<{ job_id: string }>('POST', `/api/connections/${connId}/cleanup`),
  runExport: (connId: string) => request<{ job_id: string }>('POST', `/api/connections/${connId}/export`),

  migrationPreview: (sourceId: string, destinationId: string) =>
    request<{ job_id: string }>('POST', '/api/migrate/preview', {
      source_id: sourceId,
      destination_id: destinationId,
    }),
  getMigrationPreview: (jobId: string) =>
    request<unknown>('GET', `/api/migrate/preview/${jobId}`),
  migrationRun: (sourceId: string, destinationId: string, previewJobId: string, exclusions?: Record<string, string[]>) => {
    const intExclusions: Record<string, number[]> = {};
    if (exclusions) {
      for (const [type, ids] of Object.entries(exclusions)) {
        intExclusions[type] = ids.map(id => parseInt(id, 10)).filter(n => !isNaN(n));
      }
    }
    return request<{ job_id: string }>('POST', '/api/migrate/run', {
      source_id: sourceId,
      destination_id: destinationId,
      job_id: previewJobId,
      exclusions: intExclusions,
    });
  },

  migrationPrep: (sourceId: string, destinationId: string, force = false) =>
    request<{ job_id: string }>('POST', '/api/migrate/prep', { source_id: sourceId, destination_id: destinationId, force }),
  migrationExport: (sourceId: string, destinationId: string, force = false, resume = false) =>
    request<{ job_id: string }>('POST', '/api/migrate/export', { source_id: sourceId, destination_id: destinationId, force, resume }),
  migrationTransform: (sourceId: string, destinationId: string, force = false, resume = false) =>
    request<{ job_id: string }>('POST', '/api/migrate/transform', { source_id: sourceId, destination_id: destinationId, force, resume }),
  migrationImport: (sourceId: string, destinationId: string, phase: 'phase1' | 'phase2', force = false, resume = false) =>
    request<{ job_id: string }>('POST', '/api/migrate/import', { source_id: sourceId, destination_id: destinationId, phase, force, resume }),
  migrationCleanup: (sourceId: string, destinationId: string) =>
    request<{ job_id: string }>('POST', '/api/migrate/cleanup', { source_id: sourceId, destination_id: destinationId }),

  clearMigrationState: () => request<{ cleared_progress: number; deleted_mappings: number }>('POST', '/api/migrate/clear-state'),
  getExclusions: () => request<unknown>('GET', '/api/exclusions'),

  listJobs: () => request<unknown[]>('GET', '/api/jobs'),
  getJob: (id: string) => request<unknown>('GET', `/api/jobs/${id}`),
  cancelJob: (jobId: string) => request<{ status: string }>('POST', `/api/jobs/${jobId}/cancel`),
};

export function createJobLogSocket(jobId: string, onMessage: (line: string) => void, onClose?: (status: string) => void): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${window.location.host}/ws/jobs/${jobId}/logs`);
  ws.onmessage = (e) => onMessage(e.data);
  ws.onclose = (e) => onClose?.(e.reason || 'closed');
  return ws;
}

export interface Connection {
  id: string;
  name: string;
  type: 'aap';
  role: 'source' | 'destination';
  url: string;
  token: string;
  verify_ssl: boolean;
  version?: string;
  api_prefix?: string;
  ping_status?: 'unknown' | 'ok' | 'error';
  ping_error?: string;
  auth_status?: 'unknown' | 'ok' | 'error';
  auth_error?: string;
  last_checked?: string;
}

/** Payload for create/update; type is assigned server-side (AAP-only). */
export type ConnectionPayload = Omit<Connection, 'id' | 'token' | 'type'> & {
  token?: string;
};

export interface TestResult {
  ok: boolean;
  error?: string;
}

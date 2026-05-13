# Web UI

AAP Bridge includes a browser-based interface built with React and PatternFly 5.
It provides the same capabilities as the CLI through a graphical interface with
real-time log streaming.

## Starting the Web UI

### Container Deployment (Recommended)

```bash
# Build and start all 3 containers
make build-all
make up

# Access at http://localhost:8080
```

This starts:

| Container | Port | Network | Description |
| --- | --- | --- | --- |
| **db** | 15432 | bridge | PostgreSQL 15 state database |
| **engine** | 8000 | host | FastAPI API server + migration engine |
| **ui** | 8080 | host | nginx serving React UI + API proxy |

> **Networking note:** In the default `compose.yml`, the engine and UI containers
> both use `network_mode: host` so they share the host network namespace. This is
> specific to local testing where AAP instances run as podman containers with
> host-mapped ports (e.g. `localhost:10743`). The engine needs host networking to
> reach those ports, and the UI needs it to proxy requests to the engine at
> `localhost:8000`. In rootless podman, bridge and host networks are fully
> isolated — containers on different network modes cannot communicate.
>
> In a production deployment where AAP instances are on real servers with
> routable addresses, the engine and UI can use normal bridge networking instead.

### Local Development

For frontend development with hot-reload:

```bash
# Terminal 1: Start the API server
pip install -e '.[api]'
export MIGRATION_STATE_DB_PATH=postgresql://user:pass@localhost:5432/aap_migration
aap-bridge serve --reload

# Terminal 2: Start the Vite dev server
make web-install
make web-dev

# Access at http://localhost:5173
```

## Pages

### Connections

Manage AWX and AAP instance connections. Each connection stores:

- **Name** - Friendly label
- **Type** - AWX or AAP
- **Role** - Source (migrate from) or Destination (migrate to)
- **URL** - Full instance URL (e.g., `https://aap.example.com`)
- **Token** - API authentication token
- **Verify SSL** - Whether to verify TLS certificates

Use the **Test** button to verify connectivity. This checks:

1. Ping (unauthenticated `/ping/` endpoint)
2. Auth (authenticated `/me/` endpoint)
3. Version detection

### Operations

Select a connection and run operations against it:

- **Browse** - Open the Object Browser filtered to this connection
- **Export** - Download all resources as JSON
- **Cleanup** - Delete non-default objects (destructive)

Each operation runs as an async job with live log streaming.

### Migrate

Three-step migration wizard:

1. **Select** - Choose source and destination connections
2. **Preview** - Runs an async preview job that exports source resources and
   detects conflicts on the destination. Shows counts of resources to create vs.
   skip, with per-resource exclusion checkboxes.
3. **Run** - Executes the migration with real-time log streaming and a cancel
   button.

### Object Browser

Browse any resource type (organizations, credentials, job templates, etc.) on
any connected AAP/AWX instance. Supports search filtering and shows up to 8
columns per resource type.

### Jobs

Historical listing of all async operations with:

- Job type, status (color-coded), start time, duration
- Auto-refreshes every 3 seconds
- Click "View Logs" to open the log viewer for any job

## API Endpoints

The API server exposes these endpoints:

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/connections` | Create connection |
| GET | `/api/connections` | List connections |
| PUT | `/api/connections/{id}` | Update connection |
| DELETE | `/api/connections/{id}` | Delete connection |
| POST | `/api/connections/{id}/test` | Test connectivity |
| GET | `/api/connections/{id}/resources` | List resource types |
| GET | `/api/connections/{id}/resources/{type}` | List resources |
| POST | `/api/connections/{id}/cleanup` | Run cleanup |
| POST | `/api/connections/{id}/export` | Run export |
| POST | `/api/migrate/preview` | Start migration preview |
| GET | `/api/migrate/preview/{job_id}` | Get preview results |
| POST | `/api/migrate/run` | Execute migration |
| GET | `/api/exclusions` | Get exclusion lists |
| GET | `/api/jobs` | List jobs |
| GET | `/api/jobs/{id}` | Get job details |
| POST | `/api/jobs/{id}/cancel` | Cancel running job |
| WS | `/ws/jobs/{id}/logs` | Stream job logs |

Interactive API documentation is available at `/docs` (Swagger UI) and
`/redoc` when the API server is running.

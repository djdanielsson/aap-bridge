# Web UI Quick Start

AAP Bridge includes a browser-based interface for managing migrations, running dependency analysis, and calculating infrastructure sizing — all from your browser.

## Prerequisites

- **Podman** (or Docker) with Compose support
- Access to your source and target AAP instances (URLs + API tokens)

## Launch

```bash
# Clone and enter the repo
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Build all container images
make build-all

# Start the stack (PostgreSQL + API engine + UI)
make up

# Open in browser
# http://localhost:8080
```

This starts three containers:

- **db** — PostgreSQL for migration state tracking
- **engine** — FastAPI backend (port 8000)
- **ui** — React/PatternFly frontend served by nginx (port 8080)

To stop:

```bash
make down
```

## Setting Up Connections

1. Navigate to **Connections** in the sidebar
2. Click **Add Connection**
3. Fill in:
   - **Name** — a friendly label (e.g., "AAP 2.4 Source")
   - **Type** — AWX or AAP
   - **Role** — Source (migrate from) or Destination (migrate to)
   - **URL** — the base URL of your AAP instance (e.g., `https://aap.example.com`). You can include the API path (`/api/v2` or `/api/controller/v2`) or leave it off — the tool normalizes it automatically.
   - **Token** — API Bearer token
   - **Verify SSL** — uncheck for self-signed certificates
4. Click **Save**, then **Test** to verify connectivity

!!! note "Getting an API token"
    - **AAP 2.4 and earlier:**
      ```bash
      curl -k -X POST -u "admin:password" \
        -H "Content-Type: application/json" \
        -d '{"description": "aap-bridge", "scope": "write"}' \
        https://your-aap/api/v2/tokens/ | jq -r '.token'
      ```
    - **AAP 2.6 and later:**
      ```bash
      curl -k -X POST -u "admin:password" \
        -H "Content-Type: application/json" \
        -d '{"description": "aap-bridge", "scope": "write"}' \
        https://your-aap/api/gateway/v1/tokens/ | jq -r '.token'
      ```

!!! note "Token encryption"
    Connection tokens are encrypted at rest in the database using Fernet
    symmetric encryption. The encryption key is sourced from the
    `AAP_BRIDGE_SECRET_KEY` environment variable. If not set, a key is
    auto-generated and saved to `.secret_key` on first run.

    To generate a key explicitly:
    ```bash
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ```

    Set it in your `.env` file or `compose.yml` environment section:
    ```bash
    AAP_BRIDGE_SECRET_KEY=your-generated-key-here
    ```

    **Important**: Back up your secret key. If lost, existing encrypted tokens
    in the database cannot be decrypted and connections will need to be
    re-created with new tokens.

## Running a Migration

1. Go to **Migration > Migrate** in the sidebar
2. Select your **Source** and **Destination** connections
3. Click **Preview** — this fetches all resources from the source and compares against the destination. You'll see:
   - Resources to **create** (new on destination)
   - Resources to **skip** (already exist)
   - Per-resource checkboxes to **exclude** specific items
4. Uncheck anything you don't want to migrate
5. Click **Run Migration** — logs stream in real-time, and you can cancel mid-run

## Dependency Analysis

Go to **Planning > Dependency Analysis** in the sidebar.

1. Select a source connection
2. Click **Run Analysis**
3. Results appear in four tabs:
   - **Summary** — org counts, migration order, critical path blockers, global resources
   - **Migration Phases** — which orgs can migrate in parallel
   - **Organizations** — expandable per-org cards showing resource breakdowns, cross-org dependencies, and who blocks whom
   - **Quality** — quality scores, duplicate resource details (with severity/impact/recommendation), naming convention breakdown

Use the **Download JSON** and **Download HTML Report** buttons to export results.

## Sizing Calculator

Go to **Planning > Sizing Calculator** in the sidebar.

Enter your workload parameters:

- Managed hosts, playbooks per day, job duration, forks, verbosity
- Peak usage pattern (24x7, business hours, batch window)
- Advanced: controller nodes, concurrent jobs, hub/EDA nodes, retention settings

Click **Calculate** to get sizing recommendations for:

- Execution nodes (pods, CPU, memory)
- Controller (CPU, memory)
- Database storage
- Automation Hub, Platform Gateway, EDA, Redis

## Other Pages

### Operations

Select a connection and run:

- **Export** — download all resources as JSON
- **Cleanup** — delete non-default objects from a destination (destructive)

Each operation runs as a background job with live log streaming.

### Object Browser

Browse any resource type (organizations, credentials, job templates, etc.) on any connected AAP instance. Select a connection, pick a resource type, and view the results in a searchable table.

### Jobs

View all background jobs (migrations, exports, cleanups, analyses) with status, timing, and log viewer.

## Environment Configuration

The compose stack uses environment variables for database configuration. These are set in `compose.yml`:

```yaml
environment:
  MIGRATION_STATE_DB_PATH: "postgresql://aap_migration_user:redhat123!@db:5432/aap_migration"
```

To customize the database credentials, either edit `compose.yml` directly or create a `.env` file:

```bash
POSTGRES_USER=aap_migration_user
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=aap_migration
```

## Developer Setup

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

## API Reference

Interactive API documentation is available at `/docs` (Swagger UI) and `/redoc` when the API server is running.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/connections` | Create connection |
| GET | `/api/connections` | List connections |
| PUT | `/api/connections/{id}` | Update connection |
| DELETE | `/api/connections/{id}` | Delete connection |
| POST | `/api/connections/{id}/test` | Test connectivity |
| POST | `/api/migrate/preview` | Start migration preview |
| POST | `/api/migrate/run` | Execute migration |
| POST | `/api/analysis/run` | Run dependency analysis |
| GET | `/api/analysis/{id}` | Get analysis results |
| GET | `/api/analysis/{id}/export/json` | Download analysis JSON |
| GET | `/api/analysis/{id}/export/html` | Download analysis HTML report |
| POST | `/api/sizing/calculate` | Calculate infrastructure sizing |
| GET | `/api/jobs` | List jobs |
| GET | `/api/jobs/{id}` | Get job details |
| WS | `/ws/jobs/{id}/logs` | Stream job logs |

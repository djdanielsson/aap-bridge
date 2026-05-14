# Installation

AAP Bridge can be run three ways. Choose whichever fits your environment:
The containerized options add to the original local install; they do not
replace it.

| Mode | What you need | Best for |
| --- | --- | --- |
| **Local** | Python 3.12, PostgreSQL | Direct host install, no containers |
| **Container CLI** | podman + make | Isolated CLI/TUI in a container |
| **Web UI** | podman + make | Browser-based migration interface |

---

## Local Installation

Run AAP Bridge directly on the host with no containers.

### Prerequisites

- **Python 3.12** or higher
- **PostgreSQL** database (for state management)
- **uv** package manager (recommended) or pip
- Network access to source and target AAP instances

#### Hardware Requirements

| Migration Size | RAM | Notes |
| --- | --- | --- |
| < 10,000 hosts | 4GB | Minimal setup |
| 10,000 - 50,000 hosts | 8GB | Recommended |
| 50,000+ hosts | 16GB+ | Large-scale migrations |

### Setup

```bash
# Clone the repository
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Complete setup (venv + deps + editable install + .env)
make setup

# Activate the virtual environment
source .venv/bin/activate
```

Or step by step:

```bash
make venv                 # Create Python 3.12 venv
source .venv/bin/activate
make install-dev          # Install all dependencies
make install-editable     # Install aap-bridge in editable mode
make init-env             # Create .env from .env.example
```

### Database Setup

AAP Bridge requires a PostgreSQL database for state management:

```bash
# Create database and user
psql -c "CREATE DATABASE aap_migration;"
psql -c "CREATE USER aap_migration_user WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE aap_migration TO aap_migration_user;"

# For PostgreSQL 15+, grant schema permissions
psql -d aap_migration -c "GRANT ALL ON SCHEMA public TO aap_migration_user;"
```

Edit `.env` with your database connection and AAP instance details:

```bash
MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:your_secure_password@localhost:5432/aap_migration
SOURCE__URL=https://source-aap.example.com/api/v2
SOURCE__TOKEN=your_source_token
TARGET__URL=https://target-aap.example.com/api/controller/v2
TARGET__TOKEN=your_target_token
```

!!! note
    The tool automatically creates the necessary tables on first run.

### Verify

```bash
aap-bridge --version
aap-bridge --help
```

### Run

```bash
# Interactive TUI menu
aap-bridge

# Or run a migration directly
aap-bridge migrate full --config config/config.yaml
```

---

## Container CLI

Run the CLI/TUI inside a container. PostgreSQL is included — no manual database setup needed.

### Prerequisites

- **podman** (or docker) with compose support
- **make**

### Setup

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Build the container image
make build

# Start bridge + postgres
make up-dev

# Shell into the running container
make shell
```

### Verify

Inside the container:

```bash
aap-bridge --help
```

### Run

Inside the container:

```bash
# Interactive TUI menu
aap-bridge

# Or run a migration directly
aap-bridge migrate full --dry-run
```

### Useful Commands

| Command | Description |
| --- | --- |
| `make up-dev` | Start db + bridge container |
| `make shell` | Shell into bridge container |
| `make down` | Stop all containers |
| `make logs` | Tail container logs |
| `make c-test` | Run unit tests inside container |
| `make c-check` | Run lint + typecheck + test inside container |

---

## Web UI

Browser-based interface for managing connections, previewing migrations, and streaming logs in real time. Runs as 3 containers (PostgreSQL, API engine, nginx UI).

### Prerequisites

- **podman** (or docker) with compose support
- **make**

### Setup

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Generate a persistent API token encryption key for the web API
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
# Add the printed value to .env as AAP_BRIDGE_ENCRYPTION_KEY=...

# Build engine + UI container images
make build-all

# Start all 3 containers
make up
```

### Verify

Open [http://localhost:8080](http://localhost:8080) in a browser.

### Containers

| Container | Port | Description |
| --- | --- | --- |
| **db** | 15432 | PostgreSQL 15 state database |
| **engine** | 8000 | FastAPI API server + migration engine |
| **ui** | 8080 | nginx serving React UI + API proxy |

### Useful Commands

| Command | Description |
| --- | --- |
| `make up` | Start db + engine + ui |
| `make down` | Stop all containers |
| `make logs` | Tail all container logs |
| `make shell-engine` | Shell into engine container |

See the [Web UI guide](../user-guide/web-ui.md) for full documentation of the interface.

---

## Next Steps

- [Quick Start](quickstart.md) - Run your first migration in 5 minutes
- [Configuration](configuration.md) - Configure your environment
- [CLI Reference](../user-guide/cli-reference.md) - Full command reference
- [Web UI](../user-guide/web-ui.md) - Browser interface guide

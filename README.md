# AAP Bridge

A production-grade migration tool for Ansible Automation Platform (AAP), designed to handle large-scale migrations (80,000+ hosts) between AAP versions 1.0 through 2.6.

AAP Bridge provides both a CLI and a web interface for migrating organizations, credentials, inventories, hosts, job templates, workflows, RBAC, and more — with cross-organization dependency analysis, infrastructure sizing, and quality reporting built in.

## Quick Start

Choose your preferred interface:

### Option 1: Web UI (recommended for most users)

Run the browser-based interface with Podman/Docker Compose:

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge
make build-all && make up
# Open http://localhost:8080
```

**[Web UI Guide](docs/user-guide/web-ui.md)** — Setup, creating connections, running migrations, dependency analysis, and sizing calculator.

### Option 2: CLI

Install locally and run migrations from the command line:

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge
uv venv --seed --python 3.12 && source .venv/bin/activate
uv sync
cp .env.example .env  # Edit with your AAP credentials
aap-bridge             # Interactive menu
```

**[CLI Quick Start](docs/getting-started/quickstart.md)** — Environment setup, configuration, and running your first migration.

See also: **[CLI Reference](docs/user-guide/cli-reference.md)** for all commands and options.

## Key Features

- **Migration** — Full ETL pipeline: export, transform, import with checkpoint/resume and idempotency
- **Bulk Operations** — Leverages AAP bulk APIs (200 hosts/batch) for high-performance migrations
- **Dependency Analysis** — Cross-organization dependency detection, migration ordering, circular dependency handling
- **Quality Analysis** — Duplicate resource detection, naming convention analysis, quality scoring per organization
- **Sizing Calculator** — AAP 2.6 infrastructure sizing based on Red Hat official formulas
- **State Management** — PostgreSQL-backed progress tracking with checkpoint/resume capability
- **Version Support** — Migrate from AAP 1.0, 1.1, 1.2, 2.0–2.6 to AAP 2.6

## Documentation

Full documentation: **[redhat-cop.github.io/aap-bridge](https://redhat-cop.github.io/aap-bridge/)**

| Guide | Description |
|-------|-------------|
| [Installation](docs/getting-started/installation.md) | Prerequisites and installation methods |
| [Configuration](docs/getting-started/configuration.md) | config.yaml, environment variables, performance tuning |
| [Migration Workflow](docs/user-guide/migration-workflow.md) | Step-by-step migration process |
| [Troubleshooting](docs/user-guide/troubleshooting.md) | Common issues and solutions |
| [Compatibility Matrix](docs/reference/compatibility-matrix.md) | Supported AAP version migration paths |

## Contributing

We welcome contributions. See the **[Contributing Guide](docs/developer-guide/contributing.md)** to get started.

| Guide | Description |
|-------|-------------|
| [Architecture](docs/developer-guide/architecture.md) | System design, ETL pipeline, module structure |
| [Testing](docs/developer-guide/testing.md) | Unit tests, integration tests with podman, golden images |
| [Adding Resource Types](docs/developer-guide/adding-resource-types.md) | How to add support for new AAP resources |

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

## Security

For vulnerability reporting, see [SECURITY.md](SECURITY.md).

## Support

- **Issues**: [GitHub Issues](https://github.com/redhat-cop/aap-bridge/issues)
- **Security**: Report vulnerabilities privately (see [SECURITY.md](SECURITY.md))

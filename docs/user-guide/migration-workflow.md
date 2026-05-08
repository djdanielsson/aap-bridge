# Migration Workflow

This guide explains the complete AAP migration process.

## Overview

AAP Bridge follows an ETL (Export, Transform, Load) pattern:

```text
┌──────────┐    ┌──────────┐    ┌───────────┐    ┌────────┐    ┌──────────┐
│   Prep   │──▶│  Export  │──▶│ Transform │──▶│ Import │──▶│ Validate │
└──────────┘    └──────────┘    └───────────┘    └────────┘    └──────────┘

```

## Phase 1: Preparation

```bash
aap-bridge prep

```

**Purpose:** Analyze both AAP instances and prepare for migration.

**What happens:**

1. Connects to source AAP and fetches API schema
2. Connects to target AAP and fetches API schema
3. Compares schemas to identify field differences
4. Generates transformation rules
5. Saves prep data for subsequent phases

**Output:**

- `prep/source_schema.json` - Source AAP schema
- `prep/target_schema.json` - Target AAP schema
- `prep/schema_comparison.json` - Field differences and transformations

## Phase 2: Export

```bash
aap-bridge export

```

**Purpose:** Extract all resources from source AAP.

**What happens:**

1. Exports resources in dependency order
2. Handles pagination automatically
3. Splits large datasets into multiple files
4. Tracks export progress in state database

**Export Order:**

| Order | Resources | Notes |
| --- | --- | --- |
| 1 | Organizations | Foundation resource |
| 2 | Labels | |
| 3 | Users, Teams | Includes team membership and role grants |
| 4 | Credential Types, Credentials, Credential Input Sources | |
| 5 | Execution Environments | Default platform EEs are skipped by default |
| 6 | Inventories | Smart and constructed inventories exported separately |
| 7 | Inventory Sources | Includes cloud/SCM source configuration |
| 8 | Inventory Groups | Includes nested group hierarchy |
| 9 | Hosts | Dynamic hosts skipped by default |
| 10 | Projects | |
| 11 | Notification Templates | |
| 12 | Job Templates | Includes survey spec and notification associations |
| 13 | Workflow Job Templates | Includes nodes, survey spec, and notification associations |
| 14 | Schedules | System-job schedules excluded |
| 15 | Role Definitions | AAP 2.6 DAB RBAC custom role definitions |

**Output Structure:**

```text
exports/
├── metadata.json
├── organizations/
│   └── organizations_0001.json
├── inventories/
│   ├── inventories_0001.json
│   └── inventories_0002.json
└── hosts/
    ├── hosts_0001.json
    ├── hosts_0002.json
    └── hosts_0003.json

```

## Phase 3: Transform

```bash
aap-bridge transform

```

**Purpose:** Apply schema transformations for target AAP version.

**What happens:**

1. Reads exported data
2. Applies field mappings from schema comparison
3. Removes deprecated fields
4. Adds new required fields with defaults
5. Validates transformed data

**Transformations applied:**

- Field renames (e.g., API changes between versions)
- Type conversions
- Default value injection for new required fields
- Removal of read-only fields

## Phase 4: Import

```bash
aap-bridge import

```

**Purpose:** Load transformed data into target AAP.

**What happens:**

1. Creates resources in dependency order
2. Resolves foreign key references using ID mappings
3. Uses bulk APIs where available (hosts)
4. Handles conflicts (already exists)
5. Tracks progress and creates checkpoints

**Import Features:**

- **Bulk Operations**: Hosts imported 200 at a time via the AAP bulk API
- **Host-Group Associations**: Hosts are associated with their groups after bulk import
- **Inventory Source Sync**: After importing inventory sources, the tool triggers a sync and
  waits for completion before moving to constructed and smart inventories
- **Smart Inventory Deferral**: Smart inventories are imported in a dedicated phase after
  inventory source sync to ensure correct host membership
- **Survey Specs**: Job template and workflow job template survey specs are posted after
  template creation
- **Notification Associations**: Notification template relationships
  (started/success/error/approvals) are applied after template creation
- **Nested Groups**: Inventory group parent-child relationships are recreated after all groups
  are imported
- **Classic RBAC Translation**: User and team role grants from AAP 2.3–2.5 are translated to
  the AAP 2.6 DAB RBAC model
- **Idempotency**: Skips already-migrated resources
- **Conflict Resolution**: Updates or skips existing resources
- **Checkpointing**: Can resume from any failure point

## Phase 5: Validation

```bash
aap-bridge validate

```

**Purpose:** Verify migration success.

**What happens:**

1. Compares resource counts between source and target
2. Validates field values match
3. Checks relationship integrity
4. Generates validation report

## Checkpoint and Resume

### Automatic Checkpoints

Checkpoints are created automatically during import:

- After each resource type completes
- At configurable intervals within large batches

### Viewing Checkpoints

```bash
aap-bridge checkpoint list

```

### Resuming from Failure

```bash
# Resume from last checkpoint
aap-bridge migrate resume

# Resume from specific checkpoint
aap-bridge migrate resume --checkpoint inventories_batch_50

```

## Resource Dependencies

Understanding dependencies is crucial for migration:

```text
Organizations
    ├── Users (member of)
    │       └── Team memberships
    ├── Teams (belongs to)
    │       └── Resource role grants
    ├── Credentials (owned by)
    ├── Projects (belongs to)
    └── Inventories (belongs to)
            ├── Inventory Sources → sync → Smart Inventories
            ├── Inventory Groups (with nested hierarchy)
            │       └── Hosts (associated after bulk import)
            └── Constructed Inventories (after inventory source sync)

Credential Types (standalone)
    └── Credentials (uses)
            └── Credential Input Sources

Execution Environments (standalone)

Notification Templates (org-scoped)

Job Templates
    ├── Project (uses)
    ├── Inventory (uses)
    ├── Credentials (uses)
    ├── Execution Environment (uses)
    ├── Survey Spec (sub-resource)
    └── Notification Associations (started/success/error)

Workflow Job Templates
    ├── Nodes (embedded, including approval templates)
    ├── Survey Spec (sub-resource)
    └── Notification Associations (started/success/error/approvals)

Role Definitions (AAP 2.6 DAB RBAC)
    ├── Role User Assignments
    └── Role Team Assignments
```

## Best Practices

### Before Migration

1. **Backup target AAP** - Always have a rollback plan
2. **Test in staging** - Run migration in a test environment first
3. **Check disk space** - Exports can be large
4. **Verify credentials** - Ensure API tokens have admin access

### During Migration

1. **Monitor progress** - Watch for errors in logs
2. **Don't interrupt bulk operations** - Wait for completion
3. **Use checkpoints** - Resume rather than restart on failure

### After Migration

1. **Validate thoroughly** - Run validation phase
2. **Test functionality** - Run sample job templates
3. **Check RBAC** - Verify user permissions
4. **Update credentials** - Encrypted values need manual setup

## Troubleshooting

See [Troubleshooting Guide](troubleshooting.md) for common issues and solutions.

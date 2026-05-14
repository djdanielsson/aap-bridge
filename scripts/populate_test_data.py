#!/usr/bin/env python3
"""Populate an AAP/AWX instance with realistic test data.

Creates cross-organization dependencies that exercise the dependency analyzer:
- Shared Services org provides credentials and projects to other orgs
- Platform org provides inventories to application orgs
- Job templates reference resources across org boundaries
- Workflows chain JTs from multiple orgs
- Inventory sources reference cross-org projects
- Nested group hierarchies
- Schedules on key job templates
"""

from __future__ import annotations

import argparse
import json
import random
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

SIZES = {
    "small": {"orgs": (4, 6), "per_org": (8, 12), "cred_types": (8, 12), "notif": (2, 4)},
    "med": {"orgs": (15, 25), "per_org": (8, 12), "cred_types": (20, 30), "notif": (3, 5)},
    "large": {"orgs": (40, 60), "per_org": (15, 25), "cred_types": (40, 60), "notif": (5, 10)},
    "xl": {"orgs": (80, 120), "per_org": (80, 120), "cred_types": (80, 120), "notif": (10, 20)},
    "xxl": {"orgs": (90, 110), "per_org": (450, 550), "cred_types": (80, 120), "notif": (15, 25)},
}

# Org archetypes for realistic naming and dependency patterns
ORG_ARCHETYPES = [
    ("Shared-Services", "shared"),
    ("Platform-Engineering", "platform"),
    ("Network-Operations", "app"),
    ("Security-Compliance", "app"),
    ("Cloud-Infrastructure", "app"),
    ("Application-Delivery", "app"),
    ("Database-Operations", "app"),
    ("DevOps-Tooling", "app"),
    ("Monitoring-Observability", "app"),
    ("Identity-Access-Mgmt", "app"),
    ("Storage-Backup", "app"),
    ("Release-Engineering", "app"),
    ("QA-Testing", "app"),
    ("Edge-Computing", "app"),
    ("Disaster-Recovery", "app"),
    ("Cost-Optimization", "app"),
    ("Container-Platform", "app"),
    ("Data-Engineering", "app"),
    ("ML-Operations", "app"),
    ("Site-Reliability", "app"),
]


@dataclass
class OrgState:
    id: int
    name: str
    role: str  # "shared", "platform", "app"
    cred_ids: list[int] = field(default_factory=list)
    project_ids: list[int] = field(default_factory=list)
    inv_ids: list[int] = field(default_factory=list)
    host_ids: list[int] = field(default_factory=list)
    group_ids: list[int] = field(default_factory=list)
    jt_ids: list[int] = field(default_factory=list)
    wfjt_ids: list[int] = field(default_factory=list)
    label_ids: list[int] = field(default_factory=list)


@dataclass
class State:
    orgs: list[OrgState] = field(default_factory=list)
    user_ids: list[int] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    cred_type_ids: list[int] = field(default_factory=list)
    demo_project_id: int | None = None
    created: int = 0
    failed: int = 0

    @property
    def shared_org(self) -> OrgState | None:
        return next((o for o in self.orgs if o.role == "shared"), None)

    @property
    def platform_org(self) -> OrgState | None:
        return next((o for o in self.orgs if o.role == "platform"), None)

    @property
    def app_orgs(self) -> list[OrgState]:
        return [o for o in self.orgs if o.role == "app"]

    def all_creds(self) -> list[int]:
        return [c for o in self.orgs for c in o.cred_ids]

    def all_invs(self) -> list[int]:
        return [i for o in self.orgs for i in o.inv_ids]

    def all_jts(self) -> list[int]:
        return [j for o in self.orgs for j in o.jt_ids]


class AAPClient:
    def __init__(self, host: str, token: str) -> None:
        self.base = host.rstrip("/") + "/api/v2"
        self.token = token
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def post(self, endpoint: str, data: dict) -> dict | None:
        url = f"{self.base}/{endpoint}/"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, context=self.ctx) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError:
            return None

    def post_or_get(self, endpoint: str, data: dict, name_field: str = "name") -> dict | None:
        """Create a resource, or return the existing one if it already exists."""
        r = self.post(endpoint, data)
        if r and r.get("id"):
            return r
        name = data.get(name_field, "")
        if name:
            existing = self.get(endpoint, f"name={urllib.parse.quote(str(name))}")
            if existing and existing.get("results"):
                return existing["results"][0]
        return None

    def get(self, endpoint: str, params: str = "") -> dict | None:
        url = f"{self.base}/{endpoint}/"
        if params:
            url += f"?{params}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, context=self.ctx) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError:
            return None


def rand(lo: int, hi: int) -> int:
    return random.randint(lo, hi)


def progress(label: str, i: int, total: int, extra: str = "") -> None:
    bar_len = 30
    filled = int(bar_len * i / max(total, 1))
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = int(100 * i / max(total, 1))
    suffix = f" {extra}" if extra else ""
    print(f"\r  {label:30s} {bar} {pct:3d}% ({i}/{total}){suffix}", end="", flush=True)
    if i >= total:
        print()


def populate(client: AAPClient, size_name: str) -> None:
    cfg = SIZES[size_name]
    st = State()

    num_orgs = rand(*cfg["orgs"])
    per_org = cfg["per_org"]
    num_cred_types = rand(*cfg["cred_types"])
    notif_range = cfg["notif"]

    # --- Find Demo Project ---
    resp = client.get("projects", "status=successful&page_size=1")
    if resp and resp.get("results"):
        st.demo_project_id = resp["results"][0]["id"]
        print(f"Using Demo Project id={st.demo_project_id}")
    else:
        print("WARNING: No synced project found. Job templates will be skipped.")

    # --- Organizations (with archetypes) ---
    # ~10% of orgs are isolated (no cross-org deps at all)
    num_isolated = max(1, num_orgs // 10)
    print(f"\n=== Organizations ({num_orgs}, {num_isolated} isolated) ===")
    archetypes = list(ORG_ARCHETYPES)
    for i in range(num_orgs):
        progress("Organizations", i, num_orgs)
        if i < len(archetypes):
            name, role = archetypes[i]
        else:
            name, role = f"Org-{i + 1}", "app"

        # Last N orgs become isolated — fully self-contained, no cross-org deps
        if i >= num_orgs - num_isolated:
            name = f"Standalone-{i - (num_orgs - num_isolated) + 1}"
            role = "isolated"

        r = client.post_or_get(
            "organizations", {"name": name, "description": f"{role.title()} organization"}
        )
        if r:
            st.orgs.append(OrgState(id=r["id"], name=name, role=role))
            st.created += 1
        else:
            st.failed += 1
    progress(
        "Organizations",
        num_orgs,
        num_orgs,
        f"done ({len(st.orgs)} loaded, {num_isolated} isolated)",
    )

    if not st.orgs:
        print("ERROR: No orgs found or created.")
        return

    # --- Labels (shared across orgs) ---
    label_names = [
        "production",
        "staging",
        "development",
        "critical",
        "maintenance",
        "compliance",
        "automated",
        "manual-review",
        "high-priority",
        "deprecated",
    ]
    print(f"\n=== Labels ({len(label_names)}) ===")
    for i, lname in enumerate(label_names):
        progress("Labels", i, len(label_names))
        org = random.choice(st.orgs)
        r = client.post_or_get("labels", {"name": lname, "organization": org.id})
        if r:
            org.label_ids.append(r["id"])
            st.created += 1
        else:
            st.failed += 1
    progress("Labels", len(label_names), len(label_names), "done")

    # --- Users ---
    num_users = num_orgs * rand(*per_org)
    print(f"\n=== Users ({num_users}) ===")
    for i in range(num_users):
        if i % 10 == 0:
            progress("Users", i, num_users)
        r = client.post(
            "users",
            {
                "username": f"user-{i + 1}",
                "password": "TestPass123!",
                "first_name": random.choice(
                    ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank"]
                ),
                "last_name": f"User-{i + 1}",
                "email": f"user-{i + 1}@test.example.com",
            },
        )
        if r:
            st.user_ids.append(r["id"])
            st.created += 1
        else:
            st.failed += 1
    progress("Users", num_users, num_users, f"done ({len(st.user_ids)} created)")

    # --- Teams (per org) ---
    num_teams_per = rand(*per_org)
    total_teams = len(st.orgs) * num_teams_per
    print(f"\n=== Teams (~{num_teams_per}/org) ===")
    count = 0
    for org in st.orgs:
        n = rand(max(1, num_teams_per - 2), num_teams_per + 2)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Teams", count, total_teams)
            r = client.post_or_get(
                "teams",
                {
                    "name": f"{org.name}-Team-{j + 1}",
                    "organization": org.id,
                    "description": f"Team {j + 1} in {org.name}",
                },
            )
            if r:
                st.team_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Teams", count, count, f"done ({len(st.team_ids)} created)")

    # --- Credential Types (global) ---
    print(f"\n=== Credential Types ({num_cred_types}) ===")
    cred_type_names = [
        "AWS-Access-Key",
        "Azure-Service-Principal",
        "GCP-Service-Account",
        "VMware-vCenter",
        "Satellite-API",
        "ServiceNow-API",
        "HashiVault-Token",
        "LDAP-Bind",
        "SSH-Key-Pair",
        "WinRM-Cert",
        "Artifactory-Token",
        "GitHub-PAT",
        "GitLab-Token",
        "Jira-API",
        "Slack-Webhook",
        "PagerDuty-Key",
        "Datadog-API",
        "Splunk-HEC",
        "Terraform-Cloud",
        "Kubernetes-SA",
        "Docker-Registry",
        "Nexus-Creds",
        "Consul-Token",
        "RabbitMQ-Admin",
        "Redis-Auth",
        "MongoDB-Conn",
        "PostgreSQL-Conn",
        "MySQL-Conn",
        "Oracle-Wallet",
        "S3-Access",
    ]
    for i in range(num_cred_types):
        progress("Credential Types", i, num_cred_types)
        name = cred_type_names[i] if i < len(cred_type_names) else f"Custom-CredType-{i + 1}"
        r = client.post_or_get(
            "credential_types",
            {
                "name": name,
                "kind": "cloud",
                "description": f"Custom credential type: {name}",
                "inputs": {"fields": [{"id": "token", "type": "string", "label": "API Token"}]},
                "injectors": {},
            },
        )
        if r:
            st.cred_type_ids.append(r["id"])
            st.created += 1
        else:
            st.failed += 1
    progress(
        "Credential Types",
        num_cred_types,
        num_cred_types,
        f"done ({len(st.cred_type_ids)} created)",
    )

    # --- Credentials ---
    # Shared Services org gets 3x credentials (other orgs depend on them)
    # Platform org gets 2x credentials
    # ~30% of app org JTs will use Shared Services credentials (cross-org dep)
    num_creds_per = rand(*per_org)
    print(f"\n=== Credentials (~{num_creds_per}/org, shared services gets 3x) ===")
    count = 0
    for org in st.orgs:
        multiplier = 3 if org.role == "shared" else 2 if org.role == "platform" else 1
        n = rand(max(1, num_creds_per - 2), num_creds_per + 2) * multiplier
        for j in range(n):
            count += 1
            if count % 25 == 0:
                progress("Credentials", count, count)
            ct_id = random.choice(st.cred_type_ids) if st.cred_type_ids else 1
            r = client.post_or_get(
                "credentials",
                {
                    "name": f"{org.name}-Cred-{j + 1}",
                    "credential_type": ct_id,
                    "organization": org.id,
                    "description": f"Credential {j + 1} in {org.name}",
                    "inputs": {"token": f"token-{org.name}-{j + 1}"},
                },
            )
            if r:
                org.cred_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Credentials", count, count, f"done ({sum(len(o.cred_ids) for o in st.orgs)} created)")

    # --- Projects ---
    # Shared Services org gets shared automation projects others depend on
    # Platform org gets infrastructure projects
    num_proj_per = rand(*per_org)
    print(f"\n=== Projects (~{num_proj_per}/org, shared services gets 2x) ===")
    count = 0
    for org in st.orgs:
        multiplier = 2 if org.role == "shared" else 1
        n = rand(max(1, num_proj_per - 2), num_proj_per + 2) * multiplier
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Projects", count, count)
            r = client.post_or_get(
                "projects",
                {
                    "name": f"{org.name}-Proj-{j + 1}",
                    "organization": org.id,
                    "scm_type": "git",
                    "scm_url": "https://github.com/ansible/ansible-tower-samples.git",
                    "description": f"Project {j + 1} in {org.name}",
                },
            )
            if r:
                org.project_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Projects", count, count, f"done ({sum(len(o.project_ids) for o in st.orgs)} created)")

    # --- Inventories ---
    # Platform org gets shared infrastructure inventories
    num_inv_per = rand(*per_org)
    print(f"\n=== Inventories (~{num_inv_per}/org, platform gets 2x) ===")
    count = 0
    for org in st.orgs:
        multiplier = 2 if org.role == "platform" else 1
        n = rand(max(1, num_inv_per - 2), num_inv_per + 2) * multiplier
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Inventories", count, count)
            r = client.post_or_get(
                "inventories",
                {
                    "name": f"{org.name}-Inv-{j + 1}",
                    "organization": org.id,
                    "description": f"Inventory {j + 1} in {org.name}",
                },
            )
            if r:
                org.inv_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Inventories", count, count, f"done ({sum(len(o.inv_ids) for o in st.orgs)} created)")

    # --- Hosts (per inventory, subset) ---
    num_hosts_per = rand(*per_org)
    all_invs = st.all_invs()
    inv_sample = all_invs[: min(len(all_invs), num_orgs * 2)]
    total_hosts = len(inv_sample) * num_hosts_per
    print(f"\n=== Hosts (~{num_hosts_per}/inv across {len(inv_sample)} inventories) ===")
    count = 0
    for inv_id in inv_sample:
        n = rand(max(1, num_hosts_per - 2), num_hosts_per + 2)
        for j in range(n):
            count += 1
            if count % 25 == 0:
                progress("Hosts", count, total_hosts)
            r = client.post_or_get(
                "hosts",
                {
                    "name": f"host-{inv_id}-{j + 1}.test.example.com",
                    "inventory": inv_id,
                    "description": f"Host {j + 1} in inventory {inv_id}",
                    "variables": json.dumps(
                        {
                            "ansible_host": f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
                            "env": random.choice(["prod", "staging", "dev"]),
                            "region": random.choice(
                                ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
                            ),
                        }
                    ),
                },
            )
            if r:
                # Find which org this inv belongs to
                for org in st.orgs:
                    if inv_id in org.inv_ids:
                        org.host_ids.append(r["id"])
                        break
                st.created += 1
            else:
                st.failed += 1
    progress("Hosts", count, count, f"done ({sum(len(o.host_ids) for o in st.orgs)} created)")

    # --- Groups (nested hierarchy per inventory) ---
    num_groups_per = rand(*per_org)
    print(f"\n=== Groups (~{num_groups_per}/inv, nested hierarchy) ===")
    count = 0
    for org in st.orgs:
        for inv_id in org.inv_ids[:3]:  # limit to 3 inventories per org
            # Create parent groups first
            parent_names = ["production", "staging", "development"]
            parent_ids = []
            for pname in parent_names:
                count += 1
                r = client.post_or_get(
                    "groups",
                    {
                        "name": f"{org.name}-{pname}",
                        "inventory": inv_id,
                        "description": f"{pname.title()} environment group",
                    },
                )
                if r:
                    parent_ids.append(r["id"])
                    org.group_ids.append(r["id"])
                    st.created += 1

            # Create child groups under parents
            child_names = ["webservers", "databases", "loadbalancers", "appservers", "caches"]
            for parent_id in parent_ids:
                for cname in random.sample(child_names, min(3, len(child_names))):
                    count += 1
                    r = client.post_or_get(
                        "groups",
                        {
                            "name": f"{org.name}-{cname}-{parent_id}",
                            "inventory": inv_id,
                            "description": f"{cname.title()} under group {parent_id}",
                        },
                    )
                    if r:
                        org.group_ids.append(r["id"])
                        st.created += 1
                        # Add as child of parent
                        client.post(f"groups/{parent_id}/children", {"id": r["id"]})

            if count % 10 == 0:
                progress("Groups", count, count)
    progress("Groups", count, count, f"done ({sum(len(o.group_ids) for o in st.orgs)} created)")

    # --- Job Templates (with cross-org inventory + credential dependencies!) ---
    # AAP enforces: project must be in the same org as the JT.
    # Cross-org deps come from: inventories (any org) and credentials (any org).
    if st.demo_project_id:
        num_jt_per = rand(*per_org)
        print(f"\n=== Job Templates (~{num_jt_per}/org, cross-org inventory+credential deps) ===")
        count = 0
        cross_inv = 0
        cross_cred = 0
        shared = st.shared_org
        platform = st.platform_org

        for org in st.orgs:
            n = rand(max(1, num_jt_per - 2), num_jt_per + 2)
            for j in range(n):
                count += 1
                if count % 10 == 0:
                    progress("Job Templates", count, count)

                # Project: MUST be same org (AAP enforces this)
                project_id = (
                    random.choice(org.project_ids) if org.project_ids else st.demo_project_id
                )

                if org.role == "isolated":
                    inv_id = random.choice(org.inv_ids) if org.inv_ids else None
                else:
                    # Inventory: 50% own org, 30% platform org, 20% any other org
                    roll = random.random()
                    if roll < 0.5 and org.inv_ids:
                        inv_id = random.choice(org.inv_ids)
                    elif roll < 0.8 and platform and platform.inv_ids and org.role != "platform":
                        inv_id = random.choice(platform.inv_ids)
                        cross_inv += 1
                    else:
                        other_invs = [i for o in st.orgs for i in o.inv_ids if o.name != org.name]
                        inv_id = (
                            random.choice(other_invs)
                            if other_invs
                            else (random.choice(org.inv_ids) if org.inv_ids else None)
                        )
                        if inv_id and inv_id not in org.inv_ids:
                            cross_inv += 1

                if not inv_id:
                    continue

                jt_data = {
                    "name": f"{org.name}-JT-{j + 1}",
                    "inventory": inv_id,
                    "project": project_id,
                    "playbook": "hello_world.yml",
                    "description": f"Job template {j + 1} in {org.name}",
                }

                r = client.post_or_get("job_templates", jt_data)
                if r:
                    org.jt_ids.append(r["id"])
                    st.created += 1

                    # Associate cross-org credentials via sub-endpoint
                    # ~40% of non-isolated JTs get a credential from Shared Services
                    if (
                        org.role != "isolated"
                        and shared
                        and shared.cred_ids
                        and random.random() < 0.4
                    ):
                        cred_id = random.choice(shared.cred_ids)
                        cr = client.post(f"job_templates/{r['id']}/credentials", {"id": cred_id})
                        if cr is not None:
                            cross_cred += 1

                    # ~15% get a credential from a random other org
                    if org.role != "isolated" and random.random() < 0.15:
                        other_creds = [
                            c
                            for o in st.orgs
                            for c in o.cred_ids
                            if o.name != org.name and o.role != "isolated"
                        ]
                        if other_creds:
                            cred_id = random.choice(other_creds)
                            cr = client.post(
                                f"job_templates/{r['id']}/credentials", {"id": cred_id}
                            )
                            if cr is not None:
                                cross_cred += 1
                else:
                    st.failed += 1
        progress(
            "Job Templates",
            count,
            count,
            f"done ({sum(len(o.jt_ids) for o in st.orgs)} created, {cross_inv} cross-org inv, {cross_cred} cross-org cred)",
        )
    else:
        print("\n=== Job Templates: SKIPPED (no synced project) ===")

    # --- Workflow Job Templates (with cross-org JT node references!) ---
    num_wf_per = max(1, rand(*per_org) // 2)
    print(f"\n=== Workflow Job Templates (~{num_wf_per}/org, cross-org nodes) ===")
    count = 0
    for org in st.orgs:
        n = rand(max(1, num_wf_per - 1), num_wf_per + 1)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Workflow JTs", count, count)
            r = client.post_or_get(
                "workflow_job_templates",
                {
                    "name": f"{org.name}-WF-{j + 1}",
                    "organization": org.id,
                    "description": f"Workflow {j + 1} in {org.name}",
                },
            )
            if r:
                wf_id = r["id"]
                org.wfjt_ids.append(wf_id)
                st.created += 1

                # Add 2-5 workflow nodes referencing JTs
                all_jts = st.all_jts()
                if all_jts:
                    num_nodes = rand(2, min(5, len(all_jts)))
                    prev_node_id = None
                    for _k in range(num_nodes):
                        if org.role == "isolated":
                            # Isolated: only own JTs
                            jt_id = (
                                random.choice(org.jt_ids) if org.jt_ids else random.choice(all_jts)
                            )
                        elif org.jt_ids and random.random() < 0.5:
                            # 50% own org JTs, 50% any org JTs (cross-org dependency)
                            jt_id = random.choice(org.jt_ids)
                        else:
                            jt_id = random.choice(all_jts)

                        node_data = {"unified_job_template": jt_id}
                        node = client.post(
                            f"workflow_job_templates/{wf_id}/workflow_nodes", node_data
                        )
                        if node:
                            # Chain nodes: previous node's success leads to next
                            if prev_node_id:
                                client.post(
                                    f"workflow_job_template_nodes/{prev_node_id}/success_nodes",
                                    {"id": node["id"]},
                                )
                            prev_node_id = node["id"]
                            st.created += 1
            else:
                st.failed += 1
    progress(
        "Workflow JTs", count, count, f"done ({sum(len(o.wfjt_ids) for o in st.orgs)} created)"
    )

    # --- Schedules (on some JTs) ---
    all_jts = st.all_jts()
    num_schedules = min(len(all_jts) // 3, num_orgs * 3)
    print(f"\n=== Schedules ({num_schedules}) ===")
    scheduled_jts = random.sample(all_jts, min(num_schedules, len(all_jts)))
    for i, jt_id in enumerate(scheduled_jts):
        progress("Schedules", i, num_schedules)
        r = client.post(
            f"job_templates/{jt_id}/schedules",
            {
                "name": f"Schedule-JT-{jt_id}",
                "rrule": "DTSTART:20260101T000000Z RRULE:FREQ=DAILY;INTERVAL=1",
                "description": f"Daily schedule for JT {jt_id}",
            },
        )
        if r:
            st.created += 1
        else:
            st.failed += 1
    progress("Schedules", num_schedules, num_schedules, "done")

    # --- Notification Templates (per org) ---
    num_notif = rand(*notif_range)
    print(f"\n=== Notification Templates (~{num_notif}/org) ===")
    count = 0
    notif_created = 0
    for org in st.orgs:
        n = rand(max(1, num_notif - 1), num_notif + 1)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Notification Tmpls", count, count)
            if j % 2 == 0:
                notif_data = {
                    "name": f"{org.name}-Notif-{j + 1}",
                    "organization": org.id,
                    "notification_type": "webhook",
                    "notification_configuration": {
                        "url": f"https://hooks.example.com/notify/{org.name}/{j + 1}",
                        "http_method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                }
            else:
                notif_data = {
                    "name": f"{org.name}-Notif-{j + 1}",
                    "organization": org.id,
                    "notification_type": "email",
                    "notification_configuration": {
                        "host": "smtp.example.com",
                        "port": 25,
                        "username": "",
                        "password": "",
                        "use_tls": False,
                        "use_ssl": False,
                        "recipients": [f"{org.name.lower()}@example.com"],
                        "sender": f"aap-{org.name.lower()}@example.com",
                    },
                }
            r = client.post_or_get("notification_templates", notif_data)
            if r:
                notif_created += 1
                st.created += 1
            else:
                st.failed += 1
    progress("Notification Tmpls", count, count, f"done ({notif_created} created)")

    # --- Summary ---
    total_creds = sum(len(o.cred_ids) for o in st.orgs)
    total_projs = sum(len(o.project_ids) for o in st.orgs)
    total_invs = sum(len(o.inv_ids) for o in st.orgs)
    total_hosts = sum(len(o.host_ids) for o in st.orgs)
    total_groups = sum(len(o.group_ids) for o in st.orgs)
    total_jts = sum(len(o.jt_ids) for o in st.orgs)
    total_wfs = sum(len(o.wfjt_ids) for o in st.orgs)

    print(f"\n{'=' * 60}")
    print(f"  Size:          {size_name}")
    print(f"  Organizations: {len(st.orgs)}")
    num_isolated = len([o for o in st.orgs if o.role == "isolated"])
    for org in st.orgs:
        marker = " *" if org.role == "isolated" else ""
        print(
            f"    {org.name:30s} ({org.role:8s}) C={len(org.cred_ids):3d} P={len(org.project_ids):3d} I={len(org.inv_ids):3d} JT={len(org.jt_ids):3d} WF={len(org.wfjt_ids):3d}{marker}"
        )
    print(f"  Users:         {len(st.user_ids)}")
    print(f"  Teams:         {len(st.team_ids)}")
    print(f"  Cred Types:    {len(st.cred_type_ids)}")
    print(f"  Credentials:   {total_creds}")
    print(f"  Projects:      {total_projs}")
    print(f"  Inventories:   {total_invs}")
    print(f"  Hosts:         {total_hosts}")
    print(f"  Groups:        {total_groups} (nested hierarchy)")
    print(f"  Job Templates: {total_jts} (with cross-org project/inventory/credential refs)")
    print(f"  Workflow JTs:  {total_wfs} (with cross-org JT nodes)")
    print(f"  Schedules:     {len(scheduled_jts)}")
    print(f"  Notifications: {notif_created}")
    print("  ────────────────────────────")
    print(f"  Total created: {st.created}")
    print(f"  Total failed:  {st.failed}")
    print("\n  Cross-org dependency patterns:")
    print("    Shared Services → app orgs (credentials via JT association)")
    print("    Platform Engineering → app orgs (inventories used by JTs)")
    print("    Job Templates: ~50% use cross-org inventories, ~40% get Shared Services credentials")
    print("    Workflows: ~50% of nodes reference JTs from other orgs")
    print("    Note: Projects are always same-org (AAP enforces this)")
    print(
        f"    Isolated orgs ({num_isolated}): fully self-contained, no cross-org deps (* marked above)"
    )
    print(f"{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate AAP/AWX with realistic test data")
    parser.add_argument("--host", required=True, help="AAP URL (e.g. https://localhost:10743)")
    parser.add_argument("--token", required=True, help="API Bearer token")
    parser.add_argument(
        "--size", choices=list(SIZES.keys()), default="small", help="Data size tier"
    )
    args = parser.parse_args()

    print(f"Populating {args.host} with '{args.size}' test data set")
    client = AAPClient(args.host, args.token)

    resp = client.get("ping")
    if resp is None:
        print(f"ERROR: Cannot reach {args.host}/api/v2/ping/")
        sys.exit(1)
    print(f"Connected. Version: {resp.get('version', 'unknown')}")

    populate(client, args.size)


if __name__ == "__main__":
    main()

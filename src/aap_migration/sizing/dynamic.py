"""
Dynamic Sizing: Gather live metrics from an AAP instance to auto-calculate
recommended AAP 2.6 sizing based on actual workload history.

Connects to the source AAP API, inspects jobs history, instances, instance groups,
hosts, and configuration to derive sizing inputs automatically.
"""

import math
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from aap_migration.sizing.calculator import AAP26SizingCalculator

HEADROOM_MULTIPLIER = 1.25  # 25% buffer above observed peak


class DynamicSizingCollector:
    """Collects live metrics from an AAP instance for dynamic sizing calculations."""

    def __init__(
        self,
        base_url: str,
        token: str,
        api_prefix: str | None = None,
        verify_ssl: bool = True,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix or ""
        self.token = token
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{self.api_prefix}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        resp = httpx.get(
            url,
            headers=self._headers(),
            params=params,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_paginated_all(
        self, endpoint: str, params: dict[str, Any] | None = None, max_pages: int = 50
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        query = params.copy() if params else {}
        query["page_size"] = 200
        page = 1

        while page <= max_pages:
            query["page"] = page
            data = self._get(endpoint, params=query)
            items = data.get("results", [])
            results.extend(items)
            if not data.get("next"):
                break
            page += 1

        return results

    def get_config(self) -> dict[str, Any]:
        """Get AAP configuration including version and license info."""
        try:
            return self._get("config/")
        except Exception:
            return {}

    def get_instances(self) -> list[dict[str, Any]]:
        """Get all instances (nodes) in the cluster."""
        try:
            return self._get_paginated_all("instances/")
        except Exception:
            return []

    def get_instance_groups(self) -> list[dict[str, Any]]:
        """Get all instance groups."""
        try:
            return self._get_paginated_all("instance_groups/")
        except Exception:
            return []

    def get_hosts_count(self) -> int:
        """Get total managed host count."""
        try:
            data = self._get("hosts/", params={"page_size": 1})
            return data.get("count", 0)
        except Exception:
            return 0

    def get_inventories_summary(self) -> dict[str, Any]:
        """Get inventory count and total host count across inventories."""
        try:
            data = self._get("inventories/", params={"page_size": 1})
            count = data.get("count", 0)
            return {"inventory_count": count}
        except Exception:
            return {"inventory_count": 0}

    def get_job_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Get recent job history for workload analysis.

        Fetches completed jobs from the last N days to analyze
        throughput, duration, and concurrency patterns.
        """
        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        params: dict[str, Any] = {
            "status": "successful",
            "finished__gt": since,
            "order_by": "-finished",
        }
        try:
            return self._get_paginated_all("jobs/", params=params, max_pages=25)
        except Exception:
            return []

    def get_job_templates_summary(self) -> dict[str, Any]:
        """Get job template count and fork settings."""
        try:
            templates = self._get_paginated_all("job_templates/", max_pages=10)
            forks_values = [t.get("forks", 0) for t in templates if t.get("forks", 0) > 0]
            verbosity_values = [t.get("verbosity", 1) for t in templates]

            return {
                "template_count": len(templates),
                "forks_values": forks_values,
                "avg_forks": statistics.mean(forks_values) if forks_values else 5,
                "median_forks": statistics.median(forks_values) if forks_values else 5,
                "max_forks": max(forks_values) if forks_values else 5,
                "avg_verbosity": round(statistics.mean(verbosity_values))
                if verbosity_values
                else 1,
            }
        except Exception:
            return {
                "template_count": 0,
                "forks_values": [],
                "avg_forks": 5,
                "median_forks": 5,
                "max_forks": 5,
                "avg_verbosity": 1,
            }

    def get_settings_jobs(self) -> dict[str, Any]:
        """Get job-related settings (retention, concurrency limits)."""
        try:
            data = self._get("settings/jobs/")
            return {
                "max_forks": data.get("DEFAULT_JOB_FORKS", 5),
                "job_retention_days": data.get("DAYS_TO_KEEP_LAST_JOB", 30),
            }
        except Exception:
            return {"max_forks": 5, "job_retention_days": 30}

    def analyze_job_patterns(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze job history to determine workload patterns.

        Returns metrics needed for the sizing calculator:
        - playbooks_per_day_peak
        - job_duration_hours (average)
        - tasks_per_job (average)
        - peak concurrency pattern
        """
        if not jobs:
            return {
                "playbooks_per_day_peak": 0,
                "playbooks_per_day_avg": 0,
                "job_duration_hours": 0.25,
                "tasks_per_job": 50,
                "peak_pattern": "business_hours",
                "jobs_analyzed": 0,
                "analysis_days": 0,
            }

        # Parse job timestamps and compute per-day counts
        daily_counts: dict[str, int] = {}
        durations: list[float] = []
        hourly_distribution: dict[int, int] = dict.fromkeys(range(24), 0)

        for job in jobs:
            started = job.get("started")
            finished = job.get("finished")

            if started:
                try:
                    start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    day_key = start_dt.strftime("%Y-%m-%d")
                    daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
                    hourly_distribution[start_dt.hour] += 1
                except (ValueError, AttributeError):
                    pass

            if started and finished:
                try:
                    start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                    duration_hours = (end_dt - start_dt).total_seconds() / 3600
                    if 0 < duration_hours < 24:
                        durations.append(duration_hours)
                except (ValueError, AttributeError):
                    pass

        # Calculate peak and average playbooks per day
        day_values = list(daily_counts.values()) if daily_counts else [0]
        playbooks_per_day_peak = max(day_values) if day_values else 0
        playbooks_per_day_avg = statistics.mean(day_values) if day_values else 0

        # Average job duration
        avg_duration = statistics.mean(durations) if durations else 0.25
        p95_duration = (
            sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 10 else avg_duration
        )

        # Determine peak pattern from hourly distribution
        peak_pattern = self._detect_peak_pattern(hourly_distribution)

        # Days analyzed
        analysis_days = len(daily_counts) if daily_counts else 1

        return {
            "playbooks_per_day_peak": playbooks_per_day_peak,
            "playbooks_per_day_avg": round(playbooks_per_day_avg, 1),
            "job_duration_hours": round(avg_duration, 4),
            "job_duration_p95_hours": round(p95_duration, 4),
            "peak_pattern": peak_pattern,
            "jobs_analyzed": len(jobs),
            "analysis_days": analysis_days,
            "daily_counts": daily_counts,
            "hourly_distribution": hourly_distribution,
        }

    def _detect_peak_pattern(self, hourly_distribution: dict[int, int]) -> str:
        """Detect concurrency pattern from hourly job distribution."""
        total_jobs = sum(hourly_distribution.values())
        if total_jobs == 0:
            return "business_hours"

        # Business hours (8-18): what percentage of jobs run in this window?
        business_hours_jobs = sum(hourly_distribution.get(h, 0) for h in range(8, 18))
        business_ratio = business_hours_jobs / total_jobs

        # Check for batch window (concentrated in 2-4 hours)
        sorted_hours = sorted(hourly_distribution.values(), reverse=True)
        top_4_hours = sum(sorted_hours[:4])
        batch_ratio = top_4_hours / total_jobs

        if batch_ratio > 0.7:
            return "batch_window"
        elif business_ratio > 0.75:
            return "business_hours"
        elif business_ratio < 0.45:
            return "distributed_24x7"
        else:
            return "mixed"

    def _detect_allowed_hours(self, hourly_distribution: dict[int, int]) -> int:
        """Detect effective automation hours from job distribution."""
        total_jobs = sum(hourly_distribution.values())
        if total_jobs == 0:
            return 24

        threshold = total_jobs * 0.02  # hours with >2% of jobs count as active
        active_hours = sum(1 for count in hourly_distribution.values() if count > threshold)
        return max(4, min(24, active_hours))

    def collect_all_metrics(self, history_days: int = 30) -> dict[str, Any]:
        """Collect all metrics from the live AAP instance.

        Returns a complete metrics dict ready for the sizing calculator,
        along with raw observed data for transparency.
        """
        config = self.get_config()
        instances = self.get_instances()
        instance_groups = self.get_instance_groups()
        managed_hosts = self.get_hosts_count()
        inventories = self.get_inventories_summary()
        job_templates = self.get_job_templates_summary()
        jobs = self.get_job_history(days=history_days)
        settings = self.get_settings_jobs()
        job_patterns = self.analyze_job_patterns(jobs)

        # Categorize instances
        execution_instances = [
            i for i in instances if i.get("node_type") in ("execution", "hybrid")
        ]
        control_instances = [i for i in instances if i.get("node_type") in ("control", "hybrid")]

        # Compute current resource totals
        total_current_cpu = sum(i.get("cpu", 0) or 0 for i in instances)
        total_current_memory = sum((i.get("memory", 0) or 0) for i in instances)
        total_current_memory_gb = (
            total_current_memory / (1024**3) if total_current_memory > 0 else 0
        )

        # Determine allowed hours from job patterns
        allowed_hours = self._detect_allowed_hours(job_patterns.get("hourly_distribution", {}))

        # Apply headroom to peak playbooks per day
        peak_with_headroom = math.ceil(job_patterns["playbooks_per_day_peak"] * HEADROOM_MULTIPLIER)

        # Use job template forks if available, otherwise observed
        observed_forks = max(
            int(job_templates.get("avg_forks", 5)),
            settings.get("max_forks", 5),
        )

        # Job retention from settings
        job_retention_hours = settings.get("job_retention_days", 30) * 24

        return {
            "observed": {
                "version": config.get("version"),
                "license_type": config.get("license_info", {}).get("license_type"),
                "total_instances": len(instances),
                "execution_instances": len(execution_instances),
                "control_instances": len(control_instances),
                "instance_groups": len(instance_groups),
                "instance_group_names": [ig.get("name") for ig in instance_groups],
                "managed_hosts": managed_hosts,
                "inventories": inventories.get("inventory_count", 0),
                "job_templates": job_templates.get("template_count", 0),
                "total_current_cpu": total_current_cpu,
                "total_current_memory_gb": round(total_current_memory_gb, 1),
                "jobs_analyzed": job_patterns["jobs_analyzed"],
                "analysis_days": job_patterns["analysis_days"],
                "playbooks_per_day_peak": job_patterns["playbooks_per_day_peak"],
                "playbooks_per_day_avg": job_patterns["playbooks_per_day_avg"],
                "job_duration_hours_avg": job_patterns["job_duration_hours"],
                "job_duration_hours_p95": job_patterns.get("job_duration_p95_hours"),
                "detected_peak_pattern": job_patterns["peak_pattern"],
                "detected_allowed_hours": allowed_hours,
                "avg_forks_configured": job_templates.get("avg_forks"),
                "max_forks_configured": job_templates.get("max_forks"),
                "avg_verbosity": job_templates.get("avg_verbosity", 1),
                "hourly_distribution": job_patterns.get("hourly_distribution"),
            },
            "sizing_inputs": {
                "managed_hosts": managed_hosts,
                "playbooks_per_day_peak": peak_with_headroom,
                "job_duration_hours": job_patterns["job_duration_hours"],
                "tasks_per_job": 50,  # conservative default, not easily derived from API
                "forks_observed": observed_forks,
                "verbosity_level": job_templates.get("avg_verbosity", 1),
                "allowed_hours_per_day": allowed_hours,
                "peak_pattern": job_patterns["peak_pattern"],
                "job_retention_hours": job_retention_hours,
                "num_controllers": max(2, len(control_instances)),
                "num_hub_nodes": 1,
                "hub_cpu_percent": 25,
                "hub_memory_percent": 30,
                "database_vcpu": 8,
                "database_memory_gb": 64,
                "database_cpu_percent": 50,
                "database_memory_percent": 35,
            },
            "headroom_applied": HEADROOM_MULTIPLIER,
        }


def calculate_dynamic_sizing(
    base_url: str,
    token: str,
    api_prefix: str | None = None,
    verify_ssl: bool = True,
    history_days: int = 30,
) -> dict[str, Any]:
    """Run dynamic sizing: collect metrics from live AAP and produce recommendations.

    Returns the full sizing recommendation along with the observed metrics
    and the inputs that were derived from them.
    """
    collector = DynamicSizingCollector(
        base_url=base_url,
        token=token,
        api_prefix=api_prefix,
        verify_ssl=verify_ssl,
    )

    metrics = collector.collect_all_metrics(history_days=history_days)
    sizing_inputs = metrics["sizing_inputs"]

    calculator = AAP26SizingCalculator()
    recommendation = calculator.generate_sizing_recommendation(sizing_inputs)

    # Enforce minimum specs
    _enforce_minimums(recommendation)

    return {
        "mode": "dynamic",
        "source_observed": metrics["observed"],
        "derived_inputs": sizing_inputs,
        "headroom_multiplier": metrics["headroom_applied"],
        "recommendation": recommendation,
    }


# AAP 2.6 minimum specs per Red Hat documentation
MIN_SPECS = {
    "platform_gateway": {"cpu_per_pod": 2, "memory_per_pod_gb": 4},
    "automation_controller_control_plane": {"cpu_per_pod": 2, "memory_per_pod_gb": 4},
    "automation_controller_execution_plane": {"cpu_per_pod": 2, "memory_per_pod_gb": 4},
    "automation_hub": {"cpu_per_pod": 2, "memory_per_pod_gb": 4},
    "event_driven_ansible": {"cpu_per_pod": 2, "memory_per_pod_gb": 4},
    "database": {"cpu": 2, "memory_gb": 8, "storage_gb": 60},
    "redis": {"total_cpu": 1, "total_memory_gb": 2},
}


def _enforce_minimums(recommendation: dict[str, Any]) -> None:
    """Ensure no component goes below AAP 2.6 minimum specs."""
    components = recommendation.get("components", {})
    for comp_name, mins in MIN_SPECS.items():
        comp = components.get(comp_name)
        if not comp:
            continue
        for key, min_val in mins.items():
            if key in comp and comp[key] < min_val:
                comp[key] = min_val
        # Recompute totals if per-pod values were bumped
        if "cpu_per_pod" in mins and "total_cpu" in comp:
            pod_key = next((k for k in comp if k.endswith("_pods") or k == "execution_pods"), None)
            if pod_key:
                comp["total_cpu"] = max(comp["total_cpu"], comp[pod_key] * comp["cpu_per_pod"])
        if "memory_per_pod_gb" in mins and "total_memory_gb" in comp:
            pod_key = next((k for k in comp if k.endswith("_pods") or k == "execution_pods"), None)
            if pod_key:
                comp["total_memory_gb"] = max(
                    comp["total_memory_gb"], comp[pod_key] * comp["memory_per_pod_gb"]
                )

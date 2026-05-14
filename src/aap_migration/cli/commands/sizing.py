"""CLI command for AAP 2.6 infrastructure sizing calculations."""

import json

import click

from aap_migration.sizing.calculator import AAP26SizingCalculator


@click.command(name="sizing")
@click.option("--managed-hosts", type=int, required=True, help="Total number of managed hosts")
@click.option("--playbooks-per-day", type=int, required=True, help="Peak playbook runs per day")
@click.option(
    "--job-duration", type=float, default=0.5, help="Average job duration in hours (default: 0.5)"
)
@click.option(
    "--tasks-per-job", type=int, default=50, help="Average tasks per playbook (default: 50)"
)
@click.option("--forks", type=int, default=10, help="Observed forks per job (default: 10)")
@click.option("--verbosity", type=int, default=1, help="Verbosity level 0-4 (default: 1)")
@click.option(
    "--hours-per-day", type=float, default=8, help="Allowed automation hours per day (default: 8)"
)
@click.option(
    "--peak-pattern",
    type=click.Choice(["distributed_24x7", "business_hours", "batch_window", "mixed"]),
    default="business_hours",
    help="Peak usage pattern (default: business_hours)",
)
@click.option("--output-json", type=click.Path(), help="Save results to JSON file")
def sizing_cmd(
    managed_hosts: int,
    playbooks_per_day: int,
    job_duration: float,
    tasks_per_job: int,
    forks: int,
    verbosity: int,
    hours_per_day: float,
    peak_pattern: str,
    output_json: str | None,
):
    """Calculate AAP 2.6 infrastructure sizing recommendations.

    Based on Red Hat official sizing formulas for containerized AAP 2.6 deployment.

    Examples:

        # Basic sizing
        aap-bridge sizing --managed-hosts 5000 --playbooks-per-day 100

        # Detailed sizing with custom parameters
        aap-bridge sizing --managed-hosts 50000 --playbooks-per-day 500 \\
            --forks 50 --verbosity 2 --peak-pattern batch_window

        # Export to JSON
        aap-bridge sizing --managed-hosts 5000 --playbooks-per-day 100 --output-json sizing.json
    """
    calculator = AAP26SizingCalculator()

    metrics = {
        "managed_hosts": managed_hosts,
        "playbooks_per_day_peak": playbooks_per_day,
        "job_duration_hours": job_duration,
        "tasks_per_job": tasks_per_job,
        "forks_observed": forks,
        "verbosity_level": verbosity,
        "allowed_hours_per_day": hours_per_day,
        "peak_pattern": peak_pattern,
    }

    all_warnings: list[str] = []
    for key, val in metrics.items():
        if isinstance(val, int | float):
            w = calculator.validate_input(key, val)
            if w:
                all_warnings.extend(w)
    if all_warnings:
        for w in all_warnings:
            click.echo(f"Warning: {w}")
        click.echo("")

    execution = calculator.calculate_execution_node_resources(metrics)
    controller = calculator.calculate_controller_resources(metrics)
    database = calculator.calculate_database_resources(metrics)

    click.echo("=" * 60)
    click.echo("AAP 2.6 Infrastructure Sizing Recommendations")
    click.echo("=" * 60)
    click.echo("")

    click.echo("Input Parameters:")
    click.echo(f"  Managed hosts:      {managed_hosts:,}")
    click.echo(f"  Playbooks/day:      {playbooks_per_day}")
    click.echo(f"  Job duration:       {job_duration}h")
    click.echo(f"  Tasks/job:          {tasks_per_job}")
    click.echo(f"  Forks:              {forks}")
    click.echo(f"  Verbosity:          {verbosity}")
    click.echo(f"  Hours/day:          {hours_per_day}")
    click.echo(f"  Peak pattern:       {peak_pattern}")
    click.echo("")

    click.echo("Execution Nodes:")
    click.echo(f"  Pods:               {execution.get('pods', 'N/A')}")
    click.echo(f"  CPU (per pod):      {execution.get('cpu_per_pod', 'N/A')} cores")
    click.echo(f"  Memory (per pod):   {execution.get('memory_per_pod_gb', 'N/A')} GB")
    click.echo(f"  Total forks:        {execution.get('total_forks', 'N/A')}")
    click.echo("")

    click.echo("Controller:")
    click.echo(f"  CPU:                {controller.get('cpu_cores', 'N/A')} cores")
    click.echo(f"  Memory:             {controller.get('memory_gb', 'N/A')} GB")
    click.echo("")

    click.echo("Database:")
    click.echo(f"  Storage:            {database.get('total_storage_gb', 'N/A')} GB")
    click.echo("")

    if output_json:
        results = {
            "input": metrics,
            "execution_nodes": execution,
            "controller": controller,
            "database": database,
        }
        with open(output_json, "w") as f:
            json.dump(results, f, indent=2)
        click.echo(f"Results saved to: {output_json}")

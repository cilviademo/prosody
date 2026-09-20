"""``flpf`` - the command line. Commands are thin wrappers over pipeline stages."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from flpfinisher import env as environment
from flpfinisher.fs.safety import find_flps
from flpfinisher.model.schemas import HealthStatus
from flpfinisher.obs.log import console, error_console
from flpfinisher.parse.adapter import ParseError
from flpfinisher.pipeline import (
    inspect_project,
    scan_directory,
    write_scan_errors,
    write_scan_report,
)

app = typer.Typer(
    add_completion=False,
    help="FLP Finisher - inspect and (later) arrange FL Studio projects.",
)

DEFAULT_OUT = Path("out")
DEFAULT_CORPUS = Path("corpus")

_STATUS_STYLE = {
    HealthStatus.READY: "green",
    HealthStatus.PARTIAL: "yellow",
    HealthStatus.REQUIRES_FREEZE: "yellow",
    HealthStatus.BLOCKED: "red",
    HealthStatus.UNKNOWN: "cyan",
}


@app.command()
def doctor(
    corpus: Path = typer.Option(DEFAULT_CORPUS, help="Corpus directory to count."),
) -> None:
    """Report what this machine can and cannot do."""
    info = environment.describe()
    table = Table(title="flpf doctor", show_header=False, title_justify="left")
    table.add_column("key", style="bold")
    table.add_column("value")

    table.add_row("platform", info.platform)
    table.add_row("python", info.python_version)
    table.add_row("pyflp", info.pyflp_version)
    table.add_row(
        "pyflp compat shim",
        "[yellow]applied[/yellow] (Python >= 3.11 enum guard)"
        if info.pyflp_compat_shim
        else "not needed",
    )
    table.add_row(
        "FL Studio",
        str(info.fl_executable) if info.fl_executable else f"[red]{info.fl_discovery}[/red]",
    )
    if info.fl_executable:
        table.add_row("  discovered via", info.fl_discovery)
    table.add_row("ffmpeg", str(info.ffmpeg) if info.ffmpeg else "[yellow]not found[/yellow]")
    table.add_row("FLPF_RENDER", "1 (enabled)" if info.render_enabled else "unset (render disabled)")
    table.add_row("FLPF_GUI", "1 (enabled)" if info.gui_enabled else "unset (GUI automation disabled)")

    flp_count = len(find_flps(corpus)) if corpus.exists() else 0
    table.add_row(
        "corpus",
        f"{flp_count} .flp under {corpus}" if corpus.exists() else f"[yellow]{corpus} does not exist[/yellow]",
    )

    switches = ", ".join(
        f"{k}={v}" if v else f"{k}=[yellow]UNCONFIRMED[/yellow]"
        for k, v in environment.FL_SWITCHES.items()
    )
    table.add_row("FL CLI switches", switches)
    console().print(table)

    if info.render_enabled and info.fl_executable is None:
        error_console().print(
            "[red]FLPF_RENDER=1 but FL Studio was not found; rendering cannot run.[/red]"
        )
        raise typer.Exit(code=1)


@app.command()
def scan(
    directory: Path = typer.Argument(DEFAULT_CORPUS, help="Directory of .flp files."),
    out: Path = typer.Option(DEFAULT_OUT, help="Output root."),
    artifacts: bool = typer.Option(
        False, "--artifacts", help="Also write DATA/ and REPORTS/ per project."
    ),
) -> None:
    """Parse every .flp under DIRECTORY and report the parse rate."""
    if not directory.exists():
        error_console().print(f"[red]{directory} does not exist[/red]")
        raise typer.Exit(code=2)

    rows = scan_directory(directory, out_root=out, write_artifacts_per_project=artifacts)
    if not rows:
        error_console().print(f"[yellow]no .flp files found under {directory}[/yellow]")
        raise typer.Exit(code=2)

    report = write_scan_report(rows, out / "scan_report.csv")
    errors = write_scan_errors(rows, out / "scan_errors.log")

    table = Table(title=f"scan {directory}")
    for column in ("file", "FL", "BPM", "pat", "ch", "clips", "notes", "warn", "health"):
        table.add_column(column)
    for row in rows:
        if row.ok:
            table.add_row(
                row.path.name, row.fl_version or "?",
                f"{row.tempo:g}" if row.tempo else "?",
                str(row.patterns), str(row.channels), str(row.playlist_items),
                str(row.notes), str(row.warnings), row.health or "?",
            )
        else:
            table.add_row(row.path.name, "[red]PARSE FAILED[/red]", "", "", "", "", "", "", "")
    console().print(table)

    parsed = sum(1 for r in rows if r.ok)
    rate = parsed / len(rows) * 100
    style = "green" if rate >= 80 else "red"
    console().print(
        f"[{style}]parse rate: {parsed}/{len(rows)} ({rate:.0f}%)[/{style}]  "
        f"target >= 80%"
    )
    console().print(f"wrote {report} and {errors}")


@app.command("inspect")
def inspect_cmd(
    flp: Path = typer.Argument(..., help="A single .flp file."),
    out: Path = typer.Option(DEFAULT_OUT, help="Output root."),
    write: bool = typer.Option(
        True, "--write/--no-write", help="Write DATA/ and REPORTS/ under out/<slug>/."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print project.json to stdout."),
) -> None:
    """Summarise one project. Never modifies the source."""
    if not flp.is_file():
        error_console().print(f"[red]{flp} is not a file[/red]")
        raise typer.Exit(code=2)

    try:
        result = inspect_project(flp, out_root=out if write else None)
    except ParseError as exc:
        error_console().print(f"[red]could not parse {flp.name}: {exc.cause}[/red]")
        raise typer.Exit(code=1) from exc

    if as_json:
        console().print_json(json.dumps(result.project.model_dump(mode="json")))
        return

    project = result.project
    health = result.health

    summary = Table(title=flp.name, show_header=False, title_justify="left")
    summary.add_column("key", style="bold")
    summary.add_column("value")
    summary.add_row("sha256", project.id[:16] + "...")
    summary.add_row("FL version", project.fl_version or "unknown")
    summary.add_row("tempo", f"{project.tempo:g} BPM" if project.tempo else "unknown")
    summary.add_row("time signature", f"{project.time_signature[0]}/{project.time_signature[1]}")
    summary.add_row("length", f"{project.length_bars:g} bars"
                    + (f" ({project.duration_seconds:.1f}s)" if project.duration_seconds else ""))
    summary.add_row("state", result.analysis.state.value)
    summary.add_row("patterns", f"{len(project.patterns)} ({project.note_count} notes)")
    summary.add_row("channels", str(len(project.channels)))
    summary.add_row("mixer inserts", str(len(project.mixer)))
    summary.add_row("playlist clips", str(sum(len(a.clips) for a in project.arrangements)))
    summary.add_row("samples", f"{health.samples_found} found / {health.samples_missing} missing")
    summary.add_row("plugins", str(len(project.plugins)))
    summary.add_row("unknown events", str(len(project.unknown_event_ids)))
    style = _STATUS_STYLE.get(health.status, "white")
    summary.add_row("health", f"[{style}]{health.status.value}[/{style}]")
    console().print(summary)

    if project.channels:
        roles = Table(title="channels and inferred roles")
        for column in ("#", "name", "kind", "role", "confidence", "sources"):
            roles.add_column(column)
        by_channel = {r.channel: r for r in result.analysis.roles}
        for channel in project.channels:
            assignment = by_channel.get(channel.index)
            confident = assignment is not None and assignment.is_confident
            roles.add_row(
                str(channel.index),
                channel.name or "(unnamed)",
                channel.kind.value,
                assignment.role.value if assignment else "unknown",
                f"[green]{assignment.confidence:.2f}[/green]" if confident
                else f"[yellow]{assignment.confidence:.2f}[/yellow]" if assignment else "-",
                ", ".join(assignment.sources) if assignment and assignment.sources else "-",
            )
        console().print(roles)
        console().print(
            "[dim]Role hints below 0.70 confidence are not treated as fact. "
            "The real classifier lands in Phase 5.[/dim]"
        )

    for warning in project.parse_warnings:
        console().print(f"[yellow]parse warning[/yellow] {warning.code}: {warning.message}")
    for check in health.checks:
        if check.ok is None:
            console().print(f"[cyan]undetermined[/cyan] {check.name}: {check.detail}")

    if result.out_dir:
        console().print(f"wrote {result.out_dir}")


def main() -> None:  # pragma: no cover - entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

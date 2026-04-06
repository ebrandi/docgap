"""Command-line interface for docgap."""
import logging
from pathlib import Path

import click

from docgap import __version__
from docgap.cli.commands import (
    run_pipeline,
    status_command,
    log_command,
    review_list,
    review_show,
    review_approve,
    review_approve_bulk,
    review_reject,
    init_command,
    report_command,
    config_show_command,
    reprocess_command,
    heal_command,
    validate_command,
    reset_command,
    purge_command,
)
from docgap.config.loader import get_default_config_path


class ConfigObject:
    """Configuration object passed between CLI commands."""

    def __init__(self):
        self.config_path: str = ""
        self.verbose: bool = False
        self.config = None


# Make main accessible for testing
@click.group()
@click.version_option(version=__version__, prog_name="docgap")
@click.option(
    "-c", "--config",
    default=None,
    help="Path to configuration file (default: auto-detect system or local config)",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    help="Enable verbose/debug output",
)
@click.pass_context
def main(ctx, config, verbose):
    """FreeBSD Documentation Gap Detector - monitors commits and generates documentation patches."""
    ctx.ensure_object(ConfigObject)
    ctx.obj.config_path = config if config else str(get_default_config_path())
    ctx.obj.verbose = verbose
    ctx.obj.config = None  # Will be loaded on first use
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@main.command()
@click.option(
    "--since", "-s",
    help="Process commits since this ISO timestamp (e.g., 2026-04-03T00:00:00Z)",
)
@click.option("--dry-run", is_flag=True, help="Analyze without storing results")
@click.pass_context
def run(ctx, since, dry_run):
    """Run the full detection and generation pipeline."""
    run_pipeline(ctx.obj, since, dry_run=dry_run)


@main.command()
@click.pass_context
def status(ctx):
    """Show system status and pipeline health."""
    exit_code = status_command(ctx.obj)
    if exit_code:
        ctx.exit(exit_code)


@main.command()
@click.option("--since", help="Show commits since date")
@click.option("--status", "status_filter", help="Filter by status")
@click.pass_context
def log(ctx, since, status_filter):
    """Query commit logs."""
    log_command(ctx.obj, since=since, status=status_filter)


@main.group()
@click.pass_context
def review(ctx):
    """Review flagged commits."""
    pass


@review.command("list")
@click.pass_context
def review_list_cmd(ctx):
    """List commits needing review."""
    review_list(ctx.obj)


@review.command()
@click.argument("commit_hash")
@click.pass_context
def show(ctx, commit_hash):
    """Show review details for a commit."""
    review_show(ctx.obj, commit_hash)


@review.command()
@click.argument("commit_hash", required=False, default=None)
@click.option("--all", "approve_all", is_flag=True, help="Approve all pending reviews")
@click.option("--since", "since", default=None, help="Approve commits since this ISO timestamp")
@click.option("--reviewer", default=None, help="Reviewer name (default: $USER)")
@click.pass_context
def approve(ctx, commit_hash, approve_all, since, reviewer):
    """Approve a commit for documentation."""
    if approve_all:
        exit_code = review_approve_bulk(ctx.obj, since=since, reviewer=reviewer)
    elif commit_hash:
        exit_code = review_approve(ctx.obj, commit_hash, reviewer=reviewer)
    else:
        click.echo("Error: provide COMMIT_HASH or --all", err=True)
        exit_code = 1
    if exit_code:
        ctx.exit(exit_code)


@review.command()
@click.argument("commit_hash")
@click.option("--reason", "-r", default=None, help="Reason for rejection")
@click.option("--reviewer", default=None, help="Reviewer name (default: $USER)")
@click.pass_context
def reject(ctx, commit_hash, reason, reviewer):
    """Reject a commit - no documentation needed."""
    exit_code = review_reject(ctx.obj, commit_hash, reason=reason, reviewer=reviewer)
    if exit_code:
        ctx.exit(exit_code)


@main.group()
@click.pass_context
def config(ctx):
    """Manage configuration."""
    pass


@config.command("show")
@click.pass_context
def config_show(ctx):
    """Display all configuration sections."""
    config_show_command(ctx.obj)


@main.command()
@click.pass_context
def init(ctx):
    """Initialize the database and output directories."""
    init_command(ctx.obj)


@main.command()
@click.option("--format", "output_format", type=click.Choice(["txt", "json"]), default="txt", help="Output format (txt or json)")
@click.option("--output", "output_file", default=None, help="Save report to this file path")
@click.option("--save", is_flag=True, help="Save report to {data_dir}/reports/ with timestamp")
@click.pass_context
def report(ctx, output_format, output_file, save):
    """Generate documentation reports."""
    report_command(ctx.obj, output_format=output_format, output_file=output_file, save=save)


@main.command()
@click.argument("commit_hash", required=False, default=None)
@click.option("--failed", is_flag=True, help="Reprocess all error/generation_error commits")
@click.option("--pending", is_flag=True, help="Reprocess needs_doc commits without doc_generated")
@click.option("--stage1", "stage1_hash", default=None, metavar="HASH",
              help="Re-run only Stage 1 (detection) for HASH")
@click.option("--stage2", "stage2_hash", default=None, metavar="HASH",
              help="Re-run only Stage 2 (generation) for HASH")
@click.option("--since", default=None, help="Reprocess commits since ISO timestamp")
@click.option("--dry-run", is_flag=True, help="Show what would be reprocessed")
@click.option("--max-retries", default=3, type=int, help="Max retry count per commit (default: 3)")
@click.pass_context
def reprocess(ctx, commit_hash, failed, pending, stage1_hash, stage2_hash, since, dry_run, max_retries):
    """Reprocess failed or incomplete commits through the pipeline."""
    exit_code = reprocess_command(
        ctx.obj, commit_hash=commit_hash, failed=failed, pending=pending,
        stage1_hash=stage1_hash, stage2_hash=stage2_hash, since=since,
        dry_run=dry_run, max_retries=max_retries,
    )
    if exit_code:
        ctx.exit(exit_code)


@main.command()
@click.option("--fix", is_flag=True, help="Auto-fix detected issues")
@click.option("--dry-run", is_flag=True, help="Show what --fix would do without doing it")
@click.pass_context
def heal(ctx, fix, dry_run):
    """Detect and repair interrupted runs and stuck commits."""
    exit_code = heal_command(ctx.obj, fix=fix, dry_run=dry_run)
    if exit_code:
        ctx.exit(exit_code)


@main.command()
@click.pass_context
def validate(ctx):
    """Check system integrity: database, repos, LLM, config."""
    exit_code = validate_command(ctx.obj)
    if exit_code:
        ctx.exit(exit_code)


@main.command("reset")
@click.argument("commit_hash")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def reset_cmd(ctx, commit_hash, confirm):
    """Reset a commit to 'pending' status for full reprocessing."""
    exit_code = reset_command(ctx.obj, commit_hash, confirm=confirm)
    if exit_code:
        ctx.exit(exit_code)


@main.command()
@click.option("--before", required=True, help="Purge data older than ISO timestamp")
@click.option("--status", "statuses", multiple=True,
              help="Only purge commits with these statuses (repeatable)")
@click.option("--include-output", is_flag=True, help="Also delete output directories")
@click.option("--dry-run", is_flag=True, help="Show what would be purged")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def purge(ctx, before, statuses, include_output, dry_run, confirm):
    """Clean old data from the database and output directories."""
    exit_code = purge_command(
        ctx.obj, before=before, statuses=statuses, include_output=include_output,
        dry_run=dry_run, confirm=confirm,
    )
    if exit_code:
        ctx.exit(exit_code)


if __name__ == "__main__":
    main()

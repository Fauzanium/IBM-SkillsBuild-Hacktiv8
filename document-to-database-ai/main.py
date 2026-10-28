"""
main.py
────────
Entry point for the Document to Database AI system.

Run modes:
  python main.py invoice.pdf                  → process a single file
  python main.py invoices/                    → process all files in a folder
  python main.py inv1.pdf inv2.pdf inv3.txt   → process explicit list

All results are printed as a rich table and written to logs/.
"""

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box

from src.utils.logger import setup_logging
from src.agent import DocumentToDatabaseAgent, ProcessingStatus

# Initialise structured logging before anything else
setup_logging()

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Helper: collect file paths from CLI arguments
# ─────────────────────────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".text"}


def _collect_paths(args: list[str]) -> list[Path]:
    """Expand directories and filter by supported extension."""
    paths: list[Path] = []
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            for ext in SUPPORTED_EXTENSIONS:
                paths.extend(p.glob(f"*{ext}"))
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                paths.append(p)
            else:
                console.print(f"[yellow]Skipping unsupported file: {p}[/yellow]")
        else:
            console.print(f"[red]Path not found: {p}[/red]")
    return sorted(set(paths))


# ─────────────────────────────────────────────────────────────────────────────
# Rich output table
# ─────────────────────────────────────────────────────────────────────────────
def _print_results_table(results) -> None:
    table = Table(
        title="Document to Database AI — Processing Results",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("File",            style="cyan",  no_wrap=True)
    table.add_column("Status",          style="bold",  width=10)
    table.add_column("Invoice #",       style="white")
    table.add_column("DB ID",           style="green", justify="right")
    table.add_column("Warnings",        style="yellow", justify="right")
    table.add_column("Error",           style="red")

    status_styles = {
        ProcessingStatus.SUCCESS : "[bold green]✔ SUCCESS[/bold green]",
        ProcessingStatus.SKIPPED : "[bold blue]⏭ SKIPPED[/bold blue]",
        ProcessingStatus.FAILED  : "[bold red]✘ FAILED[/bold red]",
    }

    for r in results:
        table.add_row(
            Path(r.file_path).name,
            status_styles.get(r.status, r.status.value),
            r.invoice_number or "—",
            str(r.db_id) if r.db_id else "—",
            str(len(r.validation_warnings)) if r.validation_warnings else "0",
            r.error or "",
        )

    console.print(table)

    # Summary line
    total   = len(results)
    success = sum(1 for r in results if r.status == ProcessingStatus.SUCCESS)
    skipped = sum(1 for r in results if r.status == ProcessingStatus.SKIPPED)
    failed  = sum(1 for r in results if r.status == ProcessingStatus.FAILED)
    console.print(
        f"\n[bold]Summary:[/bold] {total} file(s) processed | "
        f"[green]{success} saved[/green] | "
        f"[blue]{skipped} skipped[/blue] | "
        f"[red]{failed} failed[/red]\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Async main
# ─────────────────────────────────────────────────────────────────────────────
async def main(file_paths: list[Path]) -> None:
    if not file_paths:
        console.print("[red]No valid documents found. Provide PDF, DOCX, or TXT files.[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]Document to Database AI[/bold cyan] — {len(file_paths)} file(s) queued\n")

    agent = DocumentToDatabaseAgent()
    results = await agent.process_batch(file_paths, concurrency=3)

    _print_results_table(results)

    # Exit with non-zero code if any document failed
    failed_count = sum(1 for r in results if r.status == ProcessingStatus.FAILED)
    sys.exit(1 if failed_count > 0 else 0)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cli_args = sys.argv[1:]
    if not cli_args:
        console.print("[yellow]Usage: python main.py <file_or_folder> [file2 ...][/yellow]")
        sys.exit(0)

    paths = _collect_paths(cli_args)
    asyncio.run(main(paths))

"""
Replay a recorded coding session snapshot-by-snapshot and run the commentary agent.
Usage:  python -m arena.agent.replay recordings/session1.json
"""
import json
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from arena.agent.graph import Snapshot, run_on_snapshot

console = Console()


def replay(path: str):
    data = json.loads(Path(path).read_text())
    snapshots = data["snapshots"]
    player = data.get("player", "a")
    session_name = data.get("name", Path(path).stem)

    console.rule(f"[bold cyan]Replaying: {session_name}")
    console.print(f"Player: [bold]{player.upper()}[/]  |  Snapshots: {len(snapshots)}")
    console.print()

    results = []
    prev_code = ""

    for i, snap in enumerate(snapshots):
        code = snap["code"]
        ts_ms = snap.get("ts_ms", i * 2000)

        console.print(f"[dim]Snapshot {i+1}/{len(snapshots)} @ {ts_ms/1000:.1f}s[/dim]", end="  ")

        snapshot = Snapshot(player=player, code=code, ts_ms=ts_ms, prev_code=prev_code)
        state = run_on_snapshot(snapshot)

        event_type = state.event.event_type if state.event else "—"
        confidence = f"{state.event.confidence:.2f}" if state.event else "—"

        if state.should_comment and state.commentary:
            console.print(f"[bold green]EVENT[/] [{event_type}] conf={confidence}")
            console.print(f"  [yellow]»[/] {state.commentary}")
        else:
            console.print(f"[dim]no event ({event_type}, conf={confidence})[/dim]")

        results.append({
            "snapshot": i + 1,
            "ts_ms": ts_ms,
            "event_type": event_type,
            "confidence": state.event.confidence if state.event else 0.0,
            "should_comment": state.should_comment,
            "commentary": state.commentary or "",
            "detect_ms": state.latency_detect_ms,
            "comment_ms": state.latency_comment_ms,
        })

        prev_code = code
        time.sleep(0.1)  # small pause between API calls

    return session_name, results


def print_summary(session_name: str, results: list):
    console.rule("[bold]Summary")

    commented = [r for r in results if r["should_comment"]]
    total = len(results)
    avg_detect = sum(r["detect_ms"] for r in results) / total if total else 0
    avg_comment = sum(r["comment_ms"] for r in commented) / len(commented) if commented else 0

    table = Table(title=f"Results: {session_name}")
    table.add_column("Snap", style="dim")
    table.add_column("Event type")
    table.add_column("Conf", justify="right")
    table.add_column("Commentary")
    table.add_column("Detect ms", justify="right", style="dim")
    table.add_column("Comment ms", justify="right", style="dim")

    for r in results:
        table.add_row(
            str(r["snapshot"]),
            r["event_type"],
            f"{r['confidence']:.2f}",
            r["commentary"][:60] if r["commentary"] else "[dim]—[/dim]",
            str(r["detect_ms"]),
            str(r["comment_ms"]) if r["comment_ms"] else "—",
        )

    console.print(table)
    console.print(f"\nCommented on [bold]{len(commented)}/{total}[/] snapshots")
    console.print(f"Avg detect latency: [bold]{avg_detect:.0f}ms[/]")
    console.print(f"Avg commentary latency: [bold]{avg_comment:.0f}ms[/]")
    console.print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[red]Usage: python -m arena.agent.replay recordings/session1.json[/red]")
        sys.exit(1)

    session_name, results = replay(sys.argv[1])
    print_summary(session_name, results)

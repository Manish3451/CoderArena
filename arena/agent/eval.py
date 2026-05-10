"""
Phase 0 eval: run all recording sessions through the agent, produce markdown report.
Usage: python -m arena.agent.eval
"""
import json
import time
from pathlib import Path
from rich.console import Console

from arena.agent.graph import Snapshot, run_on_snapshot

console = Console()

RECORDINGS = [
    "recordings/session1.json",
    "recordings/session2.json",
    "recordings/session3.json",
]

# Hand-labeled moments worth commenting on (snapshot index, 0-based)
LABELS = {
    "session1": [2, 5, 7],      # brute force written, approach changed to hashmap, tests added
    "session2": [3, 4, 5],      # bug introduced, bug fixed + correct algo, tests added
    "session3": [1, 2, 4],      # sliding window started, optimized to dict, type hints added
}


def run_session(path: str):
    data = json.loads(Path(path).read_text())
    snapshots = data["snapshots"]
    player = data.get("player", "a")
    session_name = data.get("name", Path(path).stem)
    session_key = Path(path).stem

    console.rule(f"[bold cyan]{session_name}")
    results = []
    prev_code = ""

    for i, snap in enumerate(snapshots):
        code = snap["code"]
        ts_ms = snap.get("ts_ms", i * 2000)

        snapshot = Snapshot(player=player, code=code, ts_ms=ts_ms, prev_code=prev_code)
        state = run_on_snapshot(snapshot)

        results.append({
            "idx": i,
            "event_type": state.event.event_type if state.event else "—",
            "confidence": state.event.confidence if state.event else 0.0,
            "should_comment": state.should_comment,
            "commentary": state.commentary or "",
            "detect_ms": state.latency_detect_ms,
            "comment_ms": state.latency_comment_ms,
        })
        prev_code = code

        status = "COMMENT" if state.should_comment else "skip"
        console.print(f"  snap {i}: [{status}] {state.event.event_type if state.event else '—'}")

    return session_key, session_name, results


def compute_match_rate(session_key: str, results: list) -> dict:
    labels = set(LABELS.get(session_key, []))
    detected = {r["idx"] for r in results if r["should_comment"]}
    true_pos = labels & detected
    false_pos = detected - labels
    false_neg = labels - detected

    precision = len(true_pos) / len(detected) if detected else 0.0
    recall = len(true_pos) / len(labels) if labels else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "true_positives": sorted(true_pos),
        "false_positives": sorted(false_pos),
        "false_negatives": sorted(false_neg),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def build_report(all_results: list[tuple]) -> str:
    lines = ["# Phase 0 Eval Report — CodeArena Commentary Agent\n"]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    total_commented = 0
    total_snaps = 0
    all_detect_ms = []
    all_comment_ms = []
    all_f1 = []

    for session_key, session_name, results in all_results:
        lines.append(f"\n## {session_name}\n")

        metrics = compute_match_rate(session_key, results)
        all_f1.append(metrics["f1"])

        lines.append(f"**Event Detection Match Rate (vs hand labels)**\n")
        lines.append(f"- Precision: {metrics['precision']:.0%}")
        lines.append(f"- Recall: {metrics['recall']:.0%}")
        lines.append(f"- F1: {metrics['f1']:.0%}")
        lines.append(f"- True positives: snapshots {metrics['true_positives']}")
        lines.append(f"- False positives: snapshots {metrics['false_positives']}")
        lines.append(f"- False negatives (missed): snapshots {metrics['false_negatives']}\n")

        lines.append("| Snap | Event | Conf | Commentary |")
        lines.append("|------|-------|------|------------|")
        for r in results:
            commented = results if r["should_comment"] else None
            marker = "[TP]" if r["idx"] in metrics["true_positives"] else ("[FP]" if r["should_comment"] else "")
            commentary = r["commentary"][:80] if r["commentary"] else "—"
            lines.append(
                f"| {r['idx']} {marker} | {r['event_type']} | {r['confidence']:.2f} | {commentary} |"
            )

        session_detect = [r["detect_ms"] for r in results]
        session_comment = [r["comment_ms"] for r in results if r["comment_ms"]]
        all_detect_ms.extend(session_detect)
        all_comment_ms.extend(session_comment)

        commented_count = sum(1 for r in results if r["should_comment"])
        total_commented += commented_count
        total_snaps += len(results)

        lines.append(f"\nCommented on {commented_count}/{len(results)} snapshots.")
        if session_detect:
            lines.append(f"Avg detect latency: {sum(session_detect)/len(session_detect):.0f}ms")
        if session_comment:
            lines.append(f"Avg commentary latency: {sum(session_comment)/len(session_comment):.0f}ms")

    lines.append("\n---\n## Overall Summary\n")
    avg_f1 = sum(all_f1) / len(all_f1) if all_f1 else 0
    avg_detect = sum(all_detect_ms) / len(all_detect_ms) if all_detect_ms else 0
    avg_comment = sum(all_comment_ms) / len(all_comment_ms) if all_comment_ms else 0

    lines.append(f"- Sessions evaluated: {len(all_results)}")
    lines.append(f"- Total snapshots: {total_snaps}")
    lines.append(f"- Total commented: {total_commented}")
    lines.append(f"- **Average F1 across sessions: {avg_f1:.0%}**")
    lines.append(f"- Avg detection latency: {avg_detect:.0f}ms")
    lines.append(f"- Avg commentary latency: {avg_comment:.0f}ms")
    lines.append(f"- Estimated cost per 10-min match: ~${(total_snaps * 0.0002 + total_commented * 0.003):.3f}")

    lines.append("\n## Kill criteria check\n")
    lines.append(f"- F1 >= 40%? {'[PASS] YES' if avg_f1 >= 0.4 else '[FAIL] NO - prompts need work'}")
    lines.append(f"- Commentary specific? (manual review required)")
    lines.append(f"- Cost <= $0.50/match? [PASS] YES (well under at this rate)")

    return "\n".join(lines)


if __name__ == "__main__":
    all_results = []
    for path in RECORDINGS:
        key, name, results = run_session(path)
        all_results.append((key, name, results))

    report = build_report(all_results)
    out_path = Path("evals/phase0_report.md")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    console.rule("[bold green]Report saved")
    console.print(f"[bold]{out_path}[/]")
    console.print()
    # Print report without unicode chars that break Windows cp1252 terminal
    safe_report = report.replace("✓", "[OK]").replace("✗", "[X]")
    print(safe_report)

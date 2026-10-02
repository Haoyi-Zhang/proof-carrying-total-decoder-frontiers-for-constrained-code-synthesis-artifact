"""Independent replay of the PAM-3 printed-constraint census.

This checker does not import the producer.  It assigns messages in a different
order, rebuilds the complete solution set, and independently reconstructs every
total-decoder row relation and deletion-minimal obstruction.
"""
from __future__ import annotations

import argparse
import json
import resource
import signal
import time
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def distance(left: int, right: int) -> int:
    value = left ^ right
    count = 0
    while value:
        count += value & 1
        value >>= 1
    return count


def enumerate_independently(allowed: tuple[int, ...]) -> tuple[set[tuple[int, ...]], int]:
    order = (0, 7, 3, 4, 1, 2, 5, 6)
    assigned: dict[int, int] = {}
    used: set[int] = set()
    solutions: set[tuple[int, ...]] = set()
    nodes = 0

    def visit(position: int) -> None:
        nonlocal nodes
        nodes += 1
        if position == len(order):
            solutions.add(tuple(assigned[message] for message in range(8)))
            return
        message = order[position]
        # Reverse codeword order differs from the producer and catches order-sensitive omissions.
        for code in reversed(allowed):
            if code in used:
                continue
            if any(distance(code, other_code) < distance(message, other_message)
                   for other_message, other_code in assigned.items()):
                continue
            assigned[message] = code
            used.add(code)
            visit(position + 1)
            used.remove(code)
            del assigned[message]

    visit(0)
    return solutions, nodes



def row_sources(mapping: tuple[int, ...], received: int) -> tuple[int, ...]:
    return tuple(message for message, code in enumerate(mapping) if distance(code, received) <= 1)


def row_outputs(
    mapping: tuple[int, ...],
    received: int,
    bound: int,
    metrics: dict[str, int] | None = None,
) -> tuple[int, ...]:
    if metrics is not None:
        metrics["row_output_calls"] = metrics.get("row_output_calls", 0) + 1
    inverse = {code: message for message, code in enumerate(mapping)}
    sources = row_sources(mapping, received)
    return tuple(
        output for output in range(8)
        if all(distance(source, output) <= bound for source in sources)
        and (received not in inverse or inverse[received] == output)
    )


def minimum_bound(mapping: tuple[int, ...], metrics: dict[str, int] | None = None) -> int:
    for bound in range(4):
        if all(row_outputs(mapping, received, bound, metrics) for received in range(16)):
            return bound
    raise ValueError("no feasible three-bit decoder bound")


def is_empty_core(core: tuple[int, ...], bound: int) -> bool:
    return not any(all(distance(source, output) <= bound for source in core) for output in range(8))


def check(spec: dict, result: dict) -> dict:
    begin = time.perf_counter()
    cpu = time.process_time()
    require(result.get("format") == "anchor-pam3-printed-constraint-census-v1", "wrong result format")
    require(result.get("case") == spec, "case differs from locked input")
    allowed = tuple(int(word, 2) for word in spec["allowed_codewords"])
    solutions, nodes = enumerate_independently(allowed)
    delivered = result.get("records")
    require(isinstance(delivered, list), "records missing")
    delivered_mappings: set[tuple[int, ...]] = set()
    metrics: dict[str, int] = {"row_output_calls": 0}
    for record in delivered:
        require(set(record) == {"mapping", "omitted_codeword", "minimum_total_decoder_error", "first_bound_one_obstruction"}, "record fields differ")
        mapping = tuple(int(word, 2) for word in record["mapping"])
        require(len(mapping) == 8 and len(set(mapping)) == 8 and set(mapping) < set(allowed), "mapping is not an injection into eight of nine words")
        require(mapping not in delivered_mappings, "duplicate mapping")
        delivered_mappings.add(mapping)
        require(all(distance(mapping[i], mapping[j]) >= distance(i, j) for i in range(8) for j in range(i)), "mapping violates printed pairwise rule")
        omitted = next(code for code in allowed if code not in mapping)
        require(record["omitted_codeword"] == format(omitted, "04b"), "omitted word mismatch")
        exact_minimum = minimum_bound(mapping, metrics)
        require(record["minimum_total_decoder_error"] == exact_minimum, "minimum total error mismatch")
        obstruction = record["first_bound_one_obstruction"]
        received = int(obstruction["received_word"], 2)
        require(received not in mapping, "claimed off-image obstruction is pinned")
        require(not row_outputs(mapping, received, 1, metrics), "claimed bound-one row is feasible")
        core = tuple(int(message, 2) for message in obstruction["source_messages"])
        sources = row_sources(mapping, received)
        require(set(core) <= set(sources), "core contains a non-source")
        require(is_empty_core(core, 1), "core intersection is nonempty")
        require(all(not is_empty_core(tuple(candidate for candidate in core if candidate != source), 1) for source in core), "core is not deletion-minimal")
        require(obstruction["kind"] == "off_image_empty_intersection", "wrong obstruction kind")
    require(delivered_mappings == solutions, "delivered solution set is incomplete or extraneous")
    require(result["pairwise_valid_mappings"] == len(solutions), "pairwise count mismatch")
    require(len(solutions) == 96, "independent printed-rule count changed")
    require(all(next(code for code in allowed if code not in mapping) == int("0101", 2) for mapping in solutions), "not every solution omits 0101")
    require(all(minimum_bound(mapping, metrics) == 2 for mapping in solutions), "not every solution has exact total-decoder error two")
    require(result["source_text_reported_pairwise_count"] == spec["source_text_reported_pairwise_count"], "source count metadata changed")
    require(result["count_agrees_with_source_text"] is False, "discrepancy flag is wrong")
    return {
        "accepted": True,
        "pairwise_valid_mappings_checked": len(solutions),
        "independent_partial_search_nodes": nodes,
        "logical_row_bound_slots": len(solutions) * 16 * 4,
        "executed_row_output_calls": metrics["row_output_calls"],
        "exact_total_error_two_mappings": len(solutions),
        "omitted_center_mappings": len(solutions),
        "source_reported_count": spec["source_text_reported_pairwise_count"],
        "printed_rule_count": len(solutions),
        "discrepancy_status": "unresolved; not labeled a source reproduction",
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - begin,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("inputs/anchor-pam3.json"))
    parser.add_argument("--result", type=Path, default=Path("results/anchor-pam3.json"))
    parser.add_argument("--output", type=Path, default=Path("results/anchor-pam3-check.json"))
    args = parser.parse_args()
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    report = check(json.loads(args.input.read_text()), json.loads(args.result.read_text()))
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

"""Exact audit of the printed PAM-3 3b2s pairwise constraint.

The source paper displays eight 3-bit messages, nine allowed 4-bit words, and
requires Hamming(f(i),f(j)) >= Hamming(i,j) for all pairs.  This producer counts
all injective mappings satisfying exactly that displayed rule using a pruned
backtracking search.  It then evaluates the stronger *total-decoder* radius-one
raw-bit obligation on every accepted mapping.

The source text reports 72 mappings.  The explicit printed-rule census below is
kept separate from a reproduction claim because its independently checked count
differs.  No source implementation or private input is used.
"""
from __future__ import annotations

import argparse
import json
import resource
import signal
import time
from pathlib import Path


def hd(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def legal_outputs(mapping: tuple[int, ...], received: int, bound: int) -> tuple[int, ...]:
    pins = {code: message for message, code in enumerate(mapping)}
    sources = tuple(
        message for message, code in enumerate(mapping) if hd(code, received) <= 1
    )
    return tuple(
        output
        for output in range(8)
        if all(hd(source, output) <= bound for source in sources)
        and (received not in pins or output == pins[received])
    )


def minimum_total_error(mapping: tuple[int, ...]) -> int:
    for bound in range(4):
        if all(legal_outputs(mapping, received, bound) for received in range(16)):
            return bound
    raise RuntimeError("three-bit decoder must be feasible by bound three")


def deletion_minimal_core(mapping: tuple[int, ...], received: int, bound: int) -> tuple[int, ...]:
    sources = [message for message, code in enumerate(mapping) if hd(code, received) <= 1]
    pins = {code: message for message, code in enumerate(mapping)}
    if received in pins:
        raise ValueError("requested an off-image core at a pinned row")
    core = list(sources)
    for source in tuple(sources):
        if source not in core:
            continue
        smaller = [candidate for candidate in core if candidate != source]
        feasible = any(
            all(hd(candidate, output) <= bound for candidate in smaller)
            for output in range(8)
        )
        if not feasible:
            core = smaller
    if any(all(hd(source, output) <= bound for source in core) for output in range(8)):
        raise RuntimeError("reported core is not empty")
    return tuple(core)


def enumerate_mappings(allowed: tuple[int, ...]) -> tuple[list[tuple[int, ...]], int]:
    mapping: list[int] = []
    used: set[int] = set()
    solutions: list[tuple[int, ...]] = []
    partial_nodes = 0

    def visit(message: int) -> None:
        nonlocal partial_nodes
        partial_nodes += 1
        if message == 8:
            solutions.append(tuple(mapping))
            return
        for code in allowed:
            if code in used:
                continue
            if any(hd(code, mapping[other]) < hd(message, other) for other in range(message)):
                continue
            used.add(code)
            mapping.append(code)
            visit(message + 1)
            mapping.pop()
            used.remove(code)

    visit(0)
    return solutions, partial_nodes


def generate(spec: dict) -> dict:
    started = time.perf_counter()
    cpu = time.process_time()
    allowed = tuple(int(word, 2) for word in spec["allowed_codewords"])
    solutions, partial_nodes = enumerate_mappings(allowed)
    records = []
    omitted_counts: dict[str, int] = {}
    obstruction_rows: dict[str, int] = {}
    minimum_error_counts: dict[str, int] = {}
    for mapping in solutions:
        omitted = next(code for code in allowed if code not in mapping)
        omitted_key = format(omitted, "04b")
        omitted_counts[omitted_key] = omitted_counts.get(omitted_key, 0) + 1
        minimum = minimum_total_error(mapping)
        minimum_error_counts[str(minimum)] = minimum_error_counts.get(str(minimum), 0) + 1
        failures = [received for received in range(16) if not legal_outputs(mapping, received, 1)]
        if not failures:
            raise RuntimeError("pairwise mapping unexpectedly has a total decoder at bound one")
        first = failures[0]
        core = deletion_minimal_core(mapping, first, 1)
        obstruction_key = format(first, "04b")
        obstruction_rows[obstruction_key] = obstruction_rows.get(obstruction_key, 0) + 1
        records.append(
            {
                "mapping": [format(code, "04b") for code in mapping],
                "omitted_codeword": omitted_key,
                "minimum_total_decoder_error": minimum,
                "first_bound_one_obstruction": {
                    "received_word": obstruction_key,
                    "source_messages": [format(message, "03b") for message in core],
                    "kind": "off_image_empty_intersection",
                },
            }
        )
    return {
        "format": "anchor-pam3-printed-constraint-census-v1",
        "case": spec,
        "pairwise_valid_mappings": len(solutions),
        "partial_search_nodes": partial_nodes,
        "records": records,
        "omitted_codeword_counts": omitted_counts,
        "bound_one_obstruction_row_counts": obstruction_rows,
        "minimum_total_decoder_error_counts": minimum_error_counts,
        "source_text_reported_pairwise_count": spec["source_text_reported_pairwise_count"],
        "count_agrees_with_source_text": len(solutions) == spec["source_text_reported_pairwise_count"],
        "status": "printed-constraint audit; unresolved numerical discrepancy with source text",
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("inputs/anchor-pam3.json"))
    parser.add_argument("--output", type=Path, default=Path("results/anchor-pam3.json"))
    args = parser.parse_args()
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    result = generate(json.loads(args.input.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps({
        "pairwise_valid_mappings": result["pairwise_valid_mappings"],
        "partial_search_nodes": result["partial_search_nodes"],
        "minimum_total_decoder_error_counts": result["minimum_total_decoder_error_counts"],
        "count_agrees_with_source_text": result["count_agrees_with_source_text"],
    }, indent=2))


if __name__ == "__main__":
    main()

# PAM-3 3b2s printed-constraint audit

## Locked external input

The project anchor paper displays the nine four-bit words

`0000, 0001, 0011, 0100, 0101, 0111, 1100, 1101, 1111`

for its PAM-3 3b2s example and prints the pairwise no-error-growth condition

`d_H(f(i), f(j)) >= d_H(i, j)`

for all three-bit messages `i,j`. An encoding is an injection from the eight messages into eight of the nine words.

The artifact intentionally distinguishes three statements:

1. the source text reports 72 no-error-growth encodings;
2. the exact printed codeword list and inequality above define a finite combinatorial census;
3. the project's stronger total-decoder semantics additionally quantifies over every raw four-bit received word within one bit of a selected codeword.

Only statements 2 and 3 are recomputed here. Because the resulting count is 96 rather than 72, the result is described as a printed-constraint audit, not a reproduction or a correction of the source.

## Complete pairwise census

`src/anchor_census.py` assigns the messages in numeric order. At each partial assignment it rejects a candidate word immediately when it violates the printed inequality against any assigned message. This explores 3,666 partial nodes and emits all 96 complete mappings.

`src/anchor_census_check.py` assigns messages in the different order `0,7,3,4,1,2,5,6`, traverses candidate words in reverse order, and reconstructs the complete set independently. It explores 1,298 partial nodes and obtains the same 96 mappings. It compares the exact solution sets, not just their counts.

Every accepted mapping omits `0101`.

## Total-decoder consequence

For a mapping `f`, a raw received word `y`, and error bound `a`, the checker builds

`D_y(a) = { z : d_H(x,z) <= a for every x with d_H(f(x),y) <= 1 }`,

intersected with the inverse pin when `y` is an encoded word. The exact total-decoder error is the least `a` for which every `D_y(a)` is nonempty.

For all 96 pairwise-valid mappings:

- `D_0101(1)` is empty;
- `0101` is off the encoder image;
- the four source messages at that row form a deletion-minimal empty intersection of radius-one message balls; and
- all rows are feasible at bound two.

Hence every mapping has exact total-decoder error two. This supplies an externally defined census of the semantic gap; it does not evaluate logic cost for those 96 mappings and does not establish the source paper's numerical count.

## Logical coverage versus executed calls

The full audit grid contains `96 mappings * 16 received rows * 4 error bounds = 6,144` logical mapping/row/bound slots. This number describes the complete finite domain whose outcomes are classified; it is not a count of calls made by the implementation. The independent minimum-bound routine stops after the first infeasible row at a bound, so instrumentation of the current control flow records 4,512 calls to the row-output constructor. `results/anchor-pam3-check.json` retains both counters. They are intentionally not added together or relabeled as proof-tree nodes.

## Mutation and trust boundary

Eight mutations alter the count, delete or duplicate a mapping, change the omitted word, understate the total error, move the obstruction row, delete a core source, or falsely mark the source count as matched. The independent checker rejects all eight.

The result remains finite executable checking. Python, the two implementations, and the explicit formalization of the printed source condition are trusted. The unresolved 96-versus-72 discrepancy is retained as a limitation rather than hidden.

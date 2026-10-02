# Proof-carrying finite frontier: formal derivation and checker contract

This document states the mathematical contract implemented by `src/frontier_proofs.py`, independently reconstructed by `src/frontier_proof_check.py`, and supplemented by the fixed-codebook packing certificate in `src/fixed_codebook_proof.py` and `src/fixed_codebook_check.py`.  It proves correctness relative to the exact finite grammar in `inputs/cases.json` and `inputs/fixed-codebooks.json`.  It does not claim DRAT/LRAT/VeriPB compatibility, a proof-assistant theorem, or completeness outside those finite inputs.

## 1. Row relations from total-decoder semantics

For a fixed injective encoder `f`, received row `y`, and decoded-error bound `a`, let

- `S_y = {x : d_Y(f(x),y) <= 1}` be the possible source messages;
- `B_a(x) = {z : d_X(x,z) <= a}`;
- `L_y(a) = intersection_{x in S_y} B_a(x)`; and
- `D_y(a) = L_y(a) intersection {z}` when `y=f(z)`, otherwise `D_y(a)=L_y(a)`.

A total inverse decoder with error at most `a` exists exactly when every `D_y(a)` is nonempty.  When it exists, any independent choice `g(y) in D_y(a)` defines such a decoder.  Thus the unrestricted completion count is `product_y |D_y(a)|`.

If a row is empty, the certificate stores one of two directly checkable obstructions:

1. **Pin conflict.**  The row is `f(z)` and a possible source `x` satisfies `d_X(x,z)>a`.
2. **Empty-intersection core.**  The row is not pinned and a deletion-minimal subset of `S_y` has no common output within distance `a`.

The checker reconstructs `S_y`, the pin, and the Hamming distances from the input.  It does not trust a stored source set or a stored legality table.

## 2. Relational shared-product SOP encoding

Let the Boolean plane input domain be the finite set `D`.  A cube `c` is a ternary pattern over the input bits (`0`, `1`, or absent).  The plane has `o` output bits and one allowed-vector list `R_r` for every row `r in D`.  The goal is not to realize independent output-bit don't-cares: the OR of all selected products at row `r` must be one complete vector in `R_r`.

For every nonempty cube `c`, output bit `j`, and row `r`, the CNF uses:

- `s_c`: cube `c` is selected;
- `t_cj`: cube `c` is connected to output `j`; and
- `d_rj`: the realized value of output `j` at row `r`.

The clauses are:

1. `t_cj -> s_c` for every `c,j`;
2. `s_c -> OR_j t_cj`, excluding disconnected selected products;
3. `t_cj -> d_rj` for every row matched by `c`;
4. `d_rj -> OR_{c matches r} t_cj`, completing the OR equivalence;
5. one clause excluding each vector not in `R_r`; and
6. a Sinz sequential-counter encoding of `sum_c s_c <= p`.

### Lemma 1 (relational-CNF equivalence)

The CNF at product bound `p` is satisfiable if and only if a shared-product SOP with at most `p` products realizes one allowed vector in every row.

**Proof.**  Given a satisfying assignment, select exactly the cubes with `s_c=1` and connect them according to `t_cj`.  Clauses 1--2 make every selected cube connected and every connection selected.  Clauses 3--4 make `d_rj` exactly the OR of connected matching cubes.  Clause family 5 places that complete output vector in `R_r`; the sequential counter gives the product bound.

Conversely, assign `s` and `t` from any legal SOP and assign each `d_rj` to the circuit output.  OR semantics satisfies clauses 1--4, row legality satisfies 5, and the product bound satisfies 6.  The standard sequential-counter auxiliaries can then be assigned according to the number of selected variables seen in each prefix.  QED.

The encoding permits product sharing among outputs of one plane.  It does not permit sharing between encoder and decoder planes, matching the cost model.

## 3. Unit-conflict branch certificates

For the exact minimum `p`, the producer stores:

- an explicit `p`-product circuit; and
- a branch tree showing that the CNF at `p-1` products is unsatisfiable.

A branch record is either:

- `[0]`, which is valid only when repeated unit propagation has produced an empty clause under the path assignment; or
- `[v,left,right]`, which is valid only when `v` is currently unassigned, the left subtree checks after assigning `v=false`, and the right subtree checks after assigning `v=true`.

The only shared node is record zero, the conflict marker.  Every internal record must be reached exactly once.  The checker reconstructs the CNF independently, repeats unit propagation at each node, rejects branching on a propagated or out-of-range variable, rejects cycles and unreachable records, and requires both children.

### Lemma 2 (branch-tree soundness)

If the checker accepts a branch tree at formula `F`, then `F` is unsatisfiable.

**Proof.**  Induct on the accepted subtree.  At a conflict leaf, unit propagation derives a clause with every literal false, so no extension of the current path assignment satisfies `F`.  At an internal node `v`, the induction hypothesis excludes every extension with `v=false` and every extension with `v=true`.  These cases partition all Boolean extensions because `v` was unassigned.  Hence no extension satisfies `F`.  Applying the argument at the root proves unsatisfiability.  QED.

### Corollary 3 (plane minimum)

An accepted `p`-product circuit plus an accepted branch tree for bound `p-1` proves that `p` is the exact minimum product count for the row relation.

The tree is intentionally a simple finite certificate rather than a modern clause-learning trace.  Its advantage here is a small independent checker and an exact correspondence with the emitted finite CNF; its limitation is potentially exponential size.

## 4. Complete joint frontier for a locked specification

For each locked case, the producer enumerates every ordered injective encoder from the allowed channel-word set.  For each encoder and each error bound `a=0,...,k`, it either emits a checked semantic obstruction or synthesizes the exact minimum decoder relation plane.  The exact encoder plane is certified once per distinct encoder table.  The fixed OR-site charge is added only after both plane minima are known.  Every stored circuit is also checked against the connection cap.

Let `M(a)` be the minimum legal counted-site cost among all enumerated encoders and total decoders with error at most `a`, with infinity when none exists.

### Theorem 4 (proof-carrying frontier completeness)

If all encoder assignments have either a checked obstruction or a checked exact plane minimum at every bound, then the first finite value of `M` and every later strict decrease are exactly the complete nondominated error/cost frontier of the finite specification.  Every objective box `[0,a] x [0,b]` below `M(a)` is infeasible.

**Proof.**  Encoder enumeration is finite, disjoint, and exhaustive.  Lemmas 1--2 and Corollary 3 establish exact plane minima for every feasible encoder/bound relation.  Products cannot be shared across planes, so their minima add; the fixed OR charge does not depend on the chosen realization.  Therefore `M(a)` is the exact minimum cost at error bound `a`.  Since increasing `a` only enlarges the feasible set, `M` is nonincreasing.  Its first finite value is nondominated; a later strict decrease is also nondominated, while an equal value is dominated by the earlier lower-error point.  A box with `b<M(a)` contains no feasible design by definition, and a box with `b>=M(a)` contains the attaining witness.  QED.

The independent checker reconstructs every encoder, row relation, CNF, tree, circuit, objective profile, and frontier.  It then cross-checks the resulting profile against the separately implemented exhaustive function-table campaign.  The cross-check is additional evidence, not an axiom used by the proof checker to accept a tree.

## 5. Forced-cell packing certificate for a larger fixed codebook

For a row relation, a cell `(r,j)` is **forced one** when every allowed vector at row `r` has output `j=1`; it is **forced zero** when every allowed vector has `j=0`.  A product connected to output `j` cannot match a forced-zero row for `j`, because an SOP has no cancellation.

A set `P` of forced-one cells is a packing when no cube can legally cover two distinct cells of `P`: for any two cells `(r,j)` and `(r',j')`, every cube matching both rows also matches a forced-zero row for output `j` or for output `j'`.

### Lemma 5 (packing lower bound)

Every legal SOP realization uses at least `|P|` products.

**Proof.**  Each cell in `P` must be asserted by at least one connected product.  By the packing property, one product cannot assert two distinct cells of `P`.  Assigning one witnessing product to each forced-one cell is therefore injective, so at least `|P|` products are required.  QED.

The X01 certificate combines a `p`-product attaining circuit with a packing of size `p`, proving exactness without enumerating its `8^(32-8)=2^72` inverse decoder completions.  The independent checker reconstructs encoder and decoder domains, input widths, output counts, and every legal row from `inputs/fixed-codebooks.json`; certificate-carried shapes are accepted only after exact equality with that reconstruction.  It evaluates the attaining circuit and the packing lower bound on the same true Boolean domain, enumerates all 243 five-input cubes for each decoder relation, checks every packing pair, and finally rechecks all inverse pins and radius-one source/error obligations.  The feasible-bound circuits have exact errors one, two, and two.  This proof fixes the encoder assignment; it is a scaling supplement, not a claim of complete joint encoder search at that dimension.

## 6. Trust boundary and mutation coverage

The producer and checker share the written model but not source imports, data structures, cube representation, or CNF builder.  Acceptance still depends on the correctness of the small Python checker, the interpreter, and the stated model.  It is not a mechanically verified checker.

The delivered controls mutate encoder coverage, proof roots, branch variables, minimum counts, masks, semantic cores, row relations, and frontier membership for the DPLL certificates.  A second nine-control set mutates X01 domains, packings, circuits, masks, encoder rows, forced cells, and frontier data.  Its first control exactly recreates the pseudo-domain projection forgery: the three products `**1**/100`, `***1*/010`, and `****1/001` are legal on the forged row labels, but on the true received-word domain they decode codeword `00100` as `100` instead of inverse-pinned message `000`.  The repaired checker rejects the certificate at the domain binding before accepting either upper or lower cost evidence.  All nine are rejected in the clean reproduction.  Mutation success cannot prove absence of every defect, but it exercises each certificate boundary separately.

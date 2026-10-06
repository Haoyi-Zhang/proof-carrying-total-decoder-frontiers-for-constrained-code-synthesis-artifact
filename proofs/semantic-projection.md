# Total-decoder projection, conflicts, and relational realization

## Assumptions
Messages X are all k-bit words. Y is the complete q-ary length-n channel table, q in {2,3}; error radius is one symbol. Encoders f inject X into the explicit allowed set C. Decoders g:Y -> X are total and satisfy g(f(x))=x. For received y, S_y contains every x with d_Y(f(x),y)<=1. For bound a, intersect the message balls B_a(x), x in S_y, and intersect also {z} when y=f(z), to obtain D_y(a). An empty family of balls intersects to X. No circuit restriction is imposed in the first two sections below.

## 1. Exact counting by row products
Map each legal decoder g to its tuple of row outputs. It is a member of the Cartesian product over y of D_y(a). Conversely every member of that product defines a unique total decoder, satisfies every inverse pin, and differs from every admitted source at y by at most a bits. These operations are inverses. Thus N_f(a)=product_y |D_y(a)|, including zero when any list is empty. Summing over injective encoders counts disjoint function pairs. This counts functions, not circuits, and does not filter by logic caps.

At a=k, every inverse-pinned row has one choice and all other rows have 2^k choices, so N_f(k)=(2^k)^(q^n-2^k). With c allowed codewords and m=2^k messages, the sum is P(c,m)m^(q^n-m). This endpoint checks complete enumeration independently of circuit costs.

## 2. Sound and complete local conflict basis
Let E_(x,c) denote the encoder assignment f(x)=c, under exactly-one-per-message and injectivity constraints. At y=f(z), a source x with d_X(x,z)>a makes the assignments E_(x,f(x)) and E_(z,y) incompatible. Their negated disjunction is a valid conflict clause. Retaining both assignments in any other encoder retains both the inverse pin and the offending source, so the clause is globally sound within this semantic model.

At an unpinned empty row, choose source subset T with empty intersection of radius-a balls. Its certificate records y and every (x,f(x)), x in T. A checker verifies that all listed codewords lie at channel distance <=1 from y and that no message belongs to all the balls. The clause OR_(x in T) not E_(x,f(x)) is valid: every encoder retaining those assignments leaves no legal decoder output at y. Adding sources or adding an inverse pin cannot repair an empty intersection.

Completeness follows by taking any encoder with no legal total inverse decoder. Some row list must be empty. If pinned, the pinned message violates at least one source ball, giving the two-assignment clause. If unpinned, the ball intersection is empty, giving an intersection clause. Thus all these valid clauses exclude exactly the semantically infeasible encoders. This is an implicit finite clause family, not a polynomial-size compilation or an implemented SAT solver.

For a<k, Alon, Jin and Sudakov, The Helly Number of Hamming Balls and Related Problems (arXiv:2405.10275), Theorem 1.1, bounds a minimal empty subfamily by 2^(a+1). The bound is prior art. Removing redundant sources until no deletion preserves emptiness yields a deletion-minimal core. Such a core cannot exceed the Helly bound: otherwise it contains a smaller empty subfamily, contradicting deletion minimality. This does not assert minimum cardinality among all cores. At a=k all balls are X, so every injection permits a total inverse decoder and no conflict exists.

The code records one certificate per infeasible encoder-bound profile, not every possible clause. The checker recomputes all profiles, source sets, output intersections, coverage and core properties. It does not check a solver's global UNSAT proof.

## 3. Exact relational SOP interface
For fixed encoder and bound, create Boolean d_(y,j) for every valid channel row and output bit. Enumerate all input cubes c (each input absent, positive or negative), selection s_c, and connection t_(c,j). Require d_(y,j) iff OR of t_(c,j) for cubes matching the Boolean representation of y; require t_(c,j)<=s_c and s_c<=sum_j t_(c,j). For every forbidden tuple z outside D_y(a), add OR_j (d_(y,j)!=z_j). Bound sum_c s_c<=p and sum_(c,j)t_(c,j)<=ell.

A satisfying assignment directly specifies a shared-product decoder: selected cubes have nonempty connection masks and the equations are their exact OR semantics. The tuple exclusions force each row into its legal list; hence inverse correctness and the error bound follow. Conversely, merge duplicate cubes and remove disconnected products from a legal capped SOP network, which does not increase either count. Assign its selections, connections and actual row outputs to the variables. Every circuit equation and tuple constraint holds, and both caps hold. Therefore the formulation is feasible exactly when such a capped decoder realization exists. The current artifact solves and proof-logs the product-bound CNF relaxation described in `proof-frontier.md`; it does not encode the connection cap in that CNF. A combined encoder/decoder minimum-product witness must meet the original connection cap to close this relaxation. Otherwise the producer stops without certifying a frontier.

For ternary channels, raw bit pair 10 is not a symbol and no semantic row is imposed on a word containing it. All valid symbol rows, including untransmitted words, are imposed. The cube network remains a total Boolean circuit even at unspecified raw inputs.

## 4. Correlation control
B_1(00)={00,01,10}. Each output bit individually takes both values, so the Cartesian product of the bit marginals contains 11. That tuple is at distance two from 00 and is illegal. Whole-tuple exclusion is therefore necessary in general. Boolean-relation modeling and the failure of independent output don't-cares are established prior work; see Miao, Gerstlauer and Orshansky, ICCAD 2014, and the source audit. The construction here fixes a decoder-semantic test, not a new general relation theory.

## 5. Executable scope
src/semantic_projection.py uses bit-integer message distances and enumerates encoder assignments only. src/projection_check.py imports none of the producer, original synthesis engine or cost checker; it uses tuple/set distances. The checker first validates complete semantic records, then compares cumulative counts with the existing exhaustive histogram only after verifying that the histogram includes all inverse function pairs. This guard forbids comparing unfiltered semantic counts with cost-filtered results.

The recorded family has 174 encoders, 444 encoder-bound profiles, 3488 checked rows, and 234 infeasible profiles. Certificates split into 118 pin, 92 two-source, and 24 four-source conflicts. These finite checks and handwritten proofs are not proof-assistant mechanizations, external independent review, or SAT/VeriPB proof-log verification.


## 6. Concrete profiles used in the paper

The checked B03 encoder maps 00->000, 01->001, 10->111, 11->010. At y=000, S_y={00,01,11}; the unpinned intersection of their B_1 balls is {01}, but inverse correctness pins the row to 00. Thus D_y(1) is empty. Assignments (11,010) and (00,000) alone witness the pin conflict. This is an actual profile in semantic-projection.json, not a newly sampled instance.

At bound one, all 24 B02 encoders have exactly one legal completion. In B03, 16 encoders have no completion and eight have 12 each, giving 96 in total. The count distributions follow from the completely checked row-product profiles; their shared frontier point (1,10) does not imply an identical completion space.

# Mathematical derivations

## 1. Exact model

Let X = {0,1}^k, Y = {0,...,q-1}^n, q in {2,3}, and C be the allowed encoder subset of Y. An encoder f is an injection X -> C. A decoder g is a total function Y -> X satisfying g(f(x)) = x. Write d_X and d_Y for bit and symbol Hamming distance. The channel-error radius is one. Define

A(f,g) = max { d_X(x,g(y)) : x in X, y in Y, d_Y(f(x),y) <= 1 }.

The pair-only objective restricts y to another encoded word: A_pair(f) = max { d_X(x,z) : d_Y(f(x),f(z)) <= 1 }. The stronger pairwise noncontraction property requires d_X(x,z) <= d_Y(f(x),f(z)) for every pair. Neither is a total-decoder specification.

The decoder plane receives n raw bits for binary channels and 2n raw bits for ternary channels, using 0->00, 1->01, 2->11. Invalid raw ternary 10 is a Boolean don't-care, not a fourth channel symbol. Different received channel words can be valid channel words without belonging to C. They are not don't-cares for g.

## 2. Total-decoder extension criterion

For a received word y define S_y = {x : d_Y(f(x),y) <= 1}, and L_y(a) = intersection over x in S_y of B_a(x), where B_a(x) = {z in X : d_X(x,z) <= a}. An empty intersection family denotes all of X. If y=f(z), replace L_y(a) by L_y(a) intersect {z}; call the resulting set D_y(a).

**Proposition 1.** For a fixed injection f and integer a >= 0, an unrestricted total decoder with A(f,g) <= a exists if and only if every D_y(a) is nonempty.

**Proof.** If such a g exists, g(y) belongs to each B_a(x) whose source can produce y, and inverse correctness puts it at z whenever y=f(z). Thus g(y) lies in D_y(a). Conversely choose one element of every nonempty D_y(a). These finitely many choices define a total g. At codewords they satisfy the inverse relation, and at every reachable y they satisfy all the distance bounds defining A. This proves both implications. No circuit-cost assertion follows from independent row choices: products can cover multiple rows, so logic couples them. QED.

This elementary row-intersection criterion is not claimed as a new Helly theorem or a new generic constraint-satisfaction principle. Alon, Jin, and Sudakov establish the general Hamming-ball Helly number 2^(a+1), in the nontrivial dimension regime. Only its a=1, k=2 obstruction is needed below; that obstruction is proved directly.

## 3. Binary obstruction and minimum block length

**Theorem 2.** Under the complete binary payload convention, pairwise noncontraction first fails to imply existence of a total radius-one decoder with at most one decoded error at binary block length n=4. A witness has k=2 and f(00)=1000, f(01)=0100, f(10)=0010, f(11)=0001.

**Proof (failure at four).** Distinct codewords have distance two, and two-bit messages have distance at most two. Hence every pair satisfies noncontraction. All four encoded words can produce received 0000 by one bit error. For any proposed z=g(0000), the source x obtained by complementing both bits of z lies in X and has distance two from z. Therefore A(f,g)>=2 for every total g. Since the payload has only two bits, every inverse decoder has A<=2, so the minimum error is exactly two.

For X=Q_2, B_1(x)=X minus the bitwise complement of x. The four balls omit all four possible outputs, and their intersection is empty. Removing any one source ball leaves the complement of that source as a common output. Thus this is a deletion-minimal four-source obstruction. It establishes minimality of this particular witness family, not a claim that every obstruction in every code has four sources.

**Proof (no smaller binary length).** For n<=3 an injective complete binary payload has k<=n. With k=1 any output differs from a source in at most one bit, so any inverse decoder meets the requested bound. For k=2 and a received y outside the encoder image, at most n<=3 encoded words can lie at distance one from y: the binary radius-one ball has only n neighbors and y itself is not encoded. At most three radius-one balls in Q_2 omit at most three outputs, leaving a common output. At an encoded y=f(z), noncontraction implies d_X(x,z)<=1 for every source x with d_Y(f(x),y)<=1, so the pinned output z is legal. Proposition 1 now supplies the decoder. The only remaining case is k=3, necessarily n=3; the injection is onto Y, so there are no unpinned received words, and noncontraction verifies every required output. These cases exhaust n<=3. QED.

The full length-four decoder space is not enumerated in the experiment. The theorem is a handwritten proof with direct finite checks of its explicit witness.

## 4. Exact counted-site frontier for the binary witness

A plane product is a cube of literals, with constants and single literals charged one site. A product can feed several plane outputs. Encoder and decoder do not share products; every output has a fixed charged OR site. With encoder width w the cost is G=P_E+P_D+w+k.

**Theorem 3.** For the allowed set consisting of the four length-four binary unit vectors, k=2, and the stated 24-site/48-connection caps, the exact error-versus-cost frontier is {(2,12)}.

**Proof.** Every encoder must use all four allowed words, so received 0000 is adjacent to all four messages regardless of their assignment. The preceding argument forces A=2. Each of the four encoder output bits is one on exactly one distinct message. Every output needs an active product, and a product cannot be connected to two outputs: its satisfying message would then have two asserted output bits, which never occurs. Thus P_E>=4. A decoder with zero or one product can emit at most two distinct output vectors, whereas inverse correctness requires all four messages. Hence P_D>=2. Therefore G>=4+2+4+2=12.

The displayed encoder uses the four full message minterms. On received bits y1,y2,y3,y4, take g1 = not y1 AND not y2 and g0 = not y1 AND not y3. These two products return 00,01,10,11 on the listed unit vectors, respectively. They define a total decoder and attain A=2. There are four encoder and two decoder product-output connections, so both caps hold. This construction attains the lower bound, proving the unique frontier point. QED.

## 5. Ternary counterpart

**Proposition 4.** With symbol Hamming errors, the first possible ternary block length for this phenomenon is two. Take f(00)=01, f(01)=02, f(10)=10, f(11)=20.

**Proof.** Within either coordinate arm the two codewords have symbol distance one and their assigned messages have bit distance one. Between arms the symbol distance is two, no smaller than any two-bit message distance. All four codewords are at symbol distance one from 00. The same antipodal-output argument forces error two. At length one the ternary channel has only three words and can encode at most two messages of a complete binary payload, for which decoded error is always at most one. QED.

This statement does not transfer the source paper's raw-bit distance conventions to symbol errors. In particular, ternary 0->2 changes two representation bits but only one channel symbol. The binary construction is independent of this distinction. The experiment T02 establishes the counted-site minimum 12 by finite exhaustive replay; no separate handwritten proof of its logic minimum is asserted here.

## 6. Exact shared-product minimization

Fix a finite Boolean input domain D and a multioutput function h. Let U consist of all row/output pairs (r,j) with h(r)_j=1. For each cube c and output j, c is admissible for j precisely when all rows of D matching c have output j equal to one. Ignore cubes matching no rows, and define Q(c) to include every row/output pair covered by c connected to every admissible output.

**Lemma 5 (unconstrained connection relaxation).** The minimum number of shared products realizing h equals the minimum number of sets Q(c) covering U when output-connection count is unconstrained.

**Proof.** In any valid SOP implementation a product connected to j cannot match a zero row for j, since OR has no cancellation. Thus all its enabled outputs are admissible. Enabling every additional admissible output changes no zero to one and can only cover more required ones. Consequently an implementation gives a cover by Q(c) using no additional products. In the other direction, connect each cube in a cover to its admissible outputs. Every required one is covered and no required zero is covered, giving h. Duplicate products can be merged and disconnected products removed without increasing cost. QED.

It follows that removing a coverage set contained in another is safe for the *unconstrained product minimum*. It need not be safe for a connection-constrained minimum: the larger set may require more enabled outputs.

**Lemma 6 (closing the relaxation).** If the unconstrained minimum has p products and an explicit p-product witness satisfies the original connection limit, then p is also the constrained minimum.

**Proof.** Relaxation cannot increase the minimum, so every constrained realization uses at least p products. The cap-legal witness provides the reverse inequality. QED.

The implementation checks the combined encoder/decoder connection total of every function pair. If a stored minimum violates the cap, it stops; it does not infer infeasibility, select a more expensive heuristic realization, or certify completeness.

To solve the finite cover problem, select any uncovered cell u of a residual set R. The recurrence is F(empty)=0 and F(R)=1+min over c with u in Q(c) of F(R minus Q(c)). Each branch removes u. Induction on |R| proves the recurrence: any cover must contain an option covering u, and the remaining options must cover the remainder; conversely, any recurrence branch constructs a cover. The producer chooses the cell with fewest options and memoizes residual sets. The checker generates cubes from care masks and value submasks, retains all distinct nonempty coverages without dominance pruning, and searches for any cover with at most p-1 products. An explicit valid p-product circuit and exhaustion of that finite lower search establish minimality relative to the implementation and written model. They are not proof-assistant certificates.

## 7. From function minima to the complete finite frontier

Let m=2^k and N=q^n. There are P(|C|,m) injections if |C|>=m, and zero otherwise. For each injection, inverse correctness fixes exactly m distinct decoder rows, leaving N-m free rows with m choices each. Thus the number of function pairs is

D = P(|C|,m) m^(N-m).

These choices are disjoint and exhaustive. No message-label or coordinate symmetry reduction is used.

**Proposition 7.** Exhaustive enumeration of these pairs, exact per-plane product minima with all connection-relaxation gaps closed, and retention of the cheapest feasible pair for each error bound yield the complete frontier of the stated finite SOP grammar.

**Proof.** For fixed f,g, encoder and decoder product minima add because their products cannot be shared across planes. Any other implementation of the same pair has identical A and no lower G, and is therefore irrelevant to strict Pareto improvement. A function pair whose minimum exceeds the site cap has no cap-legal implementation. Every remaining pair has a cap-legal minimum witness and is enumerated once. Define M(a)=min {G(f,g): A(f,g)<=a and caps hold}, with infinity for an empty set. Feasibility at bound (a,b) is exactly M(a)<=b. M is nonincreasing. Its first finite value and later strict decreases are exactly the nondominated points: equality with an earlier value is dominated by the earlier lower-error point, whereas at a strict decrease no earlier error bound can match or improve its cost. Any box [0,a] x [0,b] with b<M(a) is infeasible; a feasible bound is covered by an attained frontier point. QED.

This is ordinary exact finite optimization. Ehlers already studies complete monotone Pareto enumeration, and Jabs et al. provide general multiobjective MaxSAT proof logging. The proposition is a correctness derivation for this implementation, not a new general certification algorithm.

## 8. Analytic frontiers of the two tradeoff cases

**Proposition 8.** The binary repetition case B05 has frontier {(0,8),(1,6)}; the no-adjacent-ones case B06 has frontier {(0,9),(1,6)}.

**Proof (B05).** The only encodings use 000 and 111. Every nonconstant encoder and decoder needs at least one product, so G>=1+1+3+1=6. Repeating the message bit uses one encoder product, shared to three outputs. Reading one received bit uses one decoder product and attains A=1 at G=6. For A=0, inverse labels must be returned on the disjoint radius-one balls around 000 and 111, which together cover the entire three-bit cube. The decoder is majority or its complemented-coordinate equivalent. The three true rows of weight exactly two require distinct cubes: any cube covering two of these rows also covers a false row of weight one. Three products suffice, giving G=1+3+4=8 and proving the two points.

**Proof (B06).** The allowed set is {000,001,010,100,101}. Exact radius-one correction of two messages requires their codewords to have distance at least three: if their distance is at most two, a received word lies in both radius-one balls and would require both outputs. At length three the distance-three condition is also sufficient. The only complementary allowed pair is 010 and 101. Its encoder needs both x and not x, so at least two products, while its uniquely error-free decoder is a coordinate-complemented majority with three products by the preceding argument. This gives G=2+3+4=9. The pair 000,001 and a single received-bit decoder attain A=1 with G=6, matching the universal nonconstant-plane lower bound. A one-bit payload has no other error level. QED.

## 9. Why this locked family cannot show a scalarization gap

**Proposition 9.** Every locked specification has at most two feasible error levels, hence at most two frontier points; both points of a two-point frontier are supported by positive linear scalarization. The tested extreme weights recover both endpoints under the 24-site cap.

**Proof.** A one-bit payload has only A=0,1. The only two-bit binary cases have length three. Four radius-one-disjoint balls in the three-bit channel would contain 4*4=16 words, exceeding its eight words, so A=0 is impossible. The two-bit ternary case has length two; any two channel words have distance at most two and have intersecting radius-one balls, so A=0 is impossible there as well. The remaining levels are A=1,2. For two frontier points (a1,g1),(a2,g2), a1<a2 and g1>g2, minimizing lambda*A+G selects the first when lambda>(g1-g2)/(a2-a1), and the second when lambda is smaller. Because both cost and error differences are positive integers with cost at most 24, weights (25,1) and (1,25) lie on opposite sides of the threshold. A singleton frontier is trivially supported. QED.

The seven tested weights are (1,25), (1,8), (1,2), (1,1), (2,1), (8,1), and (25,1), with lower-error tie breaking. No missed nondominated point is expected or observed. This theorem concerns the locked family, not all finite constrained codes.

## 10. Pin-use restrictions

The valid pair f(x)=(x,0), g(y1,y2)=y1 has inverse correctness and A=1 while ignoring the second decoder pin. Essential dependence on every pin therefore excludes a feasible decoder. A syntactic requirement that every pin occur in a product is different, but is not automatically cost preserving either: the one-product realization y1 ignores y2, whereas y1*y2 OR y1*not y2 uses two products. No one-product expression depending syntactically on y2 realizes y1 on the full two-bit domain. Unconnected padding gates change the meaning of counted cost and need their own accounting. Product permutation is a true symmetry; arbitrary pin-use requirements need a separate domain-specific proof. This observation does not establish that any reported source-paper benchmark used an invalid assumption.

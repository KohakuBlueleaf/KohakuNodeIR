# Layout Algorithm Research for KohakuNodeIR

## Problem Statement

KohakuNodeIR's node graph has two distinct edge types with orthogonal ideal
directions:

- **DATA edges**: should flow **left to right** (horizontal).
- **CONTROL edges**: should flow **top to bottom** (vertical, same column).

Current pain points:

1. Value nodes (constants / sources) are placed far from their consumers.
2. Control-connected chains span multiple columns instead of stacking vertically.
3. Backward edges (loops) are not handled gracefully.
4. The scoring function under-penalises backward edges and ignores edge crossings.

---

## 1. Layered (Sugiyama) Framework

The Sugiyama method (1981) is the dominant approach for hierarchical / directed
graph layout. It proceeds in four phases that map cleanly onto our dual-axis
problem.

### 1.1 Cycle Removal

**Goal**: Make the graph acyclic so that topological layering is possible.

**Techniques**:

| Method | Description | Complexity |
|---|---|---|
| DFS back-edge reversal | Run DFS; reverse every back-edge (edge to an ancestor on the DFS stack). Simple and deterministic. | O(V+E) |
| Greedy feedback arc set | Pick vertices with largest `out_deg - in_deg` first; orient remaining edges accordingly. Often removes fewer edges than DFS. | O(V+E) |
| Berger-Shor | Partition vertices into two sets via a max-acyclic-subgraph 2-approximation. | O(V+E) |

**For KohakuNodeIR**: DFS back-edge reversal is sufficient. We should
reverse only CONTROL back-edges (loops in control flow) while leaving DATA
back-edges as-is (they represent legitimate feedback and should be scored as
expensive but not structurally reversed).

**Handling reversed edges**: After layout, reversed edges are drawn with a
special "loop-back" routing (arcing above or below the normal flow) so the
user sees they are backward.

### 1.2 Layer Assignment (Ranking)

**Goal**: Assign each node to a discrete layer (column for data, row for
control).

| Algorithm | Description | Pros | Cons |
|---|---|---|---|
| **Longest-path** | Place each node at its longest-path distance from a source. | O(V+E), simple | Tends to produce many layers; nodes cluster near the end |
| **Coffman-Graham** | Assigns layers with a bounded width W, minimising total layers. Near-optimal for W=2. | Bounded width control | Harder to implement; only approximates for W>2 |
| **Network simplex** | Models ranking as a min-cost flow problem; minimises total edge span (sum of |layer[dst] - layer[src]|). Used by Graphviz `dot` and dagre. | Optimal edge span; compact layouts | More complex to implement; O(VE) typical |

**For KohakuNodeIR**: We should use network simplex (or at minimum
longest-path with compaction). Our current BFS longest-path already works for
the DATA axis. For the CONTROL axis, nodes connected by ctrl edges should be
assigned to consecutive rows within the same column. The key insight is:

> Layer assignment should be run **twice on separate subgraphs**:
> 1. DATA edges determine **column** assignment (left-to-right).
> 2. CTRL edges determine **row** assignment (top-to-bottom within each column).

### 1.3 Crossing Minimisation

**Goal**: Reorder nodes within each layer to minimise edge crossings.

| Algorithm | Description | Pros | Cons |
|---|---|---|---|
| **Barycenter heuristic** | Place each node at the mean position of its neighbours in the adjacent layer. Sweep top-down then bottom-up; repeat. | Simple, fast O(V+E) per sweep | No worst-case bound; can get stuck |
| **Median heuristic** | Place each node at the median of its neighbours. | Better worst-case bound (3x optimal) | Slightly worse average results than barycenter |
| **Sifting** | Try moving each node to every position in its layer; keep the best. | Better quality than barycenter | O(V^2) per layer |
| **Transpose** | After initial ordering, swap adjacent pairs if it reduces crossings. | Good refinement step | Only local improvement |

**Efficient crossing counting**: Barth et al. showed that counting crossings
between two adjacent layers reduces to counting inversions in a sequence,
solvable in O(|E| log |V|) using merge-sort. This is used by dagre.js.

**For KohakuNodeIR**: Barycenter + transpose sweeps (the dagre/Graphviz
approach) are the best fit. We should:

1. Initialise node order within each column using CTRL topology (BFS order).
2. Run barycenter sweeps considering DATA edges (horizontal neighbours).
3. Apply transpose refinement.
4. Repeat 24 times (the empirically good constant from Sugiyama literature),
   keeping the best ordering.

### 1.4 Coordinate Assignment

**Goal**: Assign pixel x,y to each node, respecting the layer ordering.

| Algorithm | Description | Pros | Cons |
|---|---|---|---|
| **Brandes-Kopf** | Linear-time algorithm; aligns nodes to "blocks" using innermost edges, then compacts. Used by dagre.js and ELK. | O(V+E), fast | Can produce suboptimal spacing for variable-size nodes |
| **Network simplex (Gansner)** | Formulates coordinate assignment as a separate network simplex problem, minimising total edge length. Used by Graphviz `dot`. | Optimal for the LP relaxation | Slower; harder to implement |
| **Priority layout** | Assign coordinates by processing nodes in priority order (e.g., by edge weight). | Simple | No optimality guarantee |

**For KohakuNodeIR**: Priority layout or a simplified Brandes-Kopf is
recommended. Since we have a grid model (col, row), the coordinate assignment
phase can be relatively simple:

1. Column widths = max node width in each column + H_SPACING.
2. Row heights = max node height in each row + V_SPACING.
3. x = cumulative column widths.
4. y = cumulative row heights.

The complexity lies in the earlier phases (layer + ordering).

---

## 2. EDA / Circuit Layout Techniques

These are relevant because circuit schematics share our dual-axis constraint
(signals flow horizontally, control/clock flows vertically).

### 2.1 Force-Directed Placement

Treat nodes as charged particles (repulsion) and edges as springs (attraction).
Iterate until equilibrium.

**Pros**: Naturally handles arbitrary edge directions; good for organic layouts.
**Cons**: No guaranteed directionality; slow convergence O(V^2) per iteration;
not ideal for hierarchical graphs with clear flow direction.

**Verdict**: Not suitable as primary algorithm for KohakuNodeIR (we need
strong directional constraints), but could be used as a **post-processing
refinement step** to reduce edge lengths after the Sugiyama phases.

### 2.2 Simulated Annealing Placement

Random perturbations (swaps, moves) accepted/rejected based on a cooling
schedule. Used extensively in VLSI placement (e.g., TimberWolf).

**Pros**: Can escape local optima; handles complex objective functions.
**Cons**: Slow (many iterations needed); non-deterministic; hard to tune.

**Verdict**: Our current optimizer already uses a greedy local-search
(swap, column-move, row-move). Adding simulated annealing with a temperature
schedule would improve quality for large graphs but adds complexity. Worth
considering as a future enhancement.

### 2.3 Analytical Placement

Formulate placement as a quadratic optimisation problem (minimise sum of
squared wire lengths). Solve with conjugate gradient or spectral methods.

**Pros**: Very fast for large circuits; global optimisation.
**Cons**: Produces overlapping placements that need legalisation; ignores
discrete constraints.

**Verdict**: Overkill for our node count (typically 10-100 nodes). Not
recommended.

### 2.4 Min-Cut Placement

Recursively bisect the chip area and the netlist, minimising the number of
edges crossing each cut line.

**Pros**: Good wire length; handles clustering naturally.
**Cons**: Recursive partitioning loses global information; quality depends on
partitioner.

**Verdict**: The recursive structure does not map well to our directional
constraints. Not recommended.

---

## 3. Existing Implementations

### 3.1 dagre.js

Used by many node editors (React Flow, Cytoscape, etc.).

**Architecture** (from Gansner et al. 1993):

1. **Ranking**: Network simplex (default), longest-path, or tight-tree.
2. **Ordering**: Barycenter heuristic with Barth et al. O(|E| log |V|)
   crossing counter.
3. **Coordinate assignment**: Brandes-Kopf with adjustments for variable
   node/edge sizes.
4. **Cycle breaking**: Greedy feedback arc set.

**Relevant for us**: dagre supports `rankdir: 'LR'` (left-to-right) which
matches our DATA axis. However, it does not natively support our dual-axis
model where CTRL and DATA have different preferred directions.

### 3.2 ELK (Eclipse Layout Kernel)

The most feature-rich open-source layout library.

**Phases**:

1. Cycle breaking (greedy, interactive, model order).
2. Layer assignment (network simplex, Coffman-Graham, MinWidth, longest-path).
3. Crossing minimisation (layer sweep with barycenter/greedy switch).
4. Node placement (Brandes-Kopf, network simplex, linear segments).
5. Edge routing (orthogonal, polyline, splines).

**Key feature**: Full port-aware layout. ELK treats ports (attachment points
on node borders) as first-class entities, which matches our KGPort model.

**Relevant for us**: ELK's layered algorithm with port constraints is the
closest existing solution to our problem. Its concept of "layer constraint"
(FIRST, LAST) could be used to force value nodes near their consumers.

### 3.3 Graphviz `dot`

The classic hierarchical layout engine (Gansner et al. 1993).

**Phases**:

1. Cycle breaking via DFS.
2. Ranking via network simplex (minimises total edge span).
3. Ordering via weighted median + transpose (iterative sweeps).
4. Coordinate assignment via auxiliary graph + network simplex.
5. Edge routing via B-splines.

**Key insight from the paper**: Edge weights affect ranking -- higher-weight
edges are kept shorter. We can exploit this by giving CTRL edges high weight
(to keep them short / same-column) and DATA edges normal weight.

---

## 4. Recommended Approach for KohakuNodeIR

### 4.1 Algorithm Selection

The recommended approach is a **modified Sugiyama method with dual-axis
awareness**:

| Phase | Algorithm | Rationale |
|---|---|---|
| Cycle breaking | DFS back-edge reversal on CTRL subgraph | Simple; ctrl loops are rare |
| Column assignment | Longest-path on DATA subgraph with value-node compaction | Already implemented; works well |
| Row assignment | Topological sort on CTRL subgraph within each column | Ensures ctrl chains stack vertically |
| Crossing minimisation | Barycenter + transpose sweeps | Good quality/speed tradeoff |
| Coordinate assignment | Grid-based with column/row width/height | Simple; our nodes have fixed sizes |
| Post-optimisation | Local search (swap, move) with improved scoring | Already implemented; needs better score function |

### 4.2 Pseudocode

```
function layout(graph):
    # Phase 0: Separate edge types
    data_edges = [e for e in graph.edges if e.type == "data"]
    ctrl_edges = [e for e in graph.edges if e.type == "control"]

    # Phase 1: Cycle breaking
    back_ctrl = find_back_edges_dfs(ctrl_edges)
    ctrl_forward = reverse_edges(ctrl_edges, back_ctrl)
    back_data = find_back_edges_dfs(data_edges)
    data_forward = reverse_edges(data_edges, back_data)

    # Phase 2: Column assignment (DATA axis, left-to-right)
    col = longest_path_ranking(data_forward)

    # Phase 2b: Value node compaction
    for node in value_nodes:  # no data inputs, no ctrl inputs
        consumer_col = min(col[c] for c in consumers(node))
        col[node] = max(0, consumer_col - 1)

    # Phase 2c: CTRL-connected column merge
    for (a, b) in ctrl_forward:
        if col[a] != col[b] and b has no data inputs from other columns:
            col[b] = col[a]  # force same column

    # Phase 3: Row assignment (CTRL axis, top-to-bottom within column)
    for each column C:
        nodes_in_C = [n for n in nodes if col[n] == C]
        row_within_C = topological_sort(ctrl_forward restricted to nodes_in_C)
        # Nodes without ctrl edges: place after ctrl chain,
        # ordered by data-dependency barycenter

    # Phase 4: Crossing minimisation
    # Build global (col, row) grid
    # Run barycenter sweeps on DATA edges:
    for sweep in range(24):
        if sweep % 2 == 0:  # left-to-right
            for c in columns left to right:
                for node in column[c]:
                    bary = mean(row[neighbor] for neighbor in left_data_neighbors(node))
                    tentative_row[node] = bary
                reorder column[c] by tentative_row, breaking ties by ctrl order
        else:  # right-to-left
            for c in columns right to left:
                ... (symmetric)
        # Transpose refinement
        for c in columns:
            for i in range(len(column[c]) - 1):
                if swapping column[c][i] and column[c][i+1] reduces crossings:
                    swap them
        # Keep best ordering seen so far

    # Phase 5: Coordinate assignment
    x = cumulative column widths + spacing
    y = cumulative row heights + spacing

    # Phase 6: Restore reversed edges (mark them as "backward" for rendering)
    for edge in back_ctrl + back_data:
        mark edge as backward (for loop-back routing)

    return positioned_graph
```

### 4.3 Handling Special Cases

#### Backward edges (loops)

1. **Detection**: DFS on each edge subgraph separately.
2. **During layout**: Temporarily reverse them so layering works.
3. **After layout**: Restore original direction; route the edge with a
   loop-back arc (going above the source or below the target).
4. **Scoring**: 3x penalty factor so the optimiser strongly avoids placing
   nodes that create unnecessary backward edges.

#### Value nodes

Value nodes (no data inputs, no ctrl inputs) are "floating" -- they can be
placed anywhere. Strategy:

1. Place in the column immediately left of their first consumer.
2. Place in the row closest to the barycenter of all their consumers.
3. During optimisation, allow value nodes to move more freely (try more
   column positions).

#### @dataflow blocks

Dataflow blocks contain nodes that have only data dependencies (no ctrl edges).
Strategy:

1. Identify connected components of data-only nodes.
2. Lay out each component as a horizontal chain.
3. Place the component in the row allocated by its parent ctrl context.

#### Mixed ctrl + data edges

When a node has both ctrl and data connections:

1. Column assignment: DATA edges take priority (determines horizontal position).
2. Row assignment: CTRL edges take priority (determines vertical position).
3. Conflict resolution: If a ctrl-connected pair must be in different columns
   (due to data edges), keep them in their data-assigned columns but draw the
   ctrl edge with extra routing.

---

## 5. Improved Scoring Function Design

The scoring function should capture five quality metrics:

### 5.1 Edge Direction Cost

| Edge Type | Ideal | Forward Cost | Backward Cost |
|---|---|---|---|
| DATA | col_diff=+1, row_diff=0 | `max(0, col_diff-1) + abs(row_diff)*2` | `abs(col_diff)*3 + abs(row_diff)` (3x penalty) |
| CONTROL | col_diff=0, row_diff=+1 | `abs(col_diff)*2 + max(0, row_diff-1)` | `abs(row_diff)*3 + abs(col_diff)*3` (3x penalty) |

### 5.2 Edge Crossing Penalty

Approximate crossing count between each pair of adjacent columns using the
inversion-counting approach:

1. For each pair of adjacent columns (c, c+1):
2. Collect all DATA edges from column c to column c+1.
3. Sort edges by source row.
4. Count inversions in the target row sequence (merge-sort method).
5. Each crossing adds a penalty (e.g., 2.0 per crossing).

For edges spanning multiple columns, count crossings at each intermediate
column boundary.

### 5.3 Node Overlap Penalty

For every pair of nodes in the same column that are adjacent in row order,
check if their bounding boxes would overlap given the assigned coordinates.
Each overlap adds a large penalty (e.g., 10.0).

### 5.4 Long Edge Penalty

Edges spanning more than 2 columns or 2 rows add extra cost proportional
to the span, to encourage compact layouts.

### 5.5 Value Node Distance

For value/source nodes, add penalty proportional to the Manhattan distance
to the barycenter of their consumers.

---

## 6. References

- Sugiyama, Tagawa, Toda. "Methods for Visual Understanding of Hierarchical
  System Structures." IEEE Trans. Systems, Man, and Cybernetics, 1981.
- Gansner, Koutsofios, North, Vo. "A Technique for Drawing Directed Graphs."
  IEEE Trans. Software Engineering, 1993.
  ([PDF](https://www.graphviz.org/documentation/TSE93.pdf))
- Brandes, Kopf. "Fast and Simple Horizontal Coordinate Assignment."
  Proc. Graph Drawing (GD), 2001.
  ([SpringerLink](https://link.springer.com/chapter/10.1007/3-540-45848-4_3))
- Barth, Junger, Mutzel. "Simple and Efficient Bilayer Cross Counting."
  Proc. Graph Drawing (GD), 2002.
  ([PDF](https://link.springer.com/content/pdf/10.1007/3-540-36151-0_13.pdf))
- Coffman, Graham. "Optimal Scheduling for Two-Processor Systems."
  Acta Informatica, 1972.
  ([Wikipedia](https://en.wikipedia.org/wiki/Coffman%E2%80%93Graham_algorithm))
- dagre.js. Directed graph layout for JavaScript.
  ([GitHub](https://github.com/dagrejs/dagre),
   [Wiki](https://github.com/dagrejs/dagre/wiki))
- ELK. Eclipse Layout Kernel.
  ([Website](https://eclipse.dev/elk/),
   [Layered algorithm reference](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html))
- Graphviz `dot` layout engine.
  ([Website](https://graphviz.org/docs/layouts/dot/))
- Healy, Nikolov. "Hierarchical Drawing Algorithms."
  Handbook of Graph Drawing and Visualization, Ch. 13.
  ([PDF](https://cs.brown.edu/people/rtamassi/gdhandbook/chapters/hierarchical.pdf))
- ComfyUI auto-nodes-layout.
  ([GitHub](https://github.com/phineas-pta/comfyui-auto-nodes-layout))

# Diagrams

Hand-written SVG. No build step, no rendering toolchain, no dependencies — open one in a browser, drop it
into a slide, or let GitHub render it inline in [`../architecture.md`](../architecture.md).

| File | View | Shows |
|---|---|---|
| `0-fixture-to-shelf.svg` | §0 | The business chain: fixture list and till data in, pizzas on the shelf out — with the pipeline's boundary drawn on it |
| `1-containers.svg` | §1 | What runs where, and the three trust zones with the privacy boundary between them |
| `3-record-lifecycle.svg` | §3 | Every path a record can take, including quarantine and the stale-marts branch |
| `5-data-model.svg` | §5 | The star schema and the combined mart |

Views §2 (sequence) and §4 (class) are monospace text inside `architecture.md`, deliberately: a sequence
ladder and a class-with-method-list read fine that way, and they stay diffable.

## Why SVG rather than Mermaid

Mermaid is easier to *edit* but has to be rendered to be seen — GitHub does it inline, most other viewers
do not, and `mermaid-cli` needs Puppeteer and a headless Chromium. SVG renders anywhere, scales without
going fuzzy at any zoom, and converts cleanly to PNG or PDF.

The trade-off is real: **editing means moving coordinates by hand.** If the design changes substantially,
redrawing beats nudging.

## Conventions

Consistent across all four, so they read as one set:

- **Blue** `#1d4ed8` — this pipeline, and the deliverable table
- **Grey** `#71717a` — other teams' systems and external sources
- **Red** `#b91c1c` — the personal data zone
- **Amber** `#b45309` — pseudonymised data, and the analyst-tunable seed
- **Green** `#15803d` — aggregate data, and successful outcomes
- **Purple** `#6d28d9` — orchestration, and the relevance bridge
- **Black fill** — the privacy boundary itself, so it reads as a wall rather than a stage

Solid arrows are data flow; dashed arrows are control, config, or feedback loops. Cardinality on the ERD
is `1..*`.

Colour is never the *only* signal — every zone is also labelled, so these survive greyscale printing.

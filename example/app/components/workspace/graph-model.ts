/**
 * Snapshot of https://context-fabric.ai/docs/concepts/graph-model, bundled so
 * the agent's system prompt always has the graph model available (the app may
 * be offline, and the docs site doesn't guarantee CORS). `loadGraphModelDoc`
 * prefers the live page and falls back to this snapshot.
 */

export const GRAPH_MODEL_DOC_URL =
  "https://context-fabric.ai/docs/concepts/graph-model"

export const GRAPH_MODEL_DOC_SNAPSHOT = `# Context-Fabric Graph Data Model

## Overview

Context-Fabric represents annotated text as a directed graph where every word,
phrase, clause, sentence, and document becomes a node. Features annotate
nodes, while edges encode containment, sequence, and relationships across any
structured corpus type.

## Slot Nodes: Atomic Units

**Slot nodes** constitute the minimal corpus units, typically words but
potentially morphemes, characters, or other atomic elements defined by the
annotation scheme. They maintain strict linear sequencing, numbered 1 to N.

Key characteristics:
- Define textual order for all other nodes
- Carry the actual text content exclusively
- All other nodes derive position from contained slots
- Example: A sentence spanning slots 100-150 precedes one spanning slots
  200-250

## Non-Slot Nodes: Containing Structures

**Non-slot nodes** represent higher-level structures: phrases, clauses,
sentences, paragraphs, sections, chapters, documents, and corpus-specific
annotations. These form overlapping hierarchies where structures nest and
intersect across multiple annotation layers.

### ID Assignment

Non-slot node IDs continue sequentially after the final slot number, grouped
by type. In a corpus with 100,000 word slots, the first non-slot type occupies
nodes 100,001-150,000, the second type 150,001-300,000, maintaining a
contiguous block of IDs per type.

### Spanning Slots

Each non-slot node spans a slot range. This span-based architecture enables
efficient containment queries without reconstructing structure from markup or
whitespace.

## Node Types

Corpora define custom node types per annotation scheme. The BHSA (Hebrew
Bible) includes: word, phrase, clause, sentence, verse, chapter, book, plus
linguistic subtypes like subphrase and clause_atom. A literary corpus might
define: word, sentence, paragraph, chapter, book.

## Features: Node Annotations

**Features** are named attributes encoding corpus annotations: part of speech,
grammatical properties, semantic tags, metadata, and relations.

### Node Features (F API)
Access individual node attributes:
- Lexical: lemma, surface form, normalized form
- Grammatical: part of speech, tense, number, gender, case
- Semantic: gloss, domain, named entity type
- Structural: function, relation, type

### Edge Features (E API)
Attributes of relationships between nodes, accessed separately from node
properties.

## Containment and Locality (L API)

The locality API navigates containment and adjacency:
- L.d(node, otype) — down: descendants of specified type
- L.u(node, otype) — up: ancestors of specified type
- L.n(node, otype) — next: following sibling of specified type
- L.p(node, otype) — previous: preceding sibling of specified type

## Sequence and Ordering

All nodes have natural ordering derived from contained slots:
1. A node's position is defined by its first slot (ties broken by last slot)
2. Containment ordering respects slot ranges
3. Search results return in textual reading order by default

## Implementation

Context-Fabric stores graphs as memory-mapped arrays:
- Slot positions: two arrays (start/end) per non-slot node type
- Features: one array per feature, indexed by node ID
- Edges: adjacency arrays with optional edge values

This enables constant-time feature lookup, efficient range queries for
containment, and memory-mapped access for corpora exceeding RAM capacity.`

let cachedDoc: string | null = null

/**
 * The graph-model doc for the agent's system prompt: the live page when
 * reachable (converted crudely from HTML by stripping tags), else the bundled
 * snapshot. Cached per session — the doc doesn't change mid-conversation.
 */
export const loadGraphModelDoc = async (): Promise<string> => {
  if (cachedDoc) return cachedDoc
  try {
    const response = await fetch(GRAPH_MODEL_DOC_URL, {
      signal: AbortSignal.timeout(4000),
    })
    if (response.ok) {
      const html = await response.text()
      const text = html
        .replace(/<script[\s\S]*?<\/script>/gi, "")
        .replace(/<style[\s\S]*?<\/style>/gi, "")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s{3,}/g, "\n\n")
        .trim()
      // A tag-stripped page still has to look like the doc; otherwise it's a
      // soft-404 or consent wall and the snapshot is more trustworthy.
      if (text.length > 500 && /slot/i.test(text)) {
        cachedDoc = text
        return cachedDoc
      }
    }
  } catch {
    // Offline or CORS-blocked — the snapshot below covers it.
  }
  cachedDoc = GRAPH_MODEL_DOC_SNAPSHOT
  return cachedDoc
}

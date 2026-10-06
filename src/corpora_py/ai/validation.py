"""Read-only node checks for the AI curation service (#232).

The caller must authorize access, resolve the scope to explicit node IDs, and
pin the loaded API to the supplied version before calling this engine. This
module neither loads corpora nor interprets client-supplied schema rules.
Required features come from the corpus's trusted schema, not from the model.

These checks complement the archive round-trip validator in corpora_mcp.
They do not clear caches, recompile datasets, infer linguistic corrections,
or claim that a loaded corpus has passed checks of its original TF files.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from numbers import Integral
from typing import Any, Literal

from .schemas import Finding, Severity, ValidateResponse

FeatureType = Literal["str", "int"]
_REBUILD = "Re-run the source walker and validate the rebuilt dataset."


def validate_nodes(
    api: Any,
    *,
    corpus: str,
    version: str,
    nodes: Iterable[int],
    required_features: Mapping[str, Mapping[str, FeatureType]] | None = None,
) -> ValidateResponse:
    """Check only the supplied nodes, preserving first-seen order.

    Invalid selection IDs or an unloaded required feature raise ValueError;
    they must not masquerade as corruption findings. Feature requirements are
    keyed by concrete otype, e.g. {"word": {"lemma": "str"}}. Missing or
    ill-typed values are reported without promising an evidence-free repair.
    """
    otype = api.F.otype
    max_node, max_slot = int(otype.maxNode), int(otype.maxSlot)
    selected: dict[int, None] = {}
    for node in nodes:
        if (
            isinstance(node, bool)
            or not isinstance(node, Integral)
            or not 1 <= int(node) <= max_node
        ):
            raise ValueError(f"Selected node must be an integer between 1 and {max_node}: {node!r}")
        selected[int(node)] = None

    requirements = required_features or {}
    loaded = set(api.Fall())
    for features in requirements.values():
        for name, value_type in features.items():
            if value_type not in ("str", "int"):
                raise ValueError(f"Unsupported required feature type: {value_type!r}")
            if name not in loaded:
                raise ValueError(
                    f"Required feature {name!r} is not loaded; load it before validation"
                )

    findings: list[Finding] = []

    def report(
        node: int,
        node_type: str,
        rule: str,
        message: str,
        consequence: str,
        *,
        structural: bool = True,
    ) -> None:
        findings.append(
            Finding(
                node_id=node,
                node_type=node_type,
                rule=rule,
                severity=Severity.error,
                message=message,
                consequence=consequence,
                fixable=False,
                unfixable_reason=(
                    _REBUILD
                    if structural
                    else "An authoritative source value is required before proposing a correction."
                ),
            )
        )

    for node in selected:
        node_type = otype.v(node)
        if not isinstance(node_type, str) or not node_type.strip():
            report(
                node,
                "unknown",
                "OTYPE_MISSING",
                f"Node {node} has no valid otype.",
                "The reader cannot classify or navigate this node.",
            )
            continue

        if (node <= max_slot) != (node_type == otype.slotType):
            report(
                node,
                node_type,
                "OTYPE_SLOT_MISMATCH",
                f"Node {node} has type {node_type!r}, inconsistent with the slot boundary.",
                "Token and structural-node lookups can return the wrong content.",
            )

        if node > max_slot:
            try:
                slots = tuple(api.E.oslots.s(node))
            except (IndexError, KeyError, TypeError, ValueError):
                report(
                    node,
                    node_type,
                    "OSLOTS_UNREADABLE",
                    f"Node {node} has unreadable slot links.",
                    "The reader cannot reconstruct the text belonging to this node.",
                )
            else:
                if not slots:
                    report(
                        node,
                        node_type,
                        "OSLOTS_EMPTY",
                        f"Node {node} has no slot links.",
                        "The node has no addressable text in the reader.",
                    )
                elif any(
                    isinstance(slot, bool)
                    or not isinstance(slot, Integral)
                    or not 1 <= int(slot) <= max_slot
                    for slot in slots
                ):
                    report(
                        node,
                        node_type,
                        "OSLOTS_INVALID",
                        f"Node {node} links outside the valid slot range 1–{max_slot}.",
                        "The node can render missing or unrelated words.",
                    )

        for name, value_type in requirements.get(node_type, {}).items():
            value = api.Fs(name).v(node)
            if value is None:
                report(
                    node,
                    node_type,
                    "FEATURE_MISSING",
                    f"Node {node} is missing required feature {name!r}.",
                    f"Reader views and queries requiring {name!r} cannot use this node.",
                    structural=False,
                )
            elif not (
                isinstance(value, str)
                if value_type == "str"
                else isinstance(value, Integral) and not isinstance(value, bool)
            ):
                report(
                    node,
                    node_type,
                    "FEATURE_TYPE",
                    f"Node {node} feature {name!r} must have type {value_type}.",
                    f"Reader views and queries may misinterpret {name!r} on this node.",
                    structural=False,
                )

    return ValidateResponse(
        corpus=corpus, version=version, checked_nodes=len(selected), findings=findings
    )

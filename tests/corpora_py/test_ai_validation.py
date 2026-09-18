"""Deterministic validation on corrupt fakes and real TF/CF loader APIs."""

from types import SimpleNamespace

import pytest

from corpora_py.ai.validation import validate_nodes


class Feature:
    def __init__(self, values):
        self.values = values

    def v(self, node):
        return self.values.get(node)


@pytest.fixture
def api():
    otype = Feature({1: "word", 2: "word", 3: "paragraph", 4: "paragraph"})
    otype.maxNode, otype.maxSlot, otype.slotType = 4, 2, "word"
    features = {
        "otype": otype,
        "lemma": Feature({1: "one", 2: "two"}),
        "number": Feature({3: 1, 4: 2}),
    }
    slots = {3: (1,), 4: (2,)}
    return SimpleNamespace(
        F=SimpleNamespace(otype=otype),
        E=SimpleNamespace(oslots=SimpleNamespace(s=slots.__getitem__)),
        Fall=lambda: tuple(features),
        Fs=features.__getitem__,
    )


def run(api, nodes=(1, 2, 3, 4), **kwargs):
    return validate_nodes(api, corpus="mini", version="1.0", nodes=nodes, **kwargs)


def test_clean_selection_is_deduplicated(api):
    result = run(api, nodes=[3, 1, 3], required_features={"word": {"lemma": "str"}})
    assert result.model_dump() == {
        "corpus": "mini",
        "version": "1.0",
        "checked_nodes": 2,
        "findings": [],
    }


@pytest.mark.parametrize("node", [0, -1, 5, True, 1.5, "1"])
def test_invalid_selection_is_rejected(api, node):
    with pytest.raises(ValueError, match="Selected node"):
        run(api, nodes=[node])


def test_empty_selection_checks_nothing(api):
    assert run(api, nodes=[]).checked_nodes == 0


def test_corruption_outside_selection_is_not_reported(api):
    api.F.otype.values[4] = None
    api.Fs("lemma").values.pop(2)
    assert not run(api, nodes=[1, 3], required_features={"word": {"lemma": "str"}}).findings


@pytest.mark.parametrize("value", [None, "", " ", 7])
def test_missing_or_invalid_otype_is_unfixable(api, value):
    api.F.otype.values[3] = value
    (finding,) = run(api, nodes=[3]).findings
    assert finding.rule == "OTYPE_MISSING"
    assert finding.node_id == 3
    assert finding.node_type == "unknown"
    assert not finding.fixable
    assert "walker" in finding.unfixable_reason
    assert finding.consequence


@pytest.mark.parametrize("node,value", [(1, "paragraph"), (3, "word")])
def test_slot_type_must_match_slot_boundary(api, node, value):
    api.F.otype.values[node] = value
    assert run(api, nodes=[node]).findings[0].rule == "OTYPE_SLOT_MISMATCH"


@pytest.mark.parametrize(
    "slots,rule",
    [
        ((), "OSLOTS_EMPTY"),
        ((0,), "OSLOTS_INVALID"),
        ((3,), "OSLOTS_INVALID"),
        ((True,), "OSLOTS_INVALID"),
        ((1.5,), "OSLOTS_INVALID"),
        (None, "OSLOTS_UNREADABLE"),
    ],
)
def test_corrupt_links_require_rebuild(api, slots, rule):
    api.E.oslots.s = lambda node: slots
    (finding,) = run(api, nodes=[3]).findings
    assert finding.rule == rule
    assert not finding.fixable
    assert "walker" in finding.unfixable_reason


def test_slots_do_not_require_oslots_edges(api):
    def unexpected(node):
        raise AssertionError("Slots have no oslots edges")

    api.E.oslots.s = unexpected
    assert not run(api, nodes=[1]).findings


def test_missing_feature_is_not_an_invented_correction(api):
    api.Fs("lemma").values.pop(1)
    (finding,) = run(api, nodes=[1], required_features={"word": {"lemma": "str"}}).findings
    assert finding.rule == "FEATURE_MISSING"
    assert "lemma" in finding.message
    assert not finding.fixable
    assert "authoritative" in finding.unfixable_reason
    assert finding.suggestion_id is None


@pytest.mark.parametrize("value", ["1", True, 1.5])
def test_required_integer_is_not_coerced(api, value):
    api.Fs("number").values[3] = value
    (finding,) = run(api, nodes=[3], required_features={"paragraph": {"number": "int"}}).findings
    assert finding.rule == "FEATURE_TYPE"


def test_required_string_is_not_coerced(api):
    api.Fs("lemma").values[1] = 10
    assert (
        run(api, nodes=[1], required_features={"word": {"lemma": "str"}}).findings[0].rule
        == "FEATURE_TYPE"
    )


def test_no_universal_lemma_requirement(api):
    api.Fs("lemma").values.clear()
    assert not run(api).findings


def test_unloaded_required_feature_is_configuration_error(api):
    with pytest.raises(ValueError, match="not loaded"):
        run(api, required_features={"word": {"missing": "str"}})


def test_unknown_feature_type_is_configuration_error(api):
    with pytest.raises(ValueError, match="Unsupported"):
        run(api, required_features={"word": {"lemma": "float"}})


@pytest.mark.parametrize("loader", ["tf.fabric", "cfabric"])
def test_real_converted_corpus_is_read_only_and_valid(tmp_path, loader):
    from importlib import import_module

    from admin.converters._text_to_tf import convert_text_to_tf

    source = tmp_path / "mini.txt"
    source.write_text("First paragraph has words.\n\nSecond paragraph has words.")
    dataset = convert_text_to_tf(str(source), tmp_path / "tf")
    loaded_api = (
        import_module(loader).Fabric(locations=str(dataset), silent="deep").loadAll(silent="deep")
    )
    assert loaded_api
    # Capture after loading: loaders may compile caches, this engine must not.
    before = {p.relative_to(dataset): p.read_bytes() for p in dataset.rglob("*") if p.is_file()}
    result = run(loaded_api, nodes=range(1, loaded_api.F.otype.maxNode + 1))
    assert result.checked_nodes == loaded_api.F.otype.maxNode
    assert result.findings == []
    assert {
        p.relative_to(dataset): p.read_bytes() for p in dataset.rglob("*") if p.is_file()
    } == before

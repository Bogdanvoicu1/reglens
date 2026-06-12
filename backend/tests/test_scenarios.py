import pytest

from app.assessments.rulebook import load_rulebook
from evals.scenarios import load_scenarios


@pytest.fixture(scope="module")
def rulebook():
    return load_rulebook()


@pytest.fixture(scope="module")
def dataset():
    return load_scenarios()


def test_dataset_loads_with_enough_scenarios(dataset):
    assert dataset.version == "v1"
    assert len(dataset.scenarios) >= 20


def test_all_asserted_rules_exist(rulebook, dataset):
    known = {r.id for r in rulebook.rules}
    unknown = {
        (s.id, rule_id)
        for s in dataset.scenarios
        for rule_id in s.expected_verdicts
        if rule_id not in known
    }
    assert not unknown, f"scenarios assert unknown rules: {sorted(unknown)}"


def test_asserted_rules_have_their_gates_asserted_as_applying(rulebook, dataset):
    """Every assertion must be evaluable: the engine skips a rule unless all
    its (transitive) `requires` apply, so those gates must be asserted too."""
    requires = {r.id: r.requires for r in rulebook.rules}

    def transitive_gates(rule_id: str) -> set[str]:
        gates: set[str] = set()
        stack = list(requires[rule_id])
        while stack:
            gate = stack.pop()
            if gate not in gates:
                gates.add(gate)
                stack.extend(requires[gate])
        return gates

    violations = [
        (s.id, rule_id, gate)
        for s in dataset.scenarios
        for rule_id in s.expected_verdicts
        for gate in transitive_gates(rule_id)
        if s.expected_verdicts.get(gate) != "applies"
    ]
    assert not violations, f"asserted rules with unasserted gates: {violations}"


def test_every_rule_has_positive_and_negative_coverage(rulebook, dataset):
    """The A4 per-rule regression gate needs at least one scenario where each
    rule applies and one where it does not."""
    positives = {r.id: 0 for r in rulebook.rules}
    negatives = {r.id: 0 for r in rulebook.rules}
    for scenario in dataset.scenarios:
        for rule_id, verdict in scenario.expected_verdicts.items():
            counter = positives if verdict == "applies" else negatives
            counter[rule_id] += 1

    missing_pos = sorted(r for r, n in positives.items() if n == 0)
    missing_neg = sorted(r for r, n in negatives.items() if n == 0)
    assert not missing_pos, f"rules without a positive scenario: {missing_pos}"
    assert not missing_neg, f"rules without a negative scenario: {missing_neg}"


def test_every_blocker_rule_has_a_dedicated_positive(rulebook, dataset):
    """Blocker detection is the hard safety gate; each prohibited practice
    needs its own triggering scenario, not just shared negatives."""
    blockers = [r.id for r in rulebook.rules if r.on_applies.severity == "blocker"]
    for rule_id in blockers:
        hits = [s.id for s in dataset.scenarios if s.expected_verdicts.get(rule_id) == "applies"]
        assert hits, f"no scenario triggers blocker rule {rule_id}"

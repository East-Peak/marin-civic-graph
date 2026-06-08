import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from verify_phase0_consolidation import assert_no_legacy_labels


def test_legacy_labels_rejected():
    with pytest.raises(AssertionError, match="legacy label"):
        assert_no_legacy_labels([{"id": "actor-x", "labels": ["Actor"], "props": {}}])


def test_settled_labels_ok():
    assert_no_legacy_labels([{"id": "person-x", "labels": ["Person"], "props": {}}])


@pytest.mark.parametrize("legacy", ["Actor", "Institution",
                                    "EconomicInterestDisclosure", "CaseParticipation"])
def test_each_legacy_label_rejected(legacy):
    with pytest.raises(AssertionError, match="legacy label"):
        assert_no_legacy_labels([{"id": "x", "labels": [legacy], "props": {}}])

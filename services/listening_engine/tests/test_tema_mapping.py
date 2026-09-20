"""Unit tests for the topic-slug -> pauta `tema` mapping (spec R9)."""
import pytest

from app.analysis.tema_mapping import TEMA_MAPPING_VERSION, pauta_tema_for

EXPECTED_MAPPING = {
    "security": "SEGURIDAD",
    "taxes": "ECONOMIA",
    "public_services": "INSTITUCIONAL",
    "infrastructure": "INFRAESTRUCTURA",
    "corruption": None,
    "public_administration": "INSTITUCIONAL",
    "other": None,
}


@pytest.mark.parametrize("slug, expected_tema", list(EXPECTED_MAPPING.items()))
def test_pauta_tema_for_known_slugs(slug, expected_tema):
    assert pauta_tema_for(slug) == expected_tema


def test_tema_mapping_version_is_non_empty_string():
    assert isinstance(TEMA_MAPPING_VERSION, str)
    assert TEMA_MAPPING_VERSION != ""


def test_pauta_tema_for_unknown_slug_raises_key_error():
    with pytest.raises(KeyError):
        pauta_tema_for("not_a_real_topic_slug")

"""Parser for Stark sequencing expressions.

The grammar is intentionally small and mechanical:
- ``>>`` splits ordered macro segments.
- ``&&`` splits dependent steps within a segment.
- ``||`` creates alternatives inside each dependent step.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StarkAlternative:
    actions: list[str]


@dataclass(frozen=True)
class StarkSegment:
    index: int
    texte: str
    branches: list[StarkAlternative]


@dataclass(frozen=True)
class StarkPlan:
    objectif: str
    segments: list[StarkSegment]


def parser_objectif_stark(objectif: str) -> StarkPlan:
    """Parse a raw Stark objective into executable macro segments."""
    texte = objectif.strip()
    if not texte:
        return StarkPlan(objectif=objectif, segments=[])

    segments = []
    for index, segment_texte in enumerate(_split_top_level(texte, ">>"), start=1):
        segment_texte = _strip_group(segment_texte)
        branches = []
        for branche_texte in _split_top_level(segment_texte, "&&"):
            alternatives = [
                _strip_group(alternative)
                for alternative in _split_top_level(_strip_group(branche_texte), "||")
                if _strip_group(alternative)
            ]
            if alternatives:
                branches.append(StarkAlternative(actions=alternatives))
        if branches:
            segments.append(StarkSegment(index=index, texte=segment_texte, branches=branches))

    return StarkPlan(objectif=objectif, segments=segments)


def _split_top_level(texte: str, operateur: str) -> list[str]:
    morceaux = []
    debut = 0
    profondeur = 0
    i = 0
    while i < len(texte):
        caractere = texte[i]
        if caractere == "(":
            profondeur += 1
            i += 1
            continue
        if caractere == ")":
            profondeur = max(0, profondeur - 1)
            i += 1
            continue
        if profondeur == 0 and texte.startswith(operateur, i):
            morceaux.append(texte[debut:i].strip())
            i += len(operateur)
            debut = i
            continue
        i += 1

    morceaux.append(texte[debut:].strip())
    return morceaux


def _strip_group(texte: str) -> str:
    texte = texte.strip()
    while texte.startswith("(") and texte.endswith(")") and _parentheses_wrap_all(texte):
        texte = texte[1:-1].strip()
    return texte


def _parentheses_wrap_all(texte: str) -> bool:
    profondeur = 0
    for index, caractere in enumerate(texte):
        if caractere == "(":
            profondeur += 1
        elif caractere == ")":
            profondeur -= 1
            if profondeur == 0 and index != len(texte) - 1:
                return False
        if profondeur < 0:
            return False
    return profondeur == 0

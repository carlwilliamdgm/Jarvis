"""Live tool signature inventory exposed to LLM prompts."""

from __future__ import annotations

import inspect
from dataclasses import dataclass


@dataclass(frozen=True)
class SignatureOutil:
    nom: str
    signature: str


REGLES_SIGNATURES = [
    "RÈGLE ABSOLUE : utilise EXACTEMENT les noms de paramètres ci-dessus.",
    "executer_commande → paramètre : commande (pas cmd, pas command)",
    "executer_powershell → paramètre : commande (pas cmd, pas command)",
    "noter → paramètre : note (pas contenu)",
    "memoriser_contexte / lire_contexte / oublier_contexte → paramètre categorie pour les catégories valides : profil, style, habitudes, objectifs, projets, contraintes, faits",
    "supprimer_surveillance_dossier → paramètre : watcher_id (l'identifiant numérique, pas le chemin)",
]


def _signature_callable(nom: str, fonction) -> SignatureOutil:
    try:
        signature = str(inspect.signature(fonction))
    except (TypeError, ValueError):
        signature = "(...)"
    return SignatureOutil(nom=nom, signature=f"{nom}{signature}")


def lister_signatures_outils() -> list[SignatureOutil]:
    """Return the current public tool registry as exact call signatures."""
    from taskflow.tools import OUTILS

    return [
        _signature_callable(nom, fonction)
        for nom, fonction in sorted(OUTILS.items())
    ]


def documenter_signatures_outils() -> str:
    """Return a prompt-ready, real-time list of public tool signatures."""
    lignes = [
        "Outils disponibles avec leurs signatures exactes :",
        "(Inventaire généré en temps réel depuis tools.OUTILS.)",
        "",
    ]
    lignes.extend(signature.signature for signature in lister_signatures_outils())
    lignes.extend(["", *REGLES_SIGNATURES])
    return "\n".join(lignes)

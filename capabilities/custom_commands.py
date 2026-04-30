from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


def ajouter_commande_personnalisee(nom: str, commande: str, description: str = "") -> str:
    data = normaliser_memoire(charger_memoire())
    commandes = data.get("commandes_personnalisees", {})
    commandes[nom] = {"commande": commande, "description": description}
    data["commandes_personnalisees"] = commandes
    sauvegarder_memoire(data)
    return f"Commande personnalisee enregistree : {nom}"


def lister_commandes_personnalisees() -> str:
    data = normaliser_memoire(charger_memoire())
    commandes = data.get("commandes_personnalisees", {})
    if not commandes:
        return "Aucune commande personnalisee enregistree."
    lignes = []
    for nom, config in sorted(commandes.items()):
        description = config.get("description") or config.get("commande", "")
        lignes.append(f"- {nom}: {description}")
    return "\n".join(lignes)


def executer_commande_personnalisee(nom: str) -> str:
    from tools import executer_commande

    data = normaliser_memoire(charger_memoire())
    commandes = data.get("commandes_personnalisees", {})
    config = commandes.get(nom)
    if not config:
        return f"Commande personnalisee introuvable : {nom}"
    return executer_commande(config["commande"])


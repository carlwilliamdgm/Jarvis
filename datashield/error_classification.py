"""Mechanical classification of system-level tool errors."""

from __future__ import annotations

from dataclasses import dataclass


CATEGORIES_ERREUR = {
    "acces_refuse",
    "cible_introuvable",
    "erreur_technique_outil",
    "ressource_systeme_insuffisante",
    "action_refusee_par_confirmation",
    "autre",
}


TABLE_ERREURS_SYSTEME = {
    # Microsoft System Error Codes, WinError.h.
    2: "cible_introuvable",  # ERROR_FILE_NOT_FOUND
    3: "cible_introuvable",  # ERROR_PATH_NOT_FOUND
    5: "acces_refuse",  # ERROR_ACCESS_DENIED
    15: "cible_introuvable",  # ERROR_INVALID_DRIVE
    21: "ressource_systeme_insuffisante",  # ERROR_NOT_READY
    32: "ressource_systeme_insuffisante",  # ERROR_SHARING_VIOLATION
    33: "ressource_systeme_insuffisante",  # ERROR_LOCK_VIOLATION
    39: "ressource_systeme_insuffisante",  # ERROR_HANDLE_DISK_FULL
    50: "autre",  # ERROR_NOT_SUPPORTED
    51: "cible_introuvable",  # ERROR_REM_NOT_LIST
    53: "cible_introuvable",  # ERROR_BAD_NETPATH
    54: "ressource_systeme_insuffisante",  # ERROR_NETWORK_BUSY
    55: "cible_introuvable",  # ERROR_DEV_NOT_EXIST
    58: "ressource_systeme_insuffisante",  # ERROR_BAD_NET_RESP
    59: "ressource_systeme_insuffisante",  # ERROR_UNEXP_NET_ERR
    64: "cible_introuvable",  # ERROR_NETNAME_DELETED
    65: "acces_refuse",  # ERROR_NETWORK_ACCESS_DENIED
    67: "cible_introuvable",  # ERROR_BAD_NET_NAME
    80: "autre",  # ERROR_FILE_EXISTS
    82: "acces_refuse",  # ERROR_CANNOT_MAKE
    87: "autre",  # ERROR_INVALID_PARAMETER
    88: "ressource_systeme_insuffisante",  # ERROR_NET_WRITE_FAULT
    108: "ressource_systeme_insuffisante",  # ERROR_DRIVE_LOCKED
    110: "cible_introuvable",  # ERROR_OPEN_FAILED
    111: "cible_introuvable",  # ERROR_BUFFER_OVERFLOW: filename too long
    112: "ressource_systeme_insuffisante",  # ERROR_DISK_FULL
    123: "cible_introuvable",  # ERROR_INVALID_NAME
    145: "ressource_systeme_insuffisante",  # ERROR_DIR_NOT_EMPTY
    148: "ressource_systeme_insuffisante",  # ERROR_PATH_BUSY
    206: "cible_introuvable",  # ERROR_FILENAME_EXCED_RANGE
    220: "ressource_systeme_insuffisante",  # ERROR_FILE_CHECKED_OUT
    267: "cible_introuvable",  # ERROR_DIRECTORY
    303: "ressource_systeme_insuffisante",  # ERROR_DELETE_PENDING
}


@dataclass(frozen=True)
class ResultatOutil:
    """String-compatible tool result carrying structured error metadata."""

    message: str
    erreur: bool = False
    categorie_erreur: str | None = None
    code_brut: int | None = None

    def __str__(self) -> str:
        return self.message


def extraire_code_erreur(exception_ou_code) -> int | None:
    if isinstance(exception_ou_code, int):
        return exception_ou_code
    if isinstance(exception_ou_code, ResultatOutil):
        return exception_ou_code.code_brut
    for attribut in ("winerror", "errno"):
        valeur = getattr(exception_ou_code, attribut, None)
        if isinstance(valeur, int):
            return valeur
    return None


def classifier_erreur_systeme(exception_ou_code) -> str:
    if isinstance(exception_ou_code, ResultatOutil) and exception_ou_code.categorie_erreur:
        return exception_ou_code.categorie_erreur
    categorie = getattr(exception_ou_code, "error_category", None)
    if categorie in CATEGORIES_ERREUR:
        return categorie
    code = extraire_code_erreur(exception_ou_code)
    return TABLE_ERREURS_SYSTEME.get(code, "autre")


def resultat_erreur(message: str, exception_ou_code=None, categorie: str | None = None) -> ResultatOutil:
    code = extraire_code_erreur(exception_ou_code)
    categorie_finale = categorie or classifier_erreur_systeme(exception_ou_code)
    if categorie_finale not in CATEGORIES_ERREUR:
        categorie_finale = "autre"
    return ResultatOutil(
        message=message,
        erreur=True,
        categorie_erreur=categorie_finale,
        code_brut=code,
    )

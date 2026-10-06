"""Lanceur silencieux Windows sans fenêtre console pour GreatOS."""

import greatos_service

if __name__ == "__main__":
    greatos_service.demarrer_service(silencieux=True)

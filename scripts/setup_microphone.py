"""Script interactif de sélection et de test du microphone pour Jarvis.

Usage :
    .venv\\Scripts\\python.exe scripts\\setup_microphone.py

Ce script :
1. Liste tous les périphériques d'entrée disponibles avec un test d'amplitude.
2. Permet de choisir le meilleur microphone de façon interactive.
3. Écrit ``JARVIS_AUDIO_INPUT_DEVICE=<id>`` dans le fichier ``.env`` du projet.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Charger .env existant sans écraser les variables déjà définies
_env_path = PROJECT_ROOT / ".env"


def _load_env() -> dict[str, str]:
    """Lit le fichier .env et retourne un dict clé→valeur."""
    env: dict[str, str] = {}
    if _env_path.is_file():
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    """Réécrit le fichier .env complet à partir du dict."""
    lines = [f"{k}={v}" for k, v in env.items()]
    _env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _test_device(device_id: int, duration_sec: float = 1.5) -> tuple[int, float]:
    """Enregistre `duration_sec` secondes et retourne (amplitude_max, amplitude_moy)."""
    import numpy as np
    import sounddevice as sd

    n_samples = int(16_000 * duration_sec)
    try:
        with sd.RawInputStream(
            device=device_id, samplerate=16_000, dtype="int16", channels=1
        ) as stream:
            data, _ = stream.read(n_samples)
        samples = abs_samples = __import__("numpy").frombuffer(bytes(data), dtype=np.int16)
        amp_max = int(np.max(np.abs(samples)))
        amp_mean = float(np.mean(np.abs(samples)))
        return amp_max, amp_mean
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def _is_bluetooth(name: str) -> bool:
    BT_KW = ("bluetooth", "hands-free", "casque", "hf audio", "bthhfenum", "headset")
    return any(kw in name.lower() for kw in BT_KW)


def main() -> None:
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        print("❌ sounddevice ou numpy manquant. Installez les dépendances d'abord.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  SÉLECTION DU MICROPHONE — Jarvis GreatOS")
    print("=" * 60)

    devices = sd.query_devices()
    input_devices = [
        (i, dev) for i, dev in enumerate(devices) if dev["max_input_channels"] > 0
    ]

    if not input_devices:
        print("❌ Aucun périphérique d'entrée détecté.")
        sys.exit(1)

    print(f"\n{len(input_devices)} périphérique(s) d'entrée détecté(s). Test en cours...\n")

    results: list[tuple[int, str, int, float, bool]] = []  # id, name, amp_max, amp_mean, is_bt

    for device_id, dev in input_devices:
        name = dev["name"]
        is_bt = _is_bluetooth(name)
        bt_tag = " [BLUETOOTH ⚠]" if is_bt else ""
        print(f"  Test ID {device_id:2d}: {name}{bt_tag} ...", end=" ", flush=True)
        try:
            amp_max, amp_mean = _test_device(device_id, duration_sec=1.0)
            status = "✓" if amp_max > 200 else "⚠"
            print(f"{status}  max={amp_max:6d}  moy={amp_mean:7.1f}")
            results.append((device_id, name, amp_max, amp_mean, is_bt))
        except RuntimeError as exc:
            print(f"✗  Erreur: {exc}")
            results.append((device_id, name, 0, 0.0, is_bt))

    # Classer : non-BT d'abord, puis par amplitude max décroissante
    results.sort(key=lambda r: (r[4], -r[2]))

    print("\n" + "-" * 60)
    print("  RÉSUMÉ (classé par recommandation)")
    print("-" * 60)
    for rank, (did, name, amp_max, amp_mean, is_bt) in enumerate(results):
        bt_tag = " [BLUETOOTH ⚠]" if is_bt else ""
        quality = "🟢 Excellent" if amp_max > 1000 else ("🟡 Faible" if amp_max > 100 else "🔴 Inutilisable")
        print(f"  {rank+1:2d}. ID {did:2d} — {name}{bt_tag}")
        print(f"       {quality}  (amp_max={amp_max}, amp_moy={amp_mean:.1f})")

    print()

    # Lecture du choix
    current_env = _load_env()
    current_device = current_env.get("JARVIS_AUDIO_INPUT_DEVICE", "")
    if current_device:
        print(f"  Périphérique actuel dans .env : ID {current_device}")

    recommended = results[0][0] if results else None
    prompt = f"  Entrez l'ID à utiliser [{recommended}] (Entrée = recommandé, 'n' = ne pas modifier) : "

    try:
        choice = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAnnulé.")
        return

    if choice.lower() == "n":
        print("  .env inchangé.")
        return

    if not choice and recommended is not None:
        chosen_id = recommended
    else:
        try:
            chosen_id = int(choice)
        except ValueError:
            print("  Choix invalide. .env inchangé.")
            return

    # Vérifier que l'ID est valide
    valid_ids = [r[0] for r in results]
    if chosen_id not in valid_ids:
        print(f"  ❌ ID {chosen_id} inconnu. .env inchangé.")
        return

    # Écrire dans .env
    chosen_name = next(r[1] for r in results if r[0] == chosen_id)
    current_env["JARVIS_AUDIO_INPUT_DEVICE"] = str(chosen_id)
    _write_env(current_env)

    print(f"\n  ✅ Microphone sélectionné : ID {chosen_id} — {chosen_name}")
    print(f"  ✅ JARVIS_AUDIO_INPUT_DEVICE={chosen_id} écrit dans {_env_path}")
    print("\n  Redémarrez Jarvis pour appliquer le changement.\n")


if __name__ == "__main__":
    main()

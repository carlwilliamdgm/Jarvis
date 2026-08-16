"""Email Integration - Intégration avec les emails via Outlook."""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import subprocess
import json

from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire


def obtenir_emails_non_lus(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Obtient les emails non lus via Outlook.
    
    Args:
        limit: Nombre maximum d'emails à récupérer
        
    Returns:
        Liste des emails non lus
    """
    try:
        commande = f"""
        $ErrorActionPreference = SilentlyContinue
        try {{
            $outlook = New-Object -ComObject Outlook.Application
            $inbox = $outlook.Session.GetDefaultFolder(6) # 6 = olFolderInbox
            $items = $inbox.Items
            $items.Sort("[ReceivedTime]", $true)
            $unread = $items.Restrict("[UnRead] = true")
            
            $emails = @()
            $count = 0
            foreach ($item in $unread) {{
                if ($count -ge {limit}) {{ break }}
                $emails += @{{
                    Subject = $item.Subject
                    Sender = $item.SenderEmailAddress
                    SenderName = $item.SenderName
                    ReceivedTime = $item.ReceivedTime.ToString('s')
                    Body = $item.Body -replace '\\r\\n', ' ' -replace '\\s+', ' '
                    Importance = $item.Importance
                    Attachments = $item.Attachments.Count
                }}
                $count++
            }}
            
            ConvertTo-Json -Compress -InputObject $emails
        }} catch {{
            Write-Output "[]"
        }}
        """
        
        resultat = subprocess.run(
            ["powershell", "-Command", commande],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if resultat.returncode == 0 and resultat.stdout.strip():
            try:
                emails = json.loads(resultat.stdout)
                if isinstance(emails, list):
                    return [_normaliser_email(e) for e in emails]
            except json.JSONDecodeError:
                pass
                
    except Exception:
        pass
    
    return [{"erreur": "Impossible d'accéder aux emails (Outlook non disponible)"}]


def _normaliser_email(email: Dict) -> Dict[str, Any]:
    """Normalise un email."""
    return {
        "sujet": email.get("Subject", "Sans sujet"),
        "expediteur": email.get("Sender", ""),
        "nom_expediteur": email.get("SenderName", ""),
        "date_reception": email.get("ReceivedTime", ""),
        "corps": email.get("Body", "")[:500],
        "importance": email.get("Importance", "normal"),
        "pieces_jointes": email.get("Attachments", 0)
    }


def obtenir_emails_recents(heures: int = 24, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Obtient les emails récents des N dernières heures.
    
    Args:
        heures: Nombre d'heures à analyser
        limit: Nombre maximum d'emails
        
    Returns:
        Liste des emails récents
    """
    try:
        commande = f"""
        $ErrorActionPreference = SilentlyContinue
        try {{
            $outlook = New-Object -ComObject Outlook.Application
            $inbox = $outlook.Session.GetDefaultFolder(6)
            $items = $inbox.Items
            $items.Sort("[ReceivedTime]", $true)
            
            $cutoff = (Get-Date).AddHours(-{heures})
            $recent = $items.Restrict("[ReceivedTime] >= '$($cutoff.ToString('s'))'")
            
            $emails = @()
            $count = 0
            foreach ($item in $recent) {{
                if ($count -ge {limit}) {{ break }}
                $emails += @{{
                    Subject = $item.Subject
                    Sender = $item.SenderEmailAddress
                    SenderName = $item.SenderName
                    ReceivedTime = $item.ReceivedTime.ToString('s')
                    Body = $item.Body -replace '\\r\\n', ' ' -replace '\\s+', ' '
                    Importance = $item.Importance
                    UnRead = $item.UnRead
                }}
                $count++
            }}
            
            ConvertTo-Json -Compress -InputObject $emails
        }} catch {{
            Write-Output "[]"
        }}
        """
        
        resultat = subprocess.run(
            ["powershell", "-Command", commande],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if resultat.returncode == 0 and resultat.stdout.strip():
            try:
                emails = json.loads(resultat.stdout)
                if isinstance(emails, list):
                    return [_normaliser_email(e) for e in emails]
            except json.JSONDecodeError:
                pass
                
    except Exception:
        pass
    
    return []


def formater_emails(emails: List[Dict[str, Any]]) -> str:
    """
    Formate les emails pour affichage.
    
    Returns:
        Description textuelle des emails
    """
    if not emails or ("erreur" in emails[0]):
        return "Aucun email disponible ou erreur d'accès."
    
    lignes = [f"=== EMAILS ({len(emails)}) ==="]
    
    for i, email in enumerate(emails, 1):
        importance_emoji = {
            "high": "🔴",
            "low": "🟢"
        }.get(email.get("importance"), "")
        
        lignes.append(f"\n{i}. {importance_emoji} {email.get('sujet', 'Sans sujet')}")
        lignes.append(f"   De : {email.get('nom_expediteur', email.get('expediteur', 'Inconnu'))}")
        
        date = email.get("date_reception", "")
        if date:
            try:
                dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                lignes.append(f"   {dt.strftime('%d/%m %H:%M')}")
            except (ValueError, TypeError):
                lignes.append(f"   {date}")
        
        if email.get("pieces_jointes", 0) > 0:
            lignes.append(f"   📎 {email['pieces_jointes']} pièce(s) jointe(s)")
    
    return "\n".join(lignes)


def detecter_emails_urgents() -> List[Dict[str, Any]]:
    """
    Détecte les emails urgents (importance haute ou mots-clés).
    
    Returns:
        Liste des emails urgents
    """
    emails = obtenir_emails_non_lus(50)
    
    mots_cles_urgence = ["urgent", "important", "critique", "urgence", "asap", "immédiat"]
    emails_urgents = []
    
    for email in emails:
        if "erreur" in email:
            continue
            
        # Vérifier l'importance
        if email.get("importance") == "high":
            emails_urgents.append({**email, "raison": "importance haute"})
            continue
        
        # Vérifier les mots-clés dans le sujet
        sujet = email.get("sujet", "").lower()
        if any(mot in sujet for mot in mots_cles_urgence):
            emails_urgents.append({**email, "raison": "mot-clé détecté"})
    
    return emails_urgents


def analyser_patterns_email(heures: int = 168) -> Dict[str, Any]:
    """
    Analyse les patterns d'emails sur une semaine.
    
    Args:
        heures: Nombre d'heures à analyser (défaut: 1 semaine)
        
    Returns:
        Analyse des patterns détectés
    """
    emails = obtenir_emails_recents(heures, limit=200)
    
    if not emails or ("erreur" in emails[0]):
        return {"message": "Pas assez de données pour analyser les patterns"}
    
    # Analyser les expéditeurs fréquents
    expediteurs = {}
    for email in emails:
        expediteur = email.get("expediteur", "")
        if expediteur:
            expediteurs[expediteur] = expediteurs.get(expediteur, 0) + 1
    
    top_expediteurs = sorted(exppediteurs.items(), key=lambda x: -x[1])[:5]
    
    # Analyser les horaires de réception
    horaires = {}
    for email in emails:
        date_str = email.get("date_reception", "")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                heure = dt.hour
                horaires[heure] = horaires.get(heure, 0) + 1
            except (ValueError, TypeError):
                continue
    
    top_horaires = sorted(horaires.items(), key=lambda x: -x[1])[:5]
    
    # Analyser les sujets fréquents
    sujets = {}
    for email in emails:
        sujet = email.get("sujet", "").lower()
        if sujet:
            # Extraire les mots-clés principaux
            mots = [mot for mot in sujet.split() if len(mot) > 3]
            for mot in mots[:3]:
                sujets[mot] = sujets.get(mot, 0) + 1
    
    top_sujets = sorted(sujets.items(), key=lambda x: -x[1])[:5]
    
    return {
        "periode_analysee": f"{heures} heures",
        "total_emails": len(emails),
        "top_expediteurs": [{"email": e, "count": c} for e, c in top_expediteurs],
        "top_horaires": [{"heure": h, "count": c} for h, c in top_horaires],
        "top_sujets": [{"mot": s, "count": c} for s, c in top_sujets]
    }


def envoyer_notification_email_urgent(email: Dict[str, Any]) -> str:
    """
    Envoie une notification pour un email urgent.
    
    Args:
        email: L'email urgent
        
    Returns:
        Résultat de la notification
    """
    from capabilities import storage
    
    titre = f"📧 Email urgent : {email.get('sujet', 'Sans sujet')}"
    message = f"De : {email.get('nom_expediteur', 'Inconnu')}\n{email.get('corps', '')[:200]}"
    
    storage.notifier(titre=titre, message=message, urgence=True)
    
    return f"Notification envoyée pour email urgent : {email.get('sujet', 'Sans sujet')}"


def synchroniser_emails_jarvis() -> str:
    """
    Synchronise les emails avec la mémoire Jarvis.
    
    Returns:
        Résultat de la synchronisation
    """
    emails = obtenir_emails_recents(24, limit=100)
    
    if not emails or ("erreur" in emails[0]):
        return "Aucun email à synchroniser."
    
    data = normaliser_memoire(charger_memoire())
    data["emails_recents"] = emails
    data["derniere_sync_emails"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sauvegarder_memoire(data)
    
    return f"Synchronisé : {len(emails)} emails récents"


def obtenir_resume_emails() -> str:
    """
    Obtient un résumé de la situation email.
    
    Returns:
        Résumé textuel
    """
    non_lus = obtenir_emails_non_lus(10)
    urgents = detecter_emails_urgents()
    patterns = analyser_patterns_email(24)
    
    lignes = ["=== RÉSUMÉ EMAILS ==="]
    
    if non_lus and "erreur" not in non_lus[0]:
        lignes.append(f"\n📬 Non lus : {len(non_lus)}")
    
    if urgents and "erreur" not in urgents[0]:
        lignes.append(f"\n🔴 Urgents : {len(urgents)}")
        for email in urgents[:3]:
            lignes.append(f"   - {email.get('sujet', 'Sans sujet')}")
    
    if "message" not in patterns:
        lignes.append(f"\n📊 24 dernières heures : {patterns.get('total_emails', 0)} emails")
        
        top_exp = patterns.get("top_expediteurs", [])
        if top_exp:
            lignes.append("   Top expéditeurs :")
            for exp in top_exp[:3]:
                lignes.append(f"     {exp['email'][:30]} : {exp['count']}")
    
    return "\n".join(lignes)

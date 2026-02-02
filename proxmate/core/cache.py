"""Gestionnaire de cache pour ProxMate."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from dataclasses import asdict

from proxmate.core.config import CONFIG_DIR


# Répertoire de cache
CACHE_DIR = CONFIG_DIR / "cache"

# TTL du cache en secondes (60s par défaut)
CACHE_TTL_SECONDS = 60


def _ensure_cache_dir(context: str) -> Path:
    """Crée le répertoire de cache pour un contexte s'il n'existe pas."""
    cache_path = CACHE_DIR / context
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


def _get_cache_file(context: str, cache_type: str) -> Path:
    """Retourne le chemin du fichier de cache pour un type donné."""
    return _ensure_cache_dir(context) / f"{cache_type}.json"


def _get_meta_file(context: str) -> Path:
    """Retourne le chemin du fichier de métadonnées du cache."""
    return _ensure_cache_dir(context) / "meta.json"


def _load_meta(context: str) -> dict[str, str]:
    """Charge les métadonnées du cache (timestamps)."""
    meta_file = _get_meta_file(context)
    if not meta_file.exists():
        return {}
    try:
        with open(meta_file, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_meta(context: str, meta: dict[str, str]) -> None:
    """Sauvegarde les métadonnées du cache."""
    meta_file = _get_meta_file(context)
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)


def _update_meta_timestamp(context: str, cache_type: str) -> None:
    """Met à jour le timestamp d'un type de cache."""
    meta = _load_meta(context)
    meta[cache_type] = datetime.now().isoformat()
    _save_meta(context, meta)


def get_cache_timestamp(context: str, cache_type: str) -> Optional[datetime]:
    """Récupère le timestamp du dernier refresh pour un type de cache."""
    meta = _load_meta(context)
    if cache_type not in meta:
        return None
    try:
        return datetime.fromisoformat(meta[cache_type])
    except Exception:
        return None


def get_cache_age_seconds(context: str, cache_type: str) -> Optional[float]:
    """Retourne l'âge du cache en secondes, ou None si pas de cache."""
    timestamp = get_cache_timestamp(context, cache_type)
    if timestamp is None:
        return None
    return (datetime.now() - timestamp).total_seconds()


def is_cache_valid(context: str, cache_type: str, max_age_seconds: int = CACHE_TTL_SECONDS) -> bool:
    """Vérifie si le cache est valide (existe et pas trop vieux)."""
    age = get_cache_age_seconds(context, cache_type)
    if age is None:
        return False
    return age <= max_age_seconds


def format_cache_age(context: str, cache_type: str) -> str:
    """Formate l'âge du cache pour affichage (ex: 'il y a 12s')."""
    age = get_cache_age_seconds(context, cache_type)
    if age is None:
        return "pas de cache"
    
    if age < 60:
        return f"il y a {int(age)}s"
    elif age < 3600:
        minutes = int(age / 60)
        return f"il y a {minutes}min"
    else:
        hours = int(age / 3600)
        return f"il y a {hours}h"


# =============================================================================
# Fonctions de lecture/écriture du cache
# =============================================================================

def set_cache(context: str, cache_type: str, data: list[Any]) -> None:
    """Sauvegarde des données dans le cache."""
    cache_file = _get_cache_file(context, cache_type)
    
    # Convertir les dataclasses en dicts
    serializable_data = []
    for item in data:
        if hasattr(item, "__dataclass_fields__"):
            serializable_data.append(asdict(item))
        elif isinstance(item, dict):
            serializable_data.append(item)
        else:
            serializable_data.append(item)
    
    with open(cache_file, "w") as f:
        json.dump(serializable_data, f, indent=2)
    
    _update_meta_timestamp(context, cache_type)


def get_cache(context: str, cache_type: str) -> Optional[list[dict]]:
    """Récupère les données du cache (brutes, en dict)."""
    cache_file = _get_cache_file(context, cache_type)
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r") as f:
            return json.load(f)
    except Exception:
        return None


def invalidate_cache(context: str, cache_type: Optional[str] = None) -> None:
    """Invalide le cache (un type spécifique ou tout le contexte)."""
    if cache_type:
        # Invalider un seul type
        cache_file = _get_cache_file(context, cache_type)
        if cache_file.exists():
            os.remove(cache_file)
        meta = _load_meta(context)
        if cache_type in meta:
            del meta[cache_type]
            _save_meta(context, meta)
    else:
        # Invalider tout le contexte
        cache_path = CACHE_DIR / context
        if cache_path.exists():
            import shutil
            shutil.rmtree(cache_path)


def get_cache_info(context: str) -> dict[str, Optional[datetime]]:
    """Récupère les infos de cache pour un contexte (timestamps par type)."""
    meta = _load_meta(context)
    result = {}
    for cache_type in ["vms", "templates", "nodes", "storages"]:
        if cache_type in meta:
            try:
                result[cache_type] = datetime.fromisoformat(meta[cache_type])
            except Exception:
                result[cache_type] = None
        else:
            result[cache_type] = None
    return result


def list_cached_contexts() -> list[str]:
    """Liste tous les contextes ayant un cache."""
    if not CACHE_DIR.exists():
        return []
    return [d.name for d in CACHE_DIR.iterdir() if d.is_dir()]


# =============================================================================
# Fonctions typées pour VMs, Templates, Nodes, Storages
# =============================================================================

def set_vms_cache(context: str, vms: list) -> None:
    """Sauvegarde le cache des VMs."""
    set_cache(context, "vms", vms)


def get_vms_cache(context: str) -> tuple[Optional[list[dict]], Optional[datetime]]:
    """Récupère le cache des VMs avec son timestamp."""
    data = get_cache(context, "vms")
    timestamp = get_cache_timestamp(context, "vms")
    return data, timestamp


def set_templates_cache(context: str, templates: list) -> None:
    """Sauvegarde le cache des templates."""
    set_cache(context, "templates", templates)


def get_templates_cache(context: str) -> tuple[Optional[list[dict]], Optional[datetime]]:
    """Récupère le cache des templates avec son timestamp."""
    data = get_cache(context, "templates")
    timestamp = get_cache_timestamp(context, "templates")
    return data, timestamp


def set_nodes_cache(context: str, nodes: list) -> None:
    """Sauvegarde le cache des nodes."""
    set_cache(context, "nodes", nodes)


def get_nodes_cache(context: str) -> tuple[Optional[list[dict]], Optional[datetime]]:
    """Récupère le cache des nodes avec son timestamp."""
    data = get_cache(context, "nodes")
    timestamp = get_cache_timestamp(context, "nodes")
    return data, timestamp


def set_storages_cache(context: str, storages: list) -> None:
    """Sauvegarde le cache des storages."""
    set_cache(context, "storages", storages)


def get_storages_cache(context: str) -> tuple[Optional[list[dict]], Optional[datetime]]:
    """Récupère le cache des storages avec son timestamp."""
    data = get_cache(context, "storages")
    timestamp = get_cache_timestamp(context, "storages")
    return data, timestamp


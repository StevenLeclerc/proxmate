"""Configuration management for ProxMate."""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ContextConfig(BaseModel):
    """Configuration d'un contexte (cluster Proxmox)."""

    host: str = Field(..., description="Adresse du serveur Proxmox (ex: 192.168.1.100)")
    port: int = Field(default=8006, description="Port de l'API Proxmox")
    user: str = Field(..., description="Utilisateur API (ex: root@pam ou user@pve)")
    token_name: str = Field(..., description="Nom du token API")
    token_value: str = Field(..., description="Valeur secrète du token API")
    verify_ssl: bool = Field(default=False, description="Vérifier le certificat SSL")
    default_node: Optional[str] = Field(default=None, description="Node par défaut")
    default_storage: str = Field(default="local-lvm", description="Storage par défaut")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Date de création")


# Alias pour rétrocompatibilité
ProxmoxConfig = ContextConfig


class VMCreationInfo(BaseModel):
    """Informations sur une VM créée par ProxMate."""

    vmid: int = Field(..., description="VMID de la VM")
    name: str = Field(..., description="Nom de la VM")
    node: str = Field(..., description="Node Proxmox où la VM est créée")
    user: str = Field(..., description="Utilisateur SSH configuré")
    ssh_public_key_path: Optional[str] = Field(default=None, description="Chemin vers la clé publique SSH utilisée")
    ip: Optional[str] = Field(default=None, description="Adresse IP (si statique)")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Date de création")


class AppConfig(BaseModel):
    """Configuration globale de l'application."""

    # Nouveau format multi-contextes
    current_context: Optional[str] = Field(default=None, description="Nom du contexte actif")
    contexts: dict[str, ContextConfig] = Field(default_factory=dict, description="Liste des contextes")

    # Ancien format (rétrocompatibilité) - sera migré vers contexts
    proxmox: Optional[ContextConfig] = None

    # Paramètres globaux
    ssh_public_key_path: str = Field(default="~/.ssh/id_rsa.pub")
    default_user: str = Field(default="ubuntu")
    template_vmid_start: int = Field(default=9000, description="VMID de départ pour les templates")


CONFIG_DIR = Path.home() / ".proxmate"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def ensure_config_dir() -> Path:
    """Crée le répertoire de configuration s'il n'existe pas."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def load_config() -> Optional[AppConfig]:
    """Charge la configuration depuis le fichier YAML."""
    if not CONFIG_FILE.exists():
        return None

    try:
        with open(CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f)
            if data is None:
                return None
            config = AppConfig(**data)

            # Migration automatique de l'ancien format vers le nouveau
            config = _migrate_config_if_needed(config)

            return config
    except Exception as e:
        raise ValueError(f"Erreur lors du chargement de la configuration: {e}")


def _migrate_config_if_needed(config: AppConfig) -> AppConfig:
    """Migre l'ancien format de config vers le nouveau format multi-contextes."""
    # Si on a l'ancien format (proxmox sans contexts) → migrer
    if config.proxmox is not None and not config.contexts:
        # Créer un contexte "default" à partir de l'ancienne config
        default_context = ContextConfig(
            host=config.proxmox.host,
            port=config.proxmox.port,
            user=config.proxmox.user,
            token_name=config.proxmox.token_name,
            token_value=config.proxmox.token_value,
            verify_ssl=config.proxmox.verify_ssl,
            default_node=config.proxmox.default_node,
            default_storage=config.proxmox.default_storage,
            created_at=datetime.now().isoformat(),
        )
        config.contexts = {"default": default_context}
        config.current_context = "default"
        config.proxmox = None  # Supprimer l'ancien format

        # Sauvegarder la migration
        save_config(config)

    return config


def save_config(config: AppConfig) -> None:
    """Sauvegarde la configuration dans le fichier YAML."""
    ensure_config_dir()

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config.model_dump(exclude_none=True), f, default_flow_style=False, allow_unicode=True)

    # Sécuriser le fichier (contient des secrets)
    os.chmod(CONFIG_FILE, 0o600)


def is_configured() -> bool:
    """Vérifie si ProxMate est configuré avec au moins un contexte."""
    config = load_config()
    if config is None:
        return False
    # Nouveau format: au moins un contexte
    if config.contexts and config.current_context:
        return True
    # Ancien format: proxmox configuré
    if config.proxmox is not None:
        return True
    return False


def get_config() -> AppConfig:
    """Récupère la configuration ou lève une erreur si non configurée."""
    config = load_config()
    if config is None:
        raise ValueError(
            "ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord."
        )
    if not config.contexts and config.proxmox is None:
        raise ValueError(
            "ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord."
        )
    return config


def get_current_context() -> Optional[ContextConfig]:
    """Récupère la configuration du contexte actif."""
    config = load_config()
    if config is None:
        return None

    if config.current_context and config.current_context in config.contexts:
        return config.contexts[config.current_context]

    # Rétrocompatibilité
    if config.proxmox:
        return config.proxmox

    return None


def get_current_context_name() -> Optional[str]:
    """Récupère le nom du contexte actif."""
    config = load_config()
    if config is None:
        return None
    return config.current_context


def list_contexts() -> dict[str, ContextConfig]:
    """Liste tous les contextes disponibles."""
    config = load_config()
    if config is None:
        return {}
    return config.contexts


def set_context(name: str) -> bool:
    """Change le contexte actif. Retourne True si succès."""
    config = load_config()
    if config is None:
        return False

    if name not in config.contexts:
        return False

    config.current_context = name
    save_config(config)
    return True


def add_context(name: str, context: ContextConfig) -> None:
    """Ajoute un nouveau contexte."""
    config = load_config()
    if config is None:
        config = AppConfig()

    config.contexts[name] = context

    # Si c'est le premier contexte, le définir comme actif
    if config.current_context is None:
        config.current_context = name

    save_config(config)


def remove_context(name: str) -> bool:
    """Supprime un contexte. Retourne True si succès."""
    config = load_config()
    if config is None:
        return False

    if name not in config.contexts:
        return False

    del config.contexts[name]

    # Si c'était le contexte actif, changer vers le premier disponible
    if config.current_context == name:
        if config.contexts:
            config.current_context = next(iter(config.contexts))
        else:
            config.current_context = None

    save_config(config)
    return True


def context_exists(name: str) -> bool:
    """Vérifie si un contexte existe."""
    config = load_config()
    if config is None:
        return False
    return name in config.contexts


# ============================================================================
# Gestion des VMs créées par ProxMate
# ============================================================================

VMS_FILE = CONFIG_DIR / "vms.yaml"


def load_created_vms() -> dict[int, VMCreationInfo]:
    """Charge la liste des VMs créées par ProxMate."""
    if not VMS_FILE.exists():
        return {}

    try:
        with open(VMS_FILE, "r") as f:
            data = yaml.safe_load(f)
            if data is None or "vms" not in data:
                return {}
            return {
                int(vmid): VMCreationInfo(**info)
                for vmid, info in data["vms"].items()
            }
    except Exception:
        return {}


def save_created_vm(vm_info: VMCreationInfo) -> None:
    """Sauvegarde les infos d'une VM créée."""
    ensure_config_dir()

    # Charger les VMs existantes
    vms = load_created_vms()

    # Ajouter/mettre à jour la VM
    vms[vm_info.vmid] = vm_info

    # Sauvegarder
    data = {
        "vms": {
            vmid: info.model_dump()
            for vmid, info in vms.items()
        }
    }

    with open(VMS_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def remove_created_vm(vmid: int) -> bool:
    """Supprime une VM de la liste des VMs créées."""
    vms = load_created_vms()
    if vmid in vms:
        del vms[vmid]
        data = {
            "vms": {
                vid: info.model_dump()
                for vid, info in vms.items()
            }
        }
        with open(VMS_FILE, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        return True
    return False


def get_created_vm(vmid: int) -> Optional[VMCreationInfo]:
    """Récupère les infos d'une VM créée par ProxMate."""
    vms = load_created_vms()
    return vms.get(vmid)

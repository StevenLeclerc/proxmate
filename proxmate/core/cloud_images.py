"""Gestion des images cloud Ubuntu pour ProxMate."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import requests

from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn

from proxmate.core.config import CONFIG_DIR


# Répertoire de cache pour les images
CACHE_DIR = CONFIG_DIR / "cache"


@dataclass
class CloudImage:
    """Définition d'une image cloud."""
    name: str
    version: str
    url: str
    filename: str
    description: str
    
    @property
    def cache_path(self) -> Path:
        """Chemin vers l'image en cache."""
        return CACHE_DIR / self.filename


# Images Ubuntu Cloud disponibles
CLOUD_IMAGES = {
    "ubuntu-22.04": CloudImage(
        name="Ubuntu 22.04 LTS",
        version="22.04",
        url="https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        filename="jammy-server-cloudimg-amd64.img",
        description="Ubuntu 22.04 LTS (Jammy Jellyfish) - Stable",
    ),
    "ubuntu-24.04": CloudImage(
        name="Ubuntu 24.04 LTS",
        version="24.04",
        url="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        filename="noble-server-cloudimg-amd64.img",
        description="Ubuntu 24.04 LTS (Noble Numbat) - Latest LTS",
    ),
}


def ensure_cache_dir() -> Path:
    """Crée le répertoire de cache s'il n'existe pas."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def get_available_images() -> dict[str, CloudImage]:
    """Retourne les images cloud disponibles."""
    return CLOUD_IMAGES


def is_image_cached(image: CloudImage) -> bool:
    """Vérifie si une image est déjà en cache."""
    return image.cache_path.exists()


def download_image(image: CloudImage, force: bool = False) -> Path:
    """
    Télécharge une image cloud Ubuntu.
    
    Args:
        image: L'image à télécharger
        force: Forcer le re-téléchargement même si en cache
        
    Returns:
        Le chemin vers l'image téléchargée
    """
    ensure_cache_dir()
    
    if is_image_cached(image) and not force:
        return image.cache_path
    
    # Télécharger avec barre de progression
    response = requests.get(image.url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
    ) as progress:
        task = progress.add_task(f"Téléchargement {image.name}", total=total_size)
        
        with open(image.cache_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    progress.update(task, advance=len(chunk))
    
    return image.cache_path


def get_image_size(image: CloudImage) -> Optional[int]:
    """Récupère la taille de l'image en cache (en bytes)."""
    if is_image_cached(image):
        return image.cache_path.stat().st_size
    return None


def clear_cache() -> None:
    """Supprime toutes les images en cache."""
    if CACHE_DIR.exists():
        for file in CACHE_DIR.iterdir():
            if file.is_file():
                file.unlink()


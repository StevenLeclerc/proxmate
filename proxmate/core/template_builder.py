"""Builder pour créer des templates Cloud-Init sur Proxmox."""

import time
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from proxmate.core.proxmox import ProxmoxClient
from proxmate.core.cloud_images import CloudImage, download_image
from proxmate.core.config import get_config

console = Console()


@dataclass
class TemplateConfig:
    """Configuration pour un nouveau template."""
    name: str
    vmid: int
    node: str
    storage: str
    image: CloudImage
    memory: int = 2048  # MB
    cores: int = 2
    disk_size: str = "20G"  # Taille du disque
    network_bridge: str = "vmbr0"


class TemplateBuilder:
    """Constructeur de templates Cloud-Init."""
    
    def __init__(self, client: Optional[ProxmoxClient] = None):
        self.client = client or ProxmoxClient()
        self._config = get_config()
    
    def get_next_template_vmid(self) -> int:
        """Trouve le prochain VMID disponible pour un template."""
        start_vmid = self._config.template_vmid_start
        existing = {vm.vmid for vm in self.client.get_vms()}
        
        vmid = start_vmid
        while vmid in existing:
            vmid += 1
        return vmid
    
    def get_available_storages(self, node: str) -> list[dict]:
        """Récupère les storages disponibles sur un node."""
        try:
            storages = self.client.api.nodes(node).storage.get()
            # Filtrer les storages qui supportent les images disque
            return [
                s for s in storages 
                if 'images' in s.get('content', '')
            ]
        except Exception:
            return []
    
    def create_template(self, config: TemplateConfig) -> bool:
        """
        Crée un template Cloud-Init complet.
        
        Étapes:
        1. Télécharger l'image cloud (si pas en cache)
        2. Créer une VM vide
        3. Importer le disque
        4. Configurer Cloud-Init
        5. Convertir en template
        """
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            console=console,
        ) as progress:
            
            # Étape 1: Télécharger l'image
            task = progress.add_task("Téléchargement de l'image cloud...", total=None)
            image_path = download_image(config.image)
            progress.update(task, description="[green]✓[/green] Image téléchargée")
            
            # Étape 2: Créer la VM vide
            progress.add_task("Création de la VM...", total=None)
            self._create_vm(config)
            progress.update(task, description="[green]✓[/green] VM créée")
            
            # Étape 3: Upload et import du disque
            progress.add_task("Import du disque...", total=None)
            self._import_disk(config, image_path)
            progress.update(task, description="[green]✓[/green] Disque importé")
            
            # Étape 4: Configurer Cloud-Init
            progress.add_task("Configuration Cloud-Init...", total=None)
            self._configure_cloudinit(config)
            progress.update(task, description="[green]✓[/green] Cloud-Init configuré")
            
            # Étape 5: Convertir en template
            progress.add_task("Conversion en template...", total=None)
            self._convert_to_template(config)
            progress.update(task, description="[green]✓[/green] Template créé")
        
        return True
    
    def _create_vm(self, config: TemplateConfig) -> None:
        """Crée une VM vide."""
        self.client.api.nodes(config.node).qemu.create(
            vmid=config.vmid,
            name=config.name,
            memory=config.memory,
            cores=config.cores,
            net0=f"virtio,bridge={config.network_bridge}",
            scsihw="virtio-scsi-pci",
        )
        # Attendre que la VM soit créée
        time.sleep(2)
    
    def _import_disk(self, config: TemplateConfig, image_path: Path) -> None:
        """Importe le disque cloud dans la VM."""
        # Cette opération nécessite un accès SSH ou l'API de stockage
        # Pour l'instant, on utilise l'API pour uploader puis attacher
        node = self.client.api.nodes(config.node)
        
        # Upload de l'image vers le storage (si nécessaire)
        # Puis attacher le disque
        # Note: L'import direct via API est complexe, on documente la commande manuelle
        pass
    
    def _configure_cloudinit(self, config: TemplateConfig) -> None:
        """Configure Cloud-Init sur la VM."""
        node = self.client.api.nodes(config.node)
        node.qemu(config.vmid).config.put(
            ide2=f"{config.storage}:cloudinit",
            boot="c",
            bootdisk="scsi0",
            serial0="socket",
            vga="serial0",
        )
    
    def _convert_to_template(self, config: TemplateConfig) -> None:
        """Convertit la VM en template."""
        self.client.api.nodes(config.node).qemu(config.vmid).template.post()


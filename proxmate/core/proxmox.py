"""Client API Proxmox pour ProxMate."""

from typing import Any, Optional
from dataclasses import dataclass

from proxmoxer import ProxmoxAPI

from proxmate.core.config import get_current_context, ContextConfig

# Alias pour rétrocompatibilité
ProxmoxConfig = ContextConfig


@dataclass
class VMInfo:
    """Informations sur une VM."""
    vmid: int
    name: str
    status: str
    node: str
    cpu: int
    maxmem: int  # en bytes
    maxdisk: int  # en bytes
    uptime: int
    template: bool = False
    ip_address: Optional[str] = None
    
    @property
    def memory_gb(self) -> float:
        """Mémoire en GB."""
        return round(self.maxmem / (1024**3), 1)
    
    @property
    def disk_gb(self) -> float:
        """Disque en GB."""
        return round(self.maxdisk / (1024**3), 1)


@dataclass
class SnapshotInfo:
    """Informations sur un snapshot de VM."""
    name: str
    description: str
    snaptime: Optional[int]  # timestamp Unix (None pour 'current')
    vmstate: bool  # True si l'état RAM est inclus
    parent: Optional[str] = None  # Snapshot parent

    @property
    def is_current(self) -> bool:
        """Vérifie si c'est le snapshot 'current' (état actuel)."""
        return self.name == "current"

    @property
    def formatted_date(self) -> str:
        """Date formatée du snapshot."""
        if self.snaptime is None:
            return "-"
        from datetime import datetime
        return datetime.fromtimestamp(self.snaptime).strftime("%Y-%m-%d %H:%M")


@dataclass
class NodeInfo:
    """Informations sur un node Proxmox."""
    node: str
    status: str
    cpu: float  # pourcentage
    maxcpu: int
    mem: int  # bytes utilisés
    maxmem: int  # bytes total
    uptime: int
    
    @property
    def memory_used_gb(self) -> float:
        return round(self.mem / (1024**3), 1)
    
    @property
    def memory_total_gb(self) -> float:
        return round(self.maxmem / (1024**3), 1)
    
    @property
    def cpu_percent(self) -> float:
        return round(self.cpu * 100, 1)


class ProxmoxClient:
    """Client pour l'API Proxmox."""

    def __init__(self, config: Optional[ContextConfig] = None):
        """Initialise le client Proxmox avec le contexte actif."""
        if config is None:
            config = get_current_context()
            if config is None:
                raise ValueError(
                    "Aucun contexte actif. Exécutez 'proxmate init' ou 'proxmate ctx create <nom>'."
                )

        self._config = config
        self._api = ProxmoxAPI(
            host=config.host,
            port=config.port,
            user=config.user,
            token_name=config.token_name,
            token_value=config.token_value,
            verify_ssl=config.verify_ssl,
        )
    
    @property
    def api(self) -> ProxmoxAPI:
        """Accès direct à l'API proxmoxer."""
        return self._api
    
    def get_nodes(self) -> list[NodeInfo]:
        """Récupère la liste des nodes du cluster."""
        nodes = self._api.nodes.get()
        return [
            NodeInfo(
                node=n["node"],
                status=n.get("status", "unknown"),
                cpu=n.get("cpu", 0),
                maxcpu=n.get("maxcpu", 0),
                mem=n.get("mem", 0),
                maxmem=n.get("maxmem", 0),
                uptime=n.get("uptime", 0),
            )
            for n in nodes
        ]
    
    def get_vms(self, node: Optional[str] = None, fetch_ips: bool = True) -> list[VMInfo]:
        """
        Récupère la liste des VMs.

        Args:
            node: Filtrer par node spécifique
            fetch_ips: Si True, récupère les IPs (plus lent). Par défaut True.
        """
        vms = []
        nodes = [node] if node else [n.node for n in self.get_nodes()]

        for n in nodes:
            try:
                qemu_list = self._api.nodes(n).qemu.get()
                for vm in qemu_list:
                    vm_info = VMInfo(
                        vmid=vm["vmid"],
                        name=vm.get("name", f"VM-{vm['vmid']}"),
                        status=vm.get("status", "unknown"),
                        node=n,
                        cpu=vm.get("cpus", 0),
                        maxmem=vm.get("maxmem", 0),
                        maxdisk=vm.get("maxdisk", 0),
                        uptime=vm.get("uptime", 0),
                        template=vm.get("template", 0) == 1,
                    )
                    # Récupérer l'IP seulement si demandé et VM running
                    if fetch_ips and vm_info.status == "running" and not vm_info.template:
                        vm_info.ip_address = self._get_vm_ip(n, vm["vmid"])
                    vms.append(vm_info)
            except Exception:
                continue

        return sorted(vms, key=lambda v: v.vmid)
    
    def _get_vm_ip(self, node: str, vmid: int) -> Optional[str]:
        """
        Récupère l'adresse IP d'une VM.

        Essaie plusieurs méthodes dans l'ordre:
        1. QEMU Guest Agent (le plus fiable si installé)
        2. Configuration Cloud-Init (ipconfig0)
        3. Configuration réseau de la VM
        """
        # Méthode 1: QEMU Guest Agent
        try:
            agent_info = self._api.nodes(node).qemu(vmid).agent("network-get-interfaces").get()
            for iface in agent_info.get("result", []):
                if iface.get("name") == "lo":
                    continue
                for ip_info in iface.get("ip-addresses", []):
                    if ip_info.get("ip-address-type") == "ipv4":
                        ip = ip_info.get("ip-address")
                        if ip and not ip.startswith("127."):
                            return ip
        except Exception:
            pass

        # Méthode 2: Configuration Cloud-Init ou réseau statique
        try:
            config = self._api.nodes(node).qemu(vmid).config.get()

            # Chercher dans ipconfig0 (Cloud-Init)
            ipconfig = config.get("ipconfig0", "")
            if "ip=" in ipconfig:
                # Format: ip=192.168.1.10/24,gw=192.168.1.1
                for part in ipconfig.split(","):
                    if part.startswith("ip="):
                        ip = part.split("=")[1].split("/")[0]
                        if ip and ip != "dhcp":
                            return ip

            # Chercher dans agent (si les infos sont cachées)
            if "agent" in config:
                # L'agent est configuré, l'IP sera disponible quand la VM démarrera
                pass

        except Exception:
            pass

        return None
    
    def get_cluster_status(self) -> dict[str, Any]:
        """Récupère le statut global du cluster."""
        try:
            status = self._api.cluster.status.get()
            return {"status": "ok", "data": status}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_templates(self) -> list[VMInfo]:
        """Récupère uniquement les templates (rapide, sans fetch des IPs)."""
        return [vm for vm in self.get_vms(fetch_ips=False) if vm.template]

    def get_storages(self, node: str, content_type: str = "images") -> list[dict]:
        """
        Récupère les storages disponibles sur un node.

        Args:
            node: Nom du node
            content_type: Type de contenu (images, rootdir, vztmpl, etc.)

        Returns:
            Liste des storages avec leurs infos (storage, type, avail, total, used)
        """
        try:
            storages = self._api.nodes(node).storage.get()
            # Filtrer les storages qui supportent le type de contenu demandé
            result = []
            for s in storages:
                content = s.get('content', '')
                if content_type in content:
                    result.append({
                        'storage': s['storage'],
                        'type': s.get('type', 'unknown'),
                        'avail': s.get('avail', 0),
                        'total': s.get('total', 0),
                        'used': s.get('used', 0),
                        'shared': s.get('shared', 0) == 1,
                    })
            return sorted(result, key=lambda x: x['storage'])
        except Exception:
            return []

    def get_snapshots(self, node: str, vmid: int) -> list[SnapshotInfo]:
        """
        Récupère la liste des snapshots d'une VM.

        Args:
            node: Nom du node
            vmid: ID de la VM

        Returns:
            Liste des snapshots triés par date (le plus récent en dernier)
        """
        try:
            snapshots = self._api.nodes(node).qemu(vmid).snapshot.get()
            result = []
            for snap in snapshots:
                result.append(SnapshotInfo(
                    name=snap.get("name", ""),
                    description=snap.get("description", ""),
                    snaptime=snap.get("snaptime"),
                    vmstate=snap.get("vmstate", 0) == 1,
                    parent=snap.get("parent"),
                ))
            # Trier par date (current à la fin)
            return sorted(result, key=lambda s: (s.snaptime or float('inf')))
        except Exception:
            return []

    def create_snapshot(
        self,
        node: str,
        vmid: int,
        snapname: str,
        description: str = "",
        vmstate: bool = False,
    ) -> str:
        """
        Crée un snapshot d'une VM.

        Args:
            node: Nom du node
            vmid: ID de la VM
            snapname: Nom du snapshot
            description: Description optionnelle
            vmstate: Inclure l'état RAM (VM doit être running)

        Returns:
            UPID de la tâche
        """
        params = {"snapname": snapname}
        if description:
            params["description"] = description
        if vmstate:
            params["vmstate"] = 1

        return self._api.nodes(node).qemu(vmid).snapshot.post(**params)

    def delete_snapshot(self, node: str, vmid: int, snapname: str) -> str:
        """
        Supprime un snapshot.

        Args:
            node: Nom du node
            vmid: ID de la VM
            snapname: Nom du snapshot à supprimer

        Returns:
            UPID de la tâche
        """
        return self._api.nodes(node).qemu(vmid).snapshot(snapname).delete()

    def rollback_snapshot(self, node: str, vmid: int, snapname: str) -> str:
        """
        Restaure une VM à un snapshot.

        Args:
            node: Nom du node
            vmid: ID de la VM
            snapname: Nom du snapshot à restaurer

        Returns:
            UPID de la tâche
        """
        return self._api.nodes(node).qemu(vmid).snapshot(snapname).rollback.post()


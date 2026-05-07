"""Utilitaires d'affichage avec Rich."""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from proxmate.core.proxmox import VMInfo, NodeInfo


console = Console()


def print_success(message: str) -> None:
    """Affiche un message de succès."""
    console.print(f"[green]✅ {message}[/green]")


def print_error(message: str) -> None:
    """Affiche un message d'erreur."""
    console.print(f"[red]❌ {message}[/red]")


def print_warning(message: str) -> None:
    """Affiche un message d'avertissement."""
    console.print(f"[yellow]⚠️  {message}[/yellow]")


def print_info(message: str) -> None:
    """Affiche un message d'information."""
    console.print(f"[blue]ℹ️  {message}[/blue]")


def format_status(status: str) -> str:
    """Formate le statut avec couleur et emoji."""
    status_map = {
        "running": "[green]🟢 running[/green]",
        "stopped": "[red]🔴 stopped[/red]",
        "paused": "[yellow]⏸️  paused[/yellow]",
        "online": "[green]🟢 online[/green]",
        "offline": "[red]🔴 offline[/red]",
    }
    return status_map.get(status, f"[dim]{status}[/dim]")


def format_bytes(size: int) -> str:
    """Formate une taille en bytes en format lisible."""
    if size >= 1024**3:
        return f"{size / (1024**3):.1f} GB"
    elif size >= 1024**2:
        return f"{size / (1024**2):.1f} MB"
    elif size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def format_ip_address(vm: VMInfo) -> str:
    """Formate l'adresse IP avec indication si elle vient du cache."""
    if not vm.ip_address:
        return "-"
    if vm.ip_from_cache:
        return f"{vm.ip_address} [dim](cache)[/dim]"
    return vm.ip_address


def display_vms_table(vms: list[VMInfo], show_templates: bool = False) -> None:
    """Affiche un tableau des VMs."""
    # Filtrer les templates si demandé
    if not show_templates:
        vms = [vm for vm in vms if not vm.template]

    if not vms:
        print_warning("Aucune VM trouvée.")
        return

    table = Table(title="🖥️  Liste des VMs", show_header=True, header_style="bold cyan")
    table.add_column("VMID", style="dim", width=6)
    table.add_column("Nom", style="bold")
    table.add_column("Node", style="dim")
    table.add_column("Status", width=12)
    table.add_column("IP", style="cyan")
    table.add_column("CPU", justify="right")
    table.add_column("RAM", justify="right")

    for vm in vms:
        table.add_row(
            str(vm.vmid),
            vm.name,
            vm.node,
            format_status(vm.status),
            format_ip_address(vm),
            str(vm.cpu),
            f"{vm.memory_gb} GB",
        )

    console.print(table)


def display_nodes_table(nodes: list[NodeInfo]) -> None:
    """Affiche un tableau des nodes."""
    if not nodes:
        print_warning("Aucun node trouvé.")
        return
    
    table = Table(title="🖧  Nodes du cluster", show_header=True, header_style="bold cyan")
    table.add_column("Node", style="bold")
    table.add_column("Status", width=12)
    table.add_column("CPU", justify="right")
    table.add_column("RAM", justify="right")
    table.add_column("Uptime", justify="right")
    
    for node in nodes:
        uptime_hours = node.uptime // 3600
        uptime_days = uptime_hours // 24
        uptime_str = f"{uptime_days}j {uptime_hours % 24}h" if uptime_days else f"{uptime_hours}h"
        
        table.add_row(
            node.node,
            format_status(node.status),
            f"{node.cpu_percent}% ({node.maxcpu} cores)",
            f"{node.memory_used_gb}/{node.memory_total_gb} GB",
            uptime_str,
        )
    
    console.print(table)


def display_templates_table(templates: list[VMInfo]) -> None:
    """Affiche un tableau des templates."""
    if not templates:
        print_warning("Aucun template trouvé.")
        return
    
    table = Table(title="📦 Templates disponibles", show_header=True, header_style="bold cyan")
    table.add_column("VMID", style="dim", width=6)
    table.add_column("Nom", style="bold")
    table.add_column("Node", style="dim")
    table.add_column("Disque", justify="right")
    table.add_column("RAM", justify="right")
    
    for t in templates:
        table.add_row(
            str(t.vmid),
            t.name,
            t.node,
            f"{t.disk_gb} GB",
            f"{t.memory_gb} GB",
        )
    
    console.print(table)


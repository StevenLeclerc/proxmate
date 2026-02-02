"""Commande status pour afficher l'état du cluster."""

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from proxmate.core.config import is_configured, get_current_context_name
from proxmate.core.proxmox import ProxmoxClient, NodeInfo, VMInfo
from proxmate.core.cache import (
    get_nodes_cache,
    get_vms_cache,
    set_nodes_cache,
    set_vms_cache,
    is_cache_valid,
    format_cache_age,
)
from proxmate.utils.display import (
    print_error,
    print_warning,
    display_nodes_table,
    console,
)


def _nodes_from_cache(cached_data: list[dict]) -> list[NodeInfo]:
    """Convertit les données du cache en objets NodeInfo."""
    return [
        NodeInfo(
            node=n["node"],
            status=n["status"],
            cpu=n["cpu"],
            maxcpu=n["maxcpu"],
            mem=n["mem"],
            maxmem=n["maxmem"],
            uptime=n["uptime"],
        )
        for n in cached_data
    ]


def _vms_from_cache(cached_data: list[dict]) -> list[VMInfo]:
    """Convertit les données du cache en objets VMInfo."""
    return [
        VMInfo(
            vmid=vm["vmid"],
            name=vm["name"],
            status=vm["status"],
            node=vm["node"],
            cpu=vm["cpu"],
            maxmem=vm["maxmem"],
            maxdisk=vm["maxdisk"],
            uptime=vm["uptime"],
            template=vm.get("template", False),
            ip_address=vm.get("ip_address"),
        )
        for vm in cached_data
    ]


def status_command(
    refresh: bool = typer.Option(
        False, "--refresh", "-r",
        help="Forcer le rafraîchissement du cache"
    ),
):
    """
    📊 Affiche l'état du cluster Proxmox.

    Montre les informations sur les nodes: CPU, mémoire, uptime.
    Utilisez --refresh pour forcer un appel API.
    """
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    try:
        client = ProxmoxClient()
        context_name = get_current_context_name()
        cache_used = False
        cache_age_str = None

        # Récupérer le statut du cluster (toujours en direct pour vérifier la connexion)
        cluster_status = client.get_cluster_status()

        if cluster_status["status"] == "error":
            error_msg = cluster_status['message']
            if "403" in error_msg or "Permission" in error_msg:
                print_error("Permission refusée. Vérifiez que votre token API a les droits nécessaires.")
                console.print("\n[dim]Assurez-vous que:[/dim]")
                console.print("  • Le token a été créé [bold]sans[/bold] 'Privilege Separation'")
                console.print("  • Ou ajoutez le rôle 'PVEAuditor' sur '/' dans Permissions")
            else:
                print_error(f"Erreur: {error_msg}")
            raise typer.Exit(1)

        # Afficher le header
        console.print(Panel.fit(
            "[bold cyan]📊 État du cluster Proxmox[/bold cyan]",
            border_style="cyan"
        ))
        console.print()

        # Récupérer les nodes (depuis le cache si possible)
        nodes = None
        if not refresh and context_name and is_cache_valid(context_name, "nodes"):
            cached_data, _ = get_nodes_cache(context_name)
            if cached_data:
                nodes = _nodes_from_cache(cached_data)
                cache_used = True
                cache_age_str = format_cache_age(context_name, "nodes")

        if nodes is None:
            nodes = client.get_nodes()
            if context_name:
                set_nodes_cache(context_name, nodes)

        # Afficher l'info du cache
        if cache_used and cache_age_str:
            console.print(f"[dim]📦 Cache: {cache_age_str}[/dim]")

        display_nodes_table(nodes)

        # Résumé des VMs (depuis le cache si possible)
        console.print()
        vms = None
        if not refresh and context_name and is_cache_valid(context_name, "vms"):
            cached_data, _ = get_vms_cache(context_name)
            if cached_data:
                vms = _vms_from_cache(cached_data)

        if vms is None:
            vms = client.get_vms(fetch_ips=False)
            if context_name:
                set_vms_cache(context_name, vms)

        templates = [vm for vm in vms if vm.template]
        running = [vm for vm in vms if not vm.template and vm.status == "running"]
        stopped = [vm for vm in vms if not vm.template and vm.status == "stopped"]

        console.print(f"[bold]📈 Résumé:[/bold]")
        console.print(f"   • VMs en cours d'exécution: [green]{len(running)}[/green]")
        console.print(f"   • VMs arrêtées: [red]{len(stopped)}[/red]")
        console.print(f"   • Templates: [blue]{len(templates)}[/blue]")

    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


"""Commande status pour afficher l'état du cluster."""

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from proxmate.core.config import is_configured, get_current_context_name
from proxmate.core.proxmox import ProxmoxClient, NodeInfo, VMInfo
from proxmate.core.cache import (
    is_cache_valid,
    format_cache_age,
    vms_from_cache,
    nodes_from_cache,
    get_nodes_or_fetch,
    get_vms_or_fetch,
    get_nodes_cache,
    get_vms_cache,
)
from proxmate.utils.display import (
    print_error,
    print_warning,
    display_nodes_table,
    console,
)


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
                nodes = nodes_from_cache(cached_data)
                cache_used = True
                cache_age_str = format_cache_age(context_name, "nodes")

        if nodes is None:
            nodes = get_nodes_or_fetch(context_name, client)

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
                vms = vms_from_cache(cached_data)

        if vms is None:
            vms = get_vms_or_fetch(context_name, client, fetch_ips=False)

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


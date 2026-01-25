"""Commande status pour afficher l'état du cluster."""

import typer
from rich.console import Console
from rich.panel import Panel

from proxmate.core.config import is_configured
from proxmate.core.proxmox import ProxmoxClient
from proxmate.utils.display import (
    print_error,
    print_warning,
    display_nodes_table,
    console,
)


def status_command():
    """
    📊 Affiche l'état du cluster Proxmox.

    Montre les informations sur les nodes: CPU, mémoire, uptime.
    """
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    try:
        client = ProxmoxClient()

        # Récupérer le statut du cluster
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
        
        # Récupérer et afficher les nodes
        nodes = client.get_nodes()
        display_nodes_table(nodes)
        
        # Résumé des VMs
        console.print()
        vms = client.get_vms()
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


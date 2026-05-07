"""Commandes de contrôle des VMs (start, stop, restart, delete)."""

import time
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from proxmate.core.config import is_configured, remove_created_vm, get_current_context_name
from proxmate.core.proxmox import ProxmoxClient, VMInfo
from proxmate.core.cache import (
    invalidate_cache,
    get_vms_or_fetch,
)
from proxmate.utils.display import print_error, print_success, print_warning, print_info

console = Console()


def _parse_selection(selection: str, max_val: int) -> list[int]:
    """
    Parse une sélection de type "1,3,5-7" en liste d'indices.

    Returns:
        Liste d'indices (0-based)
    """
    indices = []
    parts = selection.replace(" ", "").split(",")

    for part in parts:
        if not part:
            continue
        if "-" in part:
            # Range: "5-7" -> [5, 6, 7]
            try:
                start, end = part.split("-", 1)
                start_idx = int(start)
                end_idx = int(end)
                for i in range(start_idx, end_idx + 1):
                    if 1 <= i <= max_val:
                        indices.append(i - 1)
            except ValueError:
                continue
        else:
            # Single number
            try:
                idx = int(part)
                if 1 <= idx <= max_val:
                    indices.append(idx - 1)
            except ValueError:
                continue

    return sorted(set(indices))  # Unique et trié


def _delete_single_vm(client: ProxmoxClient, vm: VMInfo, purge: bool) -> bool:
    """
    Supprime une seule VM.

    Returns:
        True si succès, False sinon
    """
    try:
        # Arrêter la VM si elle tourne
        if vm.status == "running":
            print_info(f"Arrêt de {vm.name}...")
            client.api.nodes(vm.node).qemu(vm.vmid).status.stop.post()

            # Attendre l'arrêt (max 30s)
            for _ in range(30):
                time.sleep(1)
                current_vms = client.get_vms(node=vm.node, fetch_ips=False)
                current_vm = next((v for v in current_vms if v.vmid == vm.vmid), None)
                if current_vm and current_vm.status == "stopped":
                    break

        # Supprimer la VM
        delete_params = {}
        if purge:
            delete_params["purge"] = 1
            delete_params["destroy-unreferenced-disks"] = 1

        client.api.nodes(vm.node).qemu(vm.vmid).delete(**delete_params)

        # Supprimer des VMs créées par ProxMate
        remove_created_vm(vm.vmid)

        return True

    except Exception as e:
        print_error(f"Erreur pour {vm.name}: {e}")
        return False


def _get_vms_with_cache(client: ProxmoxClient) -> list[VMInfo]:
    """Récupère les VMs depuis le cache ou l'API."""
    context_name = get_current_context_name()
    return get_vms_or_fetch(context_name, client, fetch_ips=False)


def _find_vm(client: ProxmoxClient, identifier: str):
    """Trouve une VM par VMID ou par nom (utilise le cache si disponible)."""
    vms = _get_vms_with_cache(client)

    # Essayer par VMID
    if identifier.isdigit():
        vmid = int(identifier)
        for vm in vms:
            if vm.vmid == vmid:
                return vm

    # Essayer par nom
    for vm in vms:
        if vm.name == identifier:
            return vm

    return None


def start_command(
    identifier: str = typer.Argument(..., help="VMID ou nom de la VM"),
):
    """▶️  Démarre une VM."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré.")
        raise typer.Exit(1)
    
    client = ProxmoxClient()
    vm = _find_vm(client, identifier)
    
    if not vm:
        print_error(f"VM '{identifier}' non trouvée.")
        raise typer.Exit(1)
    
    if vm.status == "running":
        print_warning(f"La VM {vm.name} ({vm.vmid}) est déjà en cours d'exécution.")
        return
    
    try:
        client.api.nodes(vm.node).qemu(vm.vmid).status.start.post()
        print_success(f"VM {vm.name} ({vm.vmid}) démarrée.")
    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


def stop_command(
    identifier: str = typer.Argument(..., help="VMID ou nom de la VM"),
    force: bool = typer.Option(False, "--force", "-f", help="Forcer l'arrêt (shutdown immédiat)"),
):
    """⏹️  Arrête une VM."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré.")
        raise typer.Exit(1)
    
    client = ProxmoxClient()
    vm = _find_vm(client, identifier)
    
    if not vm:
        print_error(f"VM '{identifier}' non trouvée.")
        raise typer.Exit(1)
    
    if vm.status == "stopped":
        print_warning(f"La VM {vm.name} ({vm.vmid}) est déjà arrêtée.")
        return
    
    try:
        if force:
            client.api.nodes(vm.node).qemu(vm.vmid).status.stop.post()
            print_success(f"VM {vm.name} ({vm.vmid}) arrêtée (forcé).")
        else:
            client.api.nodes(vm.node).qemu(vm.vmid).status.shutdown.post()
            print_success(f"VM {vm.name} ({vm.vmid}) en cours d'arrêt...")
    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


def restart_command(
    identifier: str = typer.Argument(..., help="VMID ou nom de la VM"),
):
    """🔄 Redémarre une VM."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré.")
        raise typer.Exit(1)
    
    client = ProxmoxClient()
    vm = _find_vm(client, identifier)
    
    if not vm:
        print_error(f"VM '{identifier}' non trouvée.")
        raise typer.Exit(1)
    
    try:
        client.api.nodes(vm.node).qemu(vm.vmid).status.reboot.post()
        print_success(f"VM {vm.name} ({vm.vmid}) en cours de redémarrage...")
    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


def delete_command(
    identifier: Optional[str] = typer.Argument(None, help="VMID ou nom de la VM (optionnel)"),
    force: bool = typer.Option(False, "--force", "-f", help="Supprimer sans confirmation"),
    purge: bool = typer.Option(False, "--purge", "-p", help="Supprimer aussi les disques non référencés"),
):
    """🗑️  Supprime une ou plusieurs VMs."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré.")
        raise typer.Exit(1)

    client = ProxmoxClient()
    vms_to_delete: list[VMInfo] = []

    # Si pas d'identifiant, proposer une sélection interactive
    if identifier is None:
        # Récupérer toutes les VMs (pas les templates) - utilise le cache
        all_vms = [vm for vm in _get_vms_with_cache(client) if not vm.template]

        if not all_vms:
            print_warning("Aucune VM disponible.")
            raise typer.Exit(0)

        # Grouper par node
        vms_by_node: dict[str, list] = {}
        for v in all_vms:
            if v.node not in vms_by_node:
                vms_by_node[v.node] = []
            vms_by_node[v.node].append(v)

        # Afficher le tableau
        console.print("\n[bold]🗑️  Sélection des VMs à supprimer[/bold]\n")

        table = Table()
        table.add_column("#", style="dim")
        table.add_column("Nom", style="cyan")
        table.add_column("VMID")
        table.add_column("Node")
        table.add_column("Status")
        table.add_column("CPU")
        table.add_column("RAM")

        vm_list = []
        idx = 1
        for node in sorted(vms_by_node.keys()):
            for v in sorted(vms_by_node[node], key=lambda x: x.name):
                status_style = "green" if v.status == "running" else "dim"
                table.add_row(
                    str(idx),
                    v.name,
                    str(v.vmid),
                    node,
                    f"[{status_style}]{v.status}[/{status_style}]",
                    str(v.cpu),
                    f"{v.memory_gb} GB",
                )
                vm_list.append(v)
                idx += 1

        console.print(table)
        console.print()
        console.print("[dim]Exemples: 1 | 1,3,5 | 1-5 | 1,3-5,8 | 0 pour annuler[/dim]")

        # Demander la sélection multiple
        selection = Prompt.ask("Sélectionnez les VMs à supprimer", default="0")

        if selection.strip() == "0":
            print_info("Suppression annulée.")
            raise typer.Exit(0)

        indices = _parse_selection(selection, len(vm_list))

        if not indices:
            print_error("Sélection invalide.")
            raise typer.Exit(1)

        vms_to_delete = [vm_list[i] for i in indices]
    else:
        vm = _find_vm(client, identifier)

        if not vm:
            print_error(f"VM '{identifier}' non trouvée.")
            raise typer.Exit(1)

        vms_to_delete = [vm]

    # Confirmation
    if not force:
        console.print(f"\n[bold red]⚠️  Suppression de {len(vms_to_delete)} VM(s):[/bold red]")
        for vm in vms_to_delete:
            status_icon = "🟢" if vm.status == "running" else "⚫"
            console.print(f"  {status_icon} {vm.name} ({vm.vmid}) sur {vm.node}")
        console.print()

        if not Confirm.ask("[bold red]Confirmer la suppression?[/bold red]", default=False):
            print_info("Suppression annulée.")
            raise typer.Exit(0)

    # Supprimer les VMs
    success_count = 0
    error_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console,
    ) as progress:
        for vm in vms_to_delete:
            task = progress.add_task(f"Suppression de {vm.name}...", total=None)

            if _delete_single_vm(client, vm, purge):
                progress.update(task, description=f"[green]✓[/green] {vm.name} supprimée")
                success_count += 1
            else:
                progress.update(task, description=f"[red]✗[/red] {vm.name} erreur")
                error_count += 1

    # Invalider le cache après suppression
    if success_count > 0:
        context_name = get_current_context_name()
        if context_name:
            invalidate_cache(context_name, "vms")
            invalidate_cache(context_name, "templates")

    # Résumé
    console.print()
    if error_count == 0:
        print_success(f"{success_count} VM(s) supprimée(s) avec succès.")
    else:
        print_warning(f"{success_count} supprimée(s), {error_count} erreur(s).")

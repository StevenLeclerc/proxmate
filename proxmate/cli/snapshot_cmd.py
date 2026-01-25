"""Commandes de gestion des snapshots de VMs."""

import time
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from proxmate.core.config import is_configured
from proxmate.core.proxmox import ProxmoxClient, VMInfo, SnapshotInfo
from proxmate.utils.display import print_error, print_success, print_warning, print_info

console = Console()

# Typer app pour les sous-commandes snapshot
snapshot_app = typer.Typer(
    name="snapshot",
    help="📸 Gestion des snapshots de VMs",
    no_args_is_help=False,
    invoke_without_command=True,
)


def _find_vm(client: ProxmoxClient, identifier: str) -> Optional[VMInfo]:
    """Trouve une VM par VMID ou par nom."""
    vms = client.get_vms(fetch_ips=False)

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


def _select_vm_interactive(client: ProxmoxClient) -> Optional[VMInfo]:
    """Sélection interactive d'une VM."""
    all_vms = [vm for vm in client.get_vms(fetch_ips=False) if not vm.template]

    if not all_vms:
        print_warning("Aucune VM disponible.")
        return None

    console.print("\n[bold]📋 Sélectionnez une VM[/bold]\n")

    table = Table()
    table.add_column("#", style="dim")
    table.add_column("Nom", style="cyan")
    table.add_column("VMID")
    table.add_column("Node")
    table.add_column("Status")

    for idx, vm in enumerate(all_vms, 1):
        status_style = "green" if vm.status == "running" else "dim"
        table.add_row(
            str(idx),
            vm.name,
            str(vm.vmid),
            vm.node,
            f"[{status_style}]{vm.status}[/{status_style}]",
        )

    console.print(table)
    console.print()

    selection = Prompt.ask("Numéro de la VM", default="0")

    if selection == "0":
        return None

    try:
        idx = int(selection) - 1
        if 0 <= idx < len(all_vms):
            return all_vms[idx]
    except ValueError:
        pass

    print_error("Sélection invalide.")
    return None


def _select_snapshot_interactive(
    snapshots: list[SnapshotInfo], allow_multiple: bool = False
) -> Optional[list[SnapshotInfo]]:
    """Sélection interactive d'un ou plusieurs snapshots."""
    # Exclure 'current' de la sélection
    selectable = [s for s in snapshots if not s.is_current]

    if not selectable:
        print_warning("Aucun snapshot disponible.")
        return None

    console.print("\n[bold]📸 Sélectionnez un snapshot[/bold]\n")

    table = Table()
    table.add_column("#", style="dim")
    table.add_column("Nom", style="cyan")
    table.add_column("Description")
    table.add_column("Date")
    table.add_column("RAM", justify="center")

    for idx, snap in enumerate(selectable, 1):
        ram_icon = "✅" if snap.vmstate else "❌"
        table.add_row(
            str(idx),
            snap.name,
            snap.description or "-",
            snap.formatted_date,
            ram_icon,
        )

    console.print(table)
    console.print()

    if allow_multiple:
        console.print("[dim]Exemples: 1 | 1,3 | 1-3 | 0 pour annuler[/dim]")
        selection = Prompt.ask("Sélection", default="0")
    else:
        selection = Prompt.ask("Numéro du snapshot", default="0")

    if selection == "0":
        return None

    # Parse la sélection
    indices = _parse_selection(selection, len(selectable))
    if not indices:
        print_error("Sélection invalide.")
        return None

    return [selectable[i] for i in indices]


def _parse_selection(selection: str, max_val: int) -> list[int]:
    """Parse une sélection de type '1,3,5-7' en liste d'indices (0-based)."""
    indices = []
    parts = selection.replace(" ", "").split(",")

    for part in parts:
        if not part:
            continue
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                for i in range(int(start), int(end) + 1):
                    if 1 <= i <= max_val:
                        indices.append(i - 1)
            except ValueError:
                continue
        else:
            try:
                idx = int(part)
                if 1 <= idx <= max_val:
                    indices.append(idx - 1)
            except ValueError:
                continue

    return sorted(set(indices))


def _wait_for_task(client: ProxmoxClient, node: str, upid: str, timeout: int = 60) -> bool:
    """Attend la fin d'une tâche Proxmox."""
    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            return False
        try:
            task_status = client.api.nodes(node).tasks(upid).status.get()
            if task_status.get("status") == "stopped":
                return task_status.get("exitstatus", "") == "OK"
        except Exception:
            pass
        time.sleep(1)


@snapshot_app.callback()
def snapshot_callback(ctx: typer.Context):
    """📸 Gestion des snapshots de VMs."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    # Si aucune sous-commande, afficher le menu interactif
    if ctx.invoked_subcommand is None:
        _interactive_menu()


def _interactive_menu():
    """Menu interactif principal pour les snapshots."""
    console.print("\n[bold cyan]📸 Gestion des Snapshots[/bold cyan]\n")

    choices = [
        ("1", "Créer un snapshot", "create"),
        ("2", "Lister les snapshots", "list"),
        ("3", "Supprimer un snapshot", "delete"),
        ("4", "Restaurer un snapshot", "rollback"),
        ("0", "Annuler", None),
    ]

    for num, label, _ in choices:
        console.print(f"  [{num}] {label}")

    console.print()
    choice = Prompt.ask("Votre choix", default="0")

    action_map = {c[0]: c[2] for c in choices}
    action = action_map.get(choice)

    if action is None:
        print_info("Opération annulée.")
        return

    client = ProxmoxClient()

    if action == "create":
        _interactive_create(client)
    elif action == "list":
        _interactive_list(client)
    elif action == "delete":
        _interactive_delete(client)
    elif action == "rollback":
        _interactive_rollback(client)


def _interactive_create(client: ProxmoxClient):
    """Création interactive d'un snapshot."""
    vm = _select_vm_interactive(client)
    if not vm:
        return

    snapname = Prompt.ask("Nom du snapshot")
    if not snapname:
        print_error("Le nom du snapshot est requis.")
        return

    description = Prompt.ask("Description (optionnel)", default="")
    vmstate = False
    if vm.status == "running":
        vmstate = Confirm.ask("Inclure l'état RAM?", default=False)

    _do_create_snapshot(client, vm, snapname, description, vmstate)


def _interactive_list(client: ProxmoxClient):
    """Liste interactive des snapshots."""
    vm = _select_vm_interactive(client)
    if not vm:
        return

    _do_list_snapshots(client, vm)


def _interactive_delete(client: ProxmoxClient):
    """Suppression interactive de snapshots."""
    vm = _select_vm_interactive(client)
    if not vm:
        return

    snapshots = client.get_snapshots(vm.node, vm.vmid)
    selected = _select_snapshot_interactive(snapshots, allow_multiple=True)
    if not selected:
        print_info("Suppression annulée.")
        return

    if not Confirm.ask(f"Supprimer {len(selected)} snapshot(s)?", default=False):
        print_info("Suppression annulée.")
        return

    for snap in selected:
        _do_delete_snapshot(client, vm, snap.name)


def _interactive_rollback(client: ProxmoxClient):
    """Restauration interactive d'un snapshot."""
    vm = _select_vm_interactive(client)
    if not vm:
        return

    snapshots = client.get_snapshots(vm.node, vm.vmid)
    selected = _select_snapshot_interactive(snapshots, allow_multiple=False)
    if not selected:
        print_info("Restauration annulée.")
        return

    snap = selected[0]
    console.print(f"\n[bold yellow]⚠️  Attention![/bold yellow]")
    console.print(f"La VM [cyan]{vm.name}[/cyan] sera restaurée à l'état du snapshot [cyan]{snap.name}[/cyan].")
    console.print("Toutes les modifications depuis ce snapshot seront perdues.\n")

    if not Confirm.ask("Confirmer la restauration?", default=False):
        print_info("Restauration annulée.")
        return

    _do_rollback_snapshot(client, vm, snap.name)


# === Fonctions d'exécution ===


def _do_create_snapshot(
    client: ProxmoxClient, vm: VMInfo, snapname: str, description: str, vmstate: bool
):
    """Exécute la création d'un snapshot."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Création du snapshot '{snapname}'...", total=None)

        try:
            upid = client.create_snapshot(vm.node, vm.vmid, snapname, description, vmstate)
            if _wait_for_task(client, vm.node, upid, timeout=120):
                progress.update(task, description=f"[green]✓[/green] Snapshot '{snapname}' créé")
                print_success(f"Snapshot '{snapname}' créé pour {vm.name} ({vm.vmid}).")
            else:
                progress.update(task, description=f"[red]✗[/red] Échec création snapshot")
                print_error("Échec de la création du snapshot (timeout).")
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Erreur")
            print_error(f"Erreur: {e}")


def _do_list_snapshots(client: ProxmoxClient, vm: VMInfo):
    """Affiche la liste des snapshots d'une VM."""
    snapshots = client.get_snapshots(vm.node, vm.vmid)

    if not snapshots:
        print_warning(f"Aucun snapshot pour {vm.name} ({vm.vmid}).")
        return

    console.print(f"\n[bold]📸 Snapshots de {vm.name} ({vm.vmid})[/bold]\n")

    table = Table()
    table.add_column("Nom", style="cyan")
    table.add_column("Description")
    table.add_column("Date")
    table.add_column("RAM", justify="center")

    for snap in snapshots:
        if snap.is_current:
            table.add_row(
                "[dim]current[/dim]",
                "[dim]You are here![/dim]",
                "-",
                "-",
            )
        else:
            ram_icon = "✅" if snap.vmstate else "❌"
            table.add_row(
                snap.name,
                snap.description or "-",
                snap.formatted_date,
                ram_icon,
            )

    console.print(table)


def _do_delete_snapshot(client: ProxmoxClient, vm: VMInfo, snapname: str):
    """Exécute la suppression d'un snapshot."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Suppression de '{snapname}'...", total=None)

        try:
            upid = client.delete_snapshot(vm.node, vm.vmid, snapname)
            if _wait_for_task(client, vm.node, upid, timeout=120):
                progress.update(task, description=f"[green]✓[/green] '{snapname}' supprimé")
                print_success(f"Snapshot '{snapname}' supprimé.")
            else:
                progress.update(task, description=f"[red]✗[/red] Échec suppression")
                print_error("Échec de la suppression (timeout).")
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Erreur")
            print_error(f"Erreur: {e}")


def _do_rollback_snapshot(client: ProxmoxClient, vm: VMInfo, snapname: str):
    """Exécute la restauration d'un snapshot."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Restauration vers '{snapname}'...", total=None)

        try:
            upid = client.rollback_snapshot(vm.node, vm.vmid, snapname)
            if _wait_for_task(client, vm.node, upid, timeout=300):
                progress.update(task, description=f"[green]✓[/green] Restauré vers '{snapname}'")
                print_success(f"VM {vm.name} restaurée vers le snapshot '{snapname}'.")
            else:
                progress.update(task, description=f"[red]✗[/red] Échec restauration")
                print_error("Échec de la restauration (timeout).")
        except Exception as e:
            progress.update(task, description=f"[red]✗[/red] Erreur")
            print_error(f"Erreur: {e}")


# === Commandes CLI ===


@snapshot_app.command("create")
def create_command(
    identifier: Optional[str] = typer.Argument(None, help="VMID ou nom de la VM"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Nom du snapshot"),
    description: str = typer.Option("", "--description", "-d", help="Description du snapshot"),
    vmstate: bool = typer.Option(False, "--vmstate", "-s", help="Inclure l'état RAM"),
):
    """📸 Crée un snapshot d'une VM."""
    client = ProxmoxClient()

    # Mode interactif si pas d'identifiant
    if identifier is None:
        _interactive_create(client)
        return

    vm = _find_vm(client, identifier)
    if not vm:
        print_error(f"VM '{identifier}' non trouvée.")
        raise typer.Exit(1)

    # Demander le nom si pas fourni
    if not name:
        name = Prompt.ask("Nom du snapshot")
        if not name:
            print_error("Le nom du snapshot est requis.")
            raise typer.Exit(1)

    _do_create_snapshot(client, vm, name, description, vmstate)


@snapshot_app.command("list")
def list_command(
    identifier: Optional[str] = typer.Argument(None, help="VMID ou nom de la VM"),
):
    """📋 Liste les snapshots d'une VM."""
    client = ProxmoxClient()

    # Mode interactif si pas d'identifiant
    if identifier is None:
        _interactive_list(client)
        return

    vm = _find_vm(client, identifier)
    if not vm:
        print_error(f"VM '{identifier}' non trouvée.")
        raise typer.Exit(1)

    _do_list_snapshots(client, vm)


@snapshot_app.command("delete")
def delete_command(
    identifier: Optional[str] = typer.Argument(None, help="VMID ou nom de la VM"),
    snapname: Optional[str] = typer.Argument(None, help="Nom du snapshot"),
    force: bool = typer.Option(False, "--force", "-f", help="Supprimer sans confirmation"),
):
    """🗑️  Supprime un snapshot."""
    client = ProxmoxClient()

    # Mode interactif complet
    if identifier is None:
        _interactive_delete(client)
        return

    vm = _find_vm(client, identifier)
    if not vm:
        print_error(f"VM '{identifier}' non trouvée.")
        raise typer.Exit(1)

    # Mode interactif pour le snapshot
    if snapname is None:
        snapshots = client.get_snapshots(vm.node, vm.vmid)
        selected = _select_snapshot_interactive(snapshots, allow_multiple=True)
        if not selected:
            print_info("Suppression annulée.")
            return

        if not force and not Confirm.ask(f"Supprimer {len(selected)} snapshot(s)?", default=False):
            print_info("Suppression annulée.")
            return

        for snap in selected:
            _do_delete_snapshot(client, vm, snap.name)
        return

    # Mode direct
    if not force:
        if not Confirm.ask(f"Supprimer le snapshot '{snapname}'?", default=False):
            print_info("Suppression annulée.")
            return

    _do_delete_snapshot(client, vm, snapname)


@snapshot_app.command("rollback")
def rollback_command(
    identifier: Optional[str] = typer.Argument(None, help="VMID ou nom de la VM"),
    snapname: Optional[str] = typer.Argument(None, help="Nom du snapshot"),
    force: bool = typer.Option(False, "--force", "-f", help="Restaurer sans confirmation"),
):
    """⏪ Restaure une VM à un snapshot."""
    client = ProxmoxClient()

    # Mode interactif complet
    if identifier is None:
        _interactive_rollback(client)
        return

    vm = _find_vm(client, identifier)
    if not vm:
        print_error(f"VM '{identifier}' non trouvée.")
        raise typer.Exit(1)

    # Mode interactif pour le snapshot
    if snapname is None:
        snapshots = client.get_snapshots(vm.node, vm.vmid)
        selected = _select_snapshot_interactive(snapshots, allow_multiple=False)
        if not selected:
            print_info("Restauration annulée.")
            return
        snapname = selected[0].name

    # Confirmation
    if not force:
        console.print(f"\n[bold yellow]⚠️  Attention![/bold yellow]")
        console.print(f"La VM [cyan]{vm.name}[/cyan] sera restaurée à l'état du snapshot [cyan]{snapname}[/cyan].")
        console.print("Toutes les modifications depuis ce snapshot seront perdues.\n")

        if not Confirm.ask("Confirmer la restauration?", default=False):
            print_info("Restauration annulée.")
            return

    _do_rollback_snapshot(client, vm, snapname)


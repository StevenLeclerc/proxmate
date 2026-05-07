"""Commande de modification des ressources (CPU, RAM, disque) d'une ou plusieurs VMs."""

import time
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from proxmate.core.config import is_configured, get_current_context_name
from proxmate.core.proxmox import ProxmoxClient, VMInfo
from proxmate.core.cache import (
    invalidate_cache,
    get_vms_or_fetch,
)
from proxmate.utils.display import print_error, print_success, print_warning, print_info

console = Console()


def _get_vms_with_cache(client: ProxmoxClient) -> list[VMInfo]:
    """Recupere les VMs depuis le cache ou l'API."""
    context_name = get_current_context_name()
    return get_vms_or_fetch(context_name, client, fetch_ips=False)


def _find_vm(client: ProxmoxClient, identifier: str) -> Optional[VMInfo]:
    """Trouve une VM par VMID ou par nom."""
    vms = _get_vms_with_cache(client)

    if identifier.isdigit():
        vmid = int(identifier)
        for vm in vms:
            if vm.vmid == vmid:
                return vm

    for vm in vms:
        if vm.name == identifier:
            return vm

    return None


def _parse_selection(selection: str, max_val: int) -> list[int]:
    """Parse une selection de type '1,3,5-7' en liste d'indices (0-based)."""
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


def _retry_on_lock(client: ProxmoxClient, vm: VMInfo, operation_name: str, operation_func, max_retries: int = 5, delay: float = 3.0):
    """Reessaie une operation si erreur de lock Proxmox."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return operation_func()
        except Exception as e:
            error_str = str(e).lower()
            if "lock" in error_str or "timeout" in error_str:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
            raise
    raise Exception(
        f"{operation_name}: lock timeout apres {max_retries} tentatives. "
        f"Supprimez manuellement le fichier de lock sur le serveur Proxmox:\n"
        f"  ssh root@{vm.node} 'rm /var/lock/qemu-server/lock-{vm.vmid}.conf'\n"
        f"Erreur originale: {last_error}"
    )


def _wait_for_stop(client: ProxmoxClient, vm: VMInfo, timeout: int = 60) -> bool:
    """Attend l'arret effectif d'une VM (polling toutes les 2s)."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            status = client.api.nodes(vm.node).qemu(vm.vmid).status.current.get()
            if status.get("status") == "stopped":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _wait_for_start(client: ProxmoxClient, vm: VMInfo, timeout: int = 60) -> bool:
    """Attend le demarrage effectif d'une VM (polling toutes les 2s)."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            status = client.api.nodes(vm.node).qemu(vm.vmid).status.current.get()
            if status.get("status") == "running":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _select_vms_interactive(client: ProxmoxClient) -> list[VMInfo]:
    """Selection interactive de VMs avec table et selection multiple."""
    all_vms = [vm for vm in _get_vms_with_cache(client) if not vm.template]

    if not all_vms:
        print_warning("Aucune VM disponible.")
        return []

    # Grouper par node
    vms_by_node: dict[str, list] = {}
    for v in all_vms:
        if v.node not in vms_by_node:
            vms_by_node[v.node] = []
        vms_by_node[v.node].append(v)

    console.print("\n[bold]✏️  Selection des VMs a modifier[/bold]\n")

    table = Table()
    table.add_column("#", style="dim")
    table.add_column("Nom", style="cyan")
    table.add_column("VMID")
    table.add_column("Node")
    table.add_column("Status")
    table.add_column("CPU")
    table.add_column("RAM")
    table.add_column("Disque")

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
                f"{v.memory_gb:.0f} GB",
                f"{v.disk_gb:.0f} GB",
            )
            vm_list.append(v)
            idx += 1

    console.print(table)
    console.print()
    console.print("[dim]Exemples: 1 | 1,3,5 | 1-5 | 1,3-5,8 | 0 pour annuler[/dim]")

    selection = Prompt.ask("Selectionnez les VMs a modifier", default="0")

    if selection.strip() == "0":
        return []

    indices = _parse_selection(selection, len(vm_list))

    if not indices:
        print_error("Selection invalide.")
        return []

    return [vm_list[i] for i in indices]


def _get_vm_cpu_config(client: ProxmoxClient, vm: VMInfo) -> tuple[int, int]:
    """Recupere sockets et cores depuis la config Proxmox."""
    try:
        config = client.api.nodes(vm.node).qemu(vm.vmid).config.get()
        sockets = int(config.get("sockets", 1))
        cores = int(config.get("cores", 1))
        return sockets, cores
    except Exception:
        return 1, vm.cpu


def _update_single_vm(
    client: ProxmoxClient,
    vm: VMInfo,
    new_vcpus: int,
    new_memory: int,
    new_disk: int,
    was_running: bool,
) -> bool:
    """Applique les modifications a une seule VM. Retourne True si succes."""
    try:
        # Arreter la VM si elle tourne
        if was_running:
            client.api.nodes(vm.node).qemu(vm.vmid).status.shutdown.post()
            if not _wait_for_stop(client, vm, timeout=60):
                # Fallback: arret force
                client.api.nodes(vm.node).qemu(vm.vmid).status.stop.post()
                if not _wait_for_stop(client, vm, timeout=30):
                    print_error(f"Impossible d'arreter {vm.name} ({vm.vmid}).")
                    return False

        # Modifier CPU/RAM
        changes = {}
        if new_vcpus != vm.cpu:
            # Forcer sockets=1 et cores=N pour que le total = N vCPUs
            changes["sockets"] = 1
            changes["cores"] = new_vcpus
        if new_memory != int(vm.maxmem / (1024 * 1024)):
            changes["memory"] = new_memory

        if changes:
            _retry_on_lock(
                client, vm, "Configuration CPU/RAM",
                lambda: client.api.nodes(vm.node).qemu(vm.vmid).config.put(**changes),
            )

        # Redimensionner le disque si augmentation
        current_disk_gb = int(vm.maxdisk / (1024 * 1024 * 1024))
        if new_disk > current_disk_gb:
            size_diff = new_disk - current_disk_gb
            _retry_on_lock(
                client, vm, "Redimensionnement disque",
                lambda: client.api.nodes(vm.node).qemu(vm.vmid).resize.put(
                    disk="scsi0",
                    size=f"+{size_diff}G",
                ),
            )

        # Redemarrer la VM si elle etait running
        if was_running:
            client.api.nodes(vm.node).qemu(vm.vmid).status.start.post()
            if not _wait_for_start(client, vm, timeout=60):
                print_warning(f"La VM {vm.name} a ete modifiee mais le redemarrage n'a pas pu etre confirme.")

        return True

    except Exception as e:
        print_error(f"Erreur pour {vm.name} ({vm.vmid}): {e}")
        return False


def update_command(
    identifier: Optional[str] = typer.Argument(None, help="VMID ou nom de la VM (optionnel)"),
):
    """✏️  Modifier les ressources (CPU, RAM, disque) d'une ou plusieurs VMs."""
    if not is_configured():
        print_error("ProxMate n'est pas configure. Executez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    client = ProxmoxClient()
    selected_vms: list[VMInfo] = []

    # --- Etape 1: Selection des VMs ---
    if identifier is not None:
        vm = _find_vm(client, identifier)
        if not vm:
            print_error(f"VM '{identifier}' non trouvee.")
            raise typer.Exit(1)
        selected_vms = [vm]
    else:
        selected_vms = _select_vms_interactive(client)
        if not selected_vms:
            print_info("Modification annulee.")
            raise typer.Exit(0)

    # --- Etape 2: Saisie des nouvelles specs ---
    # Utiliser les specs de la premiere VM comme valeurs par defaut
    ref_vm = selected_vms[0]
    current_vcpus = ref_vm.cpu  # total vCPUs (sockets * cores)
    current_sockets, current_cores = _get_vm_cpu_config(client, ref_vm)
    current_memory = int(ref_vm.maxmem / (1024 * 1024))  # bytes -> MB
    current_disk = int(ref_vm.maxdisk / (1024 * 1024 * 1024))  # bytes -> GB

    console.print("\n[bold]⚙️  Nouvelles ressources[/bold]")
    if len(selected_vms) > 1:
        console.print(f"[dim]Valeurs par defaut basees sur {ref_vm.name} ({ref_vm.vmid})[/dim]")
    console.print()

    cpu_detail = f"{current_vcpus} vCPUs"
    if current_sockets > 1:
        cpu_detail += f" = {current_sockets} sockets x {current_cores} cores"
    new_vcpus = IntPrompt.ask(f"vCPUs [dim](actuel: {cpu_detail})[/dim]", default=current_vcpus)
    new_memory = IntPrompt.ask(f"RAM en MB [dim](actuel: {current_memory})[/dim]", default=current_memory)
    new_disk = IntPrompt.ask(f"Disque en GB [dim](actuel: {current_disk})[/dim]", default=current_disk)

    # Validation disque: pas de reduction
    if new_disk < current_disk:
        print_error(f"Impossible de reduire le disque. Minimum: {current_disk} GB (taille actuelle).")
        raise typer.Exit(1)

    # Verifier qu'il y a au moins un changement
    no_change = (new_vcpus == current_vcpus and new_memory == current_memory and new_disk == current_disk)
    if no_change and len(selected_vms) == 1:
        print_info("Aucune modification demandee.")
        raise typer.Exit(0)

    # --- Etape 3: Detection des VMs running ---
    running_vms = [vm for vm in selected_vms if vm.status == "running"]

    if running_vms:
        running_names = ", ".join(f"{vm.name}" for vm in running_vms)
        print_warning(f"Les VMs suivantes sont en cours d'execution: {running_names}")
        if not Confirm.ask("Les arreter, appliquer les modifications, puis les redemarrer?", default=True):
            print_info("Modification annulee.")
            raise typer.Exit(0)

    # --- Etape 4: Recapitulatif ---
    console.print("\n" + "\u2500" * 50)
    console.print(f"[bold]📋 Recapitulatif des modifications:[/bold]")

    # VMs concernees
    if len(selected_vms) == 1:
        vm = selected_vms[0]
        console.print(f"  \u2022 VM: [cyan]{vm.name}[/cyan] ({vm.vmid}) sur {vm.node}")
    else:
        console.print(f"  \u2022 VMs concernees ({len(selected_vms)}):")
        for vm in selected_vms:
            console.print(f"    - [cyan]{vm.name}[/cyan] ({vm.vmid}) sur {vm.node}")

    # Changements
    if new_vcpus != current_vcpus:
        console.print(f"  \u2022 CPU: {current_vcpus} \u2192 [bold]{new_vcpus}[/bold] vCPUs (1 socket x {new_vcpus} cores)")
    else:
        console.print(f"  \u2022 CPU: {current_vcpus} vCPUs [dim](inchange)[/dim]")

    if new_memory != current_memory:
        console.print(f"  \u2022 RAM: {current_memory} \u2192 [bold]{new_memory}[/bold] MB")
    else:
        console.print(f"  \u2022 RAM: {current_memory} MB [dim](inchange)[/dim]")

    if new_disk != current_disk:
        diff = new_disk - current_disk
        console.print(f"  \u2022 Disque: {current_disk} \u2192 [bold]{new_disk}[/bold] GB (+{diff} GB)")
    else:
        console.print(f"  \u2022 Disque: {current_disk} GB [dim](inchange)[/dim]")

    if running_vms:
        restart_names = ", ".join(vm.name for vm in running_vms)
        console.print(f"  \u2022 VMs a redemarrer: {restart_names}")

    console.print("\u2500" * 50)

    if not Confirm.ask("\n[bold]Appliquer ces modifications?[/bold]", default=True):
        print_info("Modification annulee.")
        raise typer.Exit(0)

    # --- Etape 5: Execution ---
    success_count = 0
    error_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console,
    ) as progress:
        for vm in selected_vms:
            was_running = vm.status == "running"
            task = progress.add_task(f"Modification de {vm.name}...", total=None)

            if _update_single_vm(client, vm, new_vcpus, new_memory, new_disk, was_running):
                progress.update(task, description=f"[green]✓[/green] {vm.name} modifiee")
                success_count += 1
            else:
                progress.update(task, description=f"[red]✗[/red] {vm.name} erreur")
                error_count += 1

    # --- Etape 6: Cache et bilan ---
    if success_count > 0:
        context_name = get_current_context_name()
        if context_name:
            invalidate_cache(context_name, "vms")

    console.print()
    if error_count == 0:
        print_success(f"{success_count} VM(s) modifiee(s) avec succes.")
    else:
        print_warning(f"{success_count} modifiee(s), {error_count} erreur(s).")

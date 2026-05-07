"""Commande ps pour afficher les details complets d'une VM."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from proxmate.core.config import is_configured, get_current_context_name, get_created_vm
from proxmate.core.proxmox import ProxmoxClient, VMInfo
from proxmate.core.cache import get_vms_or_fetch
from proxmate.utils.display import print_error, print_warning, print_info, format_bytes

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


def _select_vm_interactive(client: ProxmoxClient) -> Optional[VMInfo]:
    """Selection interactive d'une VM."""
    all_vms = [vm for vm in _get_vms_with_cache(client) if not vm.template]

    if not all_vms:
        print_warning("Aucune VM disponible.")
        return None

    # Grouper par node
    vms_by_node: dict[str, list] = {}
    for v in all_vms:
        if v.node not in vms_by_node:
            vms_by_node[v.node] = []
        vms_by_node[v.node].append(v)

    console.print("\n[bold]📋 Selectionnez une VM[/bold]\n")

    table = Table()
    table.add_column("#", style="dim")
    table.add_column("Nom", style="cyan")
    table.add_column("VMID")
    table.add_column("Node")
    table.add_column("Status")

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
            )
            vm_list.append(v)
            idx += 1

    console.print(table)
    console.print()

    selection = Prompt.ask("Numero de la VM", default="0")

    if selection.strip() == "0":
        return None

    try:
        sel_idx = int(selection) - 1
        if 0 <= sel_idx < len(vm_list):
            return vm_list[sel_idx]
    except ValueError:
        pass

    print_error("Selection invalide.")
    return None


def _format_uptime(seconds: int) -> str:
    """Formate un uptime en jours/heures/minutes."""
    if seconds == 0:
        return "-"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{days}j")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "<1m"


def _kv(key: str, value: str):
    """Affiche une ligne cle: valeur alignee."""
    console.print(f"  [dim]{key + ':':<20}[/dim]{value}")


def _section(title: str):
    """Affiche un titre de section."""
    console.print(f"\n[bold]{title}[/bold]")


def _display_vm_details(client: ProxmoxClient, vm: VMInfo):
    """Affiche les details complets d'une VM."""
    # Recuperer la config complete depuis l'API
    try:
        config = client.api.nodes(vm.node).qemu(vm.vmid).config.get()
    except Exception as e:
        print_error(f"Impossible de recuperer la config de {vm.name}: {e}")
        return

    # Recuperer le status runtime
    runtime = {}
    try:
        runtime = client.api.nodes(vm.node).qemu(vm.vmid).status.current.get()
    except Exception:
        pass

    # Recuperer les infos ProxMate (si creee par proxmate)
    created_vm = get_created_vm(vm.vmid)

    status_color = "green" if vm.status == "running" else "red" if vm.status == "stopped" else "yellow"
    status_icon = "🟢" if vm.status == "running" else "🔴" if vm.status == "stopped" else "🟡"

    # === Header ===
    console.print(f"\n[bold cyan]{vm.name}[/bold cyan]  [dim]VMID {vm.vmid}  |  {vm.node}  |[/dim]  [{status_color}]{status_icon} {vm.status}[/{status_color}]  [dim]|  up {_format_uptime(vm.uptime)}[/dim]")
    if config.get("description"):
        console.print(f"  [dim]{config['description']}[/dim]")

    # === CPU ===
    sockets = int(config.get("sockets", 1))
    cores = int(config.get("cores", 1))
    total_vcpus = sockets * cores
    cpu_type = config.get("cpu", "default")

    _section("CPU")
    vcpu_str = f"[bold]{total_vcpus}[/bold] vCPUs"
    if sockets > 1:
        vcpu_str += f" ({sockets} sockets x {cores} cores)"
    else:
        vcpu_str += f" ({cores} cores)"
    _kv("vCPUs", vcpu_str)
    _kv("Type", cpu_type)
    if config.get("numa", 0) == 1:
        _kv("NUMA", "active")
    if runtime.get("cpu") is not None:
        cpu_usage = round(float(runtime["cpu"]) * 100, 1)
        _kv("Usage", f"{cpu_usage}%")

    # === Memoire ===
    memory_mb = int(config.get("memory", 0))
    balloon = config.get("balloon", None)

    _section("Memoire")
    _kv("RAM", f"[bold]{memory_mb} MB[/bold] ({memory_mb / 1024:.1f} GB)")
    if balloon is not None:
        balloon_val = int(balloon)
        _kv("Ballooning", "[dim]desactive[/dim]" if balloon_val == 0 else f"min {balloon_val} MB")
    if runtime.get("mem") is not None and runtime.get("maxmem") is not None:
        mem_used = int(runtime["mem"])
        mem_max = int(runtime["maxmem"])
        if mem_max > 0:
            mem_pct = round(mem_used / mem_max * 100, 1)
            _kv("Usage", f"{format_bytes(mem_used)} / {format_bytes(mem_max)} ({mem_pct}%)")

    # === Disques ===
    disk_keys = sorted([k for k in config if k.startswith(("scsi", "virtio", "ide", "sata")) and not k.endswith("hw")])
    disk_entries = [(dk, config[dk]) for dk in disk_keys if not (isinstance(config[dk], str) and ("media=cdrom" in config[dk] or "none" in config[dk]))]

    if disk_entries:
        _section("Disques")
        for dk, dv in disk_entries:
            # Extraire taille du format "storage:volume,size=32G,..."
            disk_str = str(dv)
            size_part = ""
            for part in disk_str.split(","):
                if part.startswith("size="):
                    size_part = f"  [bold]{part.split('=')[1]}[/bold]"
                    break
            storage_part = disk_str.split(",")[0] if "," in disk_str else disk_str
            _kv(dk, f"{storage_part}{size_part}")
        if config.get("boot"):
            _kv("Boot", config["boot"])

    # === Reseau ===
    net_keys = sorted([k for k in config if k.startswith("net")])
    ip_address = vm.ip_address

    if not ip_address and vm.status == "running":
        try:
            ip_address = client._get_vm_ip(vm.node, vm.vmid)
        except Exception:
            pass

    if net_keys or ip_address:
        _section("Reseau")
        for nk in net_keys:
            net_str = str(config[nk])
            # Extraire modele et bridge
            parts_dict = {}
            for p in net_str.split(","):
                if "=" in p:
                    k, v = p.split("=", 1)
                    parts_dict[k] = v
                else:
                    # Premier element: "virtio=MAC" ou "e1000=MAC"
                    if "=" in p:
                        pass
                    else:
                        parts_dict["raw"] = p

            bridge = parts_dict.get("bridge", "?")
            # Trouver le modele (premier element avant le =)
            first_part = net_str.split(",")[0]
            model = first_part.split("=")[0] if "=" in first_part else first_part
            mac = first_part.split("=")[1] if "=" in first_part else ""

            _kv(nk, f"{model} sur [cyan]{bridge}[/cyan]  [dim]{mac}[/dim]")

        if ip_address:
            label = "IP (cache)" if vm.ip_from_cache else "IP"
            _kv(label, f"[bold]{ip_address}[/bold]")

    # === Cloud-Init ===
    ci_keys = ["ciuser", "cipassword", "ipconfig0", "ipconfig1", "nameserver", "searchdomain", "sshkeys"]
    ci_data = {k: config[k] for k in ci_keys if k in config}

    if ci_data:
        _section("Cloud-Init")
        for k, v in ci_data.items():
            if k == "cipassword":
                _kv(k, "[dim]********[/dim]")
            elif k == "sshkeys":
                import urllib.parse
                decoded = urllib.parse.unquote(str(v)).strip()
                if len(decoded) > 60:
                    # Afficher juste le type + fingerprint tronquee
                    decoded = decoded[:57] + "..."
                _kv(k, decoded)
            else:
                _kv(k, str(v))

    # === Options ===
    opts = []
    if config.get("ostype"):
        opts.append(("OS", config["ostype"]))
    if config.get("machine"):
        opts.append(("Machine", config["machine"]))
    if config.get("bios"):
        opts.append(("BIOS", config["bios"]))
    if config.get("agent"):
        agent_val = config["agent"]
        opts.append(("QEMU Agent", "[green]active[/green]" if str(agent_val).startswith("1") else str(agent_val)))
    if config.get("onboot") is not None:
        opts.append(("Demarrage auto", "oui" if config["onboot"] == 1 else "non"))
    if config.get("protection") is not None:
        opts.append(("Protection", "oui" if config["protection"] == 1 else "non"))
    if config.get("tags"):
        opts.append(("Tags", config["tags"]))

    if opts:
        _section("Options")
        for k, v in opts:
            _kv(k, v)

    # === ProxMate ===
    if created_vm:
        _section("ProxMate")
        _kv("User SSH", created_vm.user)
        if created_vm.ssh_public_key_path:
            _kv("Cle SSH", created_vm.ssh_public_key_path)
        if created_vm.ip:
            _kv("IP configuree", created_vm.ip)
        _kv("Creee le", created_vm.created_at)

    console.print()


def ps_command(
    identifier: Optional[str] = typer.Argument(None, help="VMID ou nom de la VM (optionnel)"),
):
    """🔍 Affiche les details complets d'une VM."""
    if not is_configured():
        print_error("ProxMate n'est pas configure. Executez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    client = ProxmoxClient()

    if identifier is not None:
        vm = _find_vm(client, identifier)
        if not vm:
            print_error(f"VM '{identifier}' non trouvee.")
            raise typer.Exit(1)
    else:
        vm = _select_vm_interactive(client)
        if not vm:
            print_info("Operation annulee.")
            raise typer.Exit(0)

    _display_vm_details(client, vm)

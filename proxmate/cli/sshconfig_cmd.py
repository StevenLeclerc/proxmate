"""Commande gensshconfig pour générer la configuration SSH."""

import shutil
import subprocess
from pathlib import Path
from collections import defaultdict

import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table

from proxmate.core.config import (
    is_configured, load_created_vms, get_current_context_name, VMCreationInfo
)
from proxmate.core.proxmox import ProxmoxClient
from proxmate.core.cache import get_vms_or_fetch
from proxmate.utils.display import print_error, print_success, print_info, print_warning

console = Console()

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
SSH_CONFIG_BACKUP_PATH = Path.home() / ".ssh" / "config.proxmate.bak"
KNOWN_HOSTS_PATH = Path.home() / ".ssh" / "known_hosts"
PROXMATE_SECTION_START = "# === PROXMATE START ==="
PROXMATE_SECTION_END = "# === PROXMATE END ==="


def _parse_proxmate_section(content: str) -> dict[str, dict]:
    """
    Parse le contenu entre les marqueurs PROXMATE START/END et extrait les entrées Host.

    Returns:
        Dict {hostname: {"ip": str, "user": str, "key": str}}
    """
    # Extraire la section ProxMate
    start_idx = content.find(PROXMATE_SECTION_START)
    end_idx = content.find(PROXMATE_SECTION_END)

    if start_idx == -1 or end_idx == -1:
        return {}

    section = content[start_idx + len(PROXMATE_SECTION_START):end_idx]
    entries = {}
    current_host = None
    current_entry = {}

    for line in section.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            # Flush current entry if we have one
            if current_host and current_entry.get("ip"):
                entries[current_host] = current_entry
                current_host = None
                current_entry = {}
            continue

        if stripped.startswith("Host "):
            # Flush previous entry
            if current_host and current_entry.get("ip"):
                entries[current_host] = current_entry
            current_host = stripped[5:].strip()
            current_entry = {}
        elif stripped.startswith("HostName "):
            current_entry["ip"] = stripped[9:].strip()
        elif stripped.startswith("User "):
            current_entry["user"] = stripped[5:].strip()
        elif stripped.startswith("IdentityFile "):
            current_entry["key"] = stripped[13:].strip()
        else:
            if current_host:
                print_warning(f"Entrée SSH malformée ignorée dans Host {current_host}: {stripped}")

    # Flush last entry
    if current_host and current_entry.get("ip"):
        entries[current_host] = current_entry

    return entries


def _get_private_key_from_public(public_key_path: str) -> str:
    """Déduit le chemin de la clé privée à partir de la clé publique."""
    pub_path = Path(public_key_path).expanduser()
    # Retirer l'extension .pub si présente
    if pub_path.suffix == ".pub":
        return str(pub_path.with_suffix(""))
    return str(pub_path)


def _build_desired_state(
    created_vms: dict[int, "VMCreationInfo"],
    current_vms: dict[int, "VMInfo"],
) -> dict[str, dict]:
    """
    Calcule l'état SSH désiré à partir de vms.yaml + IPs Proxmox.

    Returns:
        Dict {hostname: {"ip": str, "user": str, "key": str}}
    """
    desired = {}

    for vmid, vm_info in created_vms.items():
        # Résoudre l'IP: Proxmox live > vms.yaml statique
        ip = None
        if vmid in current_vms and current_vms[vmid].ip_address:
            ip = current_vms[vmid].ip_address
        elif vm_info.ip:
            ip = vm_info.ip

        if not ip:
            print_warning(f"{vm_info.name}: IP non résolue, VM ignorée.")
            continue

        # Résoudre la clé SSH
        if vm_info.ssh_public_key_path:
            key = _get_private_key_from_public(vm_info.ssh_public_key_path)
        else:
            # Demander le chemin de la clé
            console.print(f"\n[bold yellow]⚠️  Clé SSH manquante pour {vm_info.name}[/bold yellow]")
            public_key_path = Prompt.ask("Chemin de la clé publique SSH (ex: ~/.ssh/homevms.pub)")
            if public_key_path:
                key = _get_private_key_from_public(public_key_path)
            else:
                print_warning(f"{vm_info.name}: clé SSH non fournie, VM ignorée.")
                continue

        desired[vm_info.name] = {
            "ip": ip,
            "user": vm_info.user,
            "key": key,
        }

    return desired


def _compute_diff(
    existing: dict[str, dict], desired: dict[str, dict]
) -> list[dict]:
    """
    Compare l'état existant vs désiré et classifie chaque entrée.

    Returns:
        Liste de dicts avec: name, type (ADD/MODIFY/REMOVE/UNCHANGED),
        et pour MODIFY: changes [{field, old, new}]
    """
    changes = []
    all_names = sorted(set(list(existing.keys()) + list(desired.keys())))

    for name in all_names:
        in_existing = name in existing
        in_desired = name in desired

        if in_desired and not in_existing:
            changes.append({
                "name": name,
                "type": "ADD",
                "desired": desired[name],
            })
        elif in_existing and not in_desired:
            changes.append({
                "name": name,
                "type": "REMOVE",
                "existing": existing[name],
            })
        else:
            # Both exist — check for differences
            ex = existing[name]
            de = desired[name]
            field_changes = []
            for field in ("ip", "user", "key"):
                old_val = ex.get(field, "")
                new_val = de.get(field, "")
                if old_val != new_val:
                    field_changes.append({"field": field, "old": old_val, "new": new_val})

            if field_changes:
                changes.append({
                    "name": name,
                    "type": "MODIFY",
                    "existing": ex,
                    "desired": de,
                    "changes": field_changes,
                })
            else:
                changes.append({
                    "name": name,
                    "type": "UNCHANGED",
                    "existing": ex,
                })

    return changes


def _display_diff_table(changes: list[dict]) -> None:
    """Affiche les changements dans un tableau Rich avec numérotation des actions."""
    table = Table(title="Modifications SSH config")
    table.add_column("#", style="dim", width=4)
    table.add_column("", width=2)  # indicator
    table.add_column("Host", style="cyan")
    table.add_column("Détails")

    action_num = 0
    for change in changes:
        ctype = change["type"]

        if ctype == "ADD":
            action_num += 1
            d = change["desired"]
            table.add_row(
                str(action_num),
                "[green]+[/green]",
                change["name"],
                f"[green]{d['user']}@{d['ip']} (key: {d['key']})[/green]",
            )
        elif ctype == "MODIFY":
            action_num += 1
            detail_parts = []
            for fc in change["changes"]:
                detail_parts.append(f"{fc['field']}: {fc['old']} → {fc['new']}")
            table.add_row(
                str(action_num),
                "[yellow]~[/yellow]",
                change["name"],
                f"[yellow]{', '.join(detail_parts)}[/yellow]",
            )
        elif ctype == "REMOVE":
            action_num += 1
            ex = change["existing"]
            table.add_row(
                str(action_num),
                "[red]-[/red]",
                change["name"],
                f"[red]{ex.get('user', '?')}@{ex.get('ip', '?')}[/red]",
            )
        else:  # UNCHANGED
            ex = change["existing"]
            table.add_row(
                "",
                "[dim]=[/dim]",
                f"[dim]{change['name']}[/dim]",
                f"[dim]{ex.get('user', '?')}@{ex.get('ip', '?')}[/dim]",
            )

    console.print()
    console.print(table)
    console.print()


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


def _prompt_exclusions(changes: list[dict]) -> list[dict]:
    """
    Propose l'opt-out et retourne les changements retenus.

    Numérote uniquement les actions (ADD/MODIFY/REMOVE), pas les UNCHANGED.
    L'utilisateur entre les numéros à exclure.
    """
    actionable = [c for c in changes if c["type"] != "UNCHANGED"]
    if not actionable:
        return changes

    console.print("[dim]Exemples: 3 | 1,3 | 1-3 | vide = tout appliquer[/dim]")
    selection = Prompt.ask("Exclure", default="")

    if not selection.strip():
        return changes  # Keep all

    excluded_indices = set(_parse_selection(selection, len(actionable)))

    # Map action numbers back to changes
    retained = []
    action_num = 0
    for change in changes:
        if change["type"] == "UNCHANGED":
            retained.append(change)
        else:
            if action_num not in excluded_indices:
                retained.append(change)
            action_num += 1

    return retained


def _apply_changes(retained: list[dict], existing_entries: dict[str, dict]) -> str:
    """
    Produit le nouveau bloc ProxMate à partir des changements retenus.

    Conserve les UNCHANGED, applique ADD/MODIFY, supprime REMOVE.
    """
    # Build the final set of entries
    final_entries = {}

    for change in retained:
        name = change["name"]
        ctype = change["type"]

        if ctype == "UNCHANGED":
            final_entries[name] = existing_entries[name]
        elif ctype == "ADD":
            final_entries[name] = change["desired"]
        elif ctype == "MODIFY":
            final_entries[name] = change["desired"]
        # REMOVE: don't include

    # Generate the block
    lines = [PROXMATE_SECTION_START, "# Configuration générée par ProxMate", ""]
    for name in sorted(final_entries.keys()):
        entry = final_entries[name]
        lines.append(f"Host {name}")
        lines.append(f"    HostName {entry['ip']}")
        lines.append(f"    User {entry['user']}")
        lines.append(f"    IdentityFile {entry['key']}")
        lines.append("")
    lines.append(PROXMATE_SECTION_END)

    return "\n".join(lines)


def _generate_ssh_config_block(vms_by_node: dict[str, list[dict]]) -> str:
    """Génère le bloc de configuration SSH groupé par node."""
    lines = [PROXMATE_SECTION_START, "# Configuration générée par ProxMate", ""]
    
    for node in sorted(vms_by_node.keys()):
        lines.append(f"# --- Node: {node} ---")
        for vm in sorted(vms_by_node[node], key=lambda v: v["name"]):
            lines.append(f"Host {vm['name']}")
            lines.append(f"    HostName {vm['ip']}")
            lines.append(f"    User {vm['user']}")
            lines.append(f"    IdentityFile {vm['key']}")
            lines.append("")
    
    lines.append(PROXMATE_SECTION_END)
    return "\n".join(lines)


def _update_ssh_config(new_block: str) -> None:
    """Met à jour le fichier ~/.ssh/config avec le nouveau bloc ProxMate."""
    SSH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Backup avant modification
    if SSH_CONFIG_PATH.exists():
        shutil.copy2(SSH_CONFIG_PATH, SSH_CONFIG_BACKUP_PATH)
        print_info(f"Backup: {SSH_CONFIG_BACKUP_PATH}")

    if SSH_CONFIG_PATH.exists():
        content = SSH_CONFIG_PATH.read_text()
        
        # Chercher et remplacer la section existante
        if PROXMATE_SECTION_START in content:
            start_idx = content.find(PROXMATE_SECTION_START)
            end_idx = content.find(PROXMATE_SECTION_END)
            if end_idx != -1:
                end_idx += len(PROXMATE_SECTION_END)
                content = content[:start_idx] + new_block + content[end_idx:]
            else:
                content = content[:start_idx] + new_block
        else:
            # Ajouter à la fin
            content = content.rstrip() + "\n\n" + new_block + "\n"
    else:
        content = new_block + "\n"
    
    SSH_CONFIG_PATH.write_text(content)


def _remove_from_known_hosts(ip: str) -> bool:
    """Supprime une entrée du fichier known_hosts."""
    if not KNOWN_HOSTS_PATH.exists():
        return False

    try:
        lines = KNOWN_HOSTS_PATH.read_text().splitlines()
        new_lines = []
        removed = False

        for line in lines:
            # Vérifier si la ligne contient l'IP (au début ou après une virgule)
            if line.startswith(f"{ip} ") or line.startswith(f"{ip},") or f",{ip} " in line:
                removed = True
                continue
            new_lines.append(line)

        if removed:
            KNOWN_HOSTS_PATH.write_text("\n".join(new_lines) + "\n")

        return removed
    except Exception:
        return False


def _test_ssh_connection(vm_name: str, ip: str, user: str, key_path: str) -> tuple[bool, str]:
    """
    Teste la connexion SSH à une VM.

    Returns:
        (success, error_message)
    """
    try:
        # Test avec timeout court, sans vérification stricte pour détecter le problème
        result = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5",
                "-o", "StrictHostKeyChecking=yes",
                "-i", str(Path(key_path).expanduser()),
                f"{user}@{ip}",
                "echo OK"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return True, ""

        # Analyser l'erreur
        stderr = result.stderr
        if "REMOTE HOST IDENTIFICATION HAS CHANGED" in stderr or "Host key verification failed" in stderr:
            return False, "host_key_changed"
        elif "Permission denied" in stderr:
            return False, "permission_denied"
        elif "Connection refused" in stderr:
            return False, "connection_refused"
        elif "Connection timed out" in stderr or "timed out" in stderr.lower():
            return False, "timeout"
        else:
            return False, stderr.strip()

    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def _gensshconfig_interactive(created_vms, current_vms):
    """Flow interactif complet (ancien comportement, utilisé avec --force)."""
    console.print("\n[bold]VMs créées par ProxMate:[/bold]\n")

    table = Table()
    table.add_column("#", style="dim")
    table.add_column("Nom", style="cyan")
    table.add_column("VMID")
    table.add_column("Node")
    table.add_column("User")
    table.add_column("IP")
    table.add_column("Clé SSH")

    vm_list = list(created_vms.values())
    for i, vm_info in enumerate(vm_list, 1):
        current_ip = vm_info.ip
        if vm_info.vmid in current_vms:
            current_vm = current_vms[vm_info.vmid]
            if current_vm.ip_address:
                current_ip = current_vm.ip_address

        key_display = Path(vm_info.ssh_public_key_path).name if vm_info.ssh_public_key_path else "-"
        table.add_row(
            str(i), vm_info.name, str(vm_info.vmid), vm_info.node,
            vm_info.user, current_ip or "[dim]DHCP[/dim]", key_display,
        )

    console.print(table)
    console.print()

    console.print("[bold]Sélectionnez les VMs à inclure (séparées par des virgules, ou 'all'):[/bold]")
    selection = Prompt.ask("VMs", default="all")

    if selection.lower() == "all":
        selected_vms = vm_list
    else:
        try:
            indices = [int(x.strip()) - 1 for x in selection.split(",")]
            selected_vms = [vm_list[i] for i in indices if 0 <= i < len(vm_list)]
        except (ValueError, IndexError):
            print_error("Sélection invalide.")
            raise typer.Exit(1)

    if not selected_vms:
        print_error("Aucune VM sélectionnée.")
        raise typer.Exit(1)

    vms_config = defaultdict(list)
    for vm_info in selected_vms:
        console.print(f"\n[bold cyan]Configuration pour {vm_info.name}:[/bold cyan]")

        if vm_info.ssh_public_key_path:
            default_private_key = _get_private_key_from_public(vm_info.ssh_public_key_path)
            private_key = Prompt.ask("Clé privée SSH", default=default_private_key)
        else:
            console.print("[dim]Clé SSH non enregistrée lors de la création.[/dim]")
            public_key_path = Prompt.ask("Chemin de la clé publique SSH utilisée (ex: ~/.ssh/homevms.pub)")
            if public_key_path:
                private_key = _get_private_key_from_public(public_key_path)
                console.print(f"[dim]Clé privée déduite: {private_key}[/dim]")
            else:
                private_key = Prompt.ask("Clé privée SSH", default="~/.ssh/id_rsa")

        user = Prompt.ask("Utilisateur", default=vm_info.user)

        current_ip = vm_info.ip
        if vm_info.vmid in current_vms and current_vms[vm_info.vmid].ip_address:
            current_ip = current_vms[vm_info.vmid].ip_address

        if current_ip:
            ip = Prompt.ask("Adresse IP", default=current_ip)
        else:
            ip = Prompt.ask("Adresse IP (obligatoire)")
            if not ip:
                print_warning(f"IP manquante pour {vm_info.name}, VM ignorée.")
                continue

        vms_config[vm_info.node].append({
            "name": vm_info.name, "ip": ip, "user": user, "key": private_key,
        })

    if not any(vms_config.values()):
        print_error("Aucune VM configurée.")
        raise typer.Exit(1)

    config_block = _generate_ssh_config_block(vms_config)

    console.print("\n[bold]Configuration SSH générée:[/bold]\n")
    console.print(f"[dim]{config_block}[/dim]")
    console.print()

    if Confirm.ask(f"Ajouter à {SSH_CONFIG_PATH}?", default=True):
        _update_ssh_config(config_block)
        print_success(f"Configuration ajoutée à {SSH_CONFIG_PATH}")

        # Collect all VMs for testing
        all_configured = []
        for node_vms in vms_config.values():
            all_configured.extend(node_vms)
        _test_ssh_connections(all_configured)
    else:
        print_info("Configuration non sauvegardée.")


def _test_ssh_connections(vms_to_test: list[dict]) -> None:
    """Teste les connexions SSH et gère les erreurs known_hosts."""
    if not vms_to_test:
        return

    if not Confirm.ask("\n[bold]Tester les connexions SSH?[/bold]", default=True):
        return

    console.print()
    for vm in vms_to_test:
        console.print(f"[dim]Test de connexion à {vm['name']} ({vm['ip']})...[/dim]", end=" ")

        success, error = _test_ssh_connection(
            vm['name'], vm['ip'], vm['user'], vm['key']
        )

        if success:
            console.print("[green]✓ OK[/green]")
        elif error == "host_key_changed":
            console.print("[red]✗ Clé SSH changée[/red]")
            console.print(f"\n[bold yellow]La clé SSH de {vm['ip']} a changé![/bold yellow]")
            console.print("[dim]Cela arrive souvent quand une VM est recréée avec la même IP.[/dim]")

            if Confirm.ask(f"Supprimer l'ancienne clé de {KNOWN_HOSTS_PATH}?", default=True):
                if _remove_from_known_hosts(vm['ip']):
                    print_success(f"Clé supprimée pour {vm['ip']}")
                    console.print("[dim]Reconnecte-toi pour accepter la nouvelle clé.[/dim]")
                else:
                    print_warning("Impossible de supprimer la clé automatiquement.")
                    console.print(f"[dim]Exécute: ssh-keygen -R {vm['ip']}[/dim]")
        elif error == "permission_denied":
            console.print("[yellow]✗ Permission refusée[/yellow]")
            console.print(f"[dim]  Vérifie la clé SSH: {vm['key']}[/dim]")
        elif error == "connection_refused":
            console.print("[yellow]✗ Connexion refusée[/yellow]")
            console.print("[dim]  Le service SSH n'est peut-être pas démarré.[/dim]")
        elif error == "timeout":
            console.print("[yellow]✗ Timeout[/yellow]")
            console.print("[dim]  La VM n'est peut-être pas accessible.[/dim]")
        else:
            console.print(f"[yellow]✗ Erreur[/yellow]")
            if error:
                console.print(f"[dim]  {error[:80]}[/dim]")

    console.print()


def gensshconfig_command(
    force: bool = typer.Option(False, "--force", "-f", help="Régénération complète (mode interactif)"),
):
    """Génère la configuration SSH pour les VMs créées par ProxMate."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    created_vms = load_created_vms()
    if not created_vms:
        print_warning("Aucune VM créée par ProxMate.")
        console.print("[dim]Créez d'abord une VM avec: proxmate create[/dim]")
        raise typer.Exit(1)

    # Récupérer les VMs actuelles depuis Proxmox (cache ou API)
    client = ProxmoxClient()
    context_name = get_current_context_name()
    all_vms = get_vms_or_fetch(context_name, client, fetch_ips=True)
    current_vms = {vm.vmid: vm for vm in all_vms}

    # --force: ancien comportement interactif
    if force:
        _gensshconfig_interactive(created_vms, current_vms)
        return

    # --- Diff-based flow ---

    # 1. Parse existing SSH config
    existing = {}
    if SSH_CONFIG_PATH.exists():
        ssh_content = SSH_CONFIG_PATH.read_text()
        existing = _parse_proxmate_section(ssh_content)

    # 2. Build desired state
    desired = _build_desired_state(created_vms, current_vms)

    if not desired and not existing:
        print_warning("Aucune VM avec IP résolue, rien à configurer.")
        raise typer.Exit(0)

    # 3. Compute diff
    changes = _compute_diff(existing, desired)

    # 4. Check if anything changed
    actionable = [c for c in changes if c["type"] != "UNCHANGED"]
    if not actionable:
        print_success("SSH config à jour, aucune modification nécessaire.")
        return

    # 5. Display diff table
    _display_diff_table(changes)

    # 6. Opt-out selection
    retained = _prompt_exclusions(changes)
    retained_actionable = [c for c in retained if c["type"] != "UNCHANGED"]

    if not retained_actionable:
        print_info("Aucune modification retenue.")
        return

    # 7. Apply changes
    new_block = _apply_changes(retained, existing)
    _update_ssh_config(new_block)

    applied_count = len(retained_actionable)
    print_success(f"{applied_count} modification(s) appliquée(s) à {SSH_CONFIG_PATH}")

    # 8. Clean known_hosts for IP changes
    for change in retained:
        if change["type"] == "MODIFY":
            for fc in change.get("changes", []):
                if fc["field"] == "ip":
                    old_ip = fc["old"]
                    console.print(f"\n[yellow]IP changée pour {change['name']}: {old_ip} → {fc['new']}[/yellow]")
                    if Confirm.ask(f"Supprimer {old_ip} de {KNOWN_HOSTS_PATH}?", default=True):
                        if _remove_from_known_hosts(old_ip):
                            print_success(f"Clé supprimée pour {old_ip}")
                        else:
                            print_info(f"Aucune entrée trouvée pour {old_ip}")

    # 9. Test SSH connections (only ADD and MODIFY)
    vms_to_test = []
    for change in retained:
        if change["type"] in ("ADD", "MODIFY"):
            d = change["desired"]
            vms_to_test.append({
                "name": change["name"],
                "ip": d["ip"],
                "user": d["user"],
                "key": d["key"],
            })

    _test_ssh_connections(vms_to_test)

    if vms_to_test:
        console.print("[bold green]Tu peux maintenant te connecter avec:[/bold green]")
        for vm in vms_to_test:
            console.print(f"  ssh {vm['name']}")


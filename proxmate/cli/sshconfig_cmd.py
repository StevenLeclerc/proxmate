"""Commande gensshconfig pour générer la configuration SSH."""

import subprocess
import re
from pathlib import Path
from typing import Optional
from collections import defaultdict

import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table

from proxmate.core.config import (
    is_configured, get_config, load_created_vms, VMCreationInfo
)
from proxmate.core.proxmox import ProxmoxClient
from proxmate.utils.display import print_error, print_success, print_info, print_warning

console = Console()

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
KNOWN_HOSTS_PATH = Path.home() / ".ssh" / "known_hosts"
PROXMATE_SECTION_START = "# === PROXMATE START ==="
PROXMATE_SECTION_END = "# === PROXMATE END ==="


def _get_private_key_from_public(public_key_path: str) -> str:
    """Déduit le chemin de la clé privée à partir de la clé publique."""
    pub_path = Path(public_key_path).expanduser()
    # Retirer l'extension .pub si présente
    if pub_path.suffix == ".pub":
        return str(pub_path.with_suffix(""))
    return str(pub_path)


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


def gensshconfig_command():
    """🔧 Génère la configuration SSH pour les VMs créées par ProxMate."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)
    
    # Charger les VMs créées par ProxMate
    created_vms = load_created_vms()
    
    if not created_vms:
        print_warning("Aucune VM créée par ProxMate.")
        console.print("[dim]Créez d'abord une VM avec: proxmate create[/dim]")
        raise typer.Exit(1)
    
    # Récupérer les IPs actuelles des VMs depuis Proxmox
    client = ProxmoxClient()
    current_vms = {vm.vmid: vm for vm in client.get_vms(fetch_ips=True)}
    
    # Afficher les VMs disponibles
    console.print("\n[bold]📋 VMs créées par ProxMate:[/bold]\n")
    
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
        # Récupérer l'IP actuelle si disponible
        current_ip = vm_info.ip
        if vm_info.vmid in current_vms:
            current_vm = current_vms[vm_info.vmid]
            if current_vm.ip_address:
                current_ip = current_vm.ip_address
        
        key_display = Path(vm_info.ssh_public_key_path).name if vm_info.ssh_public_key_path else "-"
        table.add_row(
            str(i),
            vm_info.name,
            str(vm_info.vmid),
            vm_info.node,
            vm_info.user,
            current_ip or "[dim]DHCP[/dim]",
            key_display,
        )
    
    console.print(table)
    console.print()

    # Sélection des VMs à inclure
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

    # Collecter les infos pour chaque VM
    vms_config = defaultdict(list)

    for vm_info in selected_vms:
        console.print(f"\n[bold cyan]Configuration pour {vm_info.name}:[/bold cyan]")

        # Clé SSH - demander la clé publique si pas connue, puis déduire la privée
        if vm_info.ssh_public_key_path:
            # On a la clé publique, on déduit la privée
            default_private_key = _get_private_key_from_public(vm_info.ssh_public_key_path)
            private_key = Prompt.ask("Clé privée SSH", default=default_private_key)
        else:
            # Pas de clé connue, demander le chemin de la clé publique
            console.print("[dim]Clé SSH non enregistrée lors de la création.[/dim]")
            public_key_path = Prompt.ask("Chemin de la clé publique SSH utilisée (ex: ~/.ssh/homevms.pub)")
            if public_key_path:
                private_key = _get_private_key_from_public(public_key_path)
                console.print(f"[dim]Clé privée déduite: {private_key}[/dim]")
            else:
                private_key = Prompt.ask("Clé privée SSH", default="~/.ssh/id_rsa")

        # Utilisateur
        user = Prompt.ask("Utilisateur", default=vm_info.user)

        # IP
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
            "name": vm_info.name,
            "ip": ip,
            "user": user,
            "key": private_key,
        })

    if not any(vms_config.values()):
        print_error("Aucune VM configurée.")
        raise typer.Exit(1)

    # Générer le bloc de configuration
    config_block = _generate_ssh_config_block(vms_config)

    # Afficher la configuration générée
    console.print("\n[bold]📋 Configuration SSH générée:[/bold]\n")
    console.print(f"[dim]{config_block}[/dim]")
    console.print()

    # Proposer d'ajouter au fichier
    if Confirm.ask(f"Ajouter à {SSH_CONFIG_PATH}?", default=True):
        _update_ssh_config(config_block)
        print_success(f"Configuration ajoutée à {SSH_CONFIG_PATH}")

        # Tester les connexions SSH
        if Confirm.ask("\n[bold]Tester les connexions SSH?[/bold]", default=True):
            console.print()

            for node_vms in vms_config.values():
                for vm in node_vms:
                    console.print(f"[dim]Test de connexion à {vm['name']} ({vm['ip']})...[/dim]", end=" ")

                    success, error = _test_ssh_connection(
                        vm['name'], vm['ip'], vm['user'], vm['key']
                    )

                    if success:
                        console.print("[green]✓ OK[/green]")
                    elif error == "host_key_changed":
                        console.print("[red]✗ Clé SSH changée[/red]")
                        console.print(f"\n[bold yellow]⚠️  La clé SSH de {vm['ip']} a changé![/bold yellow]")
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

        console.print("[bold green]Tu peux maintenant te connecter avec:[/bold green]")
        for node_vms in vms_config.values():
            for vm in node_vms:
                console.print(f"  ssh {vm['name']}")
    else:
        print_info("Configuration non sauvegardée.")


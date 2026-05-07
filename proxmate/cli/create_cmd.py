"""Commande create pour créer des VMs à partir de templates."""

import time
import urllib.parse
from typing import Optional
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from proxmate.core.config import is_configured, get_config, save_created_vm, VMCreationInfo, get_current_context_name
from proxmate.core.proxmox import ProxmoxClient, VMInfo
from proxmate.core.cache import (
    get_templates_cache,
    is_cache_valid,
    invalidate_cache,
    format_cache_age,
    vms_from_cache,
    get_nodes_or_fetch,
    get_vms_or_fetch,
    get_storages_or_fetch,
)
from proxmate.utils.display import print_error, print_success, print_info, print_warning

console = Console()


def _create_single_vm(
    client: ProxmoxClient,
    vm_name: str,
    vmid: int,
    selected_node: str,
    selected_storage: Optional[str],
    selected_template,
    cores: int,
    memory: int,
    disk: int,
    ip_config: str,
    static_ip: Optional[str],
    ssh_user: str,
    user_password: Optional[str],
    ssh_key: Optional[str],
    ssh_key_path_used: Optional[str],
    start: bool,
    show_progress: bool = True,
) -> bool:
    """
    Crée une seule VM.

    Returns:
        True si succès, False sinon
    """
    try:
        # Étape 1: Cloner le template
        clone_params = {
            "newid": vmid,
            "name": vm_name,
            "target": selected_node,
            "full": 1,
        }
        if selected_storage:
            clone_params["storage"] = selected_storage

        upid = client.api.nodes(selected_template.node).qemu(selected_template.vmid).clone.post(**clone_params)

        # Attendre le clonage
        timeout = 300
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                print_error(f"Timeout clonage pour {vm_name}")
                return False
            try:
                task_status = client.api.nodes(selected_template.node).tasks(upid).status.get()
                if task_status.get("status") == "stopped":
                    if task_status.get("exitstatus", "") == "OK":
                        break
                    else:
                        print_error(f"Erreur clonage {vm_name}: {task_status.get('exitstatus')}")
                        return False
            except Exception:
                pass
            time.sleep(2)

        # Attendre que Proxmox libère le lock après le clonage
        time.sleep(3)

        # Helper pour retries sur erreur de lock
        def _retry_on_lock(operation_name: str, operation_func, max_retries: int = 5, delay: float = 3.0):
            """Réessaie une opération si erreur de lock Proxmox."""
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
                    # Autre erreur, on la propage
                    raise
            # Toutes les tentatives ont échoué
            raise Exception(f"{operation_name}: lock timeout après {max_retries} tentatives. "
                           f"Supprimez manuellement le fichier de lock sur le serveur Proxmox:\n"
                           f"  ssh root@{selected_node} 'rm /var/lock/qemu-server/lock-{vmid}.conf'\n"
                           f"Erreur originale: {last_error}")

        # Étape 2: Configurer les ressources
        _retry_on_lock(
            "Configuration CPU/RAM",
            lambda: client.api.nodes(selected_node).qemu(vmid).config.put(
                cores=cores,
                memory=memory,
            )
        )

        # Étape 3: Redimensionner le disque
        if disk > selected_template.disk_gb:
            size_diff = disk - int(selected_template.disk_gb)
            _retry_on_lock(
                "Redimensionnement disque",
                lambda: client.api.nodes(selected_node).qemu(vmid).resize.put(
                    disk="scsi0",
                    size=f"+{size_diff}G",
                )
            )

        # Étape 4: Configurer Cloud-Init
        cloudinit_params = {
            "ciuser": ssh_user,
            "ipconfig0": ip_config,
        }
        if user_password:
            cloudinit_params["cipassword"] = user_password
        if ssh_key:
            encoded_key = urllib.parse.quote(ssh_key.replace("\n", ""), safe="")
            cloudinit_params["sshkeys"] = encoded_key

        _retry_on_lock(
            "Configuration Cloud-Init",
            lambda: client.api.nodes(selected_node).qemu(vmid).config.put(**cloudinit_params)
        )

        # Étape 5: Démarrer si demandé
        if start:
            _retry_on_lock(
                "Démarrage VM",
                lambda: client.api.nodes(selected_node).qemu(vmid).status.start.post()
            )

        # Sauvegarder les infos
        vm_creation_info = VMCreationInfo(
            vmid=vmid,
            name=vm_name,
            node=selected_node,
            user=ssh_user,
            ssh_public_key_path=ssh_key_path_used,
            ip=static_ip.split("/")[0] if static_ip else None,
        )
        save_created_vm(vm_creation_info)

        return True

    except Exception as e:
        print_error(f"Erreur pour {vm_name}: {e}")
        return False


def create_command(
    template: Optional[int] = typer.Option(None, "--template", "-t", help="VMID du template à utiliser"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Nom de la VM"),
    cores: Optional[int] = typer.Option(None, "--cores", "-c", help="Nombre de CPU cores"),
    memory: Optional[int] = typer.Option(None, "--memory", "-m", help="Mémoire RAM en MB"),
    disk: Optional[int] = typer.Option(None, "--disk", "-d", help="Taille du disque en GB"),
    start: bool = typer.Option(False, "--start", "-s", help="Démarrer la VM après création"),
):
    """
    🚀 Crée une nouvelle VM à partir d'un template.
    
    Lance un wizard interactif pour configurer la VM,
    ou utilisez les options en ligne de commande.
    """
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)
    
    try:
        client = ProxmoxClient()
        config = get_config()
        context_name = get_current_context_name()
        cache_used = False

        # Récupérer les templates disponibles (depuis le cache si possible)
        templates = None
        if context_name and is_cache_valid(context_name, "templates"):
            cached_data, _ = get_templates_cache(context_name)
            if cached_data:
                templates = vms_from_cache(cached_data)
                cache_used = True

        # Fallback API
        if templates is None:
            templates = client.get_templates()

        if not templates:
            print_error("Aucun template disponible.")
            console.print("[dim]Créez d'abord un template avec:[/dim] proxmate template create")
            raise typer.Exit(1)

        console.print(Panel.fit(
            "[bold cyan]🚀 Création de VM(s)[/bold cyan]",
            border_style="cyan"
        ))
        console.print()

        # ═══════════════════════════════════════════════════════════════
        # 1. NOMBRE DE VMs (en premier pour adapter les questions suivantes)
        # ═══════════════════════════════════════════════════════════════
        console.print("[bold]📦 Combien de VMs créer?[/bold]")
        vm_count = IntPrompt.ask("Nombre", default=1)
        if vm_count < 1:
            vm_count = 1

        # ═══════════════════════════════════════════════════════════════
        # 2. RÉPARTITION SUR LES NODES (si plusieurs VMs)
        # ═══════════════════════════════════════════════════════════════
        nodes = [n for n in get_nodes_or_fetch(context_name, client) if n.status == "online"]
        distribute_on_nodes = False
        available_nodes = []
        selected_node = None

        if vm_count > 1 and len(nodes) > 1:
            distribute_on_nodes = Confirm.ask(
                f"\n[bold]🖧 Répartir automatiquement sur les {len(nodes)} nodes?[/bold]",
                default=True
            )

            if distribute_on_nodes:
                console.print("[dim]Les VMs seront réparties équitablement sur les nodes disponibles.[/dim]")
                # On calculera les nodes disponibles après avoir défini les ressources

        # ═══════════════════════════════════════════════════════════════
        # 3. TEMPLATE
        # ═══════════════════════════════════════════════════════════════
        if template is None:
            console.print("\n[bold]📦 Templates disponibles:[/bold]")
            for i, t in enumerate(templates, 1):
                console.print(f"  {i}. [cyan]{t.name}[/cyan] (VMID: {t.vmid}, {t.memory_gb} GB RAM, {t.disk_gb} GB disk)")

            choice = IntPrompt.ask("Sélectionnez un template", default=1)
            selected_template = templates[choice - 1]
        else:
            selected_template = next((t for t in templates if t.vmid == template), None)
            if not selected_template:
                print_error(f"Template {template} non trouvé.")
                raise typer.Exit(1)

        console.print(f"[dim]→ Template: {selected_template.name}[/dim]")
        template_node = selected_template.node

        # Vérifier si le template utilise un stockage local
        uses_local_storage = False
        try:
            vm_config = client.api.nodes(template_node).qemu(selected_template.vmid).config.get()
            for key, value in vm_config.items():
                if key.startswith(('scsi', 'virtio', 'ide', 'sata')) and isinstance(value, str):
                    if 'local' in value.lower() and ':' in value:
                        uses_local_storage = True
                        break
        except Exception:
            pass

        if uses_local_storage:
            print_warning(f"Template sur stockage local → VMs créées sur '{template_node}'")
            distribute_on_nodes = False
            selected_node = template_node

        # ═══════════════════════════════════════════════════════════════
        # 4. NOMS DES VMs
        # ═══════════════════════════════════════════════════════════════
        vm_names = []

        if vm_count == 1:
            # Une seule VM : demander le nom
            if name is None:
                name = Prompt.ask("\n[bold]Nom de la VM[/bold]", default="new-vm")
            vm_names = [name]
        else:
            # Plusieurs VMs : choix entre noms distincts ou incrémenteur
            console.print("\n[bold]📝 Nommage des VMs[/bold]")
            console.print("  1. Noms avec suffixe numérique (ex: web-1, web-2, web-3)")
            console.print("  2. Noms distincts pour chaque VM")

            naming_choice = IntPrompt.ask("Choix", default=1)

            if naming_choice == 1:
                # Noms avec incrémenteur
                if name is None:
                    base_name = Prompt.ask("Préfixe du nom", default="vm")
                else:
                    base_name = name
                vm_names = [f"{base_name}-{i + 1}" for i in range(vm_count)]
                console.print(f"[dim]→ Noms: {', '.join(vm_names)}[/dim]")
            else:
                # Noms distincts
                console.print(f"[dim]Entrez les {vm_count} noms:[/dim]")
                for i in range(vm_count):
                    vm_name = Prompt.ask(f"  Nom VM {i + 1}", default=f"vm-{i + 1}")
                    vm_names.append(vm_name)

        # ═══════════════════════════════════════════════════════════════
        # 4b. VÉRIFICATION DES NOMS EXISTANTS
        # ═══════════════════════════════════════════════════════════════
        # Récupérer les VMs existantes (depuis le cache si possible)
        existing_vms = get_vms_or_fetch(context_name, client, fetch_ips=False)

        existing_names = {vm.name.lower(): vm for vm in existing_vms if not vm.template}

        # Vérifier les conflits de noms
        conflicting_vms = []
        for vm_name in vm_names:
            if vm_name.lower() in existing_names:
                conflicting_vms.append(existing_names[vm_name.lower()])

        if conflicting_vms:
            console.print()
            print_warning(f"{len(conflicting_vms)} VM(s) avec ce nom existe(nt) déjà:")
            for vm in conflicting_vms:
                status_icon = "🟢" if vm.status == "running" else "🔴"
                console.print(f"  • [cyan]{vm.name}[/cyan] (VMID: {vm.vmid}) - {status_icon} {vm.status} sur {vm.node}")

            console.print()
            console.print("[bold]Que voulez-vous faire?[/bold]")
            console.print("  1. Supprimer les VMs existantes et continuer")
            console.print("  2. Changer les noms")
            console.print("  3. Annuler")

            action = IntPrompt.ask("Choix", default=3)

            if action == 1:
                # Supprimer les VMs existantes
                console.print()
                for vm in conflicting_vms:
                    try:
                        if vm.status == "running":
                            console.print(f"[dim]Arrêt de {vm.name}...[/dim]")
                            client.stop_vm(vm.node, vm.vmid, wait=True)
                        console.print(f"[dim]Suppression de {vm.name}...[/dim]")
                        client.delete_vm(vm.node, vm.vmid)
                        print_success(f"VM {vm.name} supprimée")
                    except Exception as e:
                        print_error(f"Impossible de supprimer {vm.name}: {e}")
                        raise typer.Exit(1)

                # Invalider le cache après suppression
                if context_name:
                    invalidate_cache(context_name, "vms")

            elif action == 2:
                # Demander de nouveaux noms
                console.print()
                new_vm_names = []
                for i, old_name in enumerate(vm_names):
                    if old_name.lower() in existing_names:
                        new_name = Prompt.ask(f"Nouveau nom pour [cyan]{old_name}[/cyan]", default=f"{old_name}-new")
                        new_vm_names.append(new_name)
                    else:
                        new_vm_names.append(old_name)
                vm_names = new_vm_names
                console.print(f"[dim]→ Nouveaux noms: {', '.join(vm_names)}[/dim]")
            else:
                print_info("Création annulée.")
                raise typer.Exit()

        # ═══════════════════════════════════════════════════════════════
        # 5. NODE (seulement si pas de répartition auto et pas de stockage local)
        # ═══════════════════════════════════════════════════════════════
        if not distribute_on_nodes and selected_node is None:
            if len(nodes) == 1:
                selected_node = nodes[0].node
                console.print(f"[dim]→ Node: {selected_node}[/dim]")
            else:
                nodes_sorted = sorted(nodes, key=lambda n: (n.node != template_node, n.node))
                console.print("\n[bold]🖧 Node cible:[/bold]")
                for i, n in enumerate(nodes_sorted, 1):
                    rec = " [green](recommandé)[/green]" if n.node == template_node else ""
                    console.print(f"  {i}. {n.node} (CPU: {n.cpu_percent}%, RAM: {n.memory_used_gb}/{n.memory_total_gb} GB){rec}")
                node_choice = IntPrompt.ask("Sélectionnez", default=1)
                selected_node = nodes_sorted[node_choice - 1].node

        # ═══════════════════════════════════════════════════════════════
        # 6. STORAGE
        # ═══════════════════════════════════════════════════════════════
        # Pour le storage, on prend celui du premier node (ou selected_node)
        storage_node = selected_node if selected_node else nodes[0].node
        storages = get_storages_or_fetch(context_name, client, storage_node, content_type="images")

        def format_size(bytes_val: int) -> str:
            return f"{bytes_val / (1024**3):.1f} GB"

        if not storages:
            print_warning("Aucun storage disponible.")
            selected_storage = None
        elif len(storages) == 1:
            selected_storage = storages[0]['storage']
            console.print(f"[dim]→ Storage: {selected_storage}[/dim]")
        else:
            console.print("\n[bold]💾 Storage:[/bold]")
            for i, s in enumerate(storages, 1):
                shared_tag = " [cyan](partagé)[/cyan]" if s['shared'] else ""
                avail = format_size(s['avail']) if s['avail'] else "?"
                total = format_size(s['total']) if s['total'] else "?"
                console.print(f"  {i}. {s['storage']} ({s['type']}) - {avail} libre / {total}{shared_tag}")
            storage_choice = IntPrompt.ask("Sélectionnez", default=1)
            selected_storage = storages[storage_choice - 1]['storage']

        # ═══════════════════════════════════════════════════════════════
        # 7. RESSOURCES (CPU, RAM, Disque)
        # ═══════════════════════════════════════════════════════════════
        console.print("\n[bold]⚙️  Ressources (par VM)[/bold]")

        if cores is None:
            cores = IntPrompt.ask("CPU cores", default=2)

        if memory is None:
            memory = IntPrompt.ask("RAM (MB)", default=2048)

        if disk is None:
            console.print(f"[dim]Taille template: {selected_template.disk_gb} GB[/dim]")
            disk = IntPrompt.ask("Disque (GB)", default=max(20, int(selected_template.disk_gb)))

        if disk < selected_template.disk_gb:
            print_warning(f"Minimum: {selected_template.disk_gb} GB")
            disk = int(selected_template.disk_gb)

        # Maintenant qu'on a les ressources, calculer les nodes disponibles pour la répartition
        if distribute_on_nodes:
            mem_needed_gb = memory / 1024
            for node in nodes:
                mem_available_gb = (node.maxmem - node.mem) / (1024**3)
                cpu_available = node.maxcpu * (1 - node.cpu)

                if mem_available_gb >= mem_needed_gb and cpu_available >= cores:
                    available_nodes.append({
                        "name": node.node,
                        "mem_available_gb": mem_available_gb,
                        "cpu_available": cpu_available,
                    })

            if not available_nodes:
                print_warning("Aucun node n'a assez de ressources. Création sur un seul node.")
                distribute_on_nodes = False
                selected_node = template_node
            else:
                console.print(f"[dim]→ Répartition sur: {', '.join(n['name'] for n in available_nodes)}[/dim]")

        # ═══════════════════════════════════════════════════════════════
        # 8. RÉSEAU
        # ═══════════════════════════════════════════════════════════════
        console.print("\n[bold]🌐 Réseau[/bold]")
        console.print("  1. DHCP")
        console.print("  2. IP statique")

        net_choice = IntPrompt.ask("Choix", default=1)

        ip_config = "ip=dhcp"
        static_ip = None
        if net_choice == 2:
            static_ip = Prompt.ask("IP (ex: 192.168.1.100/24)")
            gateway = Prompt.ask("Gateway (ex: 192.168.1.1)")
            ip_config = f"ip={static_ip},gw={gateway}"

        # ═══════════════════════════════════════════════════════════════
        # 9. AUTHENTIFICATION
        # ═══════════════════════════════════════════════════════════════
        console.print("\n[bold]🔑 Authentification[/bold]")
        ssh_user = Prompt.ask("Utilisateur", default=config.default_user)

        user_password = Prompt.ask("Mot de passe (vide = aucun)", password=True, default="")
        if user_password:
            password_confirm = Prompt.ask("Confirmer", password=True)
            if user_password != password_confirm:
                print_error("Mots de passe différents.")
                raise typer.Exit(1)

        # Clé SSH
        default_key_path = Path(config.ssh_public_key_path).expanduser()
        ssh_key = ""
        ssh_key_path_used = None

        if default_key_path.exists():
            if Confirm.ask(f"Utiliser {default_key_path}?", default=True):
                ssh_key = default_key_path.read_text().strip()
                ssh_key_path_used = str(default_key_path)
            else:
                # Boucle jusqu'à fichier trouvé ou annulation
                while True:
                    ssh_key_input = Prompt.ask("Autre clé SSH (vide = annuler)", default="")
                    if not ssh_key_input:
                        break
                    input_path = Path(ssh_key_input).expanduser().resolve()
                    if input_path.exists():
                        ssh_key = input_path.read_text().strip()
                        ssh_key_path_used = str(input_path)
                        console.print(f"[dim]✓ Clé chargée: {input_path}[/dim]")
                        break
                    else:
                        print_warning(f"Fichier non trouvé: {input_path}")
        else:
            # Boucle jusqu'à fichier trouvé ou annulation
            while True:
                ssh_key_input = Prompt.ask("Clé SSH publique (vide = aucune)", default="")
                if not ssh_key_input:
                    break
                input_path = Path(ssh_key_input).expanduser().resolve()
                if input_path.exists():
                    ssh_key = input_path.read_text().strip()
                    ssh_key_path_used = str(input_path)
                    console.print(f"[dim]✓ Clé chargée: {input_path}[/dim]")
                    break
                else:
                    print_warning(f"Fichier non trouvé: {input_path}")

        if not user_password and not ssh_key:
            print_warning("Aucune authentification définie!")
            if not Confirm.ask("Continuer?", default=False):
                raise typer.Exit()

        # ═══════════════════════════════════════════════════════════════
        # 10. DÉMARRAGE AUTO
        # ═══════════════════════════════════════════════════════════════
        if not start:
            start = Confirm.ask("\n[bold]Démarrer après création?[/bold]", default=True)

        # ═══════════════════════════════════════════════════════════════
        # PRÉPARATION DES VMs
        # ═══════════════════════════════════════════════════════════════
        existing_vmids = {vm.vmid for vm in existing_vms}
        base_vmid = max(existing_vmids) + 1 if existing_vmids else 100

        vms_to_create = []
        node_index = 0

        for i in range(vm_count):
            vmid = base_vmid + i
            vm_name = vm_names[i]

            # Choisir le node
            if distribute_on_nodes and available_nodes:
                target_node = available_nodes[node_index % len(available_nodes)]["name"]
                node_index += 1
            else:
                target_node = selected_node

            vms_to_create.append({
                "name": vm_name,
                "vmid": vmid,
                "node": target_node,
            })

        # Récapitulatif
        console.print("\n" + "─" * 50)
        if vm_count == 1:
            console.print("[bold]📋 Récapitulatif:[/bold]")
            console.print(f"  • Nom: [cyan]{vm_names[0]}[/cyan] (VMID: {base_vmid})")
            console.print(f"  • Node: {vms_to_create[0]['node']}")
        else:
            console.print(f"[bold]📋 Récapitulatif ({vm_count} VMs):[/bold]")
            for vm in vms_to_create:
                console.print(f"  • [cyan]{vm['name']}[/cyan] (VMID: {vm['vmid']}) → {vm['node']}")

        console.print(f"  • Storage: {selected_storage or 'par défaut'}")
        console.print(f"  • Template: {selected_template.name}")
        console.print(f"  • CPU: {cores} cores")
        console.print(f"  • RAM: {memory} MB")
        console.print(f"  • Disque: [bold]{disk} GB[/bold]")
        console.print(f"  • Réseau: {ip_config}")
        console.print(f"  • Utilisateur: {ssh_user}")
        console.print(f"  • Mot de passe: {'[green]défini[/green]' if user_password else '[dim]non défini[/dim]'}")
        console.print(f"  • Clé SSH: {'[green]définie[/green]' if ssh_key else '[dim]non définie[/dim]'}")
        console.print("─" * 50)

        confirm_msg = f"Créer {'ces ' + str(vm_count) + ' VMs' if vm_count > 1 else 'cette VM'}?"
        if not Confirm.ask(f"\n[bold]{confirm_msg}[/bold]", default=True):
            print_info("Création annulée.")
            raise typer.Exit()
        
        # Création des VMs
        console.print(f"\n[bold]🔨 Création de {vm_count} VM(s) en cours...[/bold]\n")

        success_count = 0
        error_count = 0
        created_vms = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            console=console,
        ) as progress:
            for vm_info in vms_to_create:
                task = progress.add_task(f"Création de {vm_info['name']}...", total=None)

                success = _create_single_vm(
                    client=client,
                    vm_name=vm_info["name"],
                    vmid=vm_info["vmid"],
                    selected_node=vm_info["node"],
                    selected_storage=selected_storage,
                    selected_template=selected_template,
                    cores=cores,
                    memory=memory,
                    disk=disk,
                    ip_config=ip_config,
                    static_ip=static_ip,
                    ssh_user=ssh_user,
                    user_password=user_password,
                    ssh_key=ssh_key,
                    ssh_key_path_used=ssh_key_path_used,
                    start=start,
                )

                if success:
                    progress.update(task, description=f"[green]✓[/green] {vm_info['name']} créée")
                    success_count += 1
                    created_vms.append(vm_info)
                else:
                    progress.update(task, description=f"[red]✗[/red] {vm_info['name']} erreur")
                    error_count += 1

        # Résultat final
        # Invalider le cache après création
        if success_count > 0 and context_name:
            invalidate_cache(context_name, "vms")

        console.print("\n" + "═" * 50)
        if error_count == 0:
            console.print(f"[bold green]✅ {success_count} VM(s) créée(s) avec succès![/bold green]")
        else:
            console.print(f"[bold yellow]⚠️  {success_count} créée(s), {error_count} erreur(s)[/bold yellow]")
        console.print("═" * 50)

        # Afficher les VMs créées
        if created_vms:
            table = Table(show_header=True)
            table.add_column("Nom", style="cyan")
            table.add_column("VMID")
            table.add_column("Node")
            table.add_column("IP")

            for vm in created_vms:
                ip_display = static_ip.split("/")[0] if static_ip else "DHCP"
                table.add_row(vm["name"], str(vm["vmid"]), vm["node"], ip_display)

            console.print(table)
            console.print()
            console.print("[dim]💾 Infos sauvegardées (proxmate gensshconfig)[/dim]")

    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


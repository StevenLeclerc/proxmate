"""Commandes pour gérer les templates."""

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table

from proxmate.core.config import is_configured, get_config
from proxmate.core.proxmox import ProxmoxClient
from proxmate.core.cloud_images import get_available_images, is_image_cached, download_image
from proxmate.core.template_builder import TemplateBuilder, TemplateConfig
from proxmate.utils.display import print_error, print_success, print_info, print_warning

console = Console()

# Sous-application pour les commandes template
template_app = typer.Typer(
    name="template",
    help="📦 Gestion des templates Cloud-Init",
    no_args_is_help=True,
)


@template_app.command("list")
def template_list(
    node: Optional[str] = typer.Option(None, "--node", "-n", help="Filtrer par node"),
):
    """📋 Liste les templates disponibles."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)
    
    try:
        client = ProxmoxClient()
        templates = client.get_templates()
        
        if node:
            templates = [t for t in templates if t.node == node]
        
        if not templates:
            print_warning("Aucun template trouvé.")
            console.print("\n[dim]Créez un template avec:[/dim] proxmate template create")
            return
        
        table = Table(title="📦 Templates disponibles", show_header=True, header_style="bold cyan")
        table.add_column("VMID", style="dim", width=6)
        table.add_column("Nom", style="bold")
        table.add_column("Node", style="dim")
        table.add_column("RAM", justify="right")
        table.add_column("Disque", justify="right")
        
        for t in templates:
            table.add_row(
                str(t.vmid),
                t.name,
                t.node,
                f"{t.memory_gb} GB",
                f"{t.disk_gb} GB",
            )
        
        console.print()
        console.print(table)
        console.print()
        
    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


@template_app.command("images")
def template_images():
    """🖼️  Liste les images cloud disponibles au téléchargement."""
    images = get_available_images()
    
    table = Table(title="🖼️  Images Cloud disponibles", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold")
    table.add_column("Nom")
    table.add_column("Description")
    table.add_column("En cache", justify="center")
    
    for img_id, img in images.items():
        cached = "✅" if is_image_cached(img) else "❌"
        table.add_row(img_id, img.name, img.description, cached)
    
    console.print()
    console.print(table)
    console.print()


@template_app.command("create")
def template_create():
    """🔨 Crée un nouveau template Cloud-Init (wizard interactif)."""
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)
    
    console.print(Panel.fit(
        "[bold cyan]🔨 Création d'un template Cloud-Init[/bold cyan]\n\n"
        "Ce wizard va vous guider pour créer un template VM\n"
        "prêt à l'emploi avec Cloud-Init.",
        border_style="cyan"
    ))
    console.print()
    
    try:
        client = ProxmoxClient()
        builder = TemplateBuilder(client)
        config = get_config()
        
        # 1. Sélection du node
        nodes = client.get_nodes()
        if len(nodes) == 1:
            selected_node = nodes[0].node
            print_info(f"Node sélectionné: {selected_node}")
        else:
            console.print("[bold]Nodes disponibles:[/bold]")
            for i, n in enumerate(nodes, 1):
                console.print(f"  {i}. {n.node}")
            choice = IntPrompt.ask("Sélectionnez un node", default=1)
            selected_node = nodes[choice - 1].node
        
        # 2. Sélection de l'image
        console.print("\n[bold]Images cloud disponibles:[/bold]")
        images = get_available_images()
        img_list = list(images.items())
        for i, (img_id, img) in enumerate(img_list, 1):
            cached = "[green](en cache)[/green]" if is_image_cached(img) else ""
            console.print(f"  {i}. {img.name} {cached}")
        
        img_choice = IntPrompt.ask("Sélectionnez une image", default=1)
        selected_image = img_list[img_choice - 1][1]
        
        # 3. Nom du template
        default_name = f"{selected_image.name.lower().replace(' ', '-')}-cloud"
        template_name = Prompt.ask("Nom du template", default=default_name)
        
        # 4. VMID
        next_vmid = builder.get_next_template_vmid()
        vmid = IntPrompt.ask("VMID du template", default=next_vmid)
        
        # 5. Storage
        storages = builder.get_available_storages(selected_node)
        if storages:
            console.print("\n[bold]Storages disponibles:[/bold]")
            for i, s in enumerate(storages, 1):
                console.print(f"  {i}. {s['storage']} ({s.get('type', 'unknown')})")
            storage_choice = IntPrompt.ask("Sélectionnez un storage", default=1)
            selected_storage = storages[storage_choice - 1]['storage']
        else:
            selected_storage = Prompt.ask("Storage", default=config.proxmox.default_storage)
        
        # 6. Ressources
        memory = IntPrompt.ask("Mémoire RAM (MB)", default=2048)
        cores = IntPrompt.ask("Nombre de CPU cores", default=2)
        
        # Confirmation
        console.print("\n[bold]Récapitulatif:[/bold]")
        console.print(f"  • Node: {selected_node}")
        console.print(f"  • Image: {selected_image.name}")
        console.print(f"  • Nom: {template_name}")
        console.print(f"  • VMID: {vmid}")
        console.print(f"  • Storage: {selected_storage}")
        console.print(f"  • RAM: {memory} MB")
        console.print(f"  • CPU: {cores} cores")
        
        if not Confirm.ask("\nCréer ce template?", default=True):
            print_info("Création annulée.")
            raise typer.Exit()
        
        # Créer le template
        console.print()
        template_config = TemplateConfig(
            name=template_name,
            vmid=vmid,
            node=selected_node,
            storage=selected_storage,
            image=selected_image,
            memory=memory,
            cores=cores,
        )
        
        # Note: L'import de disque via API est complexe
        # On affiche les commandes manuelles pour l'instant
        console.print("\n[yellow]⚠️  L'import automatique nécessite un accès SSH au node.[/yellow]")
        console.print("\n[bold]Exécutez ces commandes sur le node Proxmox:[/bold]\n")
        
        # Télécharger l'image d'abord
        print_info("Téléchargement de l'image...")
        image_path = download_image(selected_image)
        print_success(f"Image téléchargée: {image_path}")
        
        console.print(f"""
[cyan]# 1. Copier l'image vers le serveur Proxmox[/cyan]
scp {image_path} root@{config.proxmox.host}:/tmp/

[cyan]# 2. Sur le serveur Proxmox, exécuter:[/cyan]
qm create {vmid} --name {template_name} --memory {memory} --cores {cores} --net0 virtio,bridge=vmbr0
qm importdisk {vmid} /tmp/{selected_image.filename} {selected_storage}
qm set {vmid} --scsihw virtio-scsi-pci --scsi0 {selected_storage}:vm-{vmid}-disk-0
qm set {vmid} --ide2 {selected_storage}:cloudinit
qm set {vmid} --boot c --bootdisk scsi0
qm set {vmid} --serial0 socket --vga serial0
qm template {vmid}

[cyan]# 3. Nettoyer[/cyan]
rm /tmp/{selected_image.filename}
""")
        
        print_info("Une fois les commandes exécutées, le template sera disponible.")
        
    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


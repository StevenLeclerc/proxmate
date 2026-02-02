"""Commande init pour configurer ProxMate."""

from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from proxmate.core.config import (
    ContextConfig,
    add_context,
    is_configured,
    get_current_context_name,
    CONFIG_FILE,
)
from proxmate.utils.display import print_success, print_error, print_warning, print_info

console = Console()


def init_command():
    """
    🔧 Configure la connexion à votre cluster Proxmox.

    Cette commande vous guide à travers la configuration initiale
    pour connecter ProxMate à votre serveur Proxmox.
    """
    console.print(Panel.fit(
        "[bold cyan]🔧 Configuration de ProxMate[/bold cyan]\n\n"
        "Cette commande va configurer la connexion à votre cluster Proxmox.\n"
        "Vous aurez besoin d'un token API (créé dans Datacenter > Permissions > API Tokens).",
        border_style="cyan"
    ))
    console.print()

    # Vérifier si déjà configuré
    if is_configured():
        current = get_current_context_name()
        console.print(f"[yellow]Un contexte existe déjà: {current}[/yellow]")
        if not Confirm.ask("Créer un nouveau contexte?"):
            print_info("Utilisez 'proxmate ctx create <nom>' pour ajouter un contexte.")
            raise typer.Exit()

    # Nom du contexte
    context_name = Prompt.ask(
        "[bold]Nom du contexte[/bold]",
        default="default"
    )

    # Collecte des informations
    console.print("\n[bold]📡 Informations de connexion Proxmox[/bold]\n")

    host = Prompt.ask(
        "Adresse du serveur Proxmox",
        default="192.168.1.100"
    )

    port = int(Prompt.ask(
        "Port de l'API",
        default="8006"
    ))

    user = Prompt.ask(
        "Utilisateur API",
        default="root@pam"
    )

    console.print("\n[bold]🔑 Token API[/bold]")
    console.print("[dim]Format: Datacenter > Permissions > API Tokens[/dim]\n")

    token_name = Prompt.ask(
        "Nom du token",
        default="proxmate"
    )

    token_value = Prompt.ask(
        "Valeur secrète du token",
        password=True
    )

    verify_ssl = Confirm.ask(
        "Vérifier le certificat SSL?",
        default=False
    )

    console.print("\n[bold]⚙️  Options par défaut[/bold]\n")

    default_storage = Prompt.ask(
        "Storage par défaut",
        default="local-lvm"
    )

    default_node = Prompt.ask(
        "Node par défaut (laisser vide pour aucun)",
        default=""
    ) or None

    # Créer la configuration du contexte
    context_config = ContextConfig(
        host=host,
        port=port,
        user=user,
        token_name=token_name,
        token_value=token_value,
        verify_ssl=verify_ssl,
        default_node=default_node,
        default_storage=default_storage,
        created_at=datetime.now().isoformat(),
    )

    # Tester la connexion
    console.print("\n[bold]🔌 Test de connexion...[/bold]")

    try:
        from proxmate.core.proxmox import ProxmoxClient
        client = ProxmoxClient(context_config)
        nodes = client.get_nodes()

        if nodes:
            print_success(f"Connexion réussie! {len(nodes)} node(s) trouvé(s): {', '.join(n.node for n in nodes)}")
        else:
            print_warning("Connexion établie mais aucun node trouvé.")

    except Exception as e:
        print_error(f"Erreur de connexion: {e}")
        if not Confirm.ask("[yellow]Sauvegarder la configuration malgré l'erreur?[/yellow]"):
            print_info("Configuration annulée.")
            raise typer.Exit(1)

    # Sauvegarder le contexte
    add_context(context_name, context_config)
    console.print()
    print_success(f"Contexte '{context_name}' créé et activé!")
    console.print(f"[dim]Configuration sauvegardée dans {CONFIG_FILE}[/dim]")

    # Démarrer le daemon automatiquement
    console.print("\n[bold]🔄 Démarrage du daemon de cache...[/bold]")
    try:
        from proxmate.core.daemon import is_daemon_running, start_daemon
        import os

        if is_daemon_running():
            print_info("Le daemon est déjà en cours d'exécution.")
        else:
            pid = os.fork()
            if pid == 0:
                # Child process - devient le daemon
                start_daemon()
            else:
                # Parent process - attend un peu et vérifie
                import time
                time.sleep(1)
                if is_daemon_running():
                    print_success("Daemon démarré! Le cache sera rafraîchi toutes les 30s.")
                else:
                    print_warning("Le daemon n'a pas pu démarrer. Utilisez 'proxmate dm start' manuellement.")
    except Exception as e:
        print_warning(f"Impossible de démarrer le daemon: {e}")

    console.print("\n[dim]Vous pouvez maintenant utiliser:[/dim]")
    console.print("  • [cyan]proxmate status[/cyan] - Voir l'état du cluster")
    console.print("  • [cyan]proxmate list[/cyan] - Lister les VMs")
    console.print("  • [cyan]proxmate ctx ls[/cyan] - Lister les contextes")
    console.print("  • [cyan]proxmate dm status[/cyan] - Voir l'état du daemon")


"""Commandes de gestion des contextes (clusters Proxmox)."""

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table

from proxmate.core.config import (
    ContextConfig,
    get_current_context,
    get_current_context_name,
    list_contexts,
    set_context,
    add_context,
    remove_context,
    context_exists,
    is_configured,
)
from proxmate.utils.display import print_success, print_error, print_warning, print_info

console = Console()


# Commandes réservées pour le sous-typer
RESERVED_COMMANDS = {"ls", "create", "rm", "list"}


def ctx_command(
    name: Optional[str] = typer.Argument(None, help="Nom du contexte à activer"),
):
    """Affiche ou change le contexte actif.

    Sans argument: affiche le contexte actuel.
    Avec argument: change vers le contexte spécifié (ou propose de le créer).

    Sous-commandes disponibles via 'proxmate context':
      - proxmate context ls → liste les contextes
      - proxmate context create <name> → crée un contexte
      - proxmate context rm <name> → supprime un contexte
    """
    if name is None:
        # Afficher le contexte actuel
        _show_current_context()
    elif name in RESERVED_COMMANDS:
        # Rediriger vers les sous-commandes
        if name == "ls" or name == "list":
            ctx_ls_command()
        else:
            console.print(f"[dim]Utilisez: proxmate context {name}[/dim]")
    else:
        # Changer de contexte
        _switch_context(name)


def _show_current_context():
    """Affiche le contexte actif."""
    context_name = get_current_context_name()
    context = get_current_context()
    
    if context_name is None or context is None:
        print_warning("Aucun contexte configuré.")
        console.print("[dim]Créez un contexte avec: proxmate ctx create <nom>[/dim]")
        return
    
    console.print(f"[bold cyan]Contexte actuel:[/bold cyan] {context_name}")
    console.print(f"  [dim]Host:[/dim] {context.host}:{context.port}")
    console.print(f"  [dim]User:[/dim] {context.user}")


def _switch_context(name: str):
    """Change vers un contexte ou propose de le créer."""
    if set_context(name):
        context = get_current_context()
        print_success(f"Contexte changé: {name} ({context.host})")
    else:
        # Le contexte n'existe pas → proposer de le créer
        print_warning(f"Le contexte '{name}' n'existe pas.")
        if Confirm.ask("Créer ce contexte?", default=True):
            _create_context_wizard(name)
        else:
            console.print("[dim]Utilisez 'proxmate ctx ls' pour voir les contextes disponibles.[/dim]")


def ctx_ls_command():
    """Liste tous les contextes disponibles."""
    contexts = list_contexts()
    current = get_current_context_name()
    
    if not contexts:
        print_warning("Aucun contexte configuré.")
        console.print("[dim]Créez un contexte avec: proxmate ctx create <nom>[/dim]")
        return
    
    table = Table(title="📋 Contextes Proxmox")
    table.add_column("Nom", style="cyan")
    table.add_column("Host")
    table.add_column("User", style="dim")
    table.add_column("Créé le", style="dim")
    table.add_column("Actif", justify="center")
    
    for name, ctx in contexts.items():
        is_active = "✓" if name == current else ""
        created = ctx.created_at[:10] if ctx.created_at else "-"
        table.add_row(
            name,
            f"{ctx.host}:{ctx.port}",
            ctx.user,
            created,
            f"[green]{is_active}[/green]" if is_active else "",
        )
    
    console.print(table)


def ctx_create_command(
    name: str = typer.Argument(..., help="Nom du nouveau contexte"),
):
    """Crée un nouveau contexte (cluster Proxmox)."""
    if context_exists(name):
        print_error(f"Le contexte '{name}' existe déjà.")
        raise typer.Exit(1)
    
    _create_context_wizard(name)


def _create_context_wizard(name: str):
    """Assistant de création d'un contexte."""
    console.print(f"\n[bold cyan]🔧 Création du contexte '{name}'[/bold cyan]\n")
    
    host = Prompt.ask("Adresse du serveur Proxmox", default="192.168.1.100")
    port = int(Prompt.ask("Port", default="8006"))
    user = Prompt.ask("Utilisateur API", default="root@pam")
    token_name = Prompt.ask("Nom du token API", default="proxmate")
    token_value = Prompt.ask("Valeur du token (secret)", password=True)
    verify_ssl = Confirm.ask("Vérifier le certificat SSL?", default=False)
    
    context = ContextConfig(
        host=host,
        port=port,
        user=user,
        token_name=token_name,
        token_value=token_value,
        verify_ssl=verify_ssl,
        created_at=datetime.now().isoformat(),
    )
    
    add_context(name, context)
    print_success(f"Contexte '{name}' créé et activé!")
    console.print(f"[dim]Host: {host}:{port}[/dim]")


def ctx_rm_command(
    name: str = typer.Argument(..., help="Nom du contexte à supprimer"),
):
    """Supprime un contexte."""
    if not context_exists(name):
        print_error(f"Le contexte '{name}' n'existe pas.")
        raise typer.Exit(1)
    
    current = get_current_context_name()
    if name == current:
        print_warning(f"'{name}' est le contexte actif.")
    
    if Confirm.ask(f"Supprimer le contexte '{name}'?", default=False):
        if remove_context(name):
            print_success(f"Contexte '{name}' supprimé.")
        else:
            print_error("Erreur lors de la suppression.")


"""Commandes pour lister les VMs et templates."""

from typing import Optional

import typer
from rich.console import Console

from proxmate.core.config import is_configured
from proxmate.core.proxmox import ProxmoxClient
from proxmate.utils.display import (
    print_error,
    display_vms_table,
    display_templates_table,
    console,
)


def list_command(
    node: Optional[str] = typer.Option(
        None, "--node", "-n",
        help="Filtrer par node spécifique"
    ),
    status: Optional[str] = typer.Option(
        None, "--status", "-s",
        help="Filtrer par statut (running, stopped)"
    ),
    all_vms: bool = typer.Option(
        False, "--all", "-a",
        help="Inclure les templates dans la liste"
    ),
    fast: bool = typer.Option(
        False, "--fast", "-f",
        help="Mode rapide (sans récupération des IPs)"
    ),
):
    """
    📋 Liste toutes les VMs du cluster.

    Affiche les VMs avec leur état, adresse IP, CPU et RAM.
    Par défaut, les templates sont exclus.

    Utilisez --fast pour un affichage plus rapide (sans IPs).
    """
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    try:
        client = ProxmoxClient()
        vms = client.get_vms(node=node, fetch_ips=not fast)

        # Filtrer par statut si demandé
        if status:
            vms = [vm for vm in vms if vm.status == status]

        console.print()
        display_vms_table(vms, show_templates=all_vms)
        console.print()

    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


def templates_command(
    node: Optional[str] = typer.Option(
        None, "--node", "-n",
        help="Filtrer par node spécifique"
    ),
):
    """
    📦 Liste les templates disponibles.
    
    Affiche uniquement les templates VM du cluster.
    """
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)
    
    try:
        client = ProxmoxClient()
        templates = client.get_templates()
        
        # Filtrer par node si demandé
        if node:
            templates = [t for t in templates if t.node == node]
        
        console.print()
        display_templates_table(templates)
        console.print()
        
    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


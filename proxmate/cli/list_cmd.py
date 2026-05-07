"""Commandes pour lister les VMs et templates."""

from typing import Optional

import typer
from rich.console import Console

from proxmate.core.config import is_configured, get_current_context_name
from proxmate.core.proxmox import ProxmoxClient, VMInfo
from proxmate.core.cache import (
    get_vms_cache,
    get_templates_cache,
    set_vms_cache,
    set_templates_cache,
    is_cache_valid,
    format_cache_age,
    vms_from_cache,
)
from proxmate.utils.display import (
    print_error,
    print_info,
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
    refresh: bool = typer.Option(
        False, "--refresh", "-r",
        help="Forcer le rafraîchissement du cache"
    ),
):
    """
    📋 Liste toutes les VMs du cluster.

    Affiche les VMs avec leur état, adresse IP, CPU et RAM.
    Par défaut, les templates sont exclus.

    Utilisez --fast pour un affichage plus rapide (sans IPs).
    Utilisez --refresh pour forcer un appel API.
    """
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    try:
        context_name = get_current_context_name()
        cache_used = False
        cache_age_str = None

        # Essayer le cache d'abord (sauf si --refresh)
        if not refresh and context_name and is_cache_valid(context_name, "vms"):
            cached_data, timestamp = get_vms_cache(context_name)
            if cached_data:
                vms = vms_from_cache(cached_data)
                cache_used = True
                cache_age_str = format_cache_age(context_name, "vms")

        # Fallback API si pas de cache valide
        if not cache_used:
            client = ProxmoxClient()
            vms = client.get_vms(node=node, fetch_ips=not fast)
            # Mettre à jour le cache
            if context_name:
                set_vms_cache(context_name, vms)

        # Filtrer par node si demandé (si on vient du cache, le filtre n'a pas été appliqué)
        if cache_used and node:
            vms = [vm for vm in vms if vm.node == node]

        # Filtrer par statut si demandé
        if status:
            vms = [vm for vm in vms if vm.status == status]

        console.print()

        # Afficher l'info du cache
        if cache_used and cache_age_str:
            console.print(f"[dim]📦 Cache: {cache_age_str}[/dim]")

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
    refresh: bool = typer.Option(
        False, "--refresh", "-r",
        help="Forcer le rafraîchissement du cache"
    ),
):
    """
    📦 Liste les templates disponibles.

    Affiche uniquement les templates VM du cluster.
    Utilisez --refresh pour forcer un appel API.
    """
    if not is_configured():
        print_error("ProxMate n'est pas configuré. Exécutez 'proxmate init' d'abord.")
        raise typer.Exit(1)

    try:
        context_name = get_current_context_name()
        cache_used = False
        cache_age_str = None

        # Essayer le cache d'abord (sauf si --refresh)
        if not refresh and context_name and is_cache_valid(context_name, "templates"):
            cached_data, timestamp = get_templates_cache(context_name)
            if cached_data:
                templates = vms_from_cache(cached_data)
                cache_used = True
                cache_age_str = format_cache_age(context_name, "templates")

        # Fallback API si pas de cache valide
        if not cache_used:
            client = ProxmoxClient()
            templates = client.get_templates()
            # Mettre à jour le cache
            if context_name:
                set_templates_cache(context_name, templates)

        # Filtrer par node si demandé
        if node:
            templates = [t for t in templates if t.node == node]

        console.print()

        # Afficher l'info du cache
        if cache_used and cache_age_str:
            console.print(f"[dim]📦 Cache: {cache_age_str}[/dim]")

        display_templates_table(templates)
        console.print()

    except Exception as e:
        print_error(f"Erreur: {e}")
        raise typer.Exit(1)


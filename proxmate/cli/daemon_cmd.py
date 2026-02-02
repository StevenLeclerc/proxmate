"""Commandes de gestion du daemon ProxMate."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from proxmate.core.daemon import (
    start_daemon,
    stop_daemon,
    restart_daemon,
    is_daemon_running,
    get_daemon_status,
    get_daemon_logs,
)
from proxmate.core.cache import (
    get_cache_info,
    format_cache_age,
    list_cached_contexts,
)
from proxmate.core.config import get_current_context_name, list_contexts
from proxmate.utils.display import print_success, print_error, print_warning, print_info

console = Console()

# Sous-application Typer pour les commandes daemon
daemon_app = typer.Typer(
    name="dm",
    help="🔄 Gestion du daemon de cache",
    no_args_is_help=True,
)


@daemon_app.command("start")
def start_command():
    """▶️  Démarre le daemon de cache."""
    if is_daemon_running():
        print_warning("Le daemon est déjà en cours d'exécution.")
        status = get_daemon_status()
        console.print(f"  PID: [cyan]{status['pid']}[/cyan]")
        return
    
    console.print("[bold]🚀 Démarrage du daemon...[/bold]")
    
    # Le start_daemon() fait un fork, donc on ne revient pas ici dans le child
    import os
    pid = os.fork()
    if pid == 0:
        # Child process - devient le daemon
        start_daemon()
    else:
        # Parent process - attend un peu et vérifie
        import time
        time.sleep(1)
        if is_daemon_running():
            status = get_daemon_status()
            print_success(f"Daemon démarré (PID: {status['pid']})")
        else:
            print_error("Échec du démarrage du daemon. Vérifiez les logs.")


@daemon_app.command("stop")
def stop_command():
    """⏹️  Arrête le daemon de cache."""
    if not is_daemon_running():
        print_warning("Le daemon n'est pas en cours d'exécution.")
        return
    
    console.print("[bold]🛑 Arrêt du daemon...[/bold]")
    
    if stop_daemon():
        print_success("Daemon arrêté.")
    else:
        print_error("Échec de l'arrêt du daemon.")


@daemon_app.command("restart")
def restart_command():
    """🔄 Redémarre le daemon de cache."""
    console.print("[bold]🔄 Redémarrage du daemon...[/bold]")
    
    was_running = is_daemon_running()
    if was_running:
        stop_daemon()
        import time
        time.sleep(1)
    
    # Fork pour démarrer le nouveau daemon
    import os
    pid = os.fork()
    if pid == 0:
        start_daemon()
    else:
        import time
        time.sleep(1)
        if is_daemon_running():
            status = get_daemon_status()
            print_success(f"Daemon redémarré (PID: {status['pid']})")
        else:
            print_error("Échec du redémarrage du daemon.")


@daemon_app.command("status")
def status_command():
    """📊 Affiche le statut du daemon et du cache."""
    status = get_daemon_status()
    
    # Panel statut daemon
    if status["running"]:
        daemon_status = f"[green]●[/green] En cours d'exécution (PID: {status['pid']})"
    else:
        daemon_status = "[red]●[/red] Arrêté"
    
    console.print(Panel(
        daemon_status,
        title="[bold]🔄 Daemon ProxMate[/bold]",
        border_style="cyan"
    ))
    
    # Table des caches par contexte
    contexts = list_contexts()
    current_ctx = get_current_context_name()
    
    if contexts:
        table = Table(title="📦 État du cache", show_header=True)
        table.add_column("Contexte", style="cyan")
        table.add_column("VMs", justify="center")
        table.add_column("Templates", justify="center")
        table.add_column("Nodes", justify="center")
        table.add_column("Storages", justify="center")
        
        for ctx_name in contexts.keys():
            marker = " ✓" if ctx_name == current_ctx else ""
            cache_info = get_cache_info(ctx_name)
            
            def format_age(cache_type: str) -> str:
                age = format_cache_age(ctx_name, cache_type)
                if age == "pas de cache":
                    return "[dim]-[/dim]"
                return f"[green]{age}[/green]"
            
            table.add_row(
                f"{ctx_name}{marker}",
                format_age("vms"),
                format_age("templates"),
                format_age("nodes"),
                format_age("storages"),
            )
        
        console.print()
        console.print(table)
    
    console.print()
    console.print(f"[dim]Fichier log: {status['log_file']}[/dim]")


@daemon_app.command("logs")
def logs_command(
    lines: int = typer.Option(30, "--lines", "-n", help="Nombre de lignes à afficher"),
):
    """📜 Affiche les logs du daemon."""
    log_lines = get_daemon_logs(lines)
    
    if not log_lines:
        print_warning("Aucun log disponible.")
        return
    
    console.print(Panel(
        "".join(log_lines),
        title=f"[bold]📜 Dernières {len(log_lines)} lignes du log[/bold]",
        border_style="dim"
    ))


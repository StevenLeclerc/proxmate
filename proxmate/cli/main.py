"""Point d'entrée principal de la CLI ProxMate."""

import typer
from rich.console import Console

from proxmate import __version__

# Import des commandes
from proxmate.cli.init_cmd import init_command
from proxmate.cli.status_cmd import status_command
from proxmate.cli.list_cmd import list_command, templates_command
from proxmate.cli.template_cmd import template_app
from proxmate.cli.create_cmd import create_command
from proxmate.cli.vm_cmd import start_command, stop_command, restart_command, delete_command
from proxmate.cli.snapshot_cmd import snapshot_app
from proxmate.cli.sshconfig_cmd import gensshconfig_command
from proxmate.cli.ctx_cmd import ctx_command, ctx_ls_command, ctx_create_command, ctx_rm_command

console = Console()

app = typer.Typer(
    name="proxmate",
    help="🖥️  ProxMate - CLI pour gérer votre cluster Proxmox",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.command("version")
def version():
    """Affiche la version de ProxMate."""
    console.print(f"[bold cyan]ProxMate[/bold cyan] version [green]{__version__}[/green]")


# Enregistrer les commandes simples
app.command("init")(init_command)
app.command("status")(status_command)
app.command("list")(list_command)
app.command("templates")(templates_command)

# Commande de création de VM
app.command("create")(create_command)

# Commandes de contrôle des VMs
app.command("start")(start_command)
app.command("stop")(stop_command)
app.command("restart")(restart_command)
app.command("delete")(delete_command)

# Commande de génération de config SSH
app.command("gensshconfig")(gensshconfig_command)

# Enregistrer les sous-commandes
app.add_typer(template_app, name="template")
app.add_typer(snapshot_app, name="snapshot")

# Gestion des contextes
# proxmate ctx → affiche le contexte actuel
# proxmate ctx <name> → change de contexte (ou propose création)
app.command("ctx", help="🔄 Affiche ou change le contexte actif")(ctx_command)

# Sous-commandes pour la gestion des contextes
# proxmate context ls → liste les contextes
# proxmate context create <name> → crée un contexte
# proxmate context rm <name> → supprime un contexte
ctx_app = typer.Typer(
    name="context",
    help="🔄 Gestion des contextes (clusters Proxmox)",
)

ctx_app.command("ls", help="Liste tous les contextes")(ctx_ls_command)
ctx_app.command("create", help="Crée un nouveau contexte")(ctx_create_command)
ctx_app.command("rm", help="Supprime un contexte")(ctx_rm_command)

app.add_typer(ctx_app, name="context")


if __name__ == "__main__":
    app()


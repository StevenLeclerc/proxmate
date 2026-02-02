"""Daemon ProxMate pour le refresh automatique du cache."""

import os
import sys
import signal
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from proxmate.core.config import CONFIG_DIR, list_contexts, ContextConfig
from proxmate.core.cache import (
    set_vms_cache,
    set_templates_cache,
    set_nodes_cache,
    set_storages_cache,
)


# Fichiers du daemon
PID_FILE = CONFIG_DIR / "daemon.pid"
LOG_FILE = CONFIG_DIR / "daemon.log"

# Intervalle de refresh en secondes
REFRESH_INTERVAL = 30

# Flag pour arrêt gracieux
_shutdown_requested = False


def _setup_logging() -> logging.Logger:
    """Configure le logging du daemon."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("proxmate-daemon")
    logger.setLevel(logging.INFO)
    
    # Handler fichier
    handler = logging.FileHandler(LOG_FILE)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)
    
    return logger


def _signal_handler(signum, frame):
    """Gère les signaux pour arrêt gracieux."""
    global _shutdown_requested
    _shutdown_requested = True


def _write_pid() -> None:
    """Écrit le PID du daemon dans le fichier."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid() -> None:
    """Supprime le fichier PID."""
    if PID_FILE.exists():
        PID_FILE.unlink()


def get_daemon_pid() -> Optional[int]:
    """Récupère le PID du daemon s'il existe."""
    if not PID_FILE.exists():
        return None
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # Vérifier si le process existe
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # PID invalide ou process mort
        _remove_pid()
        return None


def is_daemon_running() -> bool:
    """Vérifie si le daemon est en cours d'exécution."""
    return get_daemon_pid() is not None


def _refresh_context(context_name: str, context_config: ContextConfig, logger: logging.Logger) -> None:
    """Rafraîchit le cache pour un contexte donné."""
    try:
        from proxmate.core.proxmox import ProxmoxClient
        
        client = ProxmoxClient(context_config)
        
        # Refresh des nodes
        nodes = client.get_nodes()
        set_nodes_cache(context_name, nodes)
        logger.debug(f"[{context_name}] {len(nodes)} nodes mis en cache")
        
        # Refresh des VMs (sans IPs pour la rapidité)
        vms = client.get_vms(fetch_ips=False)
        set_vms_cache(context_name, vms)
        logger.debug(f"[{context_name}] {len(vms)} VMs mises en cache")
        
        # Refresh des templates
        templates = [vm for vm in vms if vm.template]
        set_templates_cache(context_name, templates)
        logger.debug(f"[{context_name}] {len(templates)} templates mis en cache")
        
        # Refresh des storages (pour chaque node)
        all_storages = []
        for node in nodes:
            try:
                storages = client.get_storages(node.node)
                for s in storages:
                    s["_node"] = node.node  # Ajouter le node pour référence
                all_storages.extend(storages)
            except Exception:
                pass
        set_storages_cache(context_name, all_storages)
        logger.debug(f"[{context_name}] {len(all_storages)} storages mis en cache")
        
        logger.info(f"[{context_name}] Cache rafraîchi: {len(vms)} VMs, {len(templates)} templates, {len(nodes)} nodes")
        
    except Exception as e:
        logger.error(f"[{context_name}] Erreur lors du refresh: {e}")


def _daemon_loop(logger: logging.Logger) -> None:
    """Boucle principale du daemon."""
    global _shutdown_requested
    
    logger.info("Daemon démarré")
    
    while not _shutdown_requested:
        try:
            # Récupérer tous les contextes
            contexts = list_contexts()
            
            if not contexts:
                logger.warning("Aucun contexte configuré")
            else:
                for context_name, context_config in contexts.items():
                    if _shutdown_requested:
                        break
                    _refresh_context(context_name, context_config, logger)
            
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}")
        
        # Attendre avant le prochain refresh (avec vérification shutdown)
        for _ in range(REFRESH_INTERVAL):
            if _shutdown_requested:
                break
            time.sleep(1)
    
    logger.info("Daemon arrêté")


def _daemonize() -> None:
    """Double fork pour créer un vrai daemon Unix."""
    # Premier fork
    try:
        pid = os.fork()
        if pid > 0:
            # Parent exit
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #1 échoué: {e}\n")
        sys.exit(1)

    # Devenir leader de session
    os.setsid()

    # Deuxième fork
    try:
        pid = os.fork()
        if pid > 0:
            # Parent exit
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #2 échoué: {e}\n")
        sys.exit(1)

    # Rediriger stdin/stdout/stderr vers /dev/null
    sys.stdout.flush()
    sys.stderr.flush()

    with open("/dev/null", "r") as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    with open("/dev/null", "w") as devnull:
        os.dup2(devnull.fileno(), sys.stdout.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())


def start_daemon() -> bool:
    """
    Démarre le daemon en arrière-plan.

    Returns:
        True si le daemon a été démarré, False s'il tournait déjà.
    """
    if is_daemon_running():
        return False

    # Daemoniser
    _daemonize()

    # Configurer les signaux
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Écrire le PID
    _write_pid()

    # Configurer le logging
    logger = _setup_logging()

    try:
        _daemon_loop(logger)
    finally:
        _remove_pid()

    return True


def stop_daemon() -> bool:
    """
    Arrête le daemon.

    Returns:
        True si le daemon a été arrêté, False s'il ne tournait pas.
    """
    pid = get_daemon_pid()
    if pid is None:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        # Attendre que le process se termine
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                _remove_pid()
                return True
        # Force kill si toujours vivant
        os.kill(pid, signal.SIGKILL)
        _remove_pid()
        return True
    except ProcessLookupError:
        _remove_pid()
        return True
    except PermissionError:
        return False


def restart_daemon() -> bool:
    """Redémarre le daemon."""
    stop_daemon()
    time.sleep(1)
    return start_daemon()


def get_daemon_status() -> dict:
    """
    Récupère le statut du daemon.

    Returns:
        Dict avec pid, running, log_file, etc.
    """
    pid = get_daemon_pid()
    return {
        "running": pid is not None,
        "pid": pid,
        "pid_file": str(PID_FILE),
        "log_file": str(LOG_FILE),
    }


def get_daemon_logs(lines: int = 50) -> list[str]:
    """Récupère les dernières lignes du log du daemon."""
    if not LOG_FILE.exists():
        return []

    try:
        with open(LOG_FILE, "r") as f:
            all_lines = f.readlines()
            return all_lines[-lines:]
    except Exception:
        return []


# 🖥️ ProxMate

**CLI pour gérer votre cluster Proxmox** - Création de VMs automatisée avec Cloud-Init.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Fonctionnalités

- 🔧 **Configuration simple** - Wizard interactif pour configurer la connexion Proxmox
- 📊 **Status cluster** - Vue d'ensemble des nodes et ressources
- 📋 **Gestion des VMs** - Lister, créer, démarrer, arrêter, supprimer
- 📦 **Templates Cloud-Init** - Créer des templates à partir d'images cloud (Ubuntu, Debian, etc.)
- 🚀 **Création multiple** - Créer plusieurs VMs avec répartition automatique sur les nodes
- 📸 **Snapshots** - Gérer les snapshots de vos VMs
- 🔑 **SSH Config** - Génération automatique de `~/.ssh/config`
- 🔄 **Multi-contextes** - Gérer plusieurs clusters Proxmox

## 📦 Installation

### Option 1 : Binaire précompilé (recommandé)

Téléchargez le binaire pour votre plateforme depuis les [Releases](https://github.com/StevenLeclerc/proxmate/releases) :

| Plateforme | Fichier |
|------------|---------|
| Linux x86_64 | `proxmate-linux-x86_64` |
| Windows x86_64 | `proxmate-windows-x86_64.exe` |
| macOS Intel | `proxmate-macos-x86_64` |
| macOS Apple Silicon | `proxmate-macos-arm64` |

```bash
# Linux/macOS : rendre exécutable et déplacer dans le PATH
chmod +x proxmate-*
sudo mv proxmate-* /usr/local/bin/proxmate
```

### Option 2 : Depuis les sources

```bash
# Cloner le repo
git clone https://github.com/StevenLeclerc/proxmate.git
# ou via SSH
# git clone git@github.com:StevenLeclerc/proxmate.git
cd proxmate

# Créer un environnement virtuel
python3 -m venv .venv
source .venv/bin/activate

# Installer
pip install -e .
```

## 🚀 Démarrage rapide

### 1. Configuration initiale

```bash
proxmate init
```

Vous aurez besoin de :
- L'adresse IP/hostname de votre cluster Proxmox
- Un API Token (créé dans Datacenter → Permissions → API Tokens)

### 2. Vérifier la connexion

```bash
proxmate status
```

### 3. Créer une VM

```bash
proxmate create
```

## 📖 Commandes

| Commande | Description |
|----------|-------------|
| `proxmate init` | Configure la connexion Proxmox |
| `proxmate status` | Affiche l'état du cluster |
| `proxmate list` | Liste toutes les VMs |
| `proxmate templates` | Liste les templates disponibles |
| `proxmate create` | Crée une ou plusieurs VMs (wizard interactif) |
| `proxmate start <vmid>` | Démarre une VM |
| `proxmate stop <vmid>` | Arrête une VM |
| `proxmate restart <vmid>` | Redémarre une VM |
| `proxmate delete` | Supprime une ou plusieurs VMs (sélection interactive) |
| `proxmate gensshconfig` | Génère la config SSH pour les VMs |
| `proxmate template images` | Liste les images cloud disponibles |
| `proxmate template create` | Crée un template Cloud-Init |
| `proxmate snapshot list <vmid>` | Liste les snapshots d'une VM |
| `proxmate snapshot create <vmid>` | Crée un snapshot |
| `proxmate ctx` | Affiche le contexte actuel |
| `proxmate ctx <name>` | Change de contexte |
| `proxmate ctx ls` | Liste tous les contextes |
| `proxmate context create <name>` | Crée un nouveau contexte |
| `proxmate context rm <name>` | Supprime un contexte |

## 🔄 Multi-contextes

ProxMate supporte plusieurs clusters Proxmox via un système de contextes :

```bash
# Voir le contexte actuel
proxmate ctx

# Lister tous les contextes
proxmate ctx ls

# Changer de contexte (propose création si inexistant)
proxmate ctx production

# Créer un nouveau contexte
proxmate context create staging

# Supprimer un contexte
proxmate context rm old-cluster
```

## ⚙️ Configuration

La configuration est stockée dans `~/.proxmate/config.yaml` :

```yaml
current_context: default
contexts:
  default:
    host: 192.168.1.10
    port: 8006
    user: root@pam
    token_name: proxmate
    token_value: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    verify_ssl: false
    default_storage: local-lvm
default_user: ubuntu
ssh_public_key_path: ~/.ssh/id_rsa.pub
```

## 🔑 Création d'un API Token Proxmox

1. Connectez-vous à l'interface web Proxmox
2. Allez dans **Datacenter → Permissions → API Tokens**
3. Cliquez sur **Add**
4. Sélectionnez l'utilisateur (ex: `root@pam`)
5. Donnez un nom au token (ex: `proxmate`)
6. **Décochez** "Privilege Separation" pour hériter des permissions de l'utilisateur
7. Copiez le token généré

## 📁 Structure du projet

```
proxmate/
├── cli/           # Commandes CLI (Typer)
├── core/          # Logique métier
│   ├── config.py      # Gestion de la configuration
│   ├── proxmox.py     # Client API Proxmox
│   └── cloud_images.py # Images cloud supportées
└── utils/         # Utilitaires (affichage Rich)
```

## 📝 License

MIT License - voir [LICENSE](LICENSE)

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une PR.


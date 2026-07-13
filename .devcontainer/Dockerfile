# Yuri devcontainer Dockerfile
# Last updated: 2026-07-13 (bump: Python 3.14, Node 24 LTS, npm 11)

# This Dockerfile sets up a development environment with:
# - Ubuntu 24.04 base image
# - System dependencies for development
# - mise (runtime version manager) for managing Python and Node versions
# - uv (fast Python package manager) for installing Python tools
# - Claude Code (native installation) and OpenAI Codex (npm package)


FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies in a single layer
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && apt-get install -y --no-install-recommends \
    # Build essentials for native extensions
    build-essential \
    # SSL/crypto libraries
    libssl-dev libffi-dev \
    # Database clients
    sqlite3 mysql-client postgresql-client \
    # Python build dependencies
    libbz2-dev libreadline-dev libsqlite3-dev \
    zlib1g-dev liblzma-dev \
    # Useful utilities
    jq curl wget git unzip zip make \
    # Required for adding third-party apt repos and OAuth flows
    ca-certificates gnupg xdg-utils \
    # Large file storage for design assets (images, fonts, Figma exports)
    git-lfs \
    # GitHub CLI for PR/issue workflows
    gh \
    # Shell
    zsh \
    # Terminal multiplexer
    tmux \
    # Process/system inspection
    htop procps lsof strace \
    # File utilities
    tree file less \
    # Man pages
    man-db manpages \
    # Secret scanning
    gitleaks \
    # Terminal editors (fallback)
    vim-tiny nano \
    # Playwright Chromium runtime libraries.
    # Names use the t64 suffix introduced in Ubuntu 24.04's time_t64 transition;
    # see https://playwright.dev/docs/browsers#install-system-dependencies.
    libnss3 libnspr4 libatk-bridge2.0-0t64 libatk1.0-0t64 \
    libatspi2.0-0t64 libcairo2 libcups2t64 libdbus-1-3 \
    libdrm2 libgbm1 libglib2.0-0t64 libpango-1.0-0 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libasound2t64 libxshmfence1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


# Switch to vscode user for tool installation
USER vscode

# Set zsh as default shell for vscode user
RUN sudo chsh -s $(which zsh) vscode


# Install mise (runtime version manager)
RUN curl -fsSL https://mise.run | sh
ENV PATH="/home/vscode/.local/bin:${PATH}"

# Configure mise to auto-activate
RUN echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc && \
    echo 'eval "$(~/.local/bin/mise activate zsh)"' >> ~/.zshrc


# Install uv (fast Python package manager).
# Pinned to a version >= 14 days old at template release time. Astral
# publishes versioned installers at https://astral.sh/uv/<version>/install.sh.
# uv 0.5.0+ installs to ~/.local/bin (already on PATH from the mise step).
RUN curl -LsSf https://astral.sh/uv/0.11.8/install.sh | sh


# Configure a 7-day release cooldown for uv globally.
# Mirrors the npm `min-release-age=7` policy: uv refuses to resolve
# package versions published less than 7 days ago, blocking freshly
# poisoned releases before maintainers/registries pull them.
# `exclude-newer` accepts relative durations in uv's standalone config.
RUN mkdir -p ~/.config/uv \
    && printf 'exclude-newer = "7 days"\n' > ~/.config/uv/uv.toml


# Pre-install Python and Node via mise and make them the global default.
# `mise install` alone only downloads the runtime; `mise use --global`
# also writes ~/.config/mise/config.toml so they resolve outside a project.
# Node 24 ships with npm 11; we pin npm to 11.18.0 below for the
# min-release-age cooldown (npm 11.10.0+).
RUN mise use --global python@3.14.6 node@24.18.0


# Pin npm to a version that supports `min-release-age` (added in 11.10.0)
# and configure a 7-day release cooldown globally for the vscode user.
# Rationale: blocks freshly-published malicious versions (e.g. the
# 2026-03-31 axios token-compromise RAT was yanked within ~4 hours).
# Note: npm's `min-release-age` is in DAYS (unlike pnpm/Yarn which use
# minutes, or Bun which uses seconds). All pins below are >= 14 days old
# as of the template release date, which gives the npm/uv release-age
# filters plenty of margin and keeps the build deterministic.
RUN mise exec node -- npm install -g npm@11.18.0 \
    && mise exec node -- npm config set min-release-age 7 --location=user \
    && test "$(mise exec node -- npm config get min-release-age)" = "7"


# Install Claude Code using native installation (recommended method)
# The native install provides auto-updates and doesn't require Node.js
RUN curl -fsSL https://claude.ai/install.sh | bash

# Install OpenAI Codex from the official npm package without a version pin.
# npm's global 7-day release-age cooldown still applies, avoiding freshly
# published or partially published versions while letting Codex move quickly.
# Codex user-local config/auth/session/plugin state is persisted by the
# devcontainer volume and is intentionally not managed by generated projects.
RUN mise exec node -- npm install -g @openai/codex

# Pre-create persisted AI state mountpoints so fresh Docker named volumes inherit
# writable vscode ownership instead of root ownership.
RUN mkdir -p /home/vscode/.claude /home/vscode/.codex \
    && chown -R vscode:vscode /home/vscode/.claude /home/vscode/.codex


# Install global npm packages, pinned to versions >= 14 days old.
RUN mise exec node -- npm install -g \
    typescript@6.0.3 \
    tsx@4.21.0 \
    prettier@3.8.3 \
    eslint@10.2.1


# Install global Python tools via uv, pinned to versions >= 14 days old.
RUN uv tool install ruff==0.15.12 && \
    uv tool install black==26.3.1 && \
    uv tool install mypy==1.20.2 && \
    uv tool install pytest==9.0.3


# Install pinned ZSH plugins and enable them in .zshrc.
# Cloning into ~/.oh-my-zsh/custom/plugins/ is necessary but not
# sufficient — Oh My Zsh only loads plugins listed in the
# plugins=(...) array, which the base image initialises to (git).
ARG ZSH_AUTOSUGGESTIONS_REF=e52ee8ca55bcc56a17c828767a3f98f22a68d4eb
ARG ZSH_SYNTAX_HIGHLIGHTING_REF=db085e4661f6aafd24e5acb5b2e17e4dd5dddf3e
RUN git clone https://github.com/zsh-users/zsh-autosuggestions \
      ~/.oh-my-zsh/custom/plugins/zsh-autosuggestions \
 && git -C ~/.oh-my-zsh/custom/plugins/zsh-autosuggestions checkout --detach "$ZSH_AUTOSUGGESTIONS_REF" \
 && git clone https://github.com/zsh-users/zsh-syntax-highlighting \
      ~/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting \
 && git -C ~/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting checkout --detach "$ZSH_SYNTAX_HIGHLIGHTING_REF" \
 && sed -i 's/^plugins=(git)$/plugins=(git zsh-autosuggestions zsh-syntax-highlighting)/' ~/.zshrc

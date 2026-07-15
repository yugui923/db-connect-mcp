# DevContainer requirements

| ID | Area | Requirement |
| --- | --- | --- |
| `DEV-001` | Environment | Ubuntu 24.04 runs as `vscode` with the project at `/workspace`. |
| `DEV-002` | Network | The container uses host networking. |
| `DEV-003` | Limits | 12 GiB RAM, 12 GiB additional swap (24 GiB combined), 6 CPU cores, 4,096 PIDs, and 4 GiB shared memory. |
| `DEV-004` | Mounts | The workspace and separate Claude/Codex state volumes are mounted; the Docker socket is not. |
| `DEV-005` | Runtimes | mise provides Python and Node; uv and npm provide package management with seven-day release cooldowns. |
| `DEV-006` | Tooling | Common build, Git/GitHub, database-client, shell, inspection, formatting, linting, typing, testing, and secret-scanning tools are installed. |
| `DEV-007` | Agents | Claude Code and OpenAI Codex are installed. |
| `DEV-008` | Lifecycle | Only the audited post-create setup runs automatically; project dependencies are not installed. |

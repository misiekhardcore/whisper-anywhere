
## 2026-06-12: opencode plugin docs

Source: https://opencode.ai/docs/plugins/

### Plugin installation
- **Local files**: `.opencode/plugins/` (project) or `~/.config/opencode/plugins/` (global) — auto-discovered
- **npm packages**: `"plugin": ["package-name"]` in `opencode.json` — auto-installed via Bun, cached in `~/.cache/opencode/node_modules/`
- **npm + config**: Both regular and scoped (`@scope/pkg`) packages work
- **Local plugins with npm deps**: Add `package.json` to the config directory with dependencies

### Plugin structure
- Export a function: `export default async ({ project, client, $, directory, worktree }) => { ... }` or `export const Name = async (...) => ...`
- Returns hooks object
- TypeScript: `import type { Plugin } from "@opencode-ai/plugin"`

### Key hooks for our plugin
- `event`: Subscribe to all bus events
- `command.execute.before`: Intercept custom commands (used for `/voice` toggle)
- `tool`: Register custom tools
- `shell.env`: Inject env vars
- `client.tui.appendPrompt()`: Inject text into TUI input

### Load order
1. Global config → Project config
2. Global plugins → Project plugins

### Our plugin approach
- npm package `whisper-anywhere-opencode` is correct
- `export default` is fine (both default and named exports work)
- Plugin spawns `whisper-anywhere --stdout` as child process via `$` Bun shell or `Bun.spawn`

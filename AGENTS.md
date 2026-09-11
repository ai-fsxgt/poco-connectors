# Repository Guidelines

## Project Structure & Directory Naming

Each root directory is an independently installable connector. Use lowercase kebab-case names like `dingtalk/` or `weknora/`; never include `poco` or a version. Keep versions only in `manifest.json.package_version`; upgrade in place. Keep all package files inside the connector; shared references live in `docs/`.

## Connector Architecture

Before choosing Python, Node, or a bundled executable, verify the manifest schema, Provider runner, and target OS/architecture; a runtime installed elsewhere does not prove support. Prefer remote MCP, using a program adapter only when required. For large APIs or CLIs, expose a pinned searchable catalog and few stable dispatchers instead of thousands of tools. Treat invocations as isolated: omit commands needing a daemon, persistent local state, or unbounded listeners. Synchronize the manifest, locales, bundled Skill, and references with actual behavior.

## Safety & Supply Chain

Use a default-deny tool policy. Writes and destructive actions use `retry: never`; sensitive writes and destructive actions require confirmation. At invocation, revalidate catalog effect and confirmation so callers cannot downgrade risk. Disable upstream SDK or CLI retries where ambiguous writes could repeat. Never commit credentials or user data.

For vendored executables, pin the upstream version and commit, preserve patches and `PATCHES.md`, build deterministic archives per supported architecture, and update SHA-256 checksums with artifacts.

## Development Commands

There is no repository-wide build. Check one connector from the repository root:

```bash
connector_dir=weknora
python -m compileall "$connector_dir/provider"
for file in "$connector_dir/manifest.json" "$connector_dir"/locales/*.json; do python -m json.tool "$file" >/dev/null; done
```

Create a versioned ZIP from inside the connector directory, excluding caches and `.DS_Store`.

## Coding Style

Use Python 3.12, four-space indentation, PEP 8, `snake_case` names, `UPPER_CASE` constants, and `_`-prefixed internal helpers. Provider operations return protocol-v1 JSON. Format JSON with two-space indentation and keep locale keys identical across declared languages.

## Testing & Release Validation

No automated suite is included. Exercise affected provider operations via stdin/stdout JSON, including invalid configuration, authorization failures, discovery, invocation, and remote errors. Validate the final ZIP—not only its source directory—with the Poco backend loader in `docs/connector-package-development.mdx`. Check archive contents, manifest references, locales, Skills, tool discovery, risk metadata, and checksums. Report mocked checks separately from real OAuth, MCP, and account verification.

## Commits & Pull Requests

Use concise Conventional Commit subjects such as `feat: add Slack connector`. Keep each commit and, when practical, pull request focused on one connector. State its version, changes, validation, and credential, permission, or binary implications.

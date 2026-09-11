# Repository Guidelines

## Project Structure & Module Organization

Each root connector directory is independently installable and owns all package files. Shared framework references live in `docs/`.

## Connector Directory Naming

Use a stable lowercase kebab-case service name, such as `dingtalk/` or `weknora/`. Names must contain neither `poco` nor a version; `poco-dingtalk/` and `dingtalk-1.0.0/` are prohibited. Record versions only in `manifest.json.package_version`. Upgrade in the existing directory instead of creating a versioned sibling.

## Build, Test, and Development Commands

There is no repository-wide build system. Select one connector and run focused checks from the repository root:

```bash
connector_dir=weknora
python -m compileall "$connector_dir/provider"
for file in "$connector_dir/manifest.json" "$connector_dir"/locales/*.json; do python -m json.tool "$file" >/dev/null; done
```

These commands check Python and JSON. From the connector directory, create a versioned archive with `zip -X -r ../weknora-1.0.2.zip . -x '*/__pycache__/*' '*.pyc' '.DS_Store'`. Before publishing, use the backend loader described in `docs/connector-package-development.mdx`.

## Coding Style & Naming Conventions

Use Python 3.12, four-space indentation, PEP 8, `snake_case` functions and variables, and `UPPER_CASE` constants. Prefix internal helpers with `_`. Provider operations must return protocol-v1 JSON. Format JSON with two-space indentation. Root connector names use lowercase kebab-case without platform or version identifiers. `package_version` uses strict `major.minor.patch`. Keep locale keys identical across declared languages.

## Testing Guidelines

No automated suite or coverage threshold is included. Test the affected connector by exercising every changed provider operation through stdin/stdout JSON, including invalid configuration, authorization errors, tool discovery, invocation, and remote failures. Confirm tool schemas match its manifest policies. Verify OAuth and remote MCP changes against a real service; mocks do not establish compatibility.

## Commit & Pull Request Guidelines

This checkout has no commit history from which to infer conventions. Until one is established, use concise Conventional Commit-style subjects such as `feat: add Slack connector` or `fix: validate DingTalk token expiry`. Keep each commit focused on one connector or one documentation concern; split unrelated connector changes.

Pull requests should cover one connector when practical. Identify its version, summarize contract or runtime changes, list validation, and call out credential, permission, or vendored-binary implications. Link relevant issues. Screenshots are only needed for visible asset or presentation changes.

## Security & Package Integrity

Never commit live credentials or tokens. Treat provider programs and vendored binaries as trusted executable code: review their source or provenance, preserve archive checksums, and update checksums whenever a vendored archive changes.

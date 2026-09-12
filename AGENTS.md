# Repository Guidelines

## Project Structure & Directory Naming

Each root directory is an independently installable connector. Use lowercase kebab-case names like `dingtalk/` or `weknora/`; never include `poco` or a version. Keep versions only in `manifest.json.package_version`; upgrade in place. Keep all package files inside the connector; shared references live in `docs/`. When adding, removing, or changing the version of a connector, update the `README.md` "Current Connectors" list in the same change.

### Required Assets Directory

Every newly created or migrated connector must include an `assets/` directory, even when no icon is provided. Generating icon files is optional; the user may add custom icons later. If the directory would otherwise be empty, include `assets/.gitkeep` so Git preserves it. Before completing authoring or migration, verify that `assets/` exists; when packaging, verify that the final ZIP also includes this directory.

### Connector Versioning

When updating an existing connector, keep its manifest `key` unchanged because the key is the installed connector identity. Increase `manifest.json.package_version` for every package content update; use a minor version bump for new capabilities (for example, `1.0.0` to `1.1.0`). Do not use an upstream Skill or source release version as the connector package version. Keep the README version and manifest version synchronized.

## Connector Architecture

Before choosing Python, Node, or a bundled executable, verify the manifest schema, Provider runner, and target OS/architecture; a runtime installed elsewhere does not prove support. Prefer remote MCP, using a program adapter only when required. For large APIs or CLIs, expose a pinned searchable catalog and few stable dispatchers instead of thousands of tools. Treat invocations as isolated: omit commands needing a daemon, persistent local state, or unbounded listeners. Synchronize the manifest, locales, bundled Skill, and references with actual behavior.

## Migration & Source Reuse

Before creating files during a migration, inventory reusable material from the source connector. Directly copy platform-neutral content whose purpose and semantics already match, including documentation, general Skills, references, API schemas and catalogs, icons and other assets, configuration, and provider code. Preserve reusable files verbatim instead of regenerating or paraphrasing equivalent content. When adaptation is required, copy the source file as the baseline and make only the necessary Poco-specific changes. Do not rebuild a reusable asset from scratch without a concrete incompatibility; this reuse-first workflow avoids unnecessary implementation time, review churn, and model-token usage.

After copying, verify licensing and provenance, manifest paths, platform assumptions, installation and authorization instructions, and runtime behavior. Never carry over credentials, user data, caches, or generated build artifacts. Ensure copied documentation, locales, Skills, references, configuration, and code remain consistent with the connector's actual behavior.

## Safety & Supply Chain

Use a default-deny tool policy. Writes and destructive actions use `retry: never`; sensitive writes and destructive actions require confirmation. At invocation, revalidate catalog effect and confirmation so callers cannot downgrade risk. Disable upstream SDK or CLI retries where ambiguous writes could repeat. Never commit credentials or user data.

For upstream CLIs and other connector executables, first look for an official release binary for the target platform and use that artifact when available. Build from source only when no suitable official binary exists or the user explicitly requests source changes. Bundled connector executables target Linux amd64 only. Do not add arm64, macOS, Windows, or other runtime builds unless the user explicitly changes this platform requirement. Pin the upstream version and commit, preserve official checksums and `PATCHES.md` when applicable, and update SHA-256 checksums with artifacts. Platform compatibility issues should be reported to the Poco platform owner instead of triggering an unrequested custom rebuild.

## Development Commands

There is no repository-wide build. Check one connector from the repository root:

```bash
connector_dir=weknora
python -m compileall "$connector_dir/provider"
for file in "$connector_dir/manifest.json" "$connector_dir"/locales/*.json; do python -m json.tool "$file" >/dev/null; done
```

Create a versioned ZIP from inside the connector directory, excluding caches and `.DS_Store`.

Before packaging a connector update, verify that the manifest key is unchanged, the package version is higher than the previous release, the README entry matches the manifest, and the final ZIP contains every manifest-referenced locale, asset, Provider, Skill, and reference file.

## Coding Style

Use Python 3.12, four-space indentation, PEP 8, `snake_case` names, `UPPER_CASE` constants, and `_`-prefixed internal helpers. Provider operations return protocol-v1 JSON. Format JSON with two-space indentation and keep locale keys identical across declared languages.

## Testing & Release Validation

No automated suite is included. Exercise affected provider operations via stdin/stdout JSON, including invalid configuration, authorization failures, discovery, invocation, and remote errors. Validate the final ZIP—not only its source directory—with the Poco backend loader in `docs/connector-package-development.mdx`. Check archive contents, manifest references, locales, Skills, tool discovery, risk metadata, and checksums. Report mocked checks separately from real OAuth, MCP, and account verification.

During connector authoring and migration, do not invoke the Poco backend loader, background installation, or backend package validation. Work directly in the repository's standard connector directory structure and use the local compile, JSON, protocol, and archive checks above. Run backend-loader validation only as a release step for the final ZIP.

## Commits & Pull Requests

Use concise Conventional Commit subjects such as `feat: add Slack connector`. Keep each commit and, when practical, pull request focused on one connector. State its version, changes, validation, and credential, permission, or binary implications.

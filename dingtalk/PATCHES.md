# Bundled DWS runtime

This package bundles the Linux amd64 build of DingTalk Workspace CLI 1.0.61 from commit `50eb73a0906c5911c5c25f9c7106b6ead4f14f62`.

The Poco build applies three narrow runtime changes before compilation:

- `internal/transport/client.go`: set the default JSON-RPC retry count to zero.
- `internal/helpers/aitable.go`: set the AI table helper retry count to zero.
- `internal/localio/upload.go`: make one upload attempt instead of three.

These changes prevent a single approved write or destructive invocation from being repeated automatically after an ambiguous network failure. Platform-level write and destructive retry policy is also `never`.

# Debug signing

`ticketbox-debug.keystore` is the public, repository-level debug signing key for
`grayDebug` and `internalDebug`.

It is not a release key and must not be used for `release` builds. Its purpose is
to keep local debug builds and GitHub Actions debug APK artifacts on the same
signing certificate so `adb install -r` can replace an existing debug install.

Certificate SHA-256:

```text
91:15:22:41:7C:C5:01:6E:DA:DC:FF:AD:DE:7B:90:4D:92:8D:C4:2D:66:A7:97:84:44:45:AC:B5:BC:AE:10:6F
```

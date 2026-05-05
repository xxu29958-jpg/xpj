# 0014. iOS Shortcut Uses File Body

## Status

Accepted.

## Context

iOS Shortcuts can send URL content with either a `File` request body or a `Form` request body. During iOS 26.4 real-device testing, the form configuration could display `file = converted image` in the Shortcuts editor but still reach the backend as an invalid request. The backend then returned:

```json
{"error":"invalid_request","message":"请求参数不正确。"}
```

Cloudflare also returned `error code: 1010` for shortcut/API requests without a clear `User-Agent`.

## Decision

iPhone shortcut uploads must use:

```text
Request body: File
File: Converted Image
```

Required headers:

```http
Upload-Token: UPLOAD_TOKEN
User-Agent: TicketBox/1.0 iOS-Shortcut
```

The backend continues to support `multipart/form-data` for standard HTTP clients, but iOS shortcut documentation and runbooks should not recommend form mode as the primary path.

## Consequences

- iOS 26.4 upload setup is simpler and matches the verified real-device flow.
- Cloudflare Browser Integrity Check does not block the shortcut request because a stable client `User-Agent` is present.
- Future shortcut docs must not tell users to prefer `multipart/form-data` form mode.

# /owner vendor self-hosted assets

This directory stores third-party scripts used by the loopback-only `/owner`
console. All files are self-hosted; CDN loading is not allowed.

| File | Source | Version | License |
| --- | --- | --- | --- |
| `qrcode.js` | `https://registry.npmjs.org/qrcode-generator/-/qrcode-generator-2.0.4.tgz`, `package/dist/qrcode.js` (byte-identical, sha256 `79ec86f82856005b1c887905cfccfcfbec3821ca61c7fd5a952faa5f778f791c`) | 2.0.4 | MIT |
| `qrcode.LICENSE` | `https://github.com/kazuhikoarase/qrcode-generator` `master` `LICENSE` (the npm tarball ships no license file; the file header inside `qrcode.js` carries the same MIT notice) | 2.0.4 | MIT |

Note: the word "QR Code" is a registered trademark of DENSO WAVE
INCORPORATED (stated in the `qrcode.js` header; keep the notice intact).

Update rules:

1. Verify the kazuhikoarase/qrcode-generator release and npm metadata.
2. Download the exact npm tarball and replace `qrcode.js` and
   `qrcode.LICENSE` together.
3. Update `docs/rules/REFERENCES.md`.
4. Do not modify vendor files by hand.

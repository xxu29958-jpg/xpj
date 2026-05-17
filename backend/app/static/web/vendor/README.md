# /web vendor self-hosted assets

This directory stores third-party scripts used by the local-only `/web` UI.
All files are self-hosted; CDN loading is not allowed.

| File | Source | Version | License |
| --- | --- | --- | --- |
| `echarts.min.js` | `https://registry.npmjs.org/echarts/-/echarts-6.0.0.tgz`, `package/dist/echarts.min.js` | 6.0.0 | Apache-2.0 |
| `echarts.LICENSE` | same tarball, `package/LICENSE` | 6.0.0 | Apache-2.0 |

Update rules:

1. Verify Apache ECharts official release and npm metadata.
2. Download the exact npm tarball and replace `echarts.min.js` and `echarts.LICENSE` together.
3. Update `docs/rules/REFERENCES.md` and the related ADR.
4. Do not modify minified vendor files by hand.

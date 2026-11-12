# MIT license transition — 12 November 2026

At the owner's explicit instruction, project-owned code now uses the **standard
MIT License**, copyright (c) 2026 Ziwei Huang. This replaces the previous PolyForm
Noncommercial license and custom personal-trading permission for this revision.
Commercial use, modification and redistribution are permitted under MIT's terms;
there is no additional project-specific commercial restriction.

This change applies to the workspace, all five Python packages, the harness and
the DSH plugin. Dependency implementations, externally supplied material and
vendor data retain their own copyrights and terms.

## Exact text and upstream attribution

The [OSI MIT text](https://opensource.org/license/mit) grants broad use,
modification, distribution and sublicensing rights subject to retaining its
copyright and permission notices. It does not require downstream projects to use
MIT. The owner selected MIT for this project; matching DSH's license is a choice,
not a condition imposed by DSH. Selecting MIT does not replace other dependencies'
license obligations or market-data entitlements.

`LICENSE` contains the standard MIT text with only the copyright holder/year
filled in. Its SHA-256 is
`1ba48843bce9d0054fd71d3caede16e5de6f097c90e04367bae418de73bd25b4`.
It carries no extra conditions or custom exceptions.

DeepSeek Harness is pinned to upstream source
`e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`. Its
[exact LICENSE](https://github.com/deepseek-ai/deepseek-harness/blob/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/LICENSE)
is reproduced in `THIRD-PARTY-NOTICES.md`, including `Copyright (c) 2026 DeepSeek`,
the permission grant and warranty disclaimer. That complete upstream text has
SHA-256 `ebb4f09972aee8608be255debaf78451a68e95c290f55c240dec2ecfa16ea6be`.
The project license does not replace DeepSeek's copyright with the project owner's.
No DSH runtime source is vendored by this transition.

## Distribution consistency

- Root, five Python package projects and harness declare SPDX `MIT` and include
  `LICENSE`, `NOTICE`, and `THIRD-PARTY-NOTICES.md`. Each has byte-identical copies
  of those files.
- The DSH plugin declares `MIT` in `package.json` and explicitly includes those
  same three files in its package payload.
- The obsolete `ADDITIONAL-PERMISSION.md` files are removed. Docker instructions
  copy the current notices without referring to the deleted permission file.
- `scripts/check_licenses.py` validates the exact project/upstream text, all
  metadata/copies, wheel and sdist metadata/payloads, and the packed DSH plugin.
  It also rejects the obsolete permission file in source or built archives.
- CI now verifies actual Python distributions and the plugin archive in addition
  to source consistency; artifacts are built for verification, not published to
  PyPI, npm or a container registry.

The earlier bounded dependency inventory remains relevant as provenance, not a
new comprehensive audit: packages including Psycopg (LGPL), certifi (MPL), and
other installed/bundled components retain their original terms and notices.
See [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md). This transition makes no
claim that every dependency or redistributed binary image is MIT licensed.

## History and verification

The previous licensing review is preserved in
[commit 3694525](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team/blob/3694525d1d945233de9d75e5a8b76cf2833bce17/docs/LICENSING_REVIEW.md).
Earlier dated decisions and experimental snapshots remain historical records;
the current LICENSE and this transition describe the new revision.

Local verification passed: source/static checks, 62 harness tests, all five wheels,
all five source distributions and the packed DSH plugin. The existing repository
suite passed 862 tests with 54 database integration skips and one existing
Starlette/httpx deprecation warning. Environment failures (sandbox dependency
resolution and unavailable local npm) were retained and resolved using permitted
dependency access and the installed pnpm packer.

Exact results, artifact hashes and log hashes are recorded in
[LICENSING_VALIDATION.json](LICENSING_VALIDATION.json). No live model or data
provider requests were made. Hosted CI is reported separately on the new PR.

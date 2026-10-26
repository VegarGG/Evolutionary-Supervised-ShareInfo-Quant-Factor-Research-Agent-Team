# Licensing scope and bounded inventory — October 26, 2026

The owner approved unchanged PolyForm Noncommercial 1.0.0, copyright
2026 Ziwei Huang, the separate personal own-account trading permission, and
the research-purpose disclaimer. Separately licensed commercial uses remain
possible. These choices apply only to owned or authorized project rights;
they do not establish ownership of third-party material.

The inventory starts from main commit
`3c528beedb8307539cc6bb3d788e58e23c0598a9`. It found no previous root license,
notice, Python license metadata, vendored dependency tree, or tracked pilot
dataset/archive. A source/header search found no identified copied code with an
incompatible license. Contributor labels and absent notices are not proof of
complete ownership clearance. Referenced research documents and external pilot
inputs retain their own provenance and rights.

## Exact license source

`LICENSE` is the unmodified 4,563-byte Markdown file from the official
[PolyForm source repository](https://github.com/polyformproject/polyform-licenses/blob/1.0.0/PolyForm-Noncommercial-1.0.0.md),
Git blob `5ecc88cfc4b1cff608ed640efe913c9dd97935c3`, SHA256
`c0ea4a896d2c8c394b29f9427589996db826cd501c512279ff0ed3ef48fabbe5`.
The copyright notice and custom additional permission are separate files.
Metadata identifies the underlying license as `PolyForm-Noncommercial-1.0.0`;
the supplement is not represented as an SPDX exception.

## Dependencies and actual distribution

The check inspected locked direct/transitive dependency metadata and installed
notice files in the Linux Python 3.12 environment. It also inspected the Docker
recipes and source tree. Dependencies are referenced, not vendored in project
wheels/sdists. Production Docker builds install `--no-dev --no-editable` and copy
the complete virtual environment, including distribution notices; CI installs
development tools as well. The recipes do not delete dependency licenses or
the base image's `/usr/share/doc` notices.

| Components inspected | Observed terms / material qualification |
| --- | --- |
| Pydantic, pydantic-core/settings, Polars/runtime, PyYAML, Lark and their runtime helpers | MIT or BSD/PSF permissive terms, with installed notice files |
| NumPy 2.5.4 | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`; bundled component notices remain applicable |
| SciPy 1.18.1 | BSD plus bundled-component notices, including OpenBLAS and GCC runtime libraries with the Runtime Library Exception |
| psycopg / psycopg-binary 3.3.6 | `LGPL-3.0-only`; development/test dependencies on the reviewed main branch, with additional obligations if distributed in images |
| Hypothesis and Pathspec | MPL-2.0; development tools, no modified vendored source identified |
| Other installed locked development tools | MIT/BSD/Apache/PSF or CC0 metadata; no identified conflicting copied source |
| colorama and tzdata | Conditional locked dependencies not installed on this Linux environment; exact distributed files were not audited |
| Python 3.12 slim-bookworm, PostgreSQL 16 and uv 0.11.19 images | Upstream image digests are pinned; their OS/runtime components retain independent licenses. No complete per-image SBOM/source-offer audit was performed |

The original licensing PR excluded the then-ongoing Stage 2 changes. The combined
Stage 2 branch now includes Alembic/SQLAlchemy/Mako (MIT), MarkupSafe
(BSD-3-Clause), and runtime Psycopg. The same third-party boundary applies;
THIRD-PARTY-NOTICES.md and all package copies identify the runtime Psycopg use.

Stage 3 also uses Psycopg in the registry. Its HTTP dependencies were checked
against installed locked metadata: FastAPI 0.162.0, AnyIO 4.15.1 and annotated-doc
0.0.5 declare MIT; Starlette 1.10.0 and Uvicorn 0.54.0 declare BSD-3-Clause.
The HTTPX 0.28.1 test client declares BSD-3-Clause. No dependency source is
vendored or relicensed; this metadata check retains the inventory limits below.

No specific conflict was identified that blocks licensing the project's owned
source under the approved terms. This is a bounded technical inventory, not a
legal clearance or a claim that every binary image is ready for redistribution.
In particular, retain LGPL replacement/debugging rights and satisfy applicable
source/notice obligations before distributing an image containing Psycopg.
CI-built image archives are not publicly published container images by this
change; redistribution obligations still need assessment when artifacts are
distributed. See [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).

## Consistency checks

All five package projects and the workspace metadata declare the same SPDX
license expression. Each package carries byte-identical copies of the root
license, notice, additional permission, and third-party notice so independent
wheel/sdist consumers receive the complete project terms. `just check` checks
that identity and the official license hash. After building all workspace
packages, run `python -m scripts.check_licenses --distributions dist` to verify
the actual wheel metadata, wheel license payloads, and sdist payloads.

Local verification for this change: `just check` passed; `just test` passed all
329 tests against the real PostgreSQL service with the preserved pilot inputs
available (no skips). `uv build --all-packages` and the distribution check passed
for all five wheels and five sdists. No provider calls, image publishing, or
evaluator activation occurred. Hosted workflow results are reported separately
on the licensing PR; local checks do not imply hosted CI is green.

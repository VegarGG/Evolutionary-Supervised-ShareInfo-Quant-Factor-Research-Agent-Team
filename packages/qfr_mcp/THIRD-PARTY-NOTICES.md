# Third-party materials and distribution

LICENSE and ADDITIONAL-PERMISSION.md apply only to project rights that Ziwei
Huang owns or is authorized to license. Dependencies, operating-system packages,
and other third-party materials retain their own licenses. No noncommercial
restriction in this project is imposed on those materials. This document does
not replace their full license texts, copyright notices, or source obligations.

The repository references dependencies in pyproject.toml and uv.lock; it does
not vendor their source trees. Project wheels and source distributions include
project code and these project notices, not the dependency implementations.
The Docker recipes install dependencies and copy the resulting virtual
environment, including its .dist-info license files. The final Python image
also contains Python and Debian components with their own notices, including
those under /usr/share/doc. Preserve those files when redistributing images.

The bounded review recorded in docs/LICENSING_REVIEW.md identified:

- Runtime dependencies under MIT, BSD, PSF, and related permissive terms,
  including Pydantic, Polars, NumPy, SciPy, PyYAML, Lark, and threadpoolctl
  (BSD-3-Clause, used by the evaluator to inspect effective numerical thread pools). Binary wheels can
  bundle additional components. NumPy and SciPy include component-specific
  notices; SciPy's wheel also records OpenBLAS and GCC runtime-library terms
  with the GCC Runtime Library Exception.
- The HTTP services use FastAPI (MIT), Uvicorn (BSD-3-Clause) and HTTPX
  (BSD-3-Clause) from the existing dependency lock. HTTPX is a direct core client
  dependency; the evaluator declares FastAPI/Uvicorn for its GET-only feedback
  edge. Dependency versions and upstream notices remain unchanged.
- Ed25519 signing/verification uses cryptography 50.0.2 (Apache-2.0 OR
  BSD-3-Clause); its locked CFFI dependency uses MIT-0 and Pycparser uses
  BSD-3-Clause. Wheels may bundle OpenSSL and other components; retain their
  complete upstream license files when distributing installed environments.
- Psycopg and psycopg-binary under LGPL-3.0-only. The evaluator, registry and
  Stage 4 research database service use them at runtime as well as in development/test environments.
  Their unmodified library files and
  notices must remain separable and replaceable. Any image distributor must
  satisfy the applicable LGPL source, notice, installation/relinking, and
  reverse-engineering-for-debugging requirements. The project license does not
  remove those rights. A project license notice alone is not an LGPL source
  offer or proof of binary redistribution compliance.
- Development tools under additional terms, including MPL-2.0 for Hypothesis
  and Pathspec, Apache-2.0 for some tooling, and CC0 for rust-just. These tools
  are included in the CI environment, not the production --no-dev install.

The pinned Python, PostgreSQL, and uv container images retain their respective
upstream and bundled-component licenses. Local builds and CI artifacts are not
a separately audited binary distribution. Before publishing container images,
review the actual image's components, preserve notices, and provide any source
or other materials required by their licenses.

No licensed pilot datasets, original uploaded archives, or credentials are
granted or distributed under this project license. Referenced research and
external source material retain their owners' rights. If a specific uncredited
copy or incompatible obligation is identified, resolve it before distributing
the affected material; this bounded inventory is not a complete ownership or
legal-clearance determination.

## Vendored Docker seccomp profile

The evaluator includes the unchanged Moby default seccomp policy, separately
licensed Apache-2.0 by the Moby contributors. Source, frozen SHA256 and the complete
license accompany it under `qfr_eval/sandbox/vendor/`. Project noncommercial terms
do not replace third-party permissions. This policy is shipped in the evaluator
wheel and image; no runtime upstream download is required.

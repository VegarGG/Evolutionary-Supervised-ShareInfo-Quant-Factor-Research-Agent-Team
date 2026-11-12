# Third-party materials and distribution

The MIT License in LICENSE applies only to project rights that Ziwei Huang owns
or is authorized to license. Dependencies, operating-system packages and other
third-party materials retain their own licenses. This notice does not relicense
those materials or replace their copyright notices or source obligations.

The repository references dependencies in pyproject.toml and uv.lock; it does
not vendor their source trees. Project wheels and source distributions include
project code and these project notices, not the dependency implementations.
The Docker recipes install dependencies and copy the resulting virtual
environment, including its .dist-info license files. The final Python image
also contains Python and Debian components with their own notices, including
those under /usr/share/doc. Preserve those files when redistributing images.

The bounded review recorded in docs/LICENSING_REVIEW.md identified:

- Runtime dependencies under MIT, BSD, Apache-2.0, ISC, PSF, and related
  permissive terms, including Pydantic, pydantic-settings, PyYAML, structlog,
  Typer, FastAPI, Starlette, Uvicorn, the MCP Python SDK, HTTPX, SQLAlchemy,
  Alembic, jsonschema, and cryptography. Binary wheels can bundle additional
  components with their own notices.
- certifi under MPL-2.0, used unmodified as a transitive runtime dependency of
  HTTPX. Its source remains available from its upstream distribution.
- Psycopg and psycopg-binary under LGPL-3.0-only. They are runtime dependencies
  of the registry, research, evaluation and MCP services as well as
  development/test dependencies. Their unmodified library files and notices
  must remain separable and replaceable. Any image distributor must satisfy the
  applicable LGPL source, notice, installation/relinking, and
  reverse-engineering-for-debugging requirements. The project license does not
  remove those rights. A project license notice alone is not an LGPL source
  offer or proof of binary redistribution compliance.
- Development tools under additional terms, including MPL-2.0 for Hypothesis
  and Pathspec and Apache-2.0 for some tooling. These tools are included in the
  CI and test environments, not the production --no-dev install.

The pinned Python, PostgreSQL, and uv container images retain their respective
upstream and bundled-component licenses. Local builds and CI artifacts are not
a separately audited binary distribution. Before publishing container images,
review the actual image's components, preserve notices, and provide any source
or other materials required by their licenses.

No licensed market data, factor pools, uploaded archives, or credentials are
granted or distributed under this project license. Referenced research and
external source material retain their owners' rights. If a specific uncredited
copy or incompatible obligation is identified, resolve it before distributing
the affected material; this bounded inventory is not a complete ownership or
legal-clearance determination.

## Quant Factor Harness prototype

The separate `harness/uv.lock` pins DeepSeek Harness SDK/runtime 0.2.2rc2
(upstream MIT), BaoStock 0.9.4 (upstream BSD), and RQData 3.8.2, alongside its
other dependencies. Installed packages retain their upstream notices; DSH is
used through its SDK and plugin API, without a vendored runtime or agent-loop fork.
The project is licensed under MIT following the owner's 12 November 2026
instruction. Vendor data permissions remain separate from SDK licenses, including
for a free endpoint.

The iFind adapter was independently implemented after inspecting the HTTP protocol
in the owner's Opinion-Radar-System revision
`000254bc8abab2797fc270dbdf65dfe3879b1f07`. It does not vendor ORS source.
AKShare's pinned source was inspected for a comparison probe; AKShare is not a
runtime dependency or an automatic fallback. Source links and the tested scope
are recorded in `docs/harness/DATA_SOURCES.md`.

## DeepSeek Harness copyright and permission notice

MIT License

Copyright (c) 2026 DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

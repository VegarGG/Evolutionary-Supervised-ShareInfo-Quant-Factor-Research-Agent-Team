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

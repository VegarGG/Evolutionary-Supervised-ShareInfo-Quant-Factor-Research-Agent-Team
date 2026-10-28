# Vendored Moby seccomp policy

`moby-default.json` is the unchanged official Moby default seccomp profile,
retrieved 2026-10-28 from
https://github.com/moby/profiles/blob/main/seccomp/default.json .
Its SHA256 is
`514c38e72edc5363e87287ea87212211172c6c3251a974ca21ebfd05a56c7f5d`.
The profile is frozen by content hash; builds never fetch a moving upstream file.

Moby contributors license this material under Apache-2.0. The unchanged license
is included as `LICENSE.moby`; project PolyForm terms do not replace these rights.
QFR passes the profile explicitly with all capabilities dropped. QFR has not
added syscall allowances or replaced it with an unconfined policy. Validate both
supported architectures independently; a JSON/hash check is not runtime evidence.

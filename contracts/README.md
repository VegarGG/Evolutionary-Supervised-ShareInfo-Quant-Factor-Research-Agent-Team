# Public contract surface

The source of truth is `packages/qfr_core/src/qfr_core/contracts/` plus the public
ConfigDocument envelope. `public-contracts.json` enumerates every public model and enum,
including nested models. Run `just schemas` after source changes; `just check` rejects drift.
Every contract has a generated JSON Schema and one valid/invalid structural example.
All five semantic artifact kinds also have complete common-manifest examples.

These are synthetic shape examples. Zero hashes and signatures are placeholders, and no
example is authenticated evidence. Unknown provider identities/capabilities/prices stay null;
illustrative routing is not authorization for a paid call. Config templates remain draft.
Pydantic also enforces cross-field invariants that JSON Schema cannot express alone.

Private epoch, OfficialRecord and TrialLedgerEntry schemas live only in qfr_eval and are
excluded from public generation. ReleasedReport has a closed, profile-specific projection.
Signature verification, authorized admission, independent delivery checking, publication
hashing and runtime business logic belong to later stages. A boolean receipt-verification
field describes a trusted check result; a client assertion must never substitute for that check.

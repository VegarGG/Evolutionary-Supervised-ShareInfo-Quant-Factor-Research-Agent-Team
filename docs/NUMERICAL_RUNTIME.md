# Numerical execution identity

The Mac run of `3fad621` exposed an unsupported assumption: NumPy/SciPy can use
Apple Accelerate while threadpoolctl reports no libraries. An empty observation
does not establish a thread count. Linux development tests did not validate Apple
compatibility. The Apple follow-up remains subject to native verification.

## Apple Accelerate profile

For new native Apple ARM64 evaluator identities, `capture_runtime` explicitly
selects single-threaded BLAS/LAPACK using Apple's public `BLASSetThreading` API and
checks `BLASGetThreading`. The mode is local to the calling thread, not a host
preference. Apple's adaptive multi-threaded mode has no fixed observed count, so
it cannot satisfy this profile. This may reduce BLAS throughput; it provides a
verifiable count without changing statistical formulas or tolerances.

The versioned `apple_runtime_policy_v1.json` is packaged with the evaluator and
its hash is recorded. The implementation requires native Darwin/ARM64, the
public threading APIs (macOS 15 or later), explicit new-Accelerate build linkage
for its consumers, successful API read-back and actual loaded system-framework
evidence. Unavailable APIs, ambiguous linkage or incomplete observations fail
closed. `VECLIB_MAXIMUM_THREADS` alone never establishes compliance.

Identity includes the macOS version/build, hardware model/chip labels obtained by
two allowlisted read-only `sysctlbyname` queries, numerical extension binary hashes,
and each loaded Accelerate image's Mach-O UUID, CPU fields and SHA256 of its
mapped read-only `__TEXT` bytes. These are code-segment fingerprints, not claims
to hash an entire standalone dylib: modern dyld-cache libraries may have no such
file. ASLR addresses are excluded. Both BLAS and LAPACK images must be present.
Bounds are 4,096 images/commands, 1 MiB of load commands, 128 MiB of text per image
and 512 MiB total. Hashing reads mapped memory without a same-sized copy. Fixed
2x2 NumPy/SciPy preflight operations resolve lazy code before capture/verification;
they use no research data or confirmation observations.

`verify_runtime` reads the calling thread's actual mode without changing it.
Drift is refused before measurement or a screening claim. Moving work to another
thread does not inherit a correctness claim; that thread must satisfy verification.
The CLI bootstrap restores the frozen single-threaded profile before numerical
imports, then compares the actual initialized identity. OS/library changes are
incompatibilities, not permission to relabel an old result.

Trusted numerical worker threads call `initialize_worker_thread(runtime)` before
work, for example through `ThreadPoolExecutor(initializer=initialize_worker_thread,
initargs=(runtime,))`. Screening worker construction uses the same entry point;
an object moved to another thread requires that thread's initializer. The lease
renewal thread only performs database ownership updates and does not initialize
numerical execution. Process-wide Polars/BLAS pools and environment values must
already match; the thread initializer changes none of them.

Runtime capture, CLI bootstrap and worker initialization share a once-per-thread
setup guard. Only a fresh thread can select the frozen Accelerate mode. Reused
threads verify their actual execution without resetting it, including when
capturing another identity. Failed setup requires a fresh thread after readiness
is fixed. `verify_runtime` remains observation-only at each job and persistence
boundary, so drift cannot be hidden by initializing again before a write.

Linux continues to record its observed Polars and threadpoolctl-backed pools.
Its numerical identity remains version 1 with byte-equivalent serialization.
Apple uses numerical identity version 2 inside runtime identity version 2.
Legacy runtime identities retain their original serialization and cannot be
silently promoted to an execution pin. Existing records, goldens, hashes,
measurement settings, windows and query accounting remain unchanged.

## Verification

Cloud parser, schema and refusal tests use explicitly synthetic mappings/APIs;
they are not Apple acceptance. Native tests must run on the actual Mac:

```bash
.venv/bin/python -m pytest -q \
  tests/evaluator/test_apple_runtime.py \
  tests/evaluator/test_numerical_runtime.py \
  tests/evaluator/test_runtime_threads.py
```

The native SDK test compiles a tiny trusted C program against the already
installed Apple SDK with a 45-second timeout. It independently verifies enum
values, ABI width, setter status and getter result. Missing SDK/compiler/API
fails that check; the test neither installs tools nor changes their selection.
Other native tests perturb only the test thread's API mode, verify rejection and
restoration, and compare exact hashes in real subprocesses with different initial
Polars settings. Record all effective identities and the result on the real Mac;
Linux skips are explicitly unrun.

The matching-settings and Polars-mismatch subprocess fixtures explicitly bootstrap
all frozen controls, then retain their requested Polars value before imports. A
serialized identity alone does not initialize Accelerate's thread-local mode in a
new process. The full-restoration case separately proves that bootstrap overrides
a conflicting Polars default. A separate native child switches Accelerate back to
adaptive mode after bootstrap and must fail before producing any measurement.
Verification itself never repairs drift; all exact hash assertions are retained.

With initialized test PostgreSQL and original `QFR_PILOT_ROOT`, run
`tests/evaluator/test_records.py::test_evl_04_cli_reproduces_frozen_record_despite_later_trials`
using `--require-postgres`, first with parent `POLARS_MAX_THREADS=4`, then with the
normal Mac default. Result, series, fingerprints and clusters must match exactly.
Use a fresh counted test context; never amend old records. Native host evidence
and Docker Desktop Linux-container evidence remain distinct. These checks do not
resolve the separate runsc sandbox readiness blocker.

The worker suite exercises four real concurrent threads with exact output hashes
and no process-environment changes. Native Apple tests deliberately change a
worker's API mode after initialization and require refusal from initialization,
verification, recapture and screening before any claim. With required PostgreSQL,
the concurrent screening retry must still produce one immutable record, one
trial and one budget reservation. Its native drift negative test must produce
none and leave the running ownership state unfinished:

```bash
.venv/bin/python -m pytest --require-postgres -q \
  tests/registry/test_intake.py::test_screening_concurrent_retry_is_one_immutable_record_trial_and_budget_slot \
  tests/registry/test_intake.py::test_screening_worker_initializes_on_own_thread_before_claim \
  tests/registry/test_intake.py::test_native_screening_thread_drift_writes_no_record_trial_or_budget_slot
```

## Primary references

- [Apple BLASSetThreading](https://developer.apple.com/documentation/accelerate/blassetthreading(_:))
  and [BLASGetThreading](https://developer.apple.com/documentation/accelerate/blasgetthreading()).
- [Apple threading modes](https://developer.apple.com/documentation/accelerate/blas_threading).
- [Apple dyld image inspection](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/dyld.3.html)
  and [official Mach-O declarations](https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/loader.h).
- [NumPy show_config](https://numpy.org/doc/2.3/reference/generated/numpy.show_config.html).
- [Apple sysctlbyname](https://developer.apple.com/documentation/kernel/1387446-sysctlbyname):
  hardware reads use NULL/zero write arguments; no system configuration is altered.
- Upstream threadpoolctl [Accelerate detection](https://github.com/joblib/threadpoolctl/issues/135)
  and [thread-control limitations](https://github.com/joblib/threadpoolctl/issues/136).

# Security design

*Assume the server will be breached one day.*

## Data at rest

* The input folder is opened read-only and never changed or copied.
* Raw and intermediate data stay in memory, so none of it is written to disk.
* If spilling to disk is switched on (`security.spill_to_disk` in `config/policy.yaml`, off
  by default), each blob is encrypted with AES-256-GCM inside a private temp folder
  (permissions 0700) that is wiped when the run ends, even after an error.
* The only files written are the cleaned output, `report.json` and `records.jsonl`.

## Keys

* The only secret is `RAKSHA_SECRET`, read from the environment. Without it the program
  stops (fails closed).
* Separate keys are derived from it with HKDF: one for fake IDs, one for date shifts, one for
  the encryption vault and one for other tags such as file names. A leak of one does not
  expose the others.
* Keys live only in process memory. The secret is never printed, logged or saved.

**In production** we would keep `RAKSHA_SECRET` in a key-management service, wrap the data
keys with it (envelope encryption), and rotate it per release.

## Logs and errors

* Logging uses an allow-list: only counts, file hashes, stage names and error class names
  can be printed. Record content cannot reach the log.
* A quiet exception hook replaces tracebacks, so an error message cannot contain a name.

## Quarantine

* Files that cannot be cleaned are listed in `report.json` by SHA-256 with a reason code.
* They are never copied into `sanitized/`, so a half-cleaned file cannot leak.

## Tested

`tests/test_pipeline_e2e.py` checks that no personal data or secret appears in the output,
`report.json`, `records.jsonl` or the program's printed output, and that a missing secret
fails closed.

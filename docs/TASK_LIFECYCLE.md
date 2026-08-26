# Task Lifecycle

```text
queued --claim lease--> running --complete--> passed | failed
  ^                       |
  |                       +--cancel---------> canceled
  +----lease expired------+
```

## Guarantees

- Submission persists the task before returning its identifier.
- Claim must be atomic in every persistence adapter.
- Only the device holding the active lease may renew or complete a task.
- Expired work returns to the queue with an incremented attempt on the next claim.
- Cancellation is idempotent.
- A terminal result is immutable in the future persistent implementation.

The in-memory repository is a contract reference and test fixture. SQLite/PostgreSQL/MySQL adapters must use transactions or compare-and-set updates for claim operations.


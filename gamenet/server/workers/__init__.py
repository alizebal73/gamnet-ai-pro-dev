"""Background jobs: recovery, reconciliation, expiry (Master Spec 229).

Jobs run at server startup and on demand via the admin API. Periodic
scheduling (expiry sweeps, daily reports) arrives with P4 automation.
"""
"""In-memory realtime state (presence, leases, sockets).

Kept in process memory by design: a 1s heartbeat from every PC must not
turn into a SQLite write each time (gap-analysis risk #10). The database
is flushed periodically (see workers + `flush_presence`) and stays the
source of truth for everything financial; presence here is ephemeral and
rebuilt from heartbeats after any restart.
"""

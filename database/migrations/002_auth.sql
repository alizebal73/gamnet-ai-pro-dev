-- Migration 002: Operator auth (permissions, sessions, lockout)
-- GameNet Pro - P1-1

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS permissions (
    name        TEXT PRIMARY KEY,
    description TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id     TEXT NOT NULL REFERENCES roles(id),
    permission  TEXT NOT NULL REFERENCES permissions(name),
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (role_id, permission)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT,
    created_ip  TEXT
);

ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN locked_until TEXT;

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id);

-- Seed roles (Master Spec 92)
INSERT OR IGNORE INTO roles (id, name, description, created_at) VALUES
    ('owner',      'Owner',      'Full access.',                 strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('manager',    'Manager',    'Daily management.',            strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator',   'Operator',   'Sales and customers.',         strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('technician', 'Technician', 'PC, network, maintenance.',    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('viewer',     'Viewer',     'Read-only reports.',           strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

-- Seed permissions (Master Spec 93)
INSERT OR IGNORE INTO permissions (name, description, created_at) VALUES
    ('sales.create',         'Create sales.',                 strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('sales.cancel',         'Cancel sales.',                 strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('sales.refund',         'Refund sales.',                 strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('customer.create',      'Create customers.',             strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('customer.view',        'View customers.',               strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('customer.edit',        'Edit customers.',               strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('customer.edit_balance','Adjust customer balance.',      strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('vip.sell',             'Sell VIP.',                     strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('vip.cancel',           'Cancel VIP.',                   strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('discount.apply',       'Apply discounts.',              strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('inventory.sell',       'Sell inventory items.',         strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('inventory.adjust',     'Adjust inventory.',             strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('reports.view',         'View reports.',                 strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('reports.financial',    'View financial reports.',       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('employee.manage',      'Manage employees.',             strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('settings.edit',        'Edit settings.',                strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('backup.manage',        'Manage backups.',               strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('remote.execute',       'Execute remote PC commands.',   strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

-- Seed role -> permission mapping.
-- Owner: everything. Manager: everything except employee.manage.
INSERT OR IGNORE INTO role_permissions (role_id, permission, assigned_at)
SELECT 'owner', name, strftime('%Y-%m-%dT%H:%M:%SZ', 'now') FROM permissions;

INSERT OR IGNORE INTO role_permissions (role_id, permission, assigned_at)
SELECT 'manager', name, strftime('%Y-%m-%dT%H:%M:%SZ', 'now') FROM permissions
WHERE name != 'employee.manage';

-- Operator: daily sales work, no cancels/refunds/balance/settings.
INSERT OR IGNORE INTO role_permissions (role_id, permission, assigned_at) VALUES
    ('operator', 'sales.create',    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator', 'customer.create',  strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator', 'customer.view',    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator', 'discount.apply',   strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator', 'inventory.sell',   strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator', 'reports.view',     strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

-- Technician: see customers/reports, run remote commands.
INSERT OR IGNORE INTO role_permissions (role_id, permission, assigned_at) VALUES
    ('technician', 'customer.view',  strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('technician', 'reports.view',   strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('technician', 'remote.execute', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

-- Viewer: reports only.
INSERT OR IGNORE INTO role_permissions (role_id, permission, assigned_at) VALUES
    ('viewer', 'reports.view', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

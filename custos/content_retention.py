"""
custos/content_retention.py — whether the served path keeps content, and how it
can be erased.

The gate hashed every request into its record and kept nothing. That is a
defensible place to be, and it made every statement about erasure on the served
path empty: there was nothing to delete, so there was nothing an erasure request
could act on, and a retention claim about the API would have described a store
the API never populated.

This module makes the choice explicit and refuses to let it drift:

    CUSTOS_CONTENT_RETENTION=off     (default) keep nothing; every record
                                     carries commitment ``none``; an erasure
                                     request is refused with a reason rather
                                     than answered with a success for work that
                                     was never done.
    CUSTOS_CONTENT_RETENTION=store   keep the evaluated content in a per-tenant
                                     side store; every record carries the form
                                     the store actually used; an erasure request
                                     deletes body, salt and commitment and
                                     appends an attestation to the chain.

Neither mode is inferred from the other's configuration. A store path set while
the mode is ``off`` is refused rather than honoured, because the alternative is a
process that looks configured for retention, records ``none``, and is believed.

What this does not do, and the drill shows rather than argues: a purge cannot
reach a copy of the side store taken before it. Backup retention is the
operator's deletion policy, not this module's.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import hashlib
import os
import re
import threading
from typing import Optional

from .retention import ContentStore

MODE_ENV = "CUSTOS_CONTENT_RETENTION"
STORE_DIR_ENV = "CUSTOS_CONTENT_STORE_DIR"
ADMIN_TOKEN_ENV = "CUSTOS_RETENTION_ADMIN_TOKEN"

MODE_OFF = "off"
MODE_STORE = "store"
MODES = (MODE_OFF, MODE_STORE)

# One file per tenant, named after the tenant where the id can safely be a
# filename and by digest where it cannot. Refusing a filename would have been the
# wrong side of the boundary: tenant ids are already accepted by POST /v1/tenants
# with no character policy ("acme corp" is legal), so a refusal here turns a legal
# tenant into a 500 on the evaluate path. The name is derived, never rejected.
#
# The "t-" prefix is reserved for the hashed form. A tenant id that matches the
# readable pattern after that prefix is hashed instead, so the two forms cannot
# collide: two tenants share a file only if they are the same tenant or their
# digests collide.
_SAFE_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HASHED_PREFIX = "t-"
HASHED_NAME_BYTES = 16

_stores: dict = {}
_lock = threading.Lock()


class RetentionConfigRefused(RuntimeError):
    """The retention configuration cannot be honoured as written.

    Refused rather than resolved to a default, because every default here is a
    statement about whether the service keeps the content it reads, and a
    statement made by falling back is not one anybody chose.
    """


def content_retention_mode(env: Optional[str] = None) -> str:
    """``off`` or ``store``, read from the environment on each call.

    Read per call rather than cached at import so that a test, or an operator
    changing a deployment, gets the configuration that is in force now.
    """
    raw = os.getenv(MODE_ENV)
    if raw is None or raw.strip() == "":
        return MODE_OFF
    value = raw.strip().lower()
    if value not in MODES:
        raise RetentionConfigRefused(
            f"{MODE_ENV}={raw!r} is not a retention mode; this build implements "
            f"{' and '.join(MODES)}. Refused rather than defaulted, because "
            "guessing here decides whether the service keeps the content it reads"
        )
    return value


def store_directory(env: Optional[str] = None) -> Optional[str]:
    raw = os.getenv(STORE_DIR_ENV)
    return raw.strip() if raw and raw.strip() else None


def admin_token() -> Optional[str]:
    """The operator credential for the retention endpoints, or None.

    Unset means no administration surface: the endpoints refuse rather than
    accepting any caller. That matters more than the convenience, because a
    deletion route that opens when a variable is missing is a deletion route
    that is open.
    """
    raw = os.getenv(ADMIN_TOKEN_ENV)
    return raw.strip() if raw and raw.strip() else None


def store_path_for(directory: str, tenant_id: str) -> str:
    """Path of one tenant's content store inside the configured directory.

    Deterministic for every tenant id the API accepts, including ids that are not
    usable as filenames. Nothing here raises on a tenant id: the caller is on the
    decision path, and a legal tenant must not become an error because of how this
    module names files.
    """
    tenant_id = tenant_id or ""
    if _SAFE_TENANT.match(tenant_id) and not tenant_id.startswith(_HASHED_PREFIX):
        return os.path.join(directory, f"content-{tenant_id}.sqlite")
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[: HASHED_NAME_BYTES * 2]
    return os.path.join(directory, f"content-{_HASHED_PREFIX}{digest}.sqlite")


def content_store_for(tenant_id: str) -> Optional[ContentStore]:
    """This tenant's side store, or None when retention is off.

    None is the answer the served path acts on: it means no body is kept and
    every record must say so.
    """
    if content_retention_mode() == MODE_OFF:
        return None
    directory = store_directory()
    if directory is None:
        raise RetentionConfigRefused(
            f"{MODE_ENV}={MODE_STORE} requires {STORE_DIR_ENV}. A retention mode "
            "with nowhere to store content would record bodies it cannot delete"
        )
    path = store_path_for(directory, tenant_id)
    with _lock:
        store = _stores.get(path)
        if store is None:
            store = ContentStore(path)
            _stores[path] = store
        return store


def validate_content_retention(env: Optional[str] = None) -> dict:
    """Startup check. Returns the summary to log; raises on a configuration that
    cannot be honoured.

    Two refusals, and both are configurations that would otherwise look fine:

    - ``store`` with no directory: the mode promises deletion of content it has
      nowhere to keep.
    - ``off`` with a directory and no admin token, or with a directory at all:
      a configured store that nothing will use. Refused, because the failure is
      a reader believing the service retains and erases when it does neither.
    """
    environment = (env if env is not None else os.getenv("CUSTOS_ENV", "development"))
    environment = (environment or "development").lower()
    mode = content_retention_mode()
    directory = store_directory()
    token = admin_token()

    summary = {
        "content_retention": mode,
        "content_store_dir": directory,
        "retention_admin_configured": token is not None,
        "environment": environment,
    }

    if mode == MODE_STORE:
        if directory is None:
            raise RetentionConfigRefused(
                f"{MODE_ENV}={MODE_STORE} requires {STORE_DIR_ENV}. Refusing to "
                "start: the mode promises an erasure path and has nowhere to "
                "delete from"
            )
        if not os.path.isdir(directory):
            raise RetentionConfigRefused(
                f"{STORE_DIR_ENV}={directory!r} is not a directory. Refusing to "
                "create it, because a store path that appears when asked is a "
                "path an operator has not chosen"
            )
        if token is None:
            raise RetentionConfigRefused(
                f"{MODE_ENV}={MODE_STORE} requires {ADMIN_TOKEN_ENV}. Content is "
                "being kept and nothing can erase it, which is the state the mode "
                "exists to make impossible"
            )
    else:
        if directory is not None:
            raise RetentionConfigRefused(
                f"{STORE_DIR_ENV} is set while {MODE_ENV}={MODE_OFF}. Refused "
                "rather than ignored: a configured store the process does not use "
                "reads as retention that is on"
            )
        if token is not None:
            raise RetentionConfigRefused(
                f"{ADMIN_TOKEN_ENV} is set while {MODE_ENV}={MODE_OFF}. There is "
                "nothing to administer, and an admin credential with no surface "
                "is a credential nobody can reason about"
            )

    return summary


def reset_store_cache() -> None:
    """Drop the cached stores. Tests only: a process changing its store directory
    at runtime is not a thing the served path supports."""
    with _lock:
        _stores.clear()

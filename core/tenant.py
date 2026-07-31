"""
tenant.py — who this pipeline is selling FOR.

The pipeline is generic. Brace is not the pipeline; Brace is an example tenant
that the pipeline has been pointed at. Everything specific to a company lives
in one folder under `context/`, selected by a single config value:

    { "tenant": "brace" }

A tenant folder is four files:

    context/<name>/
        company.md      the ICP, the buying signals, who to contact
        voice.md        how the hook must sound
        copy.py         the fixed strings in the emails (this file loads it)
        blacklist.txt   never-contact companies and domains

Adding a second company is copying that folder and editing four files. No code
changes, and nothing about the send engine, the database, the pacing or the
research skills is aware of which tenant is active.

WHY copy.py IS DATA, NOT A TEMPLATE: `outreach/templates.py` still owns the
*structure* of every email — the greeting, the order of the blocks, the HTML,
and the fact that the hook lands first. A tenant supplies the sentences that
describe its own product and sender. It cannot reorder anything, inject markup,
or change which slots exist. That boundary is the harness rule applied one
level up: structure in code, copy in config, and only four per-lead slots for
the model.
"""

import importlib.util

from core import config
from core.paths import CONTEXT_DIR

DEFAULT_TENANT = "brace"

# Every name a tenant's copy.py must define. Validated at load: a missing value
# would otherwise surface as the literal string "None" inside a sent email,
# which nothing downstream checks for.
REQUIRED = (
    "SENDER_NAME",       # signs every email
    "SENDER_TITLE",      # line under the name
    "SITE_URL",          # href in the signature
    "SITE_LABEL",        # visible text for that link
    "PRODUCT_LINE",      # the one fixed sentence about what is sold
    "COLD_SUBJECT",      # may contain {company}
    "COLD_CTA",          # the ask, in the cold email
    "COLD_OPT_OUT",      # the "no problem if not" line
    "F1_OPENER",         # first follow-up, paragraph 1; may use {company}
    "F1_CLOSER",         # first follow-up, paragraph 2
    "F2_CLOSING",        # final follow-up sign-off; may use {company}
)

_cache = {}


def name():
    """The active tenant. Config, with a default so a fresh clone just works."""
    return (config.get("tenant") or DEFAULT_TENANT).strip()


def directory(tenant=None):
    return CONTEXT_DIR / (tenant or name())


def company_md(tenant=None):
    return directory(tenant) / "company.md"


def voice_md(tenant=None):
    return directory(tenant) / "voice.md"


def blacklist_path(tenant=None):
    return directory(tenant) / "blacklist.txt"


def available():
    """Tenant names present on disk, for error messages and `agent.py doctor`."""
    if not CONTEXT_DIR.exists():
        return []
    return sorted(p.name for p in CONTEXT_DIR.iterdir()
                  if p.is_dir() and (p / "copy.py").exists())


def copy(tenant=None):
    """Load and validate the active tenant's copy module.

    Loaded by path rather than imported as `context.<name>.copy` so a tenant
    folder needs no __init__.py and can be dropped in by someone who does not
    write Python packages for a living.
    """
    tenant = tenant or name()
    if tenant in _cache:
        return _cache[tenant]

    path = directory(tenant) / "copy.py"
    if not path.exists():
        found = available()
        raise RuntimeError(
            f"No tenant named {tenant!r}: {path} does not exist.\n"
            f"  Available: {', '.join(found) if found else 'none'}\n"
            f"  Set \"tenant\" in config.json, or copy an existing folder in "
            f"{CONTEXT_DIR} and edit it."
        )

    spec = importlib.util.spec_from_file_location(f"_tenant_{tenant}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing = [k for k in REQUIRED if not getattr(module, k, None)]
    if missing:
        raise RuntimeError(
            f"Tenant {tenant!r} is incomplete: {path}\n"
            f"  Missing or empty: {', '.join(missing)}\n"
            f"  Every name in core.tenant.REQUIRED must be a non-empty string. "
            f"An absent one would render as 'None' inside a real email."
        )

    _cache[tenant] = module
    return module

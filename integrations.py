from typing import Optional, Dict, Any

# Placeholder enrichment functions. Replace internals with real API calls later.
async def fetch_kofi_profile(handle_or_link: Optional[str]) -> Dict[str, Any]:
    if not handle_or_link:
        return {}
    return {"kofi": {"handle": handle_or_link, "supporter": False, "notes": "Stubbed"}}

async def fetch_steam_profile(steam_id: Optional[str]) -> Dict[str, Any]:
    if not steam_id:
        return {}
    return {"steam": {"id": steam_id, "bans": 0, "hours": "N/A (stub)" }}

async def fetch_cftools_profile(identifier: Optional[str]) -> Dict[str, Any]:
    if not identifier:
        return {}
    return {"cftools": {"id": identifier, "recent_connections": "N/A (stub)"}}

async def enrich_context(ko_fi: Optional[str], steam_id: Optional[str], cftools_id: Optional[str]) -> Dict[str, Any]:
    # Merge all lookups into a single dict
    ctx = {}
    ctx.update(await fetch_kofi_profile(ko_fi))
    ctx.update(await fetch_steam_profile(steam_id))
    ctx.update(await fetch_cftools_profile(cftools_id))
    return ctx

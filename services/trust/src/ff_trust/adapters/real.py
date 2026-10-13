"""Real data adapters (disabled stubs). Enable only with official APIs/licensed data (CLAUDE.md rule 6)."""

from ff_trust.adapters.base import AdapterDisabled
from ff_trust.domain.signals import SupplierSignals


class _DisabledAdapter:
    name = "disabled"

    async def get_signals(self, supplier_id: str) -> SupplierSignals | None:
        raise AdapterDisabled(f"{self.name} adapter is disabled: no API credentials configured")


class AlibabaSignalsAdapter(_DisabledAdapter):
    name = "alibaba"


class MadeInChinaSignalsAdapter(_DisabledAdapter):
    name = "made_in_china"

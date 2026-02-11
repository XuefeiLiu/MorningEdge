"""
FRED (Federal Reserve Economic Data) collector for macroeconomic data.
Free public API, no key required for basic access.
"""
import httpx
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from hashlib import md5

from backend.config import FRED_API_BASE_URL
from backend.models import MacroEvent, ImpactLevel
from .base import BaseCollector

logger = logging.getLogger(__name__)

# Key economic indicators to track
ECONOMIC_INDICATORS = [
    {
        "series_id": "UNRATE",
        "title": "Unemployment Rate",
        "impact": ImpactLevel.HIGH,
    },
    {
        "series_id": "CPIAUCSL",
        "title": "Consumer Price Index (CPI)",
        "impact": ImpactLevel.HIGH,
    },
    {
        "series_id": "GDP",
        "title": "Gross Domestic Product (GDP)",
        "impact": ImpactLevel.HIGH,
    },
    {
        "series_id": "FEDFUNDS",
        "title": "Federal Funds Rate",
        "impact": ImpactLevel.HIGH,
    },
    {
        "series_id": "DGS10",
        "title": "10-Year Treasury Yield",
        "impact": ImpactLevel.MEDIUM,
    },
    {
        "series_id": "DEXUSEU",
        "title": "USD/EUR Exchange Rate",
        "impact": ImpactLevel.LOW,
    },
    {
        "series_id": "PAYEMS",
        "title": "Non-Farm Payrolls",
        "impact": ImpactLevel.HIGH,
    },
    {
        "series_id": "RETAILSMNSA",
        "title": "Retail Sales",
        "impact": ImpactLevel.MEDIUM,
    },
]


class FREDCollector(BaseCollector):
    """Collector for FRED macroeconomic data."""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__("fred")
        self.base_url = FRED_API_BASE_URL
        # FRED API key is optional for basic series data
        # Get one at https://fred.stlouisfed.org/docs/api/api_key.html
        self.api_key = api_key or "DEMO"  # DEMO key has limited access
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[MacroEvent]:
        """Collect recent macroeconomic data releases."""
        events = []
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for indicator in ECONOMIC_INDICATORS:
                    try:
                        event = await self._get_indicator(
                            client,
                            indicator,
                            start_time,
                            end_time
                        )
                        if event:
                            events.append(event)
                    except Exception as e:
                        logger.error(f"Error fetching FRED indicator {indicator['series_id']}: {e}")
        except Exception as e:
            logger.error(f"FRED collection failed: {e}")
        
        return events
    
    async def _get_indicator(
        self,
        client: httpx.AsyncClient,
        indicator: dict,
        start_time: datetime,
        end_time: datetime
    ) -> Optional[MacroEvent]:
        """Get latest observation for an economic indicator."""
        series_id = indicator["series_id"]
        
        # Calculate date range (look back a bit more to catch releases)
        # Ensure dates are not in the future (FRED doesn't accept future dates)
        now = datetime.utcnow()
        effective_end = min(end_time.replace(tzinfo=None), now)
        effective_start = (start_time.replace(tzinfo=None) - timedelta(days=7))
        
        # Don't query if start is in the future
        if effective_start > now:
            return None
        
        observation_start = effective_start.strftime("%Y-%m-%d")
        observation_end = effective_end.strftime("%Y-%m-%d")
        
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": observation_start,
            "observation_end": observation_end,
            "sort_order": "desc",
            "limit": 5
        }
        
        url = f"{self.base_url}/series/observations"
        
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("FRED API rate limit reached")
            raise
        
        observations = data.get("observations", [])
        
        if not observations:
            return None
        
        # Get the most recent observation
        latest = observations[0]
        previous = observations[1] if len(observations) > 1 else None
        
        # Parse date
        date_str = latest.get("date", "")
        try:
            event_time = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            event_time = datetime.utcnow()
        
        # Check if this is within our window (release date)
        if event_time < start_time.replace(tzinfo=None):
            return None
        
        event_id = md5(f"{series_id}{date_str}".encode()).hexdigest()[:12]
        
        return MacroEvent(
            id=f"fred_{event_id}",
            title=indicator["title"],
            description=f"Latest {indicator['title']} data release",
            source="FRED",
            event_time=event_time,
            indicator=series_id,
            actual_value=latest.get("value"),
            previous_value=previous.get("value") if previous else None,
            impact_level=indicator["impact"]
        )

"""
NASDAQ 100 ticker list fetcher with company information.
"""
import logging
import httpx
from typing import List, Dict, Optional
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)

# Hardcoded NASDAQ 100 list as fallback (top 100 by market cap as of 2024)
# Note: This is a representative list. For production, fetch from API or maintain updated list.
NASDAQ_100_FALLBACK = [
    {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
    {"ticker": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ"},
    {"ticker": "AMZN", "name": "Amazon.com Inc.", "exchange": "NASDAQ"},
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ"},
    {"ticker": "GOOGL", "name": "Alphabet Inc.", "exchange": "NASDAQ"},
    {"ticker": "META", "name": "Meta Platforms Inc.", "exchange": "NASDAQ"},
    {"ticker": "TSLA", "name": "Tesla Inc.", "exchange": "NASDAQ"},
    {"ticker": "AVGO", "name": "Broadcom Inc.", "exchange": "NASDAQ"},
    {"ticker": "COST", "name": "Costco Wholesale Corporation", "exchange": "NASDAQ"},
    {"ticker": "NFLX", "name": "Netflix Inc.", "exchange": "NASDAQ"},
    {"ticker": "AMD", "name": "Advanced Micro Devices Inc.", "exchange": "NASDAQ"},
    {"ticker": "PEP", "name": "PepsiCo Inc.", "exchange": "NASDAQ"},
    {"ticker": "ADBE", "name": "Adobe Inc.", "exchange": "NASDAQ"},
    {"ticker": "CSCO", "name": "Cisco Systems Inc.", "exchange": "NASDAQ"},
    {"ticker": "CMCSA", "name": "Comcast Corporation", "exchange": "NASDAQ"},
    {"ticker": "INTC", "name": "Intel Corporation", "exchange": "NASDAQ"},
    {"ticker": "TXN", "name": "Texas Instruments Incorporated", "exchange": "NASDAQ"},
    {"ticker": "AMGN", "name": "Amgen Inc.", "exchange": "NASDAQ"},
    {"ticker": "QCOM", "name": "QUALCOMM Incorporated", "exchange": "NASDAQ"},
    {"ticker": "ISRG", "name": "Intuitive Surgical Inc.", "exchange": "NASDAQ"},
    {"ticker": "INTU", "name": "Intuit Inc.", "exchange": "NASDAQ"},
    {"ticker": "AMAT", "name": "Applied Materials Inc.", "exchange": "NASDAQ"},
    {"ticker": "BKNG", "name": "Booking Holdings Inc.", "exchange": "NASDAQ"},
    {"ticker": "VRSK", "name": "Verisk Analytics Inc.", "exchange": "NASDAQ"},
    {"ticker": "FAST", "name": "Fastenal Company", "exchange": "NASDAQ"},
    {"ticker": "ADP", "name": "Automatic Data Processing Inc.", "exchange": "NASDAQ"},
    {"ticker": "GILD", "name": "Gilead Sciences Inc.", "exchange": "NASDAQ"},
    {"ticker": "MU", "name": "Micron Technology Inc.", "exchange": "NASDAQ"},
    {"ticker": "LRCX", "name": "Lam Research Corporation", "exchange": "NASDAQ"},
    {"ticker": "SNPS", "name": "Synopsys Inc.", "exchange": "NASDAQ"},
    {"ticker": "CDNS", "name": "Cadence Design Systems Inc.", "exchange": "NASDAQ"},
    {"ticker": "KLAC", "name": "KLA Corporation", "exchange": "NASDAQ"},
    {"ticker": "MRVL", "name": "Marvell Technology Inc.", "exchange": "NASDAQ"},
    {"ticker": "NXPI", "name": "NXP Semiconductors N.V.", "exchange": "NASDAQ"},
    {"ticker": "ASML", "name": "ASML Holding N.V.", "exchange": "NASDAQ"},
    {"ticker": "CRWD", "name": "CrowdStrike Holdings Inc.", "exchange": "NASDAQ"},
    {"ticker": "PANW", "name": "Palo Alto Networks Inc.", "exchange": "NASDAQ"},
    {"ticker": "FTNT", "name": "Fortinet Inc.", "exchange": "NASDAQ"},
    {"ticker": "ZS", "name": "Zscaler Inc.", "exchange": "NASDAQ"},
    {"ticker": "TEAM", "name": "Atlassian Corporation", "exchange": "NASDAQ"},
    {"ticker": "ZM", "name": "Zoom Video Communications Inc.", "exchange": "NASDAQ"},
    {"ticker": "ANSS", "name": "ANSYS Inc.", "exchange": "NASDAQ"},
    {"ticker": "CTSH", "name": "Cognizant Technology Solutions Corporation", "exchange": "NASDAQ"},
    {"ticker": "WDAY", "name": "Workday Inc.", "exchange": "NASDAQ"},
    {"ticker": "PAYX", "name": "Paychex Inc.", "exchange": "NASDAQ"},
    {"ticker": "DXCM", "name": "Dexcom Inc.", "exchange": "NASDAQ"},
    {"ticker": "BIIB", "name": "Biogen Inc.", "exchange": "NASDAQ"},
    {"ticker": "REGN", "name": "Regeneron Pharmaceuticals Inc.", "exchange": "NASDAQ"},
    {"ticker": "ILMN", "name": "Illumina Inc.", "exchange": "NASDAQ"},
    {"ticker": "IDXX", "name": "IDEXX Laboratories Inc.", "exchange": "NASDAQ"},
    {"ticker": "ALGN", "name": "Align Technology Inc.", "exchange": "NASDAQ"},
    {"ticker": "CTAS", "name": "Cintas Corporation", "exchange": "NASDAQ"},
    {"ticker": "PCAR", "name": "PACCAR Inc", "exchange": "NASDAQ"},
    {"ticker": "ODFL", "name": "Old Dominion Freight Line Inc.", "exchange": "NASDAQ"},
    {"ticker": "ROST", "name": "Ross Stores Inc.", "exchange": "NASDAQ"},
    {"ticker": "MNST", "name": "Monster Beverage Corporation", "exchange": "NASDAQ"},
    {"ticker": "KDP", "name": "Keurig Dr Pepper Inc.", "exchange": "NASDAQ"},
    {"ticker": "EXC", "name": "Exelon Corporation", "exchange": "NASDAQ"},
    {"ticker": "AEP", "name": "American Electric Power Company Inc.", "exchange": "NASDAQ"},
    {"ticker": "XEL", "name": "Xcel Energy Inc.", "exchange": "NASDAQ"},
    {"ticker": "WBD", "name": "Warner Bros. Discovery Inc.", "exchange": "NASDAQ"},
    {"ticker": "EA", "name": "Electronic Arts Inc.", "exchange": "NASDAQ"},
    {"ticker": "TTWO", "name": "Take-Two Interactive Software Inc.", "exchange": "NASDAQ"},
    {"ticker": "CHTR", "name": "Charter Communications Inc.", "exchange": "NASDAQ"},
    {"ticker": "FANG", "name": "Diamondback Energy Inc.", "exchange": "NASDAQ"},
    {"ticker": "VRTX", "name": "Vertex Pharmaceuticals Incorporated", "exchange": "NASDAQ"},
    {"ticker": "MELI", "name": "MercadoLibre Inc.", "exchange": "NASDAQ"},
    {"ticker": "BIDU", "name": "Baidu Inc.", "exchange": "NASDAQ"},
    {"ticker": "JD", "name": "JD.com Inc.", "exchange": "NASDAQ"},
    {"ticker": "PDD", "name": "PDD Holdings Inc.", "exchange": "NASDAQ"},
    {"ticker": "NTES", "name": "NetEase Inc.", "exchange": "NASDAQ"},
    {"ticker": "ON", "name": "ON Semiconductor Corporation", "exchange": "NASDAQ"},
    {"ticker": "MCHP", "name": "Microchip Technology Incorporated", "exchange": "NASDAQ"},
    {"ticker": "SWKS", "name": "Skyworks Solutions Inc.", "exchange": "NASDAQ"},
    {"ticker": "QRVO", "name": "Qorvo Inc.", "exchange": "NASDAQ"},
    {"ticker": "MPWR", "name": "Monolithic Power Systems Inc.", "exchange": "NASDAQ"},
    {"ticker": "OLED", "name": "Universal Display Corporation", "exchange": "NASDAQ"},
    {"ticker": "DOCU", "name": "DocuSign Inc.", "exchange": "NASDAQ"},
    {"ticker": "COIN", "name": "Coinbase Global Inc.", "exchange": "NASDAQ"},
    {"ticker": "HOOD", "name": "Robinhood Markets Inc.", "exchange": "NASDAQ"},
    {"ticker": "SOFI", "name": "SoFi Technologies Inc.", "exchange": "NASDAQ"},
    {"ticker": "UPST", "name": "Upstart Holdings Inc.", "exchange": "NASDAQ"},
    {"ticker": "AFRM", "name": "Affirm Holdings Inc.", "exchange": "NASDAQ"},
    {"ticker": "PINS", "name": "Pinterest Inc.", "exchange": "NASDAQ"},
    {"ticker": "SNAP", "name": "Snap Inc.", "exchange": "NASDAQ"},
    {"ticker": "TWLO", "name": "Twilio Inc.", "exchange": "NASDAQ"},
    {"ticker": "OKTA", "name": "Okta Inc.", "exchange": "NASDAQ"},
    {"ticker": "DDOG", "name": "Datadog Inc.", "exchange": "NASDAQ"},
    {"ticker": "NET", "name": "Cloudflare Inc.", "exchange": "NASDAQ"},
    {"ticker": "SPLK", "name": "Splunk Inc.", "exchange": "NASDAQ"},
    {"ticker": "MDB", "name": "MongoDB Inc.", "exchange": "NASDAQ"},
    {"ticker": "DBX", "name": "Dropbox Inc.", "exchange": "NASDAQ"},
    {"ticker": "AKAM", "name": "Akamai Technologies Inc.", "exchange": "NASDAQ"},
    {"ticker": "FFIV", "name": "F5 Inc.", "exchange": "NASDAQ"},
    {"ticker": "VRSN", "name": "VeriSign Inc.", "exchange": "NASDAQ"},
    {"ticker": "GDDY", "name": "GoDaddy Inc.", "exchange": "NASDAQ"},
    {"ticker": "WIX", "name": "Wix.com Ltd.", "exchange": "NASDAQ"},
    {"ticker": "SHOP", "name": "Shopify Inc.", "exchange": "NASDAQ"},
    {"ticker": "ETSY", "name": "Etsy Inc.", "exchange": "NASDAQ"},
    {"ticker": "EBAY", "name": "eBay Inc.", "exchange": "NASDAQ"},
    {"ticker": "BABA", "name": "Alibaba Group Holding Limited", "exchange": "NASDAQ"},
    {"ticker": "LCID", "name": "Lucid Group Inc.", "exchange": "NASDAQ"},
    {"ticker": "RIVN", "name": "Rivian Automotive Inc.", "exchange": "NASDAQ"},
    {"ticker": "LI", "name": "Li Auto Inc.", "exchange": "NASDAQ"},
    {"ticker": "NIO", "name": "NIO Inc.", "exchange": "NASDAQ"},
    {"ticker": "XPEV", "name": "XPeng Inc.", "exchange": "NASDAQ"},
    {"ticker": "SE", "name": "Sea Limited", "exchange": "NASDAQ"},
    {"ticker": "GRAB", "name": "Grab Holdings Limited", "exchange": "NASDAQ"},
    {"ticker": "GEHC", "name": "GE HealthCare Technologies Inc.", "exchange": "NASDAQ"},
    {"ticker": "ENPH", "name": "Enphase Energy Inc.", "exchange": "NASDAQ"},
    {"ticker": "FLEX", "name": "Flex Ltd.", "exchange": "NASDAQ"},
    {"ticker": "CDW", "name": "CDW Corporation", "exchange": "NASDAQ"},
    {"ticker": "CTSH", "name": "Cognizant Technology Solutions Corporation", "exchange": "NASDAQ"},
    {"ticker": "FAST", "name": "Fastenal Company", "exchange": "NASDAQ"},
    {"ticker": "PAYX", "name": "Paychex Inc.", "exchange": "NASDAQ"},
    {"ticker": "ADI", "name": "Analog Devices Inc.", "exchange": "NASDAQ"},
    {"ticker": "NXPI", "name": "NXP Semiconductors N.V.", "exchange": "NASDAQ"},
    {"ticker": "WBD", "name": "Warner Bros. Discovery Inc.", "exchange": "NASDAQ"},
    {"ticker": "CHTR", "name": "Charter Communications Inc.", "exchange": "NASDAQ"},
    {"ticker": "CMCSA", "name": "Comcast Corporation", "exchange": "NASDAQ"},
    {"ticker": "EXC", "name": "Exelon Corporation", "exchange": "NASDAQ"},
    {"ticker": "AEP", "name": "American Electric Power Company Inc.", "exchange": "NASDAQ"},
    {"ticker": "XEL", "name": "Xcel Energy Inc.", "exchange": "NASDAQ"},
    {"ticker": "DLTR", "name": "Dollar Tree Inc.", "exchange": "NASDAQ"},
    {"ticker": "ROST", "name": "Ross Stores Inc.", "exchange": "NASDAQ"},
    {"ticker": "MNST", "name": "Monster Beverage Corporation", "exchange": "NASDAQ"},
    {"ticker": "KDP", "name": "Keurig Dr Pepper Inc.", "exchange": "NASDAQ"},
    {"ticker": "PEP", "name": "PepsiCo Inc.", "exchange": "NASDAQ"},
]





def get_nasdaq100_stocks(use_api: bool = False) -> List[Dict[str, str]]:
    """
    Get NASDAQ 100 stock list with company names and exchange.
    
    Args:
        use_api: If True, try to fetch from API (requires API key)
        
    Returns:
        List of dicts with keys: ticker, name, exchange
    """
    if use_api:
        # Try to fetch from Financial Modeling Prep API (free tier)
        api_key = os.getenv("FMP_API_KEY")
        if api_key:
            try:
                return _fetch_from_fmp_api(api_key)
            except Exception as e:
                logger.warning(f"Failed to fetch from FMP API, using fallback: {e}")
    
    # Use hardcoded fallback list (deduplicated)
    # Remove duplicates by ticker, keeping first occurrence
    seen_tickers = set()
    deduplicated = []
    for stock in NASDAQ_100_FALLBACK:
        ticker = stock["ticker"]
        if ticker not in seen_tickers:
            seen_tickers.add(ticker)
            deduplicated.append(stock)
    
    logger.info(f"Using hardcoded NASDAQ 100 list ({len(deduplicated)} unique stocks)")
    return deduplicated


def _fetch_from_fmp_api(api_key: str) -> List[Dict[str, str]]:
    """
    Fetch NASDAQ 100 from Financial Modeling Prep API.
    
    Args:
        api_key: FMP API key
        
    Returns:
        List of dicts with ticker, name, exchange
    """
    url = "https://financialmodelingprep.com/api/v3/nasdaq_constituent"
    params = {"apikey": api_key}
    
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    
    stocks = []
    for item in data:
        stocks.append({
            "ticker": item.get("symbol", ""),
            "name": item.get("name", ""),
            "exchange": "NASDAQ"
        })
    
    logger.info(f"Fetched {len(stocks)} stocks from FMP API")
    return stocks

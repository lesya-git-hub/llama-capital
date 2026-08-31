from models.universe_config import UniverseConfig


UNIVERSE_V01 = UniverseConfig(
    max_candidates=30,
    allowed_tickers={
        # Aerospace & Defense
        "RKLB",
        "PLTR",
        "LMT",
        "NOC",

        # Semiconductors
        "NVDA",
        "AMD",
        "AVGO",
        "QCOM",

        # AI / Software Infrastructure
        "MSFT",
        "GOOGL",
        "ORCL",
        "SNOW",

        # Energy / Power / Uranium
        "CCJ",
        "CEG",
        "VST",
        "LEU",

        # Biotechnology / Healthcare Innovation
        "VRTX",
        "REGN",
        "CRSP",
        "RXRX",

        # Cybersecurity
        "CRWD",
        "PANW",
        "FTNT",
        "ZS",

        # Industrial Automation / Robotics
        "ROK",
        "TER",
        "SYM",
        "CGNX",
    },
)
from .base import Provider
from .linkedin import LinkedIn
from .meta import Facebook, Instagram, Threads
from .pinterest import Pinterest
from .simulated import Simulated
from .tiktok import TikTok
from .x import X
from .youtube import YouTube

PROVIDERS: dict[str, Provider] = {p.platform: p for p in (YouTube(), Instagram(), Facebook(), Threads(), TikTok(), X(), LinkedIn(), Pinterest())}
SIMULATED = Simulated()


def provider_for(platform: str, connection: str) -> Provider:
    return SIMULATED if connection == "simulated" else PROVIDERS[platform]

"""PTClub (猫站) PT site adapter - NexusPHP style."""
import logging
from app.sites.opencd import OpenCDSite

logger = logging.getLogger(__name__)


class PTClubSite(OpenCDSite):
    """PTClub adapter - same NexusPHP structure as Open.CD."""

    name = "ptclub"

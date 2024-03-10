import logging

from .source import Source
from .pcstarter import PcStarterSource, PcStarterCdn
from .patchcdn import PatchCdnSource, PatchCdn
from .obbstarter import ObbSource
from .sourceset import SourceSet

logger = logging.getLogger('pgr-assets.sources')

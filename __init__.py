"""ORF Radiothek Music Assistant Provider."""
from typing import List, Optional
from urllib.parse import urlencode

from music_assistant_models.enums import (
    ProviderFeature,
    StreamType,
    ContentType,
    MediaType,
)
from music_assistant_models.errors import MediaNotFoundError
from music_assistant_models.media_items import (
    Radio,
    SearchResults,
    ProviderMapping,
)
from music_assistant_models.streamdetails import StreamDetails, AudioFormat
from music_assistant.models.music_provider import MusicProvider


async def setup(mass, config_entry, config):
    """Entry point called by Music Assistant."""
    return ORFRadiothekProvider(mass, config_entry, config)


class ORFRadiothekProvider(MusicProvider):
    """Provider for ORF Radiothek."""

    API_BASE = "https://audioapi.orf.at"
    API_REF = "https://orf.at/app-infos/sound/web/1.0/bundle.json?_o=sound.orf.at"
    STAPLE_URL = "/radiothek/stapled.json?_o=radiothek.orf.at"
    SEARCH_URL = "/radiothek/api/search"
    # Note: Search is currently limited to matching station names against search queries.
    # Future enhancements could include searching for specific broadcasts or podcasts.
    
    STATIONS = {
        'oe1': 'Ö1',
        'oe3': 'Hitradio Ö3',
        'fm4': 'FM4',
        'sbg': 'Radio Salzburg',
        'ooe': 'Radio Oberösterreich',
        'wie': 'Radio Wien',
        'vbg': 'Radio Vorarlberg',
        'stm': 'Radio Steiermark',
        'noe': 'Radio Niederösterreich',
        'ktn': 'Radio Kärnten',
        'bgl': 'Radio Burgenland',
        'tir': 'Radio Tirol',
    }

    def __init__(self, mass, config_entry, config):
        """Initialize the provider."""
        super().__init__(mass, config_entry, config)
        self._api_reference = None
        self.logger.info("ORF Radiothek provider initialized")

    @property
    def supported_features(self):
        """Supported provider features."""
        return {
            ProviderFeature.SEARCH,
            ProviderFeature.BROWSE,
        }

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    async def search(
        self, search_query: str, media_types: List[MediaType], limit: int = 10
    ) -> SearchResults:
        """Perform search on the API."""
        results = SearchResults()

        # Only support radio search for now
        if MediaType.RADIO not in media_types:
            return results

        parameters = {
            'q': search_query,
            'offset': 0,
            'limit': limit,
            '_o': 'radiothek.orf.at'
        }
        url = f"{self.API_BASE}{self.SEARCH_URL}?{urlencode(parameters)}"
        
        try:
            data = await self._get_data(url, absolute=True)
            if data and 'hits' in data:
                for hit in data['hits']:
                    if 'data' in hit:
                        item_data = hit['data']
                        # Try to match to a radio station
                        station = item_data.get('station')
                        if station and station in self.STATIONS:
                            radio = self._parse_radio_station(station)
                            if radio and radio not in results.radio:
                                results.radio.append(radio)
        except Exception as e:
            self.logger.error(f"Search failed: {e}")

        return results

    # ---------------------------------------------------------
    # BROWSE
    # ---------------------------------------------------------

    async def browse(self, path: str = "") -> List[Radio]:
        """Browse radio stations."""
        radio_stations = []
        
        # Get API reference to build live stream URLs
        await self._get_api_reference()
        
        for station_id, station_name in self.STATIONS.items():
            radio = self._parse_radio_station(station_id)
            if radio:
                radio_stations.append(radio)
        
        return radio_stations

    # ---------------------------------------------------------
    # LOOKUPS
    # ---------------------------------------------------------

    async def get_radio(self, prov_radio_id: str) -> Radio:
        """Get radio station details."""
        if prov_radio_id not in self.STATIONS:
            raise MediaNotFoundError(f"Radio station {prov_radio_id} not found")
        
        radio = self._parse_radio_station(prov_radio_id)
        if not radio:
            raise MediaNotFoundError(f"Radio station {prov_radio_id} not found")
        
        return radio

    # ---------------------------------------------------------
    # STREAMING
    # ---------------------------------------------------------

    async def get_stream_details(self, item_id: str, provider_item_id: str) -> StreamDetails:
        """Get stream details for a radio station."""
        # Get API reference to build live stream URL
        api_ref = await self._get_api_reference()
        
        if provider_item_id not in self.STATIONS:
            raise MediaNotFoundError(f"Radio station {provider_item_id} not found")
        
        # Safely check for stations key
        if not api_ref:
            raise MediaNotFoundError(f"API reference could not be loaded for {provider_item_id}")
        
        if 'stations' not in api_ref:
            raise MediaNotFoundError(f"API reference missing stations data for {provider_item_id}")
        
        if provider_item_id not in api_ref['stations']:
            raise MediaNotFoundError(f"Stream URL not found for {provider_item_id}")
        
        station_info = api_ref['stations'][provider_item_id]
        
        # Use the live stream URL template with adaptive quality (qxa)
        if 'liveStreamUrlTemplate' not in station_info:
            raise MediaNotFoundError(f"No live stream URL for {provider_item_id}")
        
        stream_url = station_info['liveStreamUrlTemplate'].format(quality='qxa')
        
        # Create the AudioFormat object
        audio_format = AudioFormat(
            content_type=ContentType.AAC,
            sample_rate=48000,
            bit_depth=16,
            channels=2
        )

        return StreamDetails(
            provider=self.instance_id,
            item_id=item_id,
            media_type=MediaType.RADIO,
            path=stream_url,
            audio_format=audio_format,
            stream_type=StreamType.HLS,
            can_seek=False,
        )

    # ---------------------------------------------------------
    # HTTP Helper
    # ---------------------------------------------------------

    async def _get_data(self, url: str, absolute: bool = False) -> Optional[dict]:
        """Get data from API."""
        if not absolute:
            url = f"{self.API_BASE}{url}"
        
        try:
            async with self.mass.http_session.get(url) as resp:
                if resp.status != 200:
                    self.logger.error(f"ORF Radiothek API error {resp.status}: {url}")
                    return None
                return await resp.json()
        except Exception:
            self.logger.exception("Failed calling ORF Radiothek API")
            return None

    async def _get_api_reference(self):
        """Get API reference data.
        
        Returns a dict with at minimum an empty 'stations' dict to prevent KeyErrors.
        This ensures the provider can gracefully handle API failures.
        """
        if self._api_reference is None:
            # Initialize with empty fallback structure to prevent KeyErrors downstream
            self._api_reference = {'stations': {}}
            try:
                async with self.mass.http_session.get(self.API_REF) as resp:
                    if resp.status == 200:
                        self._api_reference = await resp.json()
                    else:
                        self.logger.error(f"Failed to get API reference: {resp.status}")
            except Exception as e:
                self.logger.exception(f"Failed to get API reference: {e}")
        
        return self._api_reference

    # ---------------------------------------------------------
    # Parsing helpers
    # ---------------------------------------------------------

    def _parse_radio_station(self, station_id: str) -> Optional[Radio]:
        """Parse a radio station into a Radio object."""
        if station_id not in self.STATIONS:
            return None
        
        station_name = self.STATIONS[station_id]
        
        # Create the ProviderMapping for the Radio station
        prov_mapping = ProviderMapping(
            item_id=station_id,
            provider_domain=self.domain,
            provider_instance=self.instance_id,
            url=f"https://radiothek.orf.at/live/{station_id}"
        )

        radio = Radio(
            item_id=station_id,
            provider=self.instance_id,
            name=station_name,
            provider_mappings=[prov_mapping],
        )
        
        return radio


async def get_config_entries(
    mass,
    instance_id: str,
    action: str | None = None,
    values: dict | None = None,
) -> list:
    """Return the config entries for this provider."""
    # No configuration needed - the ORF Radiothek API is public
    return []

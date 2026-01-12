"""ORF Radiothek / ORF Sound live radio provider for Music Assistant.

Live stream URLs: bundle.json (stations + privates)
Station images/logos:
- ORF stations: stapled.json (payload.<station>.broadcast.images[*].versions[*].path)
- Privates: bundle.json privates[*].image/imageLarge
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import (
    ConfigEntryType,
    ContentType,
    ImageType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.errors import MediaNotFoundError, UnplayableMediaError
from music_assistant_models.media_items import (
    AudioFormat,
    MediaItemImage,
    ProviderMapping,
    Radio,
    SearchResults,
)
from music_assistant_models.streamdetails import StreamDetails

from music_assistant.controllers.cache import use_cache
from music_assistant.models.music_provider import MusicProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType


API_BUNDLE = "https://orf.at/app-infos/sound/web/1.0/bundle.json?_o=sound.orf.at"

CONF_STREAM_PROTO = "stream_proto"        # hls | shoutcast (ORF only)
CONF_STREAM_QUALITY = "stream_quality"    # hls: q1a/q2a/q3a/q4a/qxa ; shoutcast: q1a/q2a
CONF_INCLUDE_HIDDEN = "include_hidden"    # include hideFromStations=true
CONF_USE_STAPLED_IMAGES = "use_stapled_images"

SUPPORTED_FEATURES = {
    ProviderFeature.LIBRARY_RADIOS,
    ProviderFeature.SEARCH,
}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    return RadiothekProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    # ruff: noqa: ARG001
    values = values or {}
    return (
        ConfigEntry(
            key=CONF_STREAM_PROTO,
            type=ConfigEntryType.STRING,
            label="Preferred ORF protocol",
            required=False,
            default_value="hls",
            description="Used for ORF stations (template-based). Privates use explicit URLs from bundle.json.",
            value=values.get(CONF_STREAM_PROTO),
        ),
        ConfigEntry(
            key=CONF_STREAM_QUALITY,
            type=ConfigEntryType.STRING,
            label="ORF quality",
            required=False,
            default_value="qxa",
            description="For ORF HLS: q1a/q2a/q3a/q4a/qxa. For shoutcast: q1a/q2a.",
            value=values.get(CONF_STREAM_QUALITY),
        ),
        ConfigEntry(
            key=CONF_INCLUDE_HIDDEN,
            type=ConfigEntryType.BOOLEAN,
            label="Include hidden stations",
            required=False,
            default_value=False,
            description="Include stations with hideFromStations=true (e.g. Campus, SLO).",
            value=values.get(CONF_INCLUDE_HIDDEN),
        ),
        ConfigEntry(
            key=CONF_USE_STAPLED_IMAGES,
            type=ConfigEntryType.BOOLEAN,
            label="Use live stapled images for ORF stations",
            required=False,
            default_value=True,
            description="Fetch station/program artwork from stapled.json for ORF stations.",
            value=values.get(CONF_USE_STAPLED_IMAGES),
        ),
    )


class RadiothekProvider(MusicProvider):
    """ORF Sound live radio provider (ORF + privates)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bundle: dict[str, Any] | None = None
        self._stapled: dict[str, Any] | None = None

        self.stream_proto = "hls"
        self.stream_quality = "qxa"
        self.include_hidden = False
        self.use_stapled_images = True

    async def handle_async_init(self) -> None:
        self.stream_proto = str(self.config.get_value(CONF_STREAM_PROTO) or "hls").lower()
        self.stream_quality = str(self.config.get_value(CONF_STREAM_QUALITY) or "qxa").lower()
        self.include_hidden = bool(self.config.get_value(CONF_INCLUDE_HIDDEN) or False)
        self.use_stapled_images = bool(self.config.get_value(CONF_USE_STAPLED_IMAGES) if self.config else True)

        if self.stream_proto not in ("hls", "shoutcast"):
            self.stream_proto = "hls"

        if self.stream_proto == "shoutcast":
            if self.stream_quality not in ("q1a", "q2a"):
                self.stream_quality = "q2a"
        else:
            if self.stream_quality not in ("q1a", "q2a", "q3a", "q4a", "qxa"):
                self.stream_quality = "qxa"

        await self._get_bundle(force=True)
        if self.use_stapled_images:
            await self._get_stapled(force=True)

    @property
    def is_streaming_provider(self) -> bool:
        return True

    async def _http_get_json(self, url: str) -> dict[str, Any]:
        async with self.mass.http_session.get(
            url,
            headers={"User-Agent": "Music Assistant"},
            timeout=20,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            return data

    async def _get_bundle(self, force: bool = False) -> dict[str, Any]:
        if self._bundle is not None and not force:
            return self._bundle
        try:
            self._bundle = await self._http_get_json(API_BUNDLE)
            return self._bundle
        except (ClientError, TimeoutError, ValueError) as err:
            self.logger.warning("Failed to fetch bundle.json: %s", err)
            if self._bundle is not None:
                return self._bundle
            raise

    def _stapled_url_from_bundle(self, bundle: dict[str, Any]) -> str | None:
        # bundle.json contains apiBaseUrls.liveStapler (seen in your file) :contentReference[oaicite:4]{index=4}
        base = bundle.get("apiBaseUrls")
        if isinstance(base, dict):
            url = base.get("liveStapler")
            if isinstance(url, str) and url.startswith("http"):
                return url
        return None

    async def _get_stapled(self, force: bool = False) -> dict[str, Any]:
        if self._stapled is not None and not force:
            return self._stapled

        bundle = await self._get_bundle()
        url = self._stapled_url_from_bundle(bundle)
        if not url:
            self._stapled = {}
            return self._stapled

        try:
            self._stapled = await self._http_get_json(url)
            return self._stapled
        except (ClientError, TimeoutError, ValueError) as err:
            self.logger.warning("Failed to fetch stapled.json: %s", err)
            if self._stapled is not None:
                return self._stapled
            self._stapled = {}
            return self._stapled

    # -------- bundle parsing --------

    def _iter_orf_stations(self, bundle: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        stations = bundle.get("stations")
        if not isinstance(stations, dict):
            return []
        out: list[tuple[str, dict[str, Any]]] = []
        for key, obj in stations.items():
            if not isinstance(obj, dict):
                continue
            if "liveStreamUrlTemplate" not in obj:
                continue
            if obj.get("hideFromStations") and not self.include_hidden:
                continue
            out.append((key, obj))
        return out

    def _iter_privates(self, bundle: dict[str, Any]) -> list[dict[str, Any]]:
        priv = bundle.get("privates")
        if isinstance(priv, list):
            return [p for p in priv if isinstance(p, dict)]
        return []

    def _privates_by_id(self, bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for p in self._iter_privates(bundle):
            sid = p.get("station")
            if isinstance(sid, str) and sid:
                out[sid] = p
        return out

    # -------- images --------

    def _images_from_private(self, pobj: dict[str, Any]) -> list[MediaItemImage]:
        imgs: list[MediaItemImage] = []

        def add(url: str) -> None:
            if not url:
                return
            imgs.append(
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=url,
                    provider=self.domain,
                    remotely_accessible=True,
                )
            )

        image = pobj.get("image")
        if isinstance(image, dict) and isinstance(image.get("src"), str):
            add(image["src"])

        image_large = pobj.get("imageLarge")
        if isinstance(image_large, dict):
            for mode in ("light", "dark"):
                v = image_large.get(mode)
                if isinstance(v, dict) and isinstance(v.get("src"), str):
                    add(v["src"])

        seen: set[str] = set()
        out: list[MediaItemImage] = []
        for i in imgs:
            if i.path in seen:
                continue
            seen.add(i.path)
            out.append(i)
        return out

    def _orf_images_from_stapled(self, stapled: dict[str, Any], station_id: str) -> list[MediaItemImage]:
        """
        stapled.json shape (your sample): payload.<station>.broadcast.images[*].versions[*].path :contentReference[oaicite:5]{index=5}
        We try to pick a "program/station" style image first (imgprog / imgprog-fallback / station-like),
        then fall back to the biggest image available.
        """
        payload = stapled.get("payload")
        if not isinstance(payload, dict):
            return []
        entry = payload.get(station_id)
        if not isinstance(entry, dict):
            return []

        broadcast = entry.get("broadcast")
        if not isinstance(broadcast, dict):
            return []
        images = broadcast.get("images")
        if not isinstance(images, list):
            return []

        # flatten (score, width, url)
        candidates: list[tuple[int, int, str]] = []
        for img in images:
            if not isinstance(img, dict):
                continue
            cat = str(img.get("category") or "").lower()
            mode = str(img.get("mode") or "").lower()

            # preference: program/station artwork; avoid moderator portrait unless nothing else
            score = 0
            if "imgprog" in cat:
                score += 50
            if "fallback" in cat:
                score += 10
            if mode == "default":
                score += 5
            if "imgmod" in cat:
                score -= 5

            versions = img.get("versions")
            if not isinstance(versions, list):
                continue
            for v in versions:
                if not isinstance(v, dict):
                    continue
                url = v.get("path")
                if not isinstance(url, str) or not url.startswith("http"):
                    continue
                width = int(v.get("width") or 0)
                candidates.append((score, width, url))

        if not candidates:
            return []

        # pick best by (score, width)
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best_url = candidates[0][2]

        return [
            MediaItemImage(
                type=ImageType.THUMB,
                path=best_url,
                provider=self.domain,
                remotely_accessible=True,
            )
        ]

    # -------- stream URL helpers --------

    def _build_orf_url(self, station_id: str, station_obj: dict[str, Any]) -> str | None:
        tmpl = station_obj.get("liveStreamUrlTemplate")
        if not isinstance(tmpl, str) or "{quality}" not in tmpl:
            return None

        if self.stream_proto == "shoutcast":
            # bundle doesn't provide per-station shoutcast template; ORF uses stable pattern
            return f"https://orf-live.ors-shoutcast.at/{station_id}-{self.stream_quality}"

        return tmpl.replace("{quality}", self.stream_quality)

    def _build_private_url(self, pobj: dict[str, Any]) -> tuple[str | None, str | None]:
        streams = pobj.get("streams")
        if not isinstance(streams, list) or not streams:
            return None, None
        s0 = streams[0]
        if not isinstance(s0, dict):
            return None, None
        url = s0.get("url")
        fmt = s0.get("format")
        return (url if isinstance(url, str) else None, fmt if isinstance(fmt, str) else None)

    def _content_type_from_url_or_format(self, url: str, fmt: str | None) -> ContentType:
        if fmt:
            f = fmt.lower()
            if f == "mp3":
                return ContentType.try_parse("mp3")
            if f in ("aac", "aacp"):
                return ContentType.try_parse("aac")
        if ".m3u8" in url.lower():
            return ContentType.try_parse("aac")
        return ContentType.try_parse("unknown")

    # -------- MA object helpers --------

    def _radio_item(self, item_id: str, name: str) -> Radio:
        return Radio(
            name=name,
            item_id=item_id,
            provider=self.instance_id,
            provider_mappings={
                ProviderMapping(
                    item_id=item_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
        )

    async def _enrich_orf_images(self, radio: Radio, station_id: str) -> None:
        if not self.use_stapled_images:
            return
        stapled = await self._get_stapled()
        for img in self._orf_images_from_stapled(stapled, station_id):
            radio.metadata.add_image(img)

    # -------- MA API --------

    async def get_library_radios(self) -> AsyncGenerator[Radio, None]:
        bundle = await self._get_bundle()

        # ORF stations
        for sid, sobj in self._iter_orf_stations(bundle):
            r = self._radio_item(sid, str(sobj.get("name") or sid))
            await self._enrich_orf_images(r, sid)
            yield r

        # privates
        for pobj in self._iter_privates(bundle):
            sid = pobj.get("station")
            name = pobj.get("name")
            if not isinstance(sid, str) or not isinstance(name, str):
                continue
            r = self._radio_item(sid, name)
            for img in self._images_from_private(pobj):
                r.metadata.add_image(img)
            yield r

    @use_cache(3600 * 6)
    async def search(
        self,
        search_query: str,
        media_types: list[MediaType],
        limit: int = 10,
    ) -> SearchResults:
        res = SearchResults()
        if MediaType.RADIO not in media_types:
            return res

        bundle = await self._get_bundle()
        q = search_query.strip().lower()
        radios: list[Radio] = []

        # ORF
        for sid, sobj in self._iter_orf_stations(bundle):
            name = str(sobj.get("name") or sid)
            if q in sid.lower() or q in name.lower():
                r = self._radio_item(sid, name)
                await self._enrich_orf_images(r, sid)
                radios.append(r)
                if len(radios) >= limit:
                    break

        # privates
        if len(radios) < limit:
            for pobj in self._iter_privates(bundle):
                sid = pobj.get("station")
                name = pobj.get("name")
                if not isinstance(sid, str) or not isinstance(name, str):
                    continue
                if q in sid.lower() or q in name.lower():
                    r = self._radio_item(sid, name)
                    for img in self._images_from_private(pobj):
                        r.metadata.add_image(img)
                    radios.append(r)
                    if len(radios) >= limit:
                        break

        res.radio = radios
        return res

    @use_cache(3600 * 24)
    async def get_radio(self, prov_radio_id: str) -> Radio:
        bundle = await self._get_bundle()

        stations = dict(self._iter_orf_stations(bundle))
        if prov_radio_id in stations:
            sobj = stations[prov_radio_id]
            r = self._radio_item(prov_radio_id, str(sobj.get("name") or prov_radio_id))
            await self._enrich_orf_images(r, prov_radio_id)
            return r

        priv = self._privates_by_id(bundle).get(prov_radio_id)
        if priv:
            r = self._radio_item(prov_radio_id, str(priv.get("name") or prov_radio_id))
            for img in self._images_from_private(priv):
                r.metadata.add_image(img)
            return r

        raise MediaNotFoundError("Radio not found.")

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        if media_type != MediaType.RADIO:
            raise UnplayableMediaError("Only live radio is supported.")

        bundle = await self._get_bundle()

        # ORF
        stations = dict(self._iter_orf_stations(bundle))
        if item_id in stations:
            url = self._build_orf_url(item_id, stations[item_id])
            if not url:
                raise UnplayableMediaError("No stream URL for ORF station.")
            ctype = self._content_type_from_url_or_format(url, None)
            return StreamDetails(
                provider=self.domain,
                item_id=item_id,
                media_type=MediaType.RADIO,
                stream_type=StreamType.HTTP,
                path=url,
                audio_format=AudioFormat(content_type=ctype),
                can_seek=False,
                allow_seek=False,
            )

        # privates
        priv = self._privates_by_id(bundle).get(item_id)
        if priv:
            url, fmt = self._build_private_url(priv)
            if not url:
                raise UnplayableMediaError("No stream URL for private station.")
            ctype = self._content_type_from_url_or_format(url, fmt)
            return StreamDetails(
                provider=self.domain,
                item_id=item_id,
                media_type=MediaType.RADIO,
                stream_type=StreamType.HTTP,
                path=url,
                audio_format=AudioFormat(content_type=ctype),
                can_seek=False,
                allow_seek=False,
            )

        raise MediaNotFoundError("Radio not found.")

# ORF Radiothek Provider for Music Assistant

A Music Assistant provider for streaming live radio from ORF Radiothek, the Austrian public service broadcaster's audio streaming platform.

## Features

- **Live Radio Streams**: Access all major ORF radio stations including:
  - Ö1 (culture and information)
  - Ö3 (pop music)
  - FM4 (alternative music)
  - All 9 regional stations (Vienna, Salzburg, Tyrol, etc.)
- **High Quality Streaming**: Uses adaptive HLS streaming for best quality
- **Search**: Search for radio stations by name
- **Browse**: Browse all available ORF radio stations

## Installation

### For Music Assistant Server

1. Clone the [Music Assistant server](https://github.com/music-assistant/server) repository
2. Create a folder inside the path:
   ```
   music_assistant/providers/orf_radiothek/
   ```
3. Clone or copy this repository into the newly created folder
4. Build Music Assistant according to the server repository instructions

### As a Custom Provider

Alternatively, if Music Assistant supports custom providers, you can install this provider by placing the files in your Music Assistant custom providers directory.

## Usage

1. Open Music Assistant web UI in your browser
2. Go to **Settings** → **Providers** → **Add A New Provider**
3. Search for "ORF Radiothek" and click **Add**
4. No configuration needed - the provider will work immediately
5. Browse radio stations or use search to find specific ORF stations
6. Add stations to your library and start listening!

## Available Stations

- **Ö1**: Culture, information, and classical music
- **Ö3**: Austria's most popular pop music station
- **FM4**: Alternative and indie music
- **Radio Wien**: Vienna regional station
- **Radio Salzburg**: Salzburg regional station
- **Radio Oberösterreich**: Upper Austria regional station
- **Radio Niederösterreich**: Lower Austria regional station
- **Radio Burgenland**: Burgenland regional station
- **Radio Steiermark**: Styria regional station
- **Radio Kärnten**: Carinthia regional station
- **Radio Tirol**: Tyrol regional station
- **Radio Vorarlberg**: Vorarlberg regional station

## Technical Details

### API

The provider uses the official ORF Radiothek API:
- Base URL: `https://audioapi.orf.at`
- API Reference: `https://orf.at/app-infos/sound/web/1.0/bundle.json`
- No authentication required

### Streaming

- Streams use HLS (HTTP Live Streaming) protocol
- Adaptive quality streaming (qxa) for best performance
- AAC audio codec at 48kHz

## Limitations

- Currently only supports live radio streams
- On-demand broadcasts and podcasts are not yet implemented
- No recording functionality

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- [Music Assistant](https://github.com/music-assistant): A music library manager by [Open Home Foundation](https://www.openhomefoundation.org/)
- [ORF](https://orf.at): Austrian Broadcasting Corporation for providing the public API
- Inspired by the [Kodi ORF Radiothek Addon](https://github.com/s0faking/plugin.audio.radiothek)
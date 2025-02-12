# PGR Assets
> Backbone for huaxu's asset database

## Installation

This package is not available on PyPI, so you will need to install it from source.

```bash
pip install pgr_assets@git+https://github.com/huaxu-app/pgr-assets
```

## Common usages

```bash
# List assets on global:
pgr-assets list

# Switch servers by changing preset: (global, korea, japan, taiwan, china)
pgr-assets list --preset global

# Extract all text assets
pgr-assets extract --all-temp --output /path/to/output

# For full usage instructions see the help output of the various commands
```

## Considerations

### Why?

While there are similar tools (like [CNStudio](https://github.com/Razmoth/CNStudio)) that can fulfill the primary task, 
`pgr-assets` specializes itself towards Huaxu's goals, providing some major benefits:

- It does not require you to have any local copy of the entire game worth of game bundles 
  - It instead downloads the required files on-demand from the game's CDN servers
- It supports the internal encryption and signature scheme used for text assets
- It is aware of the file storage methods that PGR uses and properly extracts and decrypts
  the flavors of audio and video
- It converts assets into more web-friendly formats on the fly
- It can do partial updates (by relying on the sha1 cache)

All of these things made this worthwhile enough to invest in this custom tooling. 

### Python

Python was chosen for this project not specifically because I like it, but because it has the
proper intersection of libraries to fulfill my use-cases. While C# has some alternatives 
(You can grab the internal libraries of VGMtoolbox and AssetStudio),
these alternatives come with major downsides and hacking around their non-officially-a-library status.

In the end, I really didn't feel like building parsers for Unity Asset Bundles and Criware's formats,
and wanted to just focus on getting shit done.

# Pinterest Data Extractor

This Actor scrapes rich Pinterest intelligence from pins, boards, profiles, and search results using [Crawlee for Python](https://crawlee.dev/python) with [BeautifulSoupCrawler](https://crawlee.dev/python/api/class/BeautifulSoupCrawler). It normalizes pins, user profiles, images, videos, hashtags, and optional comments so you can export insights as JSON, CSV, Excel, XML, or HTML through the built-in Apify dataset exports.

## Quick Start

Once you've installed the dependencies, start the Actor:

```bash
apify run
```

Once your Actor is ready, you can push it to the Apify Console:

```bash
apify login # first, you need to log in if you haven't already done so

apify push
```

## Project Structure

```text
.actor/
├── actor.json # Actor config: name, version, env vars, runtime settings
├── dataset_schena.json # Structure and representation of data produced by an Actor
├── input_schema.json # Input validation & Console form definition
└── output_schema.json # Specifies where an Actor stores its output
src/
└── main.py # Actor entry point and orchestrator
storage/ # Local storage (mirrors Cloud during development)
├── datasets/ # Output items (JSON objects)
├── key_value_stores/ # Files, config, INPUT
└── request_queues/ # Pending crawl requests
Dockerfile # Container image definition
```

For more information, see the [Actor definition](https://docs.apify.com/platform/actors/development/actor-definition) documentation.

## How it works

The Actor reads Pinterest pages, decodes the embedded `__PWS_DATA__` payload, and walks the Redux-style state to assemble structured records. For each pin it collects the title, description, destination link, prices (when present), creation timestamps, hashtags, metrics, images, videos, and the owning user profile. Optional flags let you pull only user profiles or include on-page comments when available. The dataset view highlights key pin fields for quick inspection, and Apify dataset exports handle delivery to JSON, CSV, Excel, XML, or HTML.

## Input options

- `startUrls` (array, required): Pin, board, profile, or search URLs to crawl.
- `maxItems` (integer): Maximum number of pins to export.
- `endPage` (integer): Soft cap on crawled requests to avoid runaway pagination.
- `includeComments` (boolean): When `true`, include any on-page comments detected.
- `includeUserInfoOnly` (boolean): Export only Pinterest user profiles discovered in the payload.
- `extendOutputFunction` (string): Python function that receives a record dict and returns extra fields.
- `customMapFunction` (string): Python function that receives a record dict and returns a transformed record.

## Resources

- [Quick Start](https://docs.apify.com/platform/actors/development/quick-start) guide for building your first Actor
- [Video introduction to Python SDK](https://www.youtube.com/watch?v=C8DmvJQS3jk)
- [Webinar introducing to Crawlee for Python](https://www.youtube.com/live/ip8Ii0eLfRY)
- [Apify Python SDK documentation](https://docs.apify.com/sdk/python/)
- [Crawlee for Python documentation](https://crawlee.dev/python/docs/quick-start)
- [Python tutorials in Academy](https://docs.apify.com/academy/python)
- [Integration with Zapier](https://apify.com/integrations), Make, Google Drive and others
- [Video guide on getting data using Apify API](https://www.youtube.com/watch?v=ViYYDHSBAKM)

## Creating Actors with templates

[How to create Apify Actors with web scraping code templates](https://www.youtube.com/watch?v=u-i-Korzf8w)


## Getting started

For complete information [see this article](https://docs.apify.com/platform/actors/development#build-actor-at-apify-console). In short, you will:

1. Build the Actor
2. Run the Actor

## Pull the Actor for local development

If you would like to develop locally, you can pull the existing Actor from Apify console using Apify CLI:

1. Install `apify-cli`

    **Using Homebrew**

    ```bash
    brew install apify-cli
    ```

    **Using NPM**

    ```bash
    npm -g install apify-cli
    ```

2. Pull the Actor by its unique `<ActorId>`, which is one of the following:
    - unique name of the Actor to pull (e.g. "apify/hello-world")
    - or ID of the Actor to pull (e.g. "E2jjCZBezvAZnX8Rb")

    You can find both by clicking on the Actor title at the top of the page, which will open a modal containing both Actor unique name and Actor ID.

    This command will copy the Actor into the current directory on your local machine.

    ```bash
    apify pull <ActorId>
    ```

## Documentation reference

To learn more about Apify and Actors, take a look at the following resources:

- [Apify SDK for JavaScript documentation](https://docs.apify.com/sdk/js)
- [Apify SDK for Python documentation](https://docs.apify.com/sdk/python)
- [Apify Platform documentation](https://docs.apify.com/platform)
- [Join our developer community on Discord](https://discord.com/invite/jyEM2PRvMU)

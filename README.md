# johncutlefish threads

A small static reading site generated from a local Twitter archive: the top 50 original threads, and the top 400 standalone tweets in a month/year browser.

The official dump is **not** in this repo. Images here are only the ones those posts need.

## Local preview

```bash
python3 -m http.server --directory docs 8000
```

Then open http://localhost:8000

## Regenerate

Requires the archive’s `data/` folder next to this README (`tweets.js`, `tweets-part1.js`, `tweets_media/`).

```bash
python3 scripts/generate_site.py
```

Flags: `--threads 50 --tweets 400 --max-gap-minutes 60 --min-tweets 3`

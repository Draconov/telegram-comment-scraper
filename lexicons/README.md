# Offensive lexicon

This directory contains the dictionary used by the post-scraping analysis toolkit.

- `offensive_lexicon.csv` preserves each term together with category, meaning, source, primary aspect, secondary aspect, and annotation notes.
- `offensive_lexicon.txt` contains the same unique terms in one-term-per-line format.

For the experiments, archive the exact dictionary file or its SHA-256 hash with each analysis result. When the dictionary is revised after manual validation, save a new version instead of overwriting the version used for an already reported experiment, for example:

```text
offensive_lexicon_v1.csv
offensive_lexicon_v2.csv
```

The CSV version is recommended for analysis because it enables category- and aspect-level statistics.

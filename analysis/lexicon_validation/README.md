# Lexicon research validation toolkit

This toolkit performs the next defensible steps after scraping:

1. rerun lexicon analysis with multiline-safe CSV parsing;
2. normalize comment and post sources to the same Telegram channel identifier;
3. join dictionary categories and offensive-language aspects;
4. generate a blinded stratified validation sample;
5. calculate precision, recall, F1, false positives, false negatives, and optional inter-annotator agreement.

It uses only the Python standard library.

## Important correction

The previous analyzer passed `text.splitlines()` to `csv.DictReader`. Valid Telegram messages can contain embedded line breaks. Splitting first can break rows and place pieces of message text into columns such as `source`. Version 2 reads the intact CSV stream with `newline=""`.

Your previous analysis should therefore remain archived as a baseline, but final thesis statistics should be generated again with this version.

## Files

- `lexicon_common.py` — shared CSV, source, dictionary, matching, and sampling utilities.
- `analyze_scraping_results.py` — corrected and enriched analysis.
- `prepare_validation_sample.py` — blinded matched/unmatched sampling.
- `create_second_annotator_subset.py` — deterministic overlap subset for agreement.
- `calculate_validation_metrics.py` — weighted detector metrics and agreement.
- `ANNOTATION_GUIDELINES.md` — annotation codebook.

## Step 1 — run from the repository root

This toolkit is integrated into the repository as a Python package. Run every command from the repository root. Do not commit raw exports or annotation files containing Telegram text to a public repository.

## Step 2 — rerun corrected analysis

Use the metadata dictionary CSV, not only the TXT list:

```powershell
python -m analysis.lexicon_validation.analyze_scraping_results `
  --input "C:\path\to\exports\YOUR_RUN_ID" `
  --dictionary "lexicons\offensive_lexicon.csv" `
  --include-posts
```

The output includes:

- `analysis_summary.json`
- `word_frequencies.csv`
- `messages_with_matches.csv`
- `source_summary.csv`
- `word_frequencies_by_source.csv`
- `category_summary.csv`
- `primary_aspect_summary.csv`
- `category_by_source.csv`
- `primary_aspect_by_source.csv`

Before using the results, open `analysis_summary.json` and verify:

```json
"rows_with_extra_fields": 0,
"rows_with_missing_fields": 0,
"rows_with_unknown_source": 0,
"suspicious_source_values": []
```

A non-empty warning does not always mean corrupted data, but it must be investigated.

## Step 3 — pilot annotation sample

Start with a pilot before spending days on the full sample:

```powershell
python -m analysis.lexicon_validation.prepare_validation_sample `
  --input "C:\path\to\exports\YOUR_RUN_ID" `
  --dictionary "lexicons\offensive_lexicon.csv" `
  --include-posts `
  --matched-size 50 `
  --unmatched-size 50 `
  --seed 20260726
```

Annotate only `validation_sample_blinded.csv`. Do not open the key during annotation. For comments, the file includes `parent_post_text` as contextual information; the label still applies to the comment text itself.

After the pilot, revise `ANNOTATION_GUIDELINES.md` only when a rule was genuinely ambiguous. Then generate the main sample with a different seed or delete the pilot folder and use:

```powershell
python -m analysis.lexicon_validation.prepare_validation_sample `
  --input "C:\path\to\exports\YOUR_RUN_ID" `
  --dictionary "lexicons\offensive_lexicon.csv" `
  --include-posts `
  --matched-size 400 `
  --unmatched-size 600 `
  --seed 20260727
```

Why 400 matched and 600 unmatched:

- matched items estimate contextual precision and expose ambiguous dictionary entries;
- unmatched items estimate false negatives and reveal missing offensive expressions;
- sampling weights preserve population estimates despite stratification.

## Step 4 — annotate

Fill these columns in `validation_sample_blinded.csv`:

- `context_label`
- `usage_type`
- `target_type`
- `target_text`
- `primary_aspect_gold`
- `quoted_or_reported`
- `annotator_id`
- `annotation_notes`

Use the exact values from `ANNOTATION_GUIDELINES.md`.

For inter-annotator agreement, create a reproducible 20% overlap subset:

```powershell
python -m analysis.lexicon_validation.create_second_annotator_subset `
  --input "validation_sample_blinded.csv" `
  --percent 20 `
  --seed 20260728
```

Give the resulting `validation_sample_second_annotator.csv` to the second annotator. The script preserves the original `sample_id` values.

## Step 5 — calculate validation metrics

```powershell
python -m analysis.lexicon_validation.calculate_validation_metrics `
  --annotations "C:\path\to\validation_sample_blinded_ANNOTATED.csv" `
  --key "C:\path\to\validation_sample_key.csv"
```

With a second annotator:

```powershell
python -m analysis.lexicon_validation.calculate_validation_metrics `
  --annotations "annotator_a.csv" `
  --second-annotations "annotator_b.csv" `
  --key "validation_sample_key.csv"
```

Outputs:

- `validation_metrics.json`
- `precision_by_primary_aspect.csv`
- `precision_by_term.csv`
- `false_positives.csv`
- `false_negatives.csv`
- `evaluated_sample_with_key.csv`
- `annotator_disagreements.csv` when a second file is supplied

Use `weighted_population_estimates` from the JSON as the main detector results because the sample is stratified.

## Step 6 — revise the dictionary

Review:

- `false_positives.csv` to identify terms that are too broad or context-dependent;
- `false_negatives.csv` to find missing words, spellings, inflections, phrases, and obfuscations;
- `precision_by_term.csv` to find unreliable entries;
- `precision_by_primary_aspect.csv` to find weak categories.

Do not delete an entry only because it has one false positive. Revise it when repeated evidence shows a systematic problem. Save the revised dictionary as a new version, for example:

```text
offensive_lexicon_v1.csv
offensive_lexicon_v2.csv
```

Never overwrite the dictionary snapshot used for a reported experiment.

## Test the toolkit

From the repository root:

```powershell
python -m unittest discover `
  -s analysis\lexicon_validation\tests `
  -v
```

The test covers multiline comments, source normalization, longest-match behavior, and validation-sample creation.

## Step 7 — final thesis reporting

Report separately:

- percentage of messages containing at least one dictionary term;
- contextual precision, recall, and F1 from manual validation;
- number of comments and posts;
- dictionary version and SHA-256 hash;
- matching mode and lack of automatic lemmatization;
- sampling sizes, seed, strata, and annotation agreement;
- limitations: context dependence, spelling variation, sarcasm, quotation, and incomplete recall.

Do not state that every dictionary match is offensive. State that the dictionary detected candidate messages, which were then contextually validated.

# Annotation guidelines for contextual offensive-language validation

Annotate the message **without looking at `validation_sample_key.csv`**. The key contains the dictionary prediction and would bias the decision.

## Required labels

### `context_label`

Use exactly one value:

- `offensive` — the message uses insulting, vulgar, threatening, hateful, degrading, or dehumanizing language in context.
- `non_offensive` — the detected expression is neutral, literal, quoted for discussion, part of a name, or otherwise not used offensively in the message.
- `uncertain` — the context is insufficient or genuinely ambiguous. Use sparingly and explain why in `annotation_notes`.

A message may be offensive even when no dictionary word is present. Judge the context, not the detector.

### `usage_type`

Use one primary value:

- `direct_insult`
- `general_profanity`
- `threat_or_harm`
- `group_slur_or_hate`
- `sexual_vulgarity`
- `dehumanization`
- `neutral_or_literal`
- `quotation_or_report`
- `other`
- `uncertain`

For `non_offensive` messages, `neutral_or_literal` or `quotation_or_report` will usually fit.

### `target_type`

Use one value:

- `individual`
- `group`
- `institution`
- `self`
- `event_or_object`
- `none`
- `uncertain`

Put the named target, when present, in `target_text`.

### `primary_aspect_gold`

Use the most suitable contextual aspect:

- `Profanity / Vulgarity`
- `Sexual vulgarity`
- `Scatological vulgarity`
- `General insult`
- `Ableism / Intelligence insult`
- `Misogyny / Sexism`
- `Homophobia`
- `Threat / Harm`
- `Dehumanization / Animalization`
- `Classism / Social status insult`
- `Religious / devil-based insult`
- `Obfuscated offensive form`
- `Other`
- `None`
- `Uncertain`

Use `None` when `context_label=non_offensive`.

### `quoted_or_reported`

Use `yes`, `no`, or `uncertain`. Quotation does not automatically make a message non-offensive: a person can quote a slur in order to attack someone. Judge the function in context.

## Decision rules

1. Read the whole message, not only the suspected word. For comments, use `parent_post_text` only as context; annotate the comment itself.
2. Distinguish a dictionary match from contextual offensiveness.
3. Neutral medical, legal, linguistic, or news discussion is not automatically offensive.
4. A statement can be offensive toward an object or situation through profanity even when no person is targeted.
5. Threats and death wishes are offensive even without profanity.
6. When several aspects apply, select the main communicative function and note the secondary one in `annotation_notes`.
7. Do not change the text or sample ID.
8. Do not open `validation_sample_key.csv` until annotation and adjudication are complete.

## Recommended procedure

1. Annotate a pilot of 100 items.
2. Discuss disagreements and clarify these rules.
3. Restart the main annotation from a clean copy after the rules are stable.
4. Give at least 20% of the final sample to a second annotator.
5. Adjudicate disagreements into one final annotation file before calculating detector metrics.

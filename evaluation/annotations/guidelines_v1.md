# Annotation guidelines v1 draft

## Claim and source identity

Use the smallest complete verbatim span that expresses an independently
checkable proposition. Preserve negation, hedges and comparison context. For
example, retain "approximately" in "Model A achieved approximately 91% accuracy
on the test set." If one sentence contains two independent measures, record a
separate span for each when the contract can represent it. Keep joint context
when separating them changes the meaning. Record the pipeline UUID only after
checking it against the correct PDF and claim span.

Use the claim paper ID, split, exact text, type, and source anchor. Record
character offsets as supplied by the source system and distinguish offsets
within a page or paragraph from offsets within the extracted claim. For PDF
tables capture page, table ID, row and column. CSV rows have a null page and
their row number. Exclude repeated rendered captions from the set of distinct
claim spans.

## Numeric slots

| Slot | Recording guidance | Worked example |
|---|---|---|
| metric | Normalize a named measured quantity | Accuracy in "91% test accuracy" |
| entity | Record the subject as stated | Model A in "Model A achieved 91%" |
| value | Preserve exact decimal representation | "91.2" for an annotation transcribed as 91.2% |
| unit | Record the unit used with the value | "%" for 91.2%, "percentage points" for a difference |
| scale | Record a stated magnitude multiplier | "1000000" for 2 million parameters |
| period | Preserve the evaluation condition or date | Test set or 2024 |
| comparison_basis | Record the referenced baseline or prior condition | Model B in "3 points higher than Model B" |
| denominator | Record a stated population or divisor | 200 examples in "180 of 200" |
| precision | Note reported decimal places, including trailing zeros | 2 in "91.20%" |
| rounding | Capture approximation language or known rounding instruction | "approximately" in "approximately 91%" |

Preserve raw written values in human annotation. The current API uses Member B's
native representation. Record a proposed display mapping for A/B review before
comparing raw numeric slots across annotations and API traces.

## Verdict decision sequence

1. Decide if source quality supports a judgment. A blurred or structurally ambiguous
   cell is Needs Review. If comparable evidence cannot be determined because the
   table switches from train to test, record Needs Review and explain the conflict.
2. If no qualifying evidence exists after checking the specified evidence bundle,
   record Unsupported. A statement without a matching source can be Unsupported
   even when it appears plausible.
3. Compare the same metric, entity, period, comparison basis and unit. If the
   same test result reports 95% while the claim reports 91% and the difference
   exceeds the stated tolerance, record Contradicted.
4. If the complete claim follows from the evidence, record Supported. A claim
   reporting 91% may match a table reporting 91.2% when the policy permits the
   claim's rounding.
5. If a material part follows and another part remains unsupported, record
   Partially Supported when the frozen rubric calls for it. Example for
   calibration: a joint claim asserts improved accuracy and improved recall, but
   qualifying sources establish only improved accuracy. Record which part is
   evidenced. Escalate conflicts with direct contradiction for adjudication.

These examples are illustrative, pending D's worked examples from real sources.
The annotation record needs stable IDs, human annotator ID, date, notes and
adjudication status. A human checks each anchor and verdict. Keep independent
labels until agreement has been measured, then retain the adjudicated outcome
and the original disagreements in the review log.

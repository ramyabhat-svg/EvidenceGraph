# Independent review pilot

Use [three extracted candidates](dev-review-candidates.jsonl) from physical
pages 6 and 8 of the [versioned paper PDF](https://arxiv.org/pdf/1902.06423v1).
The PDF SHA-256 and source offsets identify the parser output. The candidates
were selected for the checkpoint from one external-pilot paper. Their source
anchors locate the claim and may differ from the evidence that supports it.
Keep the raw extraction, including joined words, so it can be reconciled later.

Give both reviewers the candidates, PDF and [annotation guidelines](guidelines_v1.md).
Each reviewer independently records the candidate ID, reviewer ID, verdict,
evidence page and location, quoted or transcribed evidence, and a short
rationale. For table evidence, record the printed table label and row/column
headers. A third reviewer or the two reviewers together can adjudicate after
both files are submitted. Keep individual files and the adjudication record.

For checkpoint scoring, first verify the live run's PDF hash. Match each
candidate's source anchor and character offsets to its extracted claim and
record the actual persisted claim UUID. Translate verified evidence locations
to persisted anchors. Record missing, ambiguous and incorrect matches.
The candidate IDs in the packet are review IDs. They carry no verdicts.

These three cases check whether the annotation and evidence alignment procedure
works. The dev calibration set also needs independently reviewed claims across
papers and verdict classes. The sealed split stays unopened.

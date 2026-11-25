# Document-level splits

The assignment in the corpus shortlist is provisional. Count papers and claims
after human annotation. The current proposed allocation is four train, three
dev, and three test candidates.

Before freezing, record the final paper IDs, PDF and optional CSV file hashes,
license and attribution, number of annotated claims, and freeze date for each
split. Reserve complete papers and all companion files in one split. Check for
duplicate PDFs and reprints across the three groups.

The annotations are human-produced. Two annotators independently label a shared
40-claim dev subset, including at least ten Needs Review cases. Compute Cohen's
kappa on the independent labels, then adjudicate disagreements. Record both the
agreement calculation and the resolutions. The corpus is currently unannotated.

Keep the test records separately sealed. Use only train/dev files for building
queries, tuning, fixture creation, and ordinary evaluation. The final test
requires the frozen C policy, the recorded experiment configuration and an
authorized final run.

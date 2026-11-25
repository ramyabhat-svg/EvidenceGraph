import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { ClaimRecord } from './App';
import type { Trace } from './api';

it('renders a populated trace and escapes extracted text and review notes', () => {
  const anchor = {page: 1, element_type: 'table_cell', table_id: 'table-1',
    row: 2, col: 3, char_start: null, char_end: null};
  const untrusted = '<b>untrusted source</b>';
  const trace: Trace = {
    claim_id: 'claim', document_id: 'doc', claim_text: untrusted, claim_type: 'quantitative',
    extraction_method: 'rule', extraction_confidence: 0.9, source_anchor: anchor,
    numeric_slots: [{value: '91.20', unit: 'percent'}],
    retrieved_evidence: [{evidence_id: 'e', evidence_text: untrusted, source_anchor: anchor,
      retrieval_rank: 1, bm25_score: 12.4, dense_score: 0.8, reranker_score: 0.9}],
    nli_results: [{evidence_id: 'e', label: 'entailment', probabilities: {entailment: 0.9},
      model_name: 'fixture-model', model_revision: 'example'}],
    numeric_checks: [{evidence_id: 'e', result: 'match', tolerance: '0.01',
      incomparable_reason: null, trace: ['Compared matching test-set values.']}],
    verdict: {verdict_status: 'Supported', policy_rule_fired: 6, abstention_reason: null,
      policy_version: 'fixture', run_id: 'run', run_timestamp: '2026-01-01T00:00:00Z'},
    review_history: [{review_id: 'r', reviewer_id: 'reviewer', override_verdict: 'Needs Review',
      previous_verdict: 'Supported', note: untrusted, created_at: '2026-01-01T00:00:01Z',
      flag_for_rerun: true}],
  };
  const output = renderToStaticMarkup(<ClaimRecord trace={trace} project="project" onReview={() => {}} />);
  expect(output).toContain('NLI entailment');
  expect(output).toContain('91.20');
  expect(output).toContain('<ol><li>Compared matching test-set values.</li></ol>');
  expect(output).toContain('data-status="Supported"');
  expect(output).toContain('data-status="Needs Review"');
  expect(output.match(/&lt;b&gt;untrusted source&lt;\/b&gt;/g)).toHaveLength(3);
  expect(output).not.toContain(untrusted);
});

import { useState } from 'react';
import type { FormEvent } from 'react';
import { request } from './api';

type Provenance = { evidence_chunk_id: string; anchor_id: string; kind: string;
  page: number | null; table_index: number | null; row: number | null; col: number | null;
  low_quality: boolean; low_quality_reasons: string[] };
type Verdict = { claim_id: string; status: string; confidence: number | null;
  reason: string; explanation: string[]; policy_version: string; evidence: Provenance[];
  numeric_verifications: { slot_index: number; result: string; reason: string | null;
    checks: { evidence_chunk_id: string; result: string; tolerance: string | null; trace: string[] }[] }[];
  nli_results: { evidence_chunk_id: string; label: string; entailment_score: number;
    contradiction_score: number; neutral_score: number }[];
  reranker_results: { evidence_chunk_id: string; score: number }[] };
type Run = { analysis_run_id: string; document_id: string; verdicts: Verdict[] };

export function EngineeringRuns() {
  const [run, setRun] = useState<Run>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = String(new FormData(event.currentTarget).get('run_id')).trim();
    if (!/^[a-f\d]{8}(-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(id)) {
      setError('Enter the analysis run UUID.');
      return;
    }
    setError('');
    setRun(undefined);
    setLoading(true);
    try {
      setRun(await request<Run>('/analysis-runs/' + id + '/verdicts'));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not load the run.');
    } finally {
      setLoading(false);
    }
  }

  return <>
    <header className="heading"><h1>Inspect a run</h1></header>
    <form className="field-sheet" onSubmit={submit}>
      <label>Analysis run UUID<input name="run_id" required placeholder="Run ID from document status" /></label>
      <button disabled={loading}>{loading ? 'Loading…' : 'Load verdicts'}</button>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
    {run && <section>
      <p>Document {run.document_id} · {run.verdicts.length} persisted verdicts</p>
      {run.verdicts.map(verdict => <details className="evidence" key={verdict.claim_id}>
        <summary><span className="status" data-status={verdict.status}>{verdict.status}</span> {verdict.claim_id}</summary>
        <p>{verdict.reason} · {verdict.policy_version}
          {verdict.confidence !== null && ' · confidence ' + verdict.confidence}</p>
        {verdict.explanation.length > 0 && <ul>{verdict.explanation.map((line, index) => <li key={index}>{line}</li>)}</ul>}
        {verdict.evidence.map(item => <article className="evidence" key={item.evidence_chunk_id}>
          <h2>{item.kind.replaceAll('_', ' ')}</h2>
          <p>{[item.page !== null && 'p. ' + item.page, item.table_index !== null && 'table ' + item.table_index,
            item.row !== null && 'row ' + item.row, item.col !== null && 'column ' + item.col]
            .filter(Boolean).join(' · ')} <small>{item.anchor_id}</small></p>
          {item.low_quality && <p>Low quality · {item.low_quality_reasons.join(', ')}</p>}
          {verdict.reranker_results.filter(score => score.evidence_chunk_id === item.evidence_chunk_id)
            .map(score => <p key={score.evidence_chunk_id}>Reranker score {score.score}</p>)}
          {verdict.nli_results.filter(result => result.evidence_chunk_id === item.evidence_chunk_id)
            .map((result, index) => <p key={index}>NLI {result.label} · entailment {result.entailment_score}
              {' · contradiction ' + result.contradiction_score + ' · neutral ' + result.neutral_score}</p>)}
          {verdict.numeric_verifications.flatMap(slot => slot.checks
            .filter(check => check.evidence_chunk_id === item.evidence_chunk_id)
            .map((check, index) => <div key={slot.slot_index + ':' + index}>
              <p>Numeric slot {slot.slot_index + 1} · {check.result}
                {check.tolerance !== null && ' · tolerance ' + check.tolerance}</p>
              <ol>{check.trace.map((step, stepIndex) => <li key={stepIndex}>{step}</li>)}</ol>
            </div>))}
        </article>)}
      </details>)}
    </section>}
  </>;
}

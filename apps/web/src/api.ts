export const verdicts = [
  'Supported', 'Partially Supported', 'Contradicted', 'Unsupported', 'Needs Review',
] as const;
export type Verdict = typeof verdicts[number];
export type Project = { project_id: string; name: string; document_count: number };
export type Document = {
  document_id: string; display_name: string; status: 'queued' | 'processing' | 'complete' | 'error';
  created_at: string; claim_count: number | null; progress_message: string; error_message: string | null;
};
export type Anchor = {
  page: number | null; element_type: string; table_id: string | null;
  row: number | null; col: number | null; char_start: number | null; char_end: number | null;
};
export type Claim = {
  claim_id: string; claim_text: string; claim_type: string; source_anchor: Anchor;
  extraction_confidence: number; extraction_method: string; verdict_status: Verdict;
};
export type Review = {
  review_id: string; reviewer_id: string; override_verdict: Verdict;
  previous_verdict: Verdict; note: string; created_at: string; flag_for_rerun: boolean;
};
export type Trace = Omit<Claim, 'verdict_status'> & {
  document_id: string;
  numeric_slots: Record<string, string | number | boolean | null>[] | null;
  retrieved_evidence: {
    evidence_id: string; evidence_text: string; source_anchor: Anchor; retrieval_rank: number | null;
    bm25_score: number | null; dense_score: number | null; reranker_score: number | null;
  }[];
  nli_results: { evidence_id: string; label: string; probabilities: Record<string, number>;
    model_name: string; model_revision: string }[];
  numeric_checks: { evidence_id: string; result: string; tolerance: string | null;
    incomparable_reason: string | null; trace: string[] }[];
  verdict: { verdict_status: Verdict; policy_rule_fired: number | null; abstention_reason: string | null;
    policy_version: string; run_id: string; run_timestamp: string };
  review_history: Review[];
};
export type Run = {
  run_id: string; document_id: string; started_at: string | null; completed_at: string | null;
  status: Document['status']; claim_count: number | null; error_count: number; policy_version: string;
  configuration?: Record<string, unknown>;
  input_hashes?: Record<string, string | null>;
};
export const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
export const engineeringEnabled = apiBase.endsWith('/workspace');

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(apiBase + path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const validation = body?.detail?.[0]?.msg;
    throw new Error(body?.message ?? validation ?? 'Request failed (' + response.status + ').');
  }
  return response.json() as Promise<T>;
}

export const post = (data: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
});

export function anchorLabel(anchor: Anchor): string {
  return [
    anchor.page === null ? null : 'p. ' + anchor.page,
    anchor.table_id, anchor.element_type.replaceAll('_', ' '),
    anchor.row === null ? null : 'row ' + anchor.row,
    anchor.col === null ? null : 'col ' + anchor.col,
    anchor.char_start === null || anchor.char_end === null ? null :
      'characters ' + anchor.char_start + '–' + anchor.char_end,
  ].filter(Boolean).join(' · ');
}

export function validateFiles(pdf: File, csv?: File): string | undefined {
  if (!/\.pdf$/i.test(pdf.name)) return 'Choose a PDF for the research paper.';
  if (!pdf.size || pdf.size > 50 * 1024 ** 2) return 'The PDF must be between 1 byte and 50 MB.';
  if (csv && !/\.csv$/i.test(csv.name)) return 'Choose a CSV for the companion data.';
  if (csv && (!csv.size || csv.size > 5 * 1024 ** 2)) return 'The CSV must be between 1 byte and 5 MB.';
}


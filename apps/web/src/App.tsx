import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { anchorLabel, apiBase, engineeringEnabled, post, request, validateFiles, verdicts } from './api';
import type { Claim, Document, Project, Review, Run, Trace } from './api';
import { EngineeringRuns } from './EngineeringRuns';
import './style.css';

const route = () => window.location.hash.slice(1).split('/').filter(Boolean);
const projectPath = (id: string) => '#/projects/' + id;
const message = (error: unknown) => error instanceof Error ? error.message : String(error);
const date = (value: string | null) => value ? new Date(value).toLocaleString() : '—';

function useResource<T>(path: string | null, polling?: (value: T) => boolean): {data?: T; error?: string} {
  const [state, setState] = useState<{ path: string | null; data?: T; error?: string }>({path: null});
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const data = await request<T>(path, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setState({path, data});
        if (polling?.(data)) timer = setTimeout(load, 5000);
      } catch (error) {
        if (!controller.signal.aborted) setState({path, error: message(error)});
      }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, polling]);
  return state.path === path ? state : {};
}

function Status({value}: {value: string}) {
  return <span className="status" data-status={value}>{value}</span>;
}

function Heading({title, children}: {title: string; children?: ReactNode}) {
  return <header className="heading"><h1>{title}</h1>{children}</header>;
}

function Loading({error}: {error?: string}) {
  return error ? <p className="error" role="alert">{error}</p> : <p role="status">Loading…</p>;
}

function Upload({project}: {project?: Project}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selectedProject, setSelectedProject] = useState(project);
  const [projectName, setProjectName] = useState(project?.name ?? '');
  const [hasPdf, setHasPdf] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const pdf = fields.get('pdf_file');
    const csv = fields.get('csv_file');
    if (!(pdf instanceof File) || !pdf.name) return;
    const companion = csv instanceof File && csv.name ? csv : undefined;
    const invalid = validateFiles(pdf, companion);
    if (invalid) { setError(invalid); return; }
    setError('');
    setBusy(true);
    try {
      const target = selectedProject ?? await request<Project>('/projects', post({
        name: String(fields.get('project_name')).trim(),
      }));
      setSelectedProject(target);
      const data = new FormData();
      data.set('pdf_file', pdf);
      if (companion) data.set('csv_file', companion);
      const name = String(fields.get('document_name') ?? '').trim();
      if (name) data.set('document_name', name);
      await request('/projects/' + target.project_id + '/documents', {method: 'POST', body: data});
      window.location.hash = projectPath(target.project_id);
    } catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  }
  return <><Heading title="Add a paper" /><div className="upload-grid">
    <form onSubmit={submit} className="field-sheet">
      <label>Project name<input name="project_name" required readOnly={!!selectedProject}
        value={projectName} onChange={event => setProjectName(event.target.value)} maxLength={255} /></label>
      <label>Document title <small>optional</small><input name="document_name" /></label>
      <label className="file">Research paper <small>PDF · up to 50 MB</small>
        <input name="pdf_file" type="file" accept=".pdf" required onChange={event => setHasPdf(!!event.target.files?.length)} /></label>
      <label className="file">Companion data <small>CSV · optional · up to 5 MB</small>
        <input name="csv_file" type="file" accept=".csv" /></label>
      {error && <p role="alert" className="error">{error}</p>}
      <button disabled={busy || !projectName.trim() || !hasPdf}>{busy ? 'Submitting…' : 'Submit for analysis'}</button>
    </form>
    <aside className="margin-note"><h2>Source notes</h2><p>Choose a text-based PDF. A companion CSV can supply values from the paper’s tables.</p><p>Analysis starts after upload. Each extracted claim links back to its source location.</p></aside>
  </div></>;
}

const hasActiveDocuments = (value: {documents: Document[]}) =>
  value.documents.some(document => ['queued', 'processing'].includes(document.status));

function Documents({project}: {project: Project}) {
  const id = project.project_id;
  const result = useResource<{documents: Document[]}>('/projects/' + id + '/documents', hasActiveDocuments);
  return <><Heading title={project.name}><a className="button" href={projectPath(id) + '/upload'}>Add paper</a></Heading>
    {!result.data ? <Loading error={result.error} /> : result.data.documents.length === 0 ?
      <p>This project has no papers yet.</p> :
      <div className="table-wrap"><table><caption>Documents</caption><thead><tr>
        <th>Document</th><th>Type</th><th>Uploaded</th><th>Status</th><th>Claims</th>
      </tr></thead><tbody>{result.data.documents.map(doc => <tr key={doc.document_id}>
        <td><a href={projectPath(id) + '/documents/' + doc.document_id}>{doc.display_name}</a>
          {doc.error_message && <small className="error">{doc.error_message}</small>}</td>
        <td>PDF</td><td>{date(doc.created_at)}</td><td><Status value={doc.status} /></td>
        <td>{doc.claim_count ?? '—'}</td></tr>)}</tbody></table></div>}
  </>;
}

function Pagination({page, total, setPage}: {page: number; total: number; setPage: (value: number) => void}) {
  const pages = Math.max(1, Math.ceil(total / 20));
  return <nav className="pagination" aria-label="Pagination"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
    <span>Page {page} of {pages} · {total} total</span>
    <button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></nav>;
}

const isActive = (document: Document) => ['queued', 'processing'].includes(document.status);

function Claims({project, id}: {project: string; id: string}) {
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(1);
  const path = '/documents/' + id;
  const document = useResource<Document>(path, isActive);
  const result = useResource<{total: number; claims: Claim[]}>(
    document.data?.status === 'complete' ? path + '/claims?page=' + page +
      (filter ? '&status=' + encodeURIComponent(filter) : '') : null);
  if (!document.data) return <Loading error={document.error} />;
  return <><Heading title={document.data.display_name}><Status value={document.data.status} /></Heading>
    {document.data.status !== 'complete' ? <p role="status">{document.data.progress_message} {document.data.error_message}</p> :
    <><div className="toolbar"><h2>Extracted claims</h2><label>Verdict <select value={filter}
      onChange={event => {setFilter(event.target.value); setPage(1);}}>
      <option value="">All verdicts</option>{verdicts.map(value => <option key={value}>{value}</option>)}
    </select></label></div>
    {!result.data ? <Loading error={result.error} /> : <>
      {result.data.claims.length === 0 && <p>No claims match this view.</p>}
      <ol className="ledger">{result.data.claims.map(claim => <li key={claim.claim_id}>
        <div><a className="claim-link" href={projectPath(project) + '/claims/' + claim.claim_id}>{claim.claim_text}</a>
          <small>{claim.claim_type} · {anchorLabel(claim.source_anchor)}</small></div><Status value={claim.verdict_status} />
      </li>)}</ol><Pagination page={page} total={result.data.total} setPage={setPage} /></>}</>}
  </>;
}

function ReviewForm({id, onReview}: {id: string; onReview: (review: Review) => void}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const note = String(data.get('note')).trim();
    if (!note) { setError('Enter a note explaining your decision.'); return; }
    setBusy(true);
    setError('');
    try {
      const review = await request<Review>('/claims/' + id + '/reviews', post({
        reviewer_id: data.get('reviewer_id'), override_verdict: data.get('override_verdict'),
        note, flag_for_rerun: data.has('flag_for_rerun'),
      }));
      onReview(review); form.reset();
    } catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  }
  return <form className="field-sheet review-form" onSubmit={submit}>
    <h2>Record a review</h2><label>Reviewer ID<input name="reviewer_id" required /></label>
    <label>Override verdict<select name="override_verdict">{verdicts.map(value => <option key={value}>{value}</option>)}</select></label>
    <label>Rationale<textarea name="note" required rows={4} /></label>
    <label className="checkbox"><input name="flag_for_rerun" type="checkbox" /> Flag for rerun</label>
    {error && <p className="error" role="alert">{error}</p>}
    <button disabled={busy}>{busy ? 'Saving…' : 'Save review'}</button>
  </form>;
}

function Detail({id, project}: {id: string; project: string}) {
  const result = useResource<Trace>('/claims/' + id);
  const [added, setAdded] = useState<Review[]>([]);
  if (!result.data) return <Loading error={result.error} />;
  return <ClaimRecord trace={result.data} project={project}
    addedReviews={added} onReview={review => setAdded(previous => [review, ...previous])} />;
}

export function ClaimRecord({trace, project, addedReviews = [], onReview}: {
  trace: Trace; project: string; addedReviews?: Review[]; onReview: (review: Review) => void;
}) {
  const reviews = [...addedReviews, ...trace.review_history];
  return <><Heading title="Claim record"><a href={projectPath(project) + '/documents/' + trace.document_id}>Back to claims</a></Heading>
    <div className="detail-grid"><div>
      <section><h2>Extracted claim</h2><blockquote>{trace.claim_text}</blockquote>
        <p className="annotation">{anchorLabel(trace.source_anchor)} · {trace.claim_type} · {trace.extraction_method} · confidence {trace.extraction_confidence}</p></section>
      <section><h2>Numeric slots</h2>{trace.numeric_slots?.length ? trace.numeric_slots.map((slot, index) =>
        <dl key={index} className="facts">{Object.entries(slot).filter(([, value]) => value !== null)
          .map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl>) :
        <p>No numeric slots.</p>}</section>
      <section><h2>Evidence and checks</h2>{trace.retrieved_evidence.length === 0 && <p>No evidence candidates.</p>}
        {trace.retrieved_evidence.map(item => <article key={item.evidence_id} className="evidence">
          <small>{item.retrieval_rank != null && `Rank ${item.retrieval_rank} · `}{anchorLabel(item.source_anchor)}</small><p>{item.evidence_text}</p>
          {[['BM25', item.bm25_score], ['Dense', item.dense_score], ['Reranker', item.reranker_score]]
            .filter(([, score]) => score !== null).map(([label, score]) => <small key={label}>{label} {score} </small>)}
          {trace.nli_results.filter(nli => nli.evidence_id === item.evidence_id).map((nli, index) =>
            <p key={index}>NLI {nli.label} · {nli.model_name}@{nli.model_revision} · {Object.entries(nli.probabilities).map(([name, value]) => name + ' ' + value).join(' · ')}</p>)}
          {trace.numeric_checks.filter(check => check.evidence_id === item.evidence_id).map((check, index) =>
            <div key={index}><strong>{check.result}</strong>{check.tolerance !== null && <small> · tolerance {check.tolerance}</small>}
              {check.incomparable_reason && <p>{check.incomparable_reason}</p>}
              <ol>{check.trace.map((step, stepIndex) => <li key={stepIndex}>{step}</li>)}</ol></div>)}
        </article>)}
        {trace.nli_results.length === 0 && <p className="annotation">No NLI results available.</p>}
      </section>
      <section><h2>Review history</h2>{reviews.length === 0 && <p>No reviews yet.</p>}
        {reviews.map(review => <article className="evidence" key={review.review_id}>
          <strong>{review.reviewer_id}</strong> · <time>{date(review.created_at)}</time>
          <p>{review.note}</p><small>{review.previous_verdict} to {review.override_verdict}
          {review.flag_for_rerun && ' · Flagged for rerun'}</small></article>)}</section>
    </div><aside><section className="margin-note"><h2>Verdict</h2><p>System <Status value={trace.verdict.verdict_status} /></p>
      {reviews[0] && <p>Human <Status value={reviews[0].override_verdict} /></p>}
      <p className="annotation">{trace.verdict.policy_version} · {date(trace.verdict.run_timestamp)}</p>
      {trace.verdict.policy_rule_fired !== null && <p>Rule {trace.verdict.policy_rule_fired}</p>}
      {trace.verdict.abstention_reason && <p>{trace.verdict.abstention_reason.replaceAll('_', ' ')}</p>}
    </section><ReviewForm id={trace.claim_id} onReview={onReview} /></aside></div>
  </>;
}

function Runs({project}: {project: string}) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const result = useResource<{total: number; runs: Run[]}>('/projects/' + project + '/runs?page=' + page);
  const detail = useResource<Run>(selected ? '/runs/' + selected : null);
  return <><Heading title="Analysis runs" />
    {!result.data ? <Loading error={result.error} /> : <>
    {result.data.runs.length === 0 && <p>No runs yet.</p>}
    <div className="table-wrap"><table><thead><tr><th>Run</th><th>Status</th><th>Started</th><th>Finished</th><th>Claims</th><th>Report</th></tr></thead>
      <tbody>{result.data.runs.map(run => <tr key={run.run_id}>
        <td><button className="text-button" onClick={() => setSelected(run.run_id)}>{run.run_id.slice(0, 8)}</button></td>
        <td><Status value={run.status} /></td><td>{date(run.started_at)}</td><td>{date(run.completed_at)}</td>
        <td>{run.claim_count ?? '—'}</td><td>{run.status === 'complete' ?
        <><a href={apiBase + '/runs/' + run.run_id + '/report?format=json'} target="_blank" rel="noreferrer">JSON</a> · <a href={apiBase + '/runs/' + run.run_id + '/report?format=html'} target="_blank" rel="noreferrer">HTML</a></> : '—'}</td>
      </tr>)}</tbody></table></div><Pagination page={page} total={result.data.total} setPage={setPage} /></>}
      {selected && <section><h2>Run configuration</h2>{!detail.data ? <Loading error={detail.error} /> :
        <dl className="facts">{Object.entries({...detail.data.configuration, ...detail.data.input_hashes})
          .map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>}</section>}
  </>;
}

export function App() {
  const [segments, setSegments] = useState(route);
  useEffect(() => {
    const update = () => { setSegments(route()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const [section, projectId, view, id] = segments;
  const engineering = engineeringEnabled && section === 'engineering';
  const projects = useResource<{projects: Project[]}>(engineering ? null : '/projects?' + segments.join('/').replaceAll('/', '_'));
  const project = useResource<Project>(section === 'projects' && projectId ? '/projects/' + projectId : null);
  let screen: ReactNode = <Upload key={segments.join('/')} />;
  if (engineering) screen = <EngineeringRuns />;
  else if (section === 'projects' && projectId) {
    if (!project.data) screen = <Loading error={project.error} />;
    else if (view === 'upload') screen = <Upload key={projectId} project={project.data} />;
    else if (view === 'runs') screen = <Runs key={projectId} project={projectId} />;
    else if (view === 'claims' && id) screen = <Detail key={id} id={id} project={projectId} />;
    else if (view === 'documents' && id) screen = <Claims key={id} id={id} project={projectId} />;
    else screen = <Documents project={project.data} />;
  }
  return <div className="shell"><a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to workspace</a><aside className="rail">
    <a className="brand" href="#/">Evidence<span>Graph</span></a>
    <div className="rail-body"><div><a className="add" href="#/">Add a paper</a>{engineeringEnabled && <p><a href="#/engineering" aria-current={engineering ? 'page' : undefined}>Inspect a run</a></p>}</div>
      <nav aria-label="Projects"><h2>Projects</h2>{projects.data?.projects.map(item =>
        <div className="rail-project" key={item.project_id}>
          <a href={projectPath(item.project_id)} aria-current={item.project_id === projectId && !view ? 'page' : undefined}>{item.name}</a>
          {item.project_id === projectId && <a className="run-link" href={projectPath(projectId) + '/runs'} aria-current={view === 'runs' ? 'page' : undefined}>Analysis runs</a>}
        </div>)}
        {projects.error && <small>Project list unavailable.</small>}
        {projects.data?.projects.length === 0 && <small>No projects yet.</small>}</nav>
    </div>
  </aside><main id="main-content" tabIndex={-1}>{screen}</main></div>;
}






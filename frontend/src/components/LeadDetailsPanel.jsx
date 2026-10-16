import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import EmailContent from './EmailContent';
import LeadOutreachFields from './LeadOutreachFields';

const field = 'block w-full rounded-md border border-gray-300 bg-white p-2 text-sm dark:border-gray-600 dark:bg-gray-800';
const date = value => value ? new Date(value).toLocaleString() : 'Not scheduled';
const stepNumber = value => Number.isInteger(value) ? value + 1 : '?';
const safeUrl = value => {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
};

function emailState(item) {
  if (item.status === 'needs_writing') return 'Needs writing';
  if (item.status === 'manual_wait') return 'Waiting for manual LinkedIn step';
  if (item.status === 'paused') return 'Paused';
  if (item.status === 'scheduled') return 'Scheduled';
  if (item.status === 'draft') return 'Draft saved';
  if (item.status === 'awaiting_schedule') return 'Awaiting schedule';
  if (item.status === 'blocked') return 'Blocked';
  return (item.status || 'Pending').replace(/_/g, ' ');
}

export default function LeadDetailsPanel({ leadId, campaignId, onClose, onSaved }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const [tab, setTab] = useState('overview');
  const [lead, setLead] = useState(null);
  const [research, setResearch] = useState(null);
  const [emails, setEmails] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setMessage('');
    try {
      const suffix = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : '';
      const [profile, notes, mail] = await Promise.all([
        api.get(`/leads/${leadId}`), api.get(`/leads/${leadId}/research`), api.get(`/leads/${leadId}/emails${suffix}`),
      ]);
      setLead(profile);
      setResearch({ summary: notes.summary || '', sources: notes.sources || [], updated_at: notes.updated_at });
      setEmails(mail.items || []);
    } catch (error) { setMessage(error.message || 'Could not load lead details'); }
    finally { setLoading(false); }
  }, [leadId, campaignId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const previousFocus = document.activeElement;
    dialogRef.current?.querySelector('[aria-label="Close lead details"]')?.focus();
    const handleKey = event => {
      if (event.key === 'Escape') { closeRef.current(); return; }
      if (event.key !== 'Tab') return;
      const focusable = [...(dialogRef.current?.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]') || [])]
        .filter(element => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', handleKey);
    return () => { document.removeEventListener('keydown', handleKey); previousFocus?.focus?.(); };
  }, []);

  async function saveResearch(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      const saved = await api.put(`/leads/${leadId}/research`, {
        summary: research.summary,
        sources: research.sources.filter(source => source.url || source.title || source.notes),
        expected_updated_at: research.updated_at || null,
      });
      setResearch({ summary: saved.summary || '', sources: saved.sources || [], updated_at: saved.updated_at });
      setMessage('Research saved');
    } catch (error) { setMessage(error.message || 'Could not save research'); }
    finally { setBusy(false); }
  }

  async function saveEmail(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      await api.patch(`/campaigns/${selectedEmail.campaign_id}/leads/${leadId}/custom-email/${selectedEmail.sequence_id}/draft`, {
        subject: draft.subject.trim() ? draft.subject : null,
        body: draft.body || null,
        is_html: draft.is_html,
        expected_updated_at: selectedEmail.draft?.updated_at || null,
      });
      setDraft(null);
      setSelectedEmail(null);
      await load();
      setMessage('Draft saved. Sending schedule was not activated.');
      onSaved?.();
    } catch (error) { setMessage(error.message || 'Could not save draft'); }
    finally { setBusy(false); }
  }

  async function releaseEmail(item) {
    setBusy(true); setMessage('');
    try {
      await api.post(`/campaigns/${item.campaign_id}/leads/${leadId}/custom-email/${item.sequence_id}/release`, {
        expected_updated_at: item.draft.updated_at,
      });
      await load();
      setSelectedEmail(null);
      setMessage('Draft released for scheduling.');
      onSaved?.();
    } catch (error) { setMessage(error.message || 'Could not release draft'); }
    finally { setBusy(false); }
  }

  const updateSource = (index, key, value) => setResearch(current => ({
    ...current, sources: current.sources.map((source, i) => i === index ? { ...source, [key]: value } : source),
  }));

  return <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-label="Lead details" className="flex h-full w-full max-w-2xl flex-col bg-white shadow-xl dark:bg-gray-900">
      <header className="flex items-start justify-between gap-4 border-b p-5 dark:border-gray-700">
        <div className="min-w-0">
          <h2 className="truncate text-xl font-semibold">{lead?.name || lead?.email || 'Lead details'}</h2>
          <p className="truncate text-sm text-gray-500">{lead?.job_title || 'Job title unknown'} · {lead?.company || 'Company unknown'}</p>
          {lead && <p className="truncate text-xs text-gray-500">{lead.email}</p>}
        </div>
        <button type="button" onClick={onClose} aria-label="Close lead details" className="rounded px-2 py-1 text-xl hover:bg-gray-100">×</button>
      </header>
      <nav aria-label="Lead sections" className="flex gap-1 border-b px-4 dark:border-gray-700">
        {['overview', 'research', 'emails'].map(value => <button key={value} type="button" onClick={() => setTab(value)}
          className={`px-4 py-3 text-sm capitalize ${tab === value ? 'border-b-2 border-teal-600 font-semibold text-teal-700' : 'text-gray-500 hover:text-gray-800'}`}>{value}</button>)}
      </nav>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5 text-sm">
        {loading && <p>Loading lead details…</p>}
        {message && <p role="status" className="rounded bg-teal-50 p-2 text-teal-800">{message}</p>}
        {!loading && lead && tab === 'overview' && <>
          <div className="flex gap-3"><Link to={`/leads/${leadId}`} onClick={onClose} className="text-teal-700 underline">Full lead history</Link><Link to="/unibox" onClick={onClose} className="text-teal-700 underline">Unibox</Link></div>
          <LeadOutreachFields key={lead.id} lead={lead} onSaved={() => { load(); onSaved?.(); }} />
          <div className="rounded border p-4 dark:border-gray-700"><h3 className="mb-2 font-semibold">Campaigns</h3>{lead.campaigns?.length ? lead.campaigns.map(c => <div key={c.campaign_id} className="py-1"><Link to={`/campaigns/${c.campaign_id}#leads`} onClick={onClose} className="text-teal-700 underline">{c.campaign_name}</Link><span className="ml-2 text-gray-500">{c.status || 'active'}</span></div>) : 'No campaigns'}</div>
        </>}
        {!loading && research && tab === 'research' && <form onSubmit={saveResearch} className="space-y-4">
          <p className="text-gray-500">LinkedIn research · Last updated {research.updated_at ? date(research.updated_at) : 'never'}</p>
          <label className="block font-medium">Research summary<textarea className={`${field} mt-1`} rows={8} value={research.summary} onChange={event => setResearch(current => ({ ...current, summary: event.target.value }))} /></label>
          <h3 className="font-semibold">Sources</h3>
          {research.sources.map((source, index) => <div key={index} className="space-y-2 rounded border p-3 dark:border-gray-700">
            <label className="block">Title<input className={field} value={source.title || ''} onChange={event => updateSource(index, 'title', event.target.value)} /></label>
            <label className="block">Source URL<input type="url" required={!!(source.title || source.notes || source.url)} className={field} value={source.url || ''} onChange={event => updateSource(index, 'url', event.target.value)} /></label>
            {safeUrl(source.url) && <a href={safeUrl(source.url)} target="_blank" rel="noopener noreferrer" className="text-teal-700 underline">Open source</a>}
            <label className="block">Notes<textarea className={field} rows={2} value={source.notes || ''} onChange={event => updateSource(index, 'notes', event.target.value)} /></label>
            <button type="button" className="text-red-600 underline" onClick={() => setResearch(current => ({ ...current, sources: current.sources.filter((_, i) => i !== index) }))}>Remove source</button>
          </div>)}
          <div className="flex gap-3"><button type="button" className="rounded border px-3 py-2" onClick={() => setResearch(current => ({ ...current, sources: [...current.sources, { url: '', title: '', notes: '' }] }))}>Add source</button><button type="submit" disabled={busy} className="rounded bg-teal-600 px-3 py-2 text-white disabled:opacity-50">Save research</button></div>
        </form>}
        {!loading && tab === 'emails' && <div className="space-y-3">
          <p className="text-gray-500">Email history and upcoming steps for this lead. A saved draft stays in its current send state.</p>
          {!emails.length && <p>No emails for this lead.</p>}
          {emails.map((item, index) => <article key={`${item.campaign_id}-${item.sequence_id}-${index}`} className="rounded border p-4 dark:border-gray-700">
            <div className="flex flex-wrap items-start justify-between gap-2"><div><strong>{item.subject || '(No subject yet)'}</strong><p className="text-gray-500">{item.campaign_name} · Step {stepNumber(item.sequence_index)}</p></div><span className="rounded bg-blue-50 px-2 py-1 text-xs text-blue-800">{emailState(item)}</span></div>
            {item.reason && <p className="mt-1 text-xs text-gray-600">{item.reason}</p>}
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs"><dt>From</dt><dd>{item.from_email || 'Not assigned'}</dd><dt>To</dt><dd>{item.to_email || lead?.email}</dd><dt>Schedule</dt><dd>{item.sent_at ? `Sent ${date(item.sent_at)}` : date(item.scheduled_at)}</dd></dl>
            <div className="mt-3 flex flex-wrap gap-3"><button type="button" className="text-teal-700 underline" onClick={() => { setSelectedEmail(item); setDraft(null); }}>Preview</button>{item.editable && item.editing_source && <button type="button" className="text-teal-700 underline" onClick={() => { setSelectedEmail(item); setDraft({ subject: item.editing_source.subject ?? '', body: item.editing_source.body ?? '', is_html: item.editing_source.is_html }); }}>Edit this lead’s email</button>}{item.editable && !item.editing_source && <span className="text-xs text-amber-700">Editing source unavailable. Refresh the lead to edit.</span>}{item.editable && item.draft && <button type="button" disabled={busy} className="text-amber-700 underline disabled:opacity-50" onClick={() => releaseEmail(item)} title="Allow this saved draft to enter the send schedule">Release draft for scheduling</button>}</div>
          </article>)}
          {selectedEmail && <div className="rounded border border-teal-300 p-4 dark:border-teal-700">
            <div className="flex justify-between"><h3 className="font-semibold">{draft ? 'Edit this lead’s email' : 'Email preview'}</h3><button type="button" onClick={() => { setSelectedEmail(null); setDraft(null); }} aria-label="Close email preview">×</button></div>
            {draft ? <form onSubmit={saveEmail} className="mt-3 space-y-3"><label className="block">Subject<input className={field} placeholder={selectedEmail.sequence_index > 0 ? 'Leave blank to reply in thread' : ''} value={draft.subject} onChange={event => setDraft(current => ({ ...current, subject: event.target.value }))} /></label><label className="block">Body<textarea rows={10} className={field} value={draft.body} onChange={event => setDraft(current => ({ ...current, body: event.target.value }))} /></label><label className="flex gap-2"><input type="checkbox" checked={draft.is_html} onChange={event => setDraft(current => ({ ...current, is_html: event.target.checked }))} />HTML body</label><p className="text-xs text-gray-500">Saving this draft does not start or resume sending.</p><button type="submit" disabled={busy} className="rounded bg-teal-600 px-3 py-2 text-white disabled:opacity-50">Save draft</button></form> : <div className="mt-3 space-y-2"><p><strong>From:</strong> {selectedEmail.from_email || 'Not assigned'}</p><p><strong>To:</strong> {selectedEmail.to_email || lead?.email}</p><p><strong>Subject:</strong> {selectedEmail.subject || '(No subject yet)'}</p><p><strong>Schedule:</strong> {selectedEmail.sent_at ? `Sent ${date(selectedEmail.sent_at)}` : date(selectedEmail.scheduled_at)}</p><p><strong>Campaign step:</strong> {selectedEmail.campaign_name} · Step {stepNumber(selectedEmail.sequence_index)}</p><div className="rounded bg-gray-50 p-3 dark:bg-gray-800">{selectedEmail.body ? (selectedEmail.is_html ? <EmailContent html={selectedEmail.body} stripTracking blockImages /> : <p className="whitespace-pre-wrap">{selectedEmail.body}</p>) : <p className="text-gray-500">{selectedEmail.kind === 'sent' ? 'Body was not saved for this historical email.' : 'No content yet.'}</p>}</div></div>}
          </div>}
        </div>}
      </div>
    </section>
  </div>;
}

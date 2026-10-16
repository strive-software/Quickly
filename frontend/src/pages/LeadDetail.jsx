import LeadName from '../components/LeadName';
import { useEffect, useState, useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import LeadOutreachFields from '../components/LeadOutreachFields';
import { api } from '../api';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { useNotify } from '../context/NotificationContext';
import { useConfirm } from '../context/ConfirmContext';
import { useLoading } from '../context/LoadingContext';

function formatDt(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

const reviewLabels = { accepted: 'Accepted', rejected: 'Rejected', confirmed: 'Confirmed by recipient' };

export default function LeadDetail() {
  const { id } = useParams();
  const notify = useNotify();
  const confirm = useConfirm();
  const loading = useLoading();
  const [lead, setLead] = useState(null);
  const [error, setError] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(null);

  const load = useCallback(async () => {
    loading.start();
    setError(null);
    try {
      const l = await api.get(`/leads/${id}`);
      setLead(l);
    } catch (e) {
      setError(e.message || 'Failed to load lead');
      notify({ type: 'error', message: 'Could not load lead' });
    } finally {
      loading.stop();
    }
  }, [id, loading, notify]);

  useEffect(() => {
    load();
  }, [load]);

  async function reviewUnconfirmed(row, decision) {
    const prompt = decision === 'accepted'
      ? 'Accept this request and unsubscribe the lead?'
      : 'Reject this unconfirmed request? An older Beacon page may already have shown the recipient a success message. Sending remains paused; resume separately after review.';
    if (!await confirm(prompt)) return;
    setReviewBusy(row.request_id);
    try {
      await api.post(`/leads/${id}/unconfirmed-unsubscribes/${row.request_id}/review`, { decision });
      notify({ type: 'success', message: decision === 'accepted' ? 'Unsubscribe request accepted' : 'Request rejected. Sending remains paused.' });
      await load();
    } catch (e) { notify({ type: 'error', message: e.message || 'Could not review request' }); }
    finally { setReviewBusy(null); }
  }

  if (error && !lead) {
    return (
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-8">
        <h1 className="text-2xl font-semibold mb-4">Lead</h1>
        <p className="text-red-600">{error}</p>
        <Button as={Link} to="/leads" variant="outline">Back to Leads</Button>
      </div>
    );
  }

  if (!lead) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto p-8">
        <p className="text-gray-500">Loading…</p>
      </div>
    );
  }

  const customEntries = Object.entries(lead.custom_data || {});

  return (
    <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="text-sm text-gray-500 mb-1">
            <Link to="/leads" className="text-teal-500 hover:underline">Leads</Link>
            <span className="mx-2">/</span>
            <span className="font-mono text-xs">#{lead.id}</span>
          </div>
          <h1 className="text-2xl font-semibold"><LeadName name={lead.name} linkedinUrl={lead.linkedin_url} fallback={lead.email} /></h1>
          <p className="text-gray-600 mt-1 font-mono text-sm">{lead.email}</p>
        </div>
        <Button as={Link} to="/unibox" variant="outline" size="sm">
          Open Unibox
        </Button>
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        {lead.email_verification_status && (
          <span className="bg-gray-200 dark:bg-gray-600 text-gray-800 dark:text-gray-100 rounded-full px-2 py-0.5">
            verify: {lead.email_verification_status}
          </span>
        )}
        {lead.provider && (
          <span className="bg-slate-100 text-slate-700 rounded-full px-2 py-0.5 text-xs">
            {lead.provider}
          </span>
        )}
      </div>

      <LeadOutreachFields key={lead.id} lead={lead} />

      <Card className="p-4">
        <h2 className="text-lg font-semibold mb-3 border-b border-gray-200 dark:border-gray-700 pb-2">
          Campaigns
        </h2>
        {lead.campaigns?.length ? (
          <ul className="space-y-3">
            {lead.campaigns.map((c) => (
              <li
                key={c.campaign_id}
                className="flex flex-col sm:flex-row sm:flex-wrap sm:items-baseline sm:justify-between gap-2 border-b border-gray-100 dark:border-gray-700 pb-2 last:border-0"
              >
                <div>
                  <Link
                    to={`/campaigns/${c.campaign_id}#leads`}
                    className="text-teal-600 hover:underline font-medium"
                  >
                    {c.campaign_name}
                  </Link>
                  <span className="text-xs text-gray-400 font-mono ml-2">{c.campaign_public_id}</span>
                </div>
                <div className="text-xs text-gray-600 flex flex-wrap gap-2">
                  <span className="rounded-full bg-gray-100 px-2 py-0.5">status: {c.status || 'active'}</span>
                  {c.interest && (
                    <span className="rounded-full bg-violet-50 text-violet-800 px-2 py-0.5">
                      interest: {c.interest}
                    </span>
                  )}
                  <span className="rounded-full bg-gray-50 px-2 py-0.5">
                    opened {c.opened ? 'yes' : 'no'} · clicked {c.clicked ? 'yes' : 'no'} · replied{' '}
                    {c.replied ? 'yes' : 'no'}
                  </span>
                  {c.sending_paused && (
                    <span className="rounded-full bg-amber-100 text-amber-900 px-2 py-0.5">paused</span>
                  )}
                </div>
                <span className="text-sm text-gray-500">enrolled {formatDt(c.enrolled_at)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-gray-500 text-sm">Not enrolled in any campaign.</p>
        )}
      </Card>

      <Card className="p-4">
        <h2 className="text-lg font-semibold mb-3 border-b border-gray-200 dark:border-gray-700 pb-2">
          Custom data
        </h2>
        {customEntries.length ? (
          <table className="w-full table-auto border-collapse text-sm">
            <tbody>
              {customEntries.map(([k, v]) => (
                <tr key={k} className="even:bg-gray-50 dark:even:bg-gray-800/50">
                  <td className="border border-gray-200 dark:border-gray-600 px-2 py-1 font-medium text-gray-700 dark:text-gray-300">
                    {k}
                  </td>
                  <td className="border border-gray-200 dark:border-gray-600 px-2 py-1 font-mono text-xs break-all">
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-gray-500 text-sm">No custom fields.</p>
        )}
      </Card>

      <Card className="p-4 overflow-auto">
        <h2 className="text-lg font-semibold mb-3 border-b border-gray-200 dark:border-gray-700 pb-2">
          Interactions
        </h2>
        <p className="text-xs text-gray-500 mb-3">
          Outbound sends, inbound replies, and unsubscribe requests. Full mail threads: Unibox.
        </p>
        {lead.interactions?.length ? (
          <ul className="space-y-3 text-sm">
            {lead.interactions.map((row, i) => (
              <li
                key={`${row.at}-${row.kind}-${i}`}
                className={`border-l-2 pl-3 ${
                  row.direction === 'outbound' ? 'border-teal-400' : 'border-violet-400'
                }`}
              >
                <div className="font-medium">
                  {row.direction === 'outbound' ? 'Sent' : 'Received'}{' '}
                  {row.kind && row.kind !== 'sent' ? `· ${row.kind.replace(/_/g, ' ')}` : ''}
                </div>
                <div className="text-gray-500 text-xs mt-0.5">
                  {row.campaign_name && <span>{row.campaign_name} · </span>}
                  {row.subject && <span className="font-medium text-gray-600">{row.subject} · </span>}
                  {formatDt(row.at)}
                </div>
                {row.snippet && (
                  <p className="text-xs text-gray-600 mt-1 line-clamp-3">{row.snippet}</p>
                )}
                {row.kind === 'unsubscribed' && (
                  <p className="text-xs text-gray-600 mt-1">
                    Unsubscribe via {row.mechanism || 'unknown method'}
                    {row.request_method ? ` · ${row.request_method}` : ''}
                    {row.ip_address ? ` · IP ${row.ip_address}` : ''}
                    {row.user_agent ? ` · ${row.user_agent}` : ''}
                  </p>
                )}
                {row.kind === 'unconfirmed_unsubscribe' && <div className="mt-2 space-y-1 text-xs text-gray-700">
                  <p>{row.request_count || 1} request{row.request_count === 1 ? '' : 's'} · Last seen {formatDt(row.last_seen_at)}</p>
                  <p>{row.unsubscribe_review_hold ? (row.review_decision ? 'Sending remains paused' : 'Sending paused for review') : row.review_decision ? 'Review resolved' : 'Review required'}{row.ip_address ? ` · IP ${row.ip_address}` : ''}{row.user_agent ? ` · ${row.user_agent}` : ''}</p>
                  {row.review_decision ? <p className="font-medium">{reviewLabels[row.review_decision] || row.review_decision} {row.reviewed_at ? `· ${formatDt(row.reviewed_at)}` : ''}</p> : <div className="flex gap-3 pt-1">
                    <button type="button" disabled={reviewBusy === row.request_id} onClick={() => reviewUnconfirmed(row, 'accepted')} className="text-red-700 underline disabled:opacity-50">Accept unsubscribe</button>
                    <button type="button" disabled={reviewBusy === row.request_id} onClick={() => reviewUnconfirmed(row, 'rejected')} className="text-teal-700 underline disabled:opacity-50">Reject request</button>
                  </div>}
                </div>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-gray-500 text-sm">No interaction history yet.</p>
        )}
      </Card>
    </div>
  );
}

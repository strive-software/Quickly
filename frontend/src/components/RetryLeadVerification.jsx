import { useState } from 'react';
import { api } from '../api';
import { useNotify } from '../context/NotificationContext';

export default function RetryLeadVerification({ leadId, status, onDone }) {
  const [busy, setBusy] = useState(false);
  const notify = useNotify();
  if (status && !['pending', 'verification_error'].includes(status)) return null;

  async function retry() {
    setBusy(true);
    try {
      const result = await api.post(`/leads/${leadId}/verify`, {});
      notify({ type: 'success', message: result.queued ? 'Verification queued for this lead.' : 'Verification already in progress for this lead.' });
      onDone?.();
    } catch (error) {
      notify({ type: 'error', message: error.message || 'Could not retry verification' });
    } finally { setBusy(false); }
  }

  return <button type="button" disabled={busy} onClick={retry} className="text-xs text-teal-700 underline disabled:opacity-50">
    {busy ? 'Checking…' : status ? 'Retry verification' : 'Verify email'}
  </button>;
}

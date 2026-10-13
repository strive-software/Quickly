import { useEffect, useRef } from 'react';
import DOMPurify from 'dompurify';
import { Button } from './ui/Button';

// ── Email Preview Modal for schedule items ────────────────────────────────────
export default function EmailPreviewModal({ item, onClose }) {
  const isHtml = item.sequence_is_html;
  const body = item.sequence_body || '';
  const backdropDown = useRef(false);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onMouseDown={e => { backdropDown.current = e.target === e.currentTarget; }}
      onClick={() => { if (backdropDown.current) onClose(); }}
    >
      <div
        role="dialog" aria-modal="true" aria-label="Email Preview"
        data-darkreader-ignore
        className="rounded shadow w-full max-w-3xl max-h-[90vh] flex flex-col"
        style={{ backgroundColor: 'white' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h2 className="font-semibold text-gray-800">Email Preview</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              {item.type === 'sent' ? `Sent to ${item.lead_email}` : `Scheduled for ${item.lead_email}`}
            </p>
            {item.type === 'scheduled' && <p className="text-xs text-gray-400 mt-1">Current preview; content may change. Preheader text, an unsubscribe link, and quoted history may be added when sent.</p>}
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">×</button>
        </div>

        {/* Meta */}
        <div className="px-6 py-3 border-b bg-gray-50 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span className="text-gray-500">
            <span className="font-medium text-gray-700">From:</span> {item.inbox_email || '—'}
          </span>
          <span className="text-gray-500">
            <span className="font-medium text-gray-700">Campaign:</span> {item.campaign_name}
          </span>
          <span className="text-gray-500">
            <span className="font-medium text-gray-700">Sequence:</span> #{(item.sequence_index ?? 0) + 1}
          </span>
          {item.type === 'sent' && item.sent_at && (
            <span className="text-gray-500">
              <span className="font-medium text-gray-700">Sent:</span> {new Date(item.sent_at).toLocaleString()}
            </span>
          )}
          {item.type === 'scheduled' && item.scheduled_at && (
            <span className="text-gray-500">
              <span className="font-medium text-gray-700">Scheduled:</span> {new Date(item.scheduled_at).toLocaleString()}
            </span>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {/* Subject */}
          <div className="bg-gray-50 rounded-lg px-4 py-3">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Subject</span>
            <p className="font-medium text-gray-800">
              {!item.subject || item.subject === '(reply in thread)'
                ? <em className="text-gray-400 font-normal">Reply in thread</em>
                : item.subject}
            </p>
          </div>
          {/* Body */}
          <div>
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Body</span>
            {item.type === 'sent' && item.body_available === false ? (
              <p className="text-gray-400 italic text-sm">Original body unavailable</p>
            ) : body ? (
              isHtml ? (
                <iframe
                  title="Email body"
                  sandbox=""
                  referrerPolicy="no-referrer"
                  className="border rounded-lg bg-white w-full min-h-80"
                  srcDoc={`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'"><style>body{font:14px sans-serif;overflow-wrap:anywhere;padding:12px}</style>${DOMPurify.sanitize(body, { USE_PROFILES: { html: true }, FORBID_TAGS: ['style'], FORBID_ATTR: ['style', 'src', 'srcset', 'poster', 'background'] })}`}
                />
              ) : (
                <pre className="border rounded-lg p-5 bg-gray-50 text-sm whitespace-pre-wrap font-sans text-gray-800">
                  {body}
                </pre>
              )
            ) : (
              <p className="text-gray-400 italic text-sm">No body available</p>
            )}
          </div>
        </div>

        <div className="px-6 py-3 border-t flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  );
}


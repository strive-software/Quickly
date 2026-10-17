import { rememberLinkedInLead } from '../linkedinCapture';

/** Keep imported or legacy profile values from becoming unsafe external links. */
function profileUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && !url.username && !url.password &&
        (url.hostname === 'linkedin.com' || url.hostname.endsWith('.linkedin.com'))) {
      return url.href;
    }
  } catch { /* Missing or malformed profile: render plain text. */ }
  return null;
}

export default function LeadName({ name, linkedinUrl, leadId, fallback = '—' }) {
  const href = profileUrl(linkedinUrl);
  if (!name || !href) return name || fallback;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="text-teal-600 dark:text-teal-400 underline underline-offset-2 hover:text-teal-500"
      title="Open LinkedIn profile in a new tab"
      onClick={event => { event.stopPropagation(); rememberLinkedInLead(leadId, href); }}
      onAuxClick={event => { if (event.button === 1) rememberLinkedInLead(leadId, href); }}>
      {name}
    </a>
  );
}

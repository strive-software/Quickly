# Quickly LinkedIn Research

This private Chrome extension captures text from a LinkedIn page you opened
manually and saves it under the corresponding lead's **Research → Sources**.
It does not navigate LinkedIn, run background scraping, or send content to a
third party. Chrome may still expose extension activity to a site; no
undetectability guarantee is made.

## Install

1. Open `chrome://extensions` in Chrome, enable **Developer mode**, then
   choose **Load unpacked**.
2. Select this `extensions/linkedin-research` directory.
3. Pin **Quickly LinkedIn Research** to the toolbar.

## Use

1. Keep Quickly open and signed in. In Leads, open the person's LinkedIn
   profile by clicking their linked name. The CRM remembers that lead for
   30 minutes in this browser.
2. On the LinkedIn page, click the extension. Capture selected text or the
   visible page, then review and edit the preview.
3. Choose the Quickly tab and click **Save to lead research**. On first use,
   Chrome asks for access to that CRM origin. The text is saved to a LinkedIn
   source entry for the lead; an existing research summary is preserved.
4. Return to the lead's Research tab to review or edit the saved text.

The extension refuses pages other than LinkedIn, mismatched profiles, empty
text, or expired lead context. It captures at most 9,500 characters. If
Quickly says the context is missing, open the lead's LinkedIn link again.

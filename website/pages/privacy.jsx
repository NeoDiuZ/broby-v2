/**
 * @file pages/privacy.jsx
 * @description Public Privacy Policy page. Renders the v2.2 Privacy Policy
 * authored in BrobyVault, sanitised at build time (getStaticProps).
 * Source: website/content/legal/privacy.md (synced from
 * ~/BrobyVault/Drafts/Privacy-Policy-v2.2-DRAFT.md).
 */
import { LegalDocPage } from '../components/legal/LegalDocPage.jsx'
import { renderLegalMarkdown } from '../lib/legal.js'

export async function getStaticProps() {
  const html = renderLegalMarkdown('privacy')
  return { props: { html } }
}

export default function PrivacyPage({ html }) {
  return (
    <LegalDocPage
      title="Privacy Policy"
      version="v2.2"
      effectiveDate="8 May 2026"
      lastUpdated="8 May 2026"
      description="Broby Pte. Ltd. Privacy Policy — how we collect, use, and protect personal data through the BrobyVets veterinary AI scribe."
      html={html}
    />
  )
}

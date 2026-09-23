/**
 * @file pages/terms.jsx
 * @description Public Terms of Service page. Renders the v2.2 Terms authored
 * in BrobyVault, sanitised at build time (getStaticProps).
 * Source: website/content/legal/terms.md (synced from
 * ~/BrobyVault/Drafts/Terms-of-Service-v2.2-DRAFT.md).
 */
import { LegalDocPage } from '../components/legal/LegalDocPage.jsx'
import { renderLegalMarkdown } from '../lib/legal.js'

export async function getStaticProps() {
  const html = renderLegalMarkdown('terms')
  return { props: { html } }
}

export default function TermsPage({ html }) {
  return (
    <LegalDocPage
      title="Terms of Service"
      version="v2.2"
      effectiveDate="8 May 2026"
      lastUpdated="8 May 2026"
      description="Broby Pte. Ltd. Terms of Service — the legal terms governing use of the BrobyVets veterinary AI scribe."
      html={html}
    />
  )
}

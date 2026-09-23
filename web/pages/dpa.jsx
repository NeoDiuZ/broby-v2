/**
 * @file pages/dpa.jsx
 * @description Public Data Processing Agreement page. Renders the v2.2 DPA
 * authored in BrobyVault, sanitised at build time (getStaticProps).
 * Source: website/content/legal/dpa.md (synced from
 * ~/BrobyVault/Drafts/Data-Processing-Agreement-v2.2-DRAFT.md).
 */
import { LegalDocPage } from '../marketing/components/legal/LegalDocPage.jsx'
import { renderLegalMarkdown } from '../marketing/lib/legal.js'

export async function getStaticProps() {
  const html = renderLegalMarkdown('dpa')
  return { props: { html } }
}

export default function DpaPage({ html }) {
  return (
    <LegalDocPage
      title="Data Processing Agreement"
      version="v2.2"
      effectiveDate="8 May 2026"
      lastUpdated="8 May 2026"
      description="Broby Pte. Ltd. Data Processing Agreement — the contractual terms for processing personal data through the BrobyVets service under PDPA-SG and PDPA-MY."
      html={html}
    />
  )
}

export function StagingBanner() {
 return <aside aria-label="Broby V2 preview status" style={{background:'#173b35',color:'white',fontSize:13,padding:'14px 18px',textAlign:'center',lineHeight:1.6}}>
  <strong>Broby V2 · synthetic preview.</strong> Customer messaging and live payments are not enabled.
  {' '}These legal documents are reference copies from the earlier product and await approval for V2.
  {' '}V2 has no verified automatic 90-day audio deletion. Real-clinic onboarding remains pending.
  {' '}<a style={{textDecoration:'underline',color:'inherit'}} href="/app">Open clinic workspace →</a>
 </aside>
}

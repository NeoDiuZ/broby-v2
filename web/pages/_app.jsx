/**
 * @file _app.jsx
 * @description App-wide chrome. Loads global stylesheet, Plus Jakarta Sans
 * (used by /privacy /terms /dpa /subprocessors via tailwind `font-plus-jakarta`),
 * and the V2 synthetic-preview status notice, including hosted legal pages.
 */

import Head from 'next/head'
import { StagingBanner } from '../marketing/components/StagingBanner.jsx'

function MyApp({ Component, pageProps }) {
  return (
    <>
      <Head>
        <link rel="stylesheet" href="/marketing.css" />
        <title>Broby Vets</title>
        <link rel="icon" href="/favicon.ico" />
        <link rel="icon" type="image/png" href="/images/broby-logo.png" />
      </Head>
      <StagingBanner />
      <Component {...pageProps} />
    </>
  )
}

export default MyApp
